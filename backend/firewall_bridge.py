"""Optional HAK_GAL bridge — spare-parts warehouse, not a hard security boundary.

WorldBase baseline: prompt_guard.slim_prompt_scan (0 VRAM, always available).
HAK_GAL (:8001): optional enrichment when up — fail-open by default (chat + MCP).

Full HAK_GAL stack can consume ~16 GB VRAM; do not treat it as always-on.

See docs/FIREWALL.md and research/HAK_GAL_PICK_LIST.md.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any

import httpx
from fastapi import APIRouter, Depends

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/firewall", tags=["firewall"])

FIREWALL_HOST = os.getenv("FIREWALL_HOST", "localhost:8001").strip()
FIREWALL_URL = f"http://{FIREWALL_HOST}/v1/detect" if FIREWALL_HOST else ""
TIMEOUT = 30.0  # HAK_GAL may need time for lazy ONNX loading on first request
RISK_THRESHOLD = float(os.getenv("WORLDBASE_FIREWALL_RISK_THRESHOLD", "0.7"))
FIREWALL_USER_ID = os.getenv("WORLDBASE_FIREWALL_USER_ID", "operator").strip() or "operator"
FIREWALL_TRACE = os.getenv("WORLDBASE_FIREWALL_TRACE", "0").strip().lower() in ("1", "true", "yes")
FIREWALL_SHADOW = os.getenv("WORLDBASE_FIREWALL_SHADOW", "0").strip().lower() in ("1", "true", "yes")
FIREWALL_MCP = os.getenv("WORLDBASE_FIREWALL_MCP", "0").strip().lower() in ("1", "true", "yes")
FIREWALL_MCP_FAIL_CLOSED = os.getenv("WORLDBASE_FIREWALL_MCP_FAIL_CLOSED", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
_HISTORY_MAX = int(os.getenv("WORLDBASE_FIREWALL_HISTORY_MAX", "50"))
_TOOL_ARGS_MAX = int(os.getenv("WORLDBASE_FIREWALL_TOOL_ARGS_MAX", "6000"))

_history: deque[dict[str, Any]] = deque(maxlen=max(1, _HISTORY_MAX))


class FirewallBlockedError(PermissionError):
    """MCP or explicit gate — request blocked by HAK_GAL."""

    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(detail.get("message", "Firewall blocked"))


class FirewallUnavailableError(PermissionError):
    """MCP fail-closed — HAK_GAL not reachable."""

    def __init__(self, detail: dict[str, Any]):
        self.detail = detail
        super().__init__(detail.get("message", "Firewall unavailable"))


def firewall_configured() -> bool:
    """True when FIREWALL_HOST is set (bridge may still be unreachable)."""
    return bool(FIREWALL_HOST)


def firewall_mcp_enabled() -> bool:
    return firewall_configured() and FIREWALL_MCP


def _extract_user_text(messages: list[dict]) -> str:
    """Return the last user message text for scanning."""
    texts = []
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            texts.append(str(m["content"]))
    return texts[-1] if texts else ""


def should_block_firewall(data: dict | None) -> bool:
    """Apply HAK_GAL primary flags, then env risk threshold fallback."""
    if not data:
        return False
    if data.get("blocked") or data.get("should_block"):
        return True
    risk = data.get("risk_score")
    if risk is None:
        return False
    try:
        return float(risk) > RISK_THRESHOLD
    except (TypeError, ValueError):
        return False


def _build_detect_body(
    text: str,
    *,
    session_id: str | None,
    source_tool: str,
    user_id: str | None,
    context: dict | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "text": text,
        "session_id": (session_id or "").strip() or "worldbase-anonymous",
        "source_tool": source_tool or "worldbase_chat",
        "user_id": (user_id or FIREWALL_USER_ID).strip() or FIREWALL_USER_ID,
        "routing_mode": "production",
    }
    if context:
        body["context"] = context
    return body


def _tool_scan_text(tool_name: str, arguments: dict | None) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    try:
        args_json = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        args_json = str(args)
    if len(args_json) > _TOOL_ARGS_MAX:
        args_json = args_json[:_TOOL_ARGS_MAX] + "..."
    return f"MCP tool {tool_name}: {args_json}"


def record_firewall_decision(
    *,
    source: str,
    source_tool: str,
    session_id: str | None,
    text_preview: str,
    scan: dict[str, Any],
    blocked: bool,
    shadow: bool = False,
) -> dict[str, Any]:
    data = scan.get("data") if isinstance(scan.get("data"), dict) else {}
    entry = {
        "timestamp": time.time(),
        "source": source,
        "source_tool": source_tool,
        "session_id": session_id,
        "text_preview": text_preview[:500],
        "blocked": blocked,
        "shadow": shadow,
        "available": scan.get("_available", False),
        "risk_score": data.get("risk_score"),
        "category": data.get("category"),
        "matched_patterns": (data.get("matched_patterns") or [])[:5],
        "decision_trace": scan.get("decision_trace") if FIREWALL_TRACE else None,
    }
    _history.appendleft(entry)
    return entry


def get_firewall_history(limit: int = 20) -> list[dict[str, Any]]:
    n = max(1, min(limit, _HISTORY_MAX))
    return list(_history)[:n]


def _slim_meta_for_ui(slim: dict[str, Any]) -> dict[str, Any]:
    matched = slim.get("matched")
    return {
        "blocked": True,
        "should_block": True,
        "engine": slim.get("engine", "worldbase_slim"),
        "category": slim.get("label"),
        "matched_patterns": [matched] if matched else [],
        "risk_score": 1.0,
        "source": "chat_slim",
    }


async def guard_chat_user_text(
    text: str,
    *,
    session_id: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Slim guard first, then optional HAK_GAL. Returns (firewall_meta, block_payload)."""
    from prompt_guard import slim_guard_enabled, slim_prompt_scan

    sid = (str(session_id).strip() or None) if session_id else None

    if slim_guard_enabled() and text.strip():
        slim = slim_prompt_scan(text, mcp=False)
        if slim.get("blocked"):
            record_firewall_decision(
                source="chat_slim",
                source_tool="worldbase_chat",
                session_id=sid,
                text_preview=text,
                scan={"_available": True, "data": {"blocked": True, "category": slim.get("label")}},
                blocked=True,
            )
            meta = _slim_meta_for_ui(slim)
            return meta, {
                "message": {
                    "role": "assistant",
                    "content": (
                        "⚠️ **SLIM GUARD BLOCK**\n\n"
                        "This message was flagged by the WorldBase slim prompt guard (0 VRAM).\n"
                        f"Category: {meta.get('category', '—')}\n"
                        f"Matched: {', '.join(meta.get('matched_patterns') or []) or '—'}\n\n"
                        "Set `firewall: false` to bypass (not recommended)."
                    ),
                },
                "done": True,
                "firewall_blocked": True,
                "firewall_meta": meta,
            }

    scan = await firewall_scan(
        text,
        session_id=sid,
        source_tool="worldbase_chat",
        record=True,
    )
    data = scan.get("data") if isinstance(scan.get("data"), dict) else None
    if data and should_block_firewall(data):
        return data, {
            "message": {
                "role": "assistant",
                "content": (
                    "⚠️ **FIREWALL BLOCK**\n\n"
                    "This message was flagged by the LLM-Security-Firewall.\n"
                    f"Risk Score: {data.get('risk_score', '—')}\n"
                    f"Matched: {', '.join(data.get('matched_patterns', [])[:3]) or '—'}\n\n"
                    "Set `firewall: false` to bypass (not recommended)."
                ),
            },
            "done": True,
            "firewall_blocked": True,
            "firewall_meta": data,
        }
    return data, None


