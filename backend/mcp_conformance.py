"""MCP protocol conformance checks and tool annotations (E-06).

Provides:
- Protocol version checking (MCP spec version compatibility)
- Tool annotations (readOnlyHint, destructiveHint, idempotentHint) per MCP spec
- Output budget enforcement (max response size in bytes)

Feature flag: WORLDBASE_MCP_CONFORMANCE=1 (default off — opt-in).
"""

from __future__ import annotations

import json
import os
from typing import Any

from structured_log import get_logger

log = get_logger("mcp_conformance")

# MCP protocol version we claim compatibility with.
MCP_PROTOCOL_VERSION = "2025-06-18"

# Supported protocol versions (newest first).
_SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def conformance_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MCP_CONFORMANCE", "0"))


# ---------------------------------------------------------------------------
# Tool annotations — per MCP spec 2025-06-18 § Tool Annotations
# ---------------------------------------------------------------------------

_TOOL_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "worldbase_health": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_briefing_latest": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_briefing_generate": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "worldbase_nodes": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_situations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_fusion_hotspots": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_intel_subgraph": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_feed_sample": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_feed_allowlist": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_feed_status": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_orchestrate": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "worldbase_agent_status": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_entity_search": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_chat": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "worldbase_darkweb_search": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
    },
    "worldbase_domain_intel": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_breach_status": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_breach_check_password": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_cyber_ip_lookup": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_intel_entities": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_intel_edges": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_extract_iocs": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_globe_fly_to": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_globe_toggle_layer": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_globe_get_camera": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_globe_layers": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_describe_tool": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
    "worldbase_list_tools": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    },
}


def get_tool_annotations(tool_name: str) -> dict[str, bool]:
    """Return MCP spec annotations for a tool. Defaults to read-only if unknown."""
    return _TOOL_ANNOTATIONS.get(
        tool_name,
        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    )


def all_tool_annotations() -> dict[str, dict[str, bool]]:
    """Return the full annotation mapping."""
    return dict(_TOOL_ANNOTATIONS)


# ---------------------------------------------------------------------------
# Protocol version checking
# ---------------------------------------------------------------------------


def check_protocol_version(client_version: str | None) -> dict[str, Any]:
    """Check if a client's requested protocol version is supported.

    Returns a dict with:
    - supported: bool
    - server_version: our protocol version
    - client_version: what the client requested
    - negotiated: the version to use (client's if supported, else server's)
    """
    server_ver = MCP_PROTOCOL_VERSION
    if not client_version:
        return {
            "supported": True,
            "server_version": server_ver,
            "client_version": None,
            "negotiated": server_ver,
        }
    supported = client_version in _SUPPORTED_VERSIONS
    return {
        "supported": supported,
        "server_version": server_ver,
        "client_version": client_version,
        "negotiated": client_version if supported else server_ver,
    }


# ---------------------------------------------------------------------------
# Output budget enforcement
# ---------------------------------------------------------------------------

_DEFAULT_OUTPUT_BUDGET = int(
    os.getenv("WORLDBASE_MCP_OUTPUT_BUDGET_BYTES", "1048576")
)  # 1 MB


class OutputBudgetExceeded(Exception):
    """Raised when a tool response exceeds the configured byte budget."""

    def __init__(self, tool: str, size: int, budget: int) -> None:
        self.tool = tool
        self.size = size
        self.budget = budget
        super().__init__(
            f"MCP output budget exceeded for '{tool}': {size} bytes > {budget} bytes"
        )


def enforce_output_budget(
    tool_name: str, response: Any, budget: int | None = None
) -> Any:
    """Check if a response exceeds the output budget. Raises if over.

    Returns the response unchanged if within budget.
    If conformance is disabled, returns immediately without checking.
    """
    if not conformance_enabled():
        return response

    limit = budget or _DEFAULT_OUTPUT_BUDGET
    try:
        serialized = json.dumps(response, default=str, ensure_ascii=False)
        size = len(serialized.encode("utf-8"))
    except Exception:
        return response

    if size > limit:
        log.warning(
            "mcp_output_budget_exceeded",
            tool=tool_name,
            size=size,
            budget=limit,
        )
        raise OutputBudgetExceeded(tool_name, size, limit)

    return response


# ---------------------------------------------------------------------------
# Conformance summary (for /api/mcp/conformance endpoint)
# ---------------------------------------------------------------------------


def get_conformance_status() -> dict[str, Any]:
    """Full conformance dashboard: protocol version, annotations, output budget."""
    return {
        "enabled": conformance_enabled(),
        "protocol_version": MCP_PROTOCOL_VERSION,
        "supported_versions": list(_SUPPORTED_VERSIONS),
        "output_budget_bytes": _DEFAULT_OUTPUT_BUDGET,
        "tool_count": len(_TOOL_ANNOTATIONS),
        "tools_with_annotations": sorted(_TOOL_ANNOTATIONS.keys()),
    }
