"""API Contract Generation — Pydantic → OpenAPI → TypeScript client.

Extracts the FastAPI OpenAPI schema, generates a typed TypeScript client
with interfaces for all endpoints, and writes it to the frontend.

Usage (CLI):
    python backend/api_contracts.py --output frontend/src/lib/apiClient.ts

Usage (programmatic):
    from api_contracts import generate_ts_client
    ts_code = generate_ts_client(openapi_schema)

Endpoints:
  GET  /api/contracts/openapi.json  — raw OpenAPI schema
  GET  /api/contracts/ts-client     — generated TypeScript client
  POST /api/contracts/refresh       — re-extract and return fresh schema
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("worldbase.api_contracts")

router = APIRouter(prefix="/api/contracts", tags=["api-contracts"])

# Module-level cache for the OpenAPI schema
_OPENAPI_CACHE: dict[str, Any] | None = None
_TS_CACHE: str | None = None
_CACHE_TS: float = 0.0
_CACHE_TTL = 300.0  # 5 min


# ---------------------------------------------------------------------------
# OpenAPI schema extraction
# ---------------------------------------------------------------------------


def _get_app():
    """Import the FastAPI app lazily to avoid circular imports."""
    import main

    return main.app


def extract_openapi(*, force_refresh: bool = False) -> dict[str, Any]:
    """Extract the OpenAPI schema from the FastAPI app."""
    global _OPENAPI_CACHE, _CACHE_TS
    if (
        _OPENAPI_CACHE
        and not force_refresh
        and (datetime.now(timezone.utc).timestamp() - _CACHE_TS) < _CACHE_TTL
    ):
        return _OPENAPI_CACHE
    app = _get_app()
    schema = app.openapi()
    _OPENAPI_CACHE = schema
    _CACHE_TS = datetime.now(timezone.utc).timestamp()
    return schema


# ---------------------------------------------------------------------------
# TypeScript type generation
# ---------------------------------------------------------------------------

_PY_TO_TS: dict[str, str] = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "array": "any[]",
    "object": "Record<string, any>",
    "null": "null",
}


def _ts_type(schema: dict[str, Any] | None, fallback: str = "any") -> str:
    """Convert an OpenAPI schema node to a TypeScript type string."""
    if not schema:
        return fallback
    if "$ref" in schema:
        ref = schema["$ref"].split("/")[-1]
        return ref
    t = schema.get("type")
    if t == "array":
        item_type = _ts_type(schema.get("items"), "any")
        return f"{item_type}[]"
    if t == "object":
        props = schema.get("properties", {})
        if not props and schema.get("additionalProperties"):
            return "Record<string, any>"
        if not props:
            return "Record<string, any>"
        fields = []
        for name, prop in props.items():
            optional = name not in (schema.get("required") or [])
            ts_t = _ts_type(prop)
            fields.append(f"  {name}{'?' if optional else ''}: {ts_t}")
        return "{\n" + "\n".join(fields) + "\n}"
    if t in _PY_TO_TS:
        return _PY_TO_TS[t]
    if schema.get("enum"):
        return " | ".join(f'"{e}"' for e in schema["enum"])
    if schema.get("oneOf"):
        return " | ".join(_ts_type(s) for s in schema["oneOf"])
    if schema.get("anyOf"):
        return " | ".join(_ts_type(s) for s in schema["anyOf"])
    return fallback


def _generate_interfaces(components: dict[str, Any]) -> str:
    """Generate TypeScript interfaces from OpenAPI components/schemas."""
    schemas = components.get("schemas", {}) if components else {}
    if not schemas:
        return "// No schema components found\n"
    lines: list[str] = []
    for name, schema in sorted(schemas.items()):
        ts_type = _ts_type(schema)
        if ts_type.startswith("{"):
            lines.append(f"export interface {name} {ts_type}\n")
        else:
            lines.append(f"export type {name} = {ts_type};\n")
    return "\n".join(lines)


def _path_to_method_name(path: str, method: str) -> str:
    """Convert a path + method to a camelCase function name."""
    # Remove path params braces: /api/foo/{id} -> foo_id
    clean = re.sub(r"[{}]", "", path)
    # Remove /api/ prefix
    clean = re.sub(r"^/api/", "", clean)
    # Split on / and _ and -
    parts = re.split(r"[/_\-]+", clean)
    # First part is the method prefix
    name_parts: list[str] = [method.lower()]
    for part in parts:
        if part:
            name_parts.append(part)
    # camelCase
    result = name_parts[0]
    for p in name_parts[1:]:
        result += p[0].upper() + p[1:]
    return result


def _generate_endpoint_functions(paths: dict[str, Any], base_url: str) -> str:
    """Generate TypeScript fetch functions for each endpoint."""
    lines: list[str] = []
    lines.append(f"const BASE_URL = '{base_url}';")
    lines.append("")
    lines.append("/** Centralized fetch wrapper with API key injection. */")
    lines.append(
        "async function apiFetch(path: string, init?: RequestInit): Promise<any> {"
    )
    lines.append("  const apiKey = localStorage.getItem('WORLDBASE_API_KEY') || '';")
    lines.append("  const headers = new Headers(init?.headers);")
    lines.append("  if (apiKey) headers.set('X-API-Key', apiKey);")
    lines.append(
        "  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');"
    )
    lines.append(
        "  const resp = await fetch(`${BASE_URL}${path}`, { ...init, headers });"
    )
    lines.append("  if (!resp.ok) {")
    lines.append("    const text = await resp.text().catch(() => resp.statusText);")
    lines.append("    throw new Error(`API ${resp.status}: ${text}`);")
    lines.append("  }")
    lines.append("  const ct = resp.headers.get('content-type') || '';")
    lines.append("  if (ct.includes('application/json')) return resp.json();")
    lines.append("  return resp.text();")
    lines.append("}")
    lines.append("")

    seen_names: dict[str, int] = {}

    for path in sorted(paths.keys()):
        path_item = paths[path]
        for method in ("get", "post", "put", "patch", "delete"):
            if method not in path_item:
                continue
            op = path_item[method]
            func_name = _path_to_method_name(path, method)
            # Deduplicate function names
            if func_name in seen_names:
                seen_names[func_name] += 1
                func_name = f"{func_name}_{seen_names[func_name]}"
            else:
                seen_names[func_name] = 0

            # Build parameters
            params = op.get("parameters", [])
            path_params = [p for p in params if p.get("in") == "path"]
            query_params = [p for p in params if p.get("in") == "query"]
            body_ref = (
                op.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
                or {}
            ).get("$ref")

            # Build TS function signature
            ts_params: list[str] = []
            for p in path_params:
                p_name = p["name"]
                p_type = _ts_type(p.get("schema", {}), "string")
                ts_params.append(f"{p_name}: {p_type}")
            for p in query_params:
                p_name = p["name"]
                p_type = _ts_type(p.get("schema", {}), "any")
                required = p.get("required", False)
                ts_params.append(f"{p_name}{'?' if not required else ''}: {p_type}")
            if body_ref:
                body_type = body_ref.split("/")[-1]
                ts_params.append(f"body: {body_type}")

            # Build path with interpolated params
            ts_path = path
            for p in path_params:
                ts_path = ts_path.replace(f"{{{p['name']}}}", f"${{{p['name']}}}")

            # Build query string
            query_lines: list[str] = []
            if query_params:
                query_lines.append("  const params = new URLSearchParams();")
                for p in query_params:
                    p_name = p["name"]
                    required = p.get("required", False)
                    if required:
                        query_lines.append(
                            f"  params.set('{p_name}', String({p_name}));"
                        )
                    else:
                        query_lines.append(
                            f"  if ({p_name} !== undefined && {p_name} !== null) params.set('{p_name}', String({p_name}));"
                        )
                query_lines.append(
                    "  const qs = params.toString() ? `?${params.toString()}` : '';"
                )
                ts_path = f"{ts_path}${{qs}}"
            else:
                if "{" not in ts_path:
                    pass  # no interpolation needed

            # Build fetch call
            fetch_path = (
                f"`{ts_path}`" if "{" in ts_path or "$" in ts_path else f"'{ts_path}'"
            )
            if query_params:
                # Rebuild: path already has ${qs} appended
                fetch_path = f"`{ts_path}`"

            method_upper = method.upper()
            init_parts: list[str] = []
            if method != "get":
                init_parts.append(f"    method: '{method_upper}',")
            if body_ref:
                init_parts.append("    body: JSON.stringify(body),")

            if init_parts:
                init_str = ", {\n" + "\n".join(init_parts) + "\n  }"
            else:
                init_str = ""

            # Response type
            responses = op.get("responses", {})
            ok_response = (
                responses.get("200")
                or responses.get("201")
                or responses.get("default")
                or {}
            )
            resp_schema = (
                ok_response.get("content", {})
                .get("application/json", {})
                .get("schema", {})
                or {}
            )
            resp_type = _ts_type(resp_schema, "any")

            # JSDoc
            summary = op.get("summary", "")
            desc = op.get("description", "")
            jsdoc_lines = ["/**"]
            if summary:
                jsdoc_lines.append(f" * {summary}")
            if desc:
                jsdoc_lines.append(f" * {desc}")
            jsdoc_lines.append(f" * @method {method_upper}")
            jsdoc_lines.append(f" * @path {path}")
            jsdoc_lines.append(" */")

            lines.append("\n".join(jsdoc_lines))
            param_str = ", ".join(ts_params) if ts_params else ""
            lines.append(
                f"export async function {func_name}({param_str}): Promise<{resp_type}> {{"
            )
            for ql in query_lines:
                lines.append(ql)
            lines.append(f"  return apiFetch({fetch_path}{init_str});")
            lines.append("}")
            lines.append("")

    return "\n".join(lines)


def generate_ts_client(
    schema: dict[str, Any] | None = None,
    *,
    base_url: str = "http://127.0.0.1:8002",
) -> str:
    """Generate a complete TypeScript client from an OpenAPI schema."""
    if schema is None:
        schema = extract_openapi()

    header = [
        "// AUTO-GENERATED by api_contracts.py — do not edit manually.",
        f"// Generated: {datetime.now(timezone.utc).isoformat()}",
        f"// OpenAPI version: {schema.get('openapi', 'unknown')}",
        f"// API title: {schema.get('info', {}).get('title', 'unknown')}",
        f"// API version: {schema.get('info', {}).get('version', 'unknown')}",
        "",
        "/* eslint-disable */",
        "",
    ]

    interfaces = _generate_interfaces(schema.get("components", {}))
    endpoints = _generate_endpoint_functions(schema.get("paths", {}), base_url)

    return "\n".join(header) + "\n" + interfaces + "\n\n" + endpoints + "\n"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/openapi.json")
async def api_openapi_schema():
    """Return the raw OpenAPI schema."""
    return extract_openapi()


@router.get("/ts-client", response_class=PlainTextResponse)
async def api_ts_client():
    """Return the generated TypeScript client code."""
    global _TS_CACHE
    if _TS_CACHE is None:
        _TS_CACHE = generate_ts_client()
    return PlainTextResponse(_TS_CACHE, media_type="text/typescript; charset=utf-8")


@router.post("/refresh")
async def api_refresh_contracts():
    """Force re-extraction of the OpenAPI schema and TS client."""
    global _OPENAPI_CACHE, _TS_CACHE, _CACHE_TS
    schema = extract_openapi(force_refresh=True)
    _TS_CACHE = generate_ts_client(schema)
    return {
        "ok": True,
        "paths": len(schema.get("paths", {})),
        "schemas": len(schema.get("components", {}).get("schemas", {})),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