async def firewall_scan(
    text: str,
    *,
    session_id: str | None = None,
    source_tool: str = "worldbase_chat",
    user_id: str | None = None,
    context: dict | None = None,
    record: bool = False,
) -> dict:
    """Scan text through the external firewall. Returns {_available: false} on failure."""
    if not text.strip() or not firewall_configured():
        return {}
    headers = {"Content-Type": "application/json"}
    if FIREWALL_TRACE:
        headers["X-Logging"] = "true"
    body = _build_detect_body(
        text,
        session_id=session_id,
        source_tool=source_tool,
        user_id=user_id,
        context=context,
    )
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(FIREWALL_URL, json=body, headers=headers)
            if r.status_code != 200:
                out = {"_error": f"firewall returned {r.status_code}", "_available": False}
                if record:
                    record_firewall_decision(
                        source="scan",
                        source_tool=source_tool,
                        session_id=body["session_id"],
                        text_preview=text,
                        scan=out,
                        blocked=False,
                    )
                return out
            out = {**r.json(), "_available": True, "_request": body}
            if record:
                record_firewall_decision(
                    source="scan",
                    source_tool=source_tool,
                    session_id=body["session_id"],
                    text_preview=text,
                    scan=out,
                    blocked=should_block_firewall(out.get("data")),
                    shadow=FIREWALL_SHADOW,
                )
            return out
    except Exception:
        out = {"_available": False}
        if record:
            record_firewall_decision(
                source="scan",
                source_tool=source_tool,
                session_id=body["session_id"],
                text_preview=text,
                scan=out,
                blocked=False,
            )
        return out


