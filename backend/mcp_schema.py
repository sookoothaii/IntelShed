"""V4-44 MCP outputSchema generation and tool introspection.

Provides meaningful JSON Schema output definitions for each WorldBase MCP tool,
so MCP clients can validate responses and author JMESPath projections without
a trial ``tools/call``.

Also provides the ``describe_tool`` meta-tool: returns the full uncompressed
tool definition (useful when the compressed ``tools/list`` description is
ambiguous).

Feature flag: ``WORLDBASE_MCP_OUTPUT_SCHEMA=1`` (default on — spec compliance).

Pure Python, 0 VRAM.
"""

from __future__ import annotations

import os
from typing import Any


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def output_schema_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MCP_OUTPUT_SCHEMA", "1"))


# ---------------------------------------------------------------------------
# Output schemas per tool — manually curated for meaningful client introspection
# ---------------------------------------------------------------------------

_OUTPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "worldbase_health": {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "time": {"type": "string", "format": "date-time"},
            "ftm_ready": {"type": "boolean"},
            "feed_cache_count": {"type": "integer"},
            "mcp_auth_required": {"type": "boolean"},
        },
        "required": ["status", "time", "ftm_ready", "feed_cache_count"],
    },
    "worldbase_briefing_latest": {
        "type": "object",
        "properties": {
            "created_at": {"type": "string", "format": "date-time"},
            "style": {"type": "string"},
            "alert_count": {"type": "integer"},
            "fusion_hotspot_count": {"type": "integer"},
            "digest": {"type": "object"},
            "intel": {"type": "object"},
            "text_preview": {"type": "string"},
            "text_truncated": {"type": "boolean"},
            "text": {"type": "string"},
        },
    },
    "worldbase_briefing_generate": {
        "type": "object",
        "properties": {
            "generated": {"type": "boolean"},
            "created_at": {"type": "string", "format": "date-time"},
            "style": {"type": "string"},
            "lang": {"type": "string"},
            "alert_count": {"type": "integer"},
            "fusion_hotspot_count": {"type": "integer"},
            "digest": {"type": "object"},
            "text_preview": {"type": "string"},
            "text_truncated": {"type": "boolean"},
            "text_length": {"type": "integer"},
            "text": {"type": "string"},
        },
    },
    "worldbase_nodes": {
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "online": {"type": "boolean"},
                        "last_seen": {"type": "string"},
                        "gps": {"type": "object"},
                    },
                },
            },
        },
    },
    "worldbase_situations": {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "returned": {"type": "integer"},
            "generated_at": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object"}},
        },
    },
    "worldbase_fusion_hotspots": {
        "type": "object",
        "properties": {
            "top": {"type": "integer"},
            "hotspots": {"type": "array", "items": {"type": "object"}},
            "summary": {"type": "object"},
        },
    },
    "worldbase_intel_subgraph": {
        "type": "object",
        "properties": {
            "available": {"type": "boolean"},
            "nodes": {"type": "array", "items": {"type": "object"}},
            "edges": {"type": "array", "items": {"type": "object"}},
            "seeds": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
    },
    "worldbase_feed_sample": {
        "type": "object",
        "properties": {
            "feed_id": {"type": "string"},
            "source": {"type": "string"},
            "sample": {"type": ["object", "array"]},
        },
    },
    "worldbase_feed_allowlist": {
        "type": "object",
        "properties": {
            "feeds": {"type": "array", "items": {"type": "string"}},
        },
    },
    "worldbase_feed_status": {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "feeds": {"type": "object"},
            "feed_count": {"type": "integer"},
            "feeds_fresh": {"type": "integer"},
            "feeds_stale": {"type": "integer"},
            "feeds_error": {"type": "integer"},
        },
    },
    "worldbase_orchestrate": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "route": {"type": "string"},
            "phases": {"type": "object"},
            "result": {"type": "object"},
            "blackboard": {"type": "object"},
        },
    },
    "worldbase_agent_status": {
        "type": "object",
        "properties": {
            "orchestrator_enabled": {"type": "boolean"},
            "agents": {"type": "object"},
            "blackboard_enabled": {"type": "boolean"},
        },
    },
    "worldbase_entity_search": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean"},
            "count": {"type": "integer"},
            "entity": {"type": "object"},
            "entities": {"type": "array", "items": {"type": "object"}},
            "entity_id": {"type": "string"},
            "schema": {"type": "string"},
            "dataset": {"type": "string"},
        },
    },
    "worldbase_chat": {
        "type": "object",
        "properties": {
            "message": {"type": "object"},
            "done": {"type": "boolean"},
            "model": {"type": "string"},
            "provider": {"type": "string"},
            "error": {"type": "string"},
            "client_actions": {"type": "array"},
            "firewall_result": {"type": "object"},
        },
    },
    "worldbase_darkweb_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "results": {"type": "array", "items": {"type": "object"}},
            "count": {"type": "integer"},
            "ingest": {"type": "object"},
        },
    },
    "worldbase_domain_intel": {
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "crt": {"type": "array"},
            "wayback": {"type": "array"},
            "rdap": {"type": "object"},
            "ftm_ingest": {"type": "object"},
        },
    },
    "worldbase_globe_fly_to": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "error": {"type": "string"},
            "lat": {"type": "number"},
            "lon": {"type": "number"},
            "title": {"type": "string"},
        },
    },
    "worldbase_globe_toggle_layer": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "layer": {"type": "string"},
            "enabled": {"type": "boolean"},
        },
    },
    "worldbase_globe_get_camera": {
        "type": "object",
        "properties": {
            "camera": {"type": ["object", "null"]},
            "subscribers": {"type": "integer"},
        },
    },
    "worldbase_globe_layers": {
        "type": "object",
        "properties": {
            "layers": {"type": "array", "items": {"type": "string"}},
        },
    },
}


def get_output_schema(tool_name: str) -> dict[str, Any] | None:
    """Return the curated output JSON schema for *tool_name*, or None."""
    if not output_schema_enabled():
        return None
    return _OUTPUT_SCHEMAS.get(tool_name)


def all_output_schemas() -> dict[str, dict[str, Any]]:
    """Return the full mapping of tool_name → output schema."""
    if not output_schema_enabled():
        return {}
    return dict(_OUTPUT_SCHEMAS)


def describe_tool(tool_name: str, mcp_instance=None) -> dict[str, Any]:
    """Return the full uncompressed tool definition for *tool_name*.

    When *mcp_instance* is provided (the FastMCP server), the tool's
    input schema and description are pulled from the live registration.
    The output schema is always sourced from the curated registry above.
    """
    short = (
        tool_name.replace("worldbase_", "")
        if tool_name.startswith("worldbase_")
        else tool_name
    )
    out_schema = get_output_schema(tool_name)

    description: str = ""
    input_schema: dict[str, Any] = {}

    if mcp_instance is not None:
        try:
            tool = mcp_instance._tool_manager.get_tool(tool_name)
            description = tool.description or ""
            input_schema = tool.parameters or {}
        except Exception:
            pass

    return {
        "tool": tool_name,
        "short_name": short,
        "description": description,
        "inputSchema": input_schema,
        "outputSchema": out_schema,
        "jmespath_supported": True,
    }


def list_tool_names() -> list[str]:
    """Return all known tool names."""
    return sorted(_OUTPUT_SCHEMAS.keys())
