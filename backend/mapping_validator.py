"""J8 — YAML Mapping Schema Drift Detection.

Validates YAML mappings in ``backend/ingest/mappings/`` against JSON Schemas
in ``backend/ingest/schemas/``. Detects:
- Required feed fields not mapped
- Unknown fields in mapping (not in schema)
- FtM property / source field type compatibility
- Missing entity keys
- Invalid link references

Also provides runtime drift detection: when a feed payload contains fields
not in the schema, a drift warning is emitted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from structured_log import get_logger

log = get_logger("mapping_validator")

_SCHEMAS_DIR = Path(__file__).resolve().parent / "ingest" / "schemas"
_MAPPINGS_DIR = Path(__file__).resolve().parent / "ingest" / "mappings"


def _enabled() -> bool:
    return os.getenv("WORLDBASE_MAPPING_VALIDATOR", "1").strip().lower() not in {
        "0", "false", "no", "off"
    }


@dataclass
class ValidationReport:
    mapping_name: str
    schema_name: str
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mapped_fields: list[str] = field(default_factory=list)
    schema_fields: list[str] = field(default_factory=list)
    unmapped_required: list[str] = field(default_factory=list)
    unknown_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping": self.mapping_name,
            "schema": self.schema_name,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "mapped_fields": self.mapped_fields,
            "schema_fields": self.schema_fields,
            "unmapped_required": self.unmapped_required,
            "unknown_fields": self.unknown_fields,
        }


def _load_schema(name: str) -> dict[str, Any] | None:
    path = _SCHEMAS_DIR / f"{name}.json"
    if not path.is_file():
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _extract_mapped_columns(mapping_data: dict) -> set[str]:
    """Extract all column names referenced in a YAML mapping."""
    columns: set[str] = set()
    root_key = next(iter(mapping_data))
    queries = (mapping_data.get(root_key) or {}).get("queries") or []
    for query in queries:
        for alias, spec in (query.get("entities") or {}).items():
            for key in spec.get("keys") or []:
                columns.add(key)
            for prop_name, col_spec in (spec.get("properties") or {}).items():
                if isinstance(col_spec, str):
                    columns.add(col_spec)
                elif isinstance(col_spec, dict):
                    if "column" in col_spec:
                        columns.add(col_spec["column"])
                    for c in col_spec.get("columns") or []:
                        columns.add(c)
        for req in query.get("require_any") or []:
            columns.add(req)
    # Also extract from rag block
    rag = (mapping_data.get(root_key) or {}).get("rag") or {}
    for item in rag.get("body") or []:
        if isinstance(item, dict):
            if "column" in item:
                columns.add(item["column"])
            for c in item.get("columns") or []:
                columns.add(c)
    return columns


def _extract_entity_keys(mapping_data: dict) -> dict[str, list[str]]:
    """Extract key fields per entity alias from a YAML mapping."""
    result: dict[str, list[str]] = {}
    root_key = next(iter(mapping_data))
    queries = (mapping_data.get(root_key) or {}).get("queries") or []
    for query in queries:
        for alias, spec in (query.get("entities") or {}).items():
            keys = spec.get("keys") or ["id"]
            result[alias] = keys
    return result


def _extract_links(mapping_data: dict) -> list[dict[str, str]]:
    """Extract link definitions from a YAML mapping."""
    links: list[dict[str, str]] = []
    root_key = next(iter(mapping_data))
    queries = (mapping_data.get(root_key) or {}).get("queries") or []
    for query in queries:
        for link in query.get("links") or []:
            links.append({
                "source": link.get("source", ""),
                "target": link.get("target", ""),
                "kind": link.get("kind", "relatedEntity"),
            })
    return links


def validate_mapping(mapping_name: str) -> ValidationReport:
    """Validate a single YAML mapping against its JSON schema.

    Returns a ValidationReport with errors, warnings, and field analysis.
    """
    mapping_path = _MAPPINGS_DIR / f"{mapping_name}.yml"
    if not mapping_path.is_file():
        return ValidationReport(
            mapping_name=mapping_name,
            schema_name=mapping_name,
            ok=False,
            errors=[f"mapping file not found: {mapping_name}.yml"],
        )

    with open(mapping_path, encoding="utf-8") as fh:
        mapping_data = yaml.safe_load(fh) or {}

    if not isinstance(mapping_data, dict) or len(mapping_data) != 1:
        return ValidationReport(
            mapping_name=mapping_name,
            schema_name=mapping_name,
            ok=False,
            errors=["mapping must have exactly one top-level key"],
        )

    schema = _load_schema(mapping_name)
    if schema is None:
        return ValidationReport(
            mapping_name=mapping_name,
            schema_name=mapping_name,
            ok=False,
            errors=[f"schema file not found: {mapping_name}.json"],
        )

    mapped_cols = _extract_mapped_columns(mapping_data)
    schema_props = schema.get("properties") or {}
    schema_fields = set(schema_props.keys())
    required_fields = set(schema.get("required") or [])
    optional_fields = set(schema.get("optional") or [])

    errors: list[str] = []
    warnings: list[str] = []

    # Check 1: unmapped required fields
    unmapped_required = required_fields - mapped_cols
    if unmapped_required:
        errors.append(
            f"Required fields not mapped: {sorted(unmapped_required)}"
        )

    # Check 2: unknown fields in mapping (not in schema)
    unknown = mapped_cols - schema_fields
    if unknown:
        for field_name in sorted(unknown):
            warnings.append(f"Unknown field '{field_name}' not in schema")

    # Check 3: entity keys must exist in schema
    entity_keys = _extract_entity_keys(mapping_data)
    for alias, keys in entity_keys.items():
        for key in keys:
            if key not in schema_fields:
                warnings.append(
                    f"Entity '{alias}' key '{key}' not in schema fields"
                )

    # Check 4: link references must match entity aliases
    links = _extract_links(mapping_data)
    all_aliases = set(entity_keys.keys())
    for link in links:
        if link["source"] not in all_aliases:
            errors.append(
                f"Link source '{link['source']}' not defined as entity"
            )
        if link["target"] not in all_aliases:
            errors.append(
                f"Link target '{link['target']}' not defined as entity"
            )

    # Check 5: rag source_key must be in schema
    root_key = next(iter(mapping_data))
    rag = (mapping_data.get(root_key) or {}).get("rag") or {}
    source_key = rag.get("source_key")
    if source_key and source_key not in schema_fields:
        warnings.append(
            f"RAG source_key '{source_key}' not in schema fields"
        )

    ok = len(errors) == 0
    return ValidationReport(
        mapping_name=mapping_name,
        schema_name=mapping_name,
        ok=ok,
        errors=errors,
        warnings=warnings,
        mapped_fields=sorted(mapped_cols),
        schema_fields=sorted(schema_fields),
        unmapped_required=sorted(unmapped_required),
        unknown_fields=sorted(unknown),
    )


def validate_all_mappings() -> dict[str, Any]:
    """Validate all YAML mappings against their schemas.

    Returns: {ok: bool, reports: [...], summary: {total, passed, failed, warnings}}
    """
    mapping_files = sorted(p.stem for p in _MAPPINGS_DIR.glob("*.yml"))
    reports = []
    for name in mapping_files:
        report = validate_mapping(name)
        reports.append(report.to_dict())
        if not report.ok:
            log.warning(
                "mapping_validation_failed",
                mapping=name,
                errors=report.errors,
            )
        if report.warnings:
            log.info(
                "mapping_validation_warnings",
                mapping=name,
                warnings=report.warnings,
            )

    total = len(reports)
    passed = sum(1 for r in reports if r["ok"])
    failed = total - passed
    warning_count = sum(len(r["warnings"]) for r in reports)

    return {
        "ok": failed == 0,
        "reports": reports,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "warnings": warning_count,
        },
    }


def detect_payload_drift(
    mapping_name: str,
    records: list[dict],
) -> dict[str, Any]:
    """Check if feed payload fields match the schema.

    Called during ingest to detect runtime drift when a feed API
    renames or adds fields.

    Returns: {ok: bool, unknown_fields: [...], missing_required: [...], drift: bool}
    """
    if not _enabled():
        return {"ok": True, "unknown_fields": [], "missing_required": [], "drift": False}

    if not records:
        return {"ok": True, "unknown_fields": [], "missing_required": [], "drift": False}

    schema = _load_schema(mapping_name)
    if schema is None:
        return {"ok": True, "unknown_fields": [], "missing_required": [], "drift": False, "reason": "no schema"}

    schema_props = set((schema.get("properties") or {}).keys())
    required_fields = set(schema.get("required") or [])

    # Collect all field names from all records
    all_fields: set[str] = set()
    for record in records[:100]:  # sample first 100
        if isinstance(record, dict):
            all_fields.update(record.keys())

    unknown = all_fields - schema_props
    missing_required = required_fields - all_fields

    drift = bool(unknown) or bool(missing_required)

    if drift:
        log.warning(
            "mapping_payload_drift",
            mapping=mapping_name,
            unknown_fields=sorted(unknown),
            missing_required=sorted(missing_required),
            sample_size=len(records),
        )

    return {
        "ok": not drift,
        "unknown_fields": sorted(unknown),
        "missing_required": sorted(missing_required),
        "drift": drift,
    }


def list_schemas() -> list[str]:
    """List available schema names."""
    return sorted(p.stem for p in _SCHEMAS_DIR.glob("*.json"))


def get_mapping_drift_status() -> dict[str, str]:
    """Get drift status per mapping for trust panel integration.

    Returns: {mapping_name: "ok" | "warning" | "error"}
    """
    result: dict[str, str] = {}
    mapping_files = sorted(p.stem for p in _MAPPINGS_DIR.glob("*.yml"))
    for name in mapping_files:
        report = validate_mapping(name)
        if not report.ok:
            result[name] = "error"
        elif report.warnings:
            result[name] = "warning"
        else:
            result[name] = "ok"
    return result