async def firewall_scan_tool(
    tool_name: str,
    arguments: dict | None = None,
    *,
    session_id: str | None = None,
) -> dict:
    """Scan MCP tool invocation via HAK_GAL (source_tool=worldbase_mcp)."""
    text = _tool_scan_text(tool_name, arguments)
    sid = (session_id or "").strip() or "worldbase-mcp"
    return await firewall_scan(
        text,
        session_id=sid,
        source_tool="worldbase_mcp",
        context={"tool_name": tool_name, "arguments": arguments or {}},
        record=True,
    )


async def ensure_mcp_tool_allowed(
    tool_name: str,
    arguments: dict | None = None,
    *,
    session_id: str | None = None,
) -> dict | None:
    """Gate MCP write tools: slim guard first, optional HAK_GAL scan (fail-open)."""
    from prompt_guard import slim_guard_mcp_enabled, slim_prompt_scan

    text = _tool_scan_text(tool_name, arguments)

    if slim_guard_mcp_enabled():
        slim = slim_prompt_scan(text, mcp=True)
        if slim.get("blocked"):
            record_firewall_decision(
                source="mcp_slim",
                source_tool="worldbase_mcp",
                session_id=session_id or "worldbase-mcp",
                text_preview=text,
                scan={"_available": True, "data": {"blocked": True, "category": slim.get("label")}},
                blocked=True,
            )
            raise FirewallBlockedError(
                {
                    "message": "Slim prompt guard blocked MCP tool invocation",
                    "tool": tool_name,
                    "blocked": True,
                    "engine": "worldbase_slim",
                    "label": slim.get("label"),
                    "matched": slim.get("matched"),
                }
            )

    if not firewall_mcp_enabled():
        return None

    scan = await firewall_scan_tool(tool_name, arguments, session_id=session_id)
    data = scan.get("data") if isinstance(scan.get("data"), dict) else {}
    would_block = should_block_firewall(data)

    if not scan.get("_available"):
        if FIREWALL_MCP_FAIL_CLOSED:
            raise FirewallUnavailableError(
                {
                    "message": "HAK_GAL unreachable — MCP write blocked (fail-closed env)",
                    "tool": tool_name,
                    "host": FIREWALL_HOST,
                }
            )
        return None

    if would_block and not FIREWALL_SHADOW:
        raise FirewallBlockedError(
            {
                "message": "HAK_GAL flagged MCP tool invocation",
                "tool": tool_name,
                "blocked": True,
                "engine": "hak_gal",
                "risk_score": data.get("risk_score"),
                "category": data.get("category"),
                "matched_patterns": (data.get("matched_patterns") or [])[:5],
            }
        )

    return data


@router.get("/status")
async def firewall_status():
    """Return whether the external firewall is reachable."""
    result = await firewall_scan(
        "hello",
        session_id="worldbase-status-probe",
        source_tool="worldbase_status",
    )
    available = result.get("_available", False)
    from prompt_guard import slim_guard_enabled, slim_guard_mcp_enabled, slim_pattern_count

    phase = "B" if (firewall_mcp_enabled() or slim_guard_mcp_enabled()) else "A"

    return {
        "status": "healthy" if available else "unreachable",
        "enabled": firewall_configured(),
        "reachable": available,
        "host": FIREWALL_HOST or None,
        "url": FIREWALL_URL or None,
        "version": "HAK_GAL v9.4+",
        "risk_threshold": RISK_THRESHOLD,
        "trace_enabled": FIREWALL_TRACE,
        "shadow_mode": FIREWALL_SHADOW,
        "mcp_gate_enabled": firewall_mcp_enabled(),
        "mcp_fail_closed": FIREWALL_MCP_FAIL_CLOSED,
        "slim_guard": slim_guard_enabled(),
        "slim_guard_mcp": slim_guard_mcp_enabled(),
        "slim_pattern_count": slim_pattern_count(),
        "slim_pattern_count_mcp": slim_pattern_count(mcp=True),
        "history_count": len(_history),
        "phase": phase,
        "note": "HAK_GAL is optional enrichment; slim guard is the WorldBase baseline.",
    }


@router.get("/history")
async def firewall_history(limit: int = 20):
    """Recent firewall decisions (in-memory ring buffer)."""
    return {"count": len(_history), "items": get_firewall_history(limit)}


@router.post("/test")
async def firewall_test(payload: dict, _auth: str | None = Depends(verify_lan_auth)):
    """Test a query — slim guard first, then optional HAK_GAL."""
    query = payload.get("query", "").strip()
    if not query:
        return {"error": "No query provided"}

    from prompt_guard import slim_guard_enabled, slim_prompt_scan

    session_id = payload.get("session_id") or payload.get("chat_session_id")

    if slim_guard_enabled():
        slim = slim_prompt_scan(query, mcp=False)
        if slim.get("blocked"):
            meta = _slim_meta_for_ui(slim)
            record_firewall_decision(
                source="slim_test",
                source_tool=str(payload.get("source_tool") or "worldbase_test"),
                session_id=str(session_id) if session_id else None,
                text_preview=query,
                scan={"_available": True, "data": {"blocked": True, "category": slim.get("label")}},
                blocked=True,
            )
            return {**meta, "would_block": True, "query": query}

    if not firewall_configured():
        return {
            "blocked": False,
            "would_block": False,
            "engine": "worldbase_slim",
            "note": "HAK_GAL not configured; slim guard passed",
            "query": query,
        }

    result = await firewall_scan(
        query,
        session_id=session_id,
        source_tool=str(payload.get("source_tool") or "worldbase_test"),
        user_id=payload.get("user_id"),
        context=payload.get("context") if isinstance(payload.get("context"), dict) else None,
        record=True,
    )
    if not result.get("_available"):
        return {
            "blocked": False,
            "would_block": False,
            "engine": "worldbase_slim",
            "note": "HAK_GAL unreachable; slim guard passed",
            "host": FIREWALL_HOST,
            "query": query,
        }
    data = result.get("data", result)
    if isinstance(data, dict):
        data = {**data, "would_block": should_block_firewall(data), "query": query}
    return data
