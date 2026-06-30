"""WorldBase MCP surface — Streamable HTTP read + write tools for Cursor / Claude.

Reuses the same Python paths as chat_tools and REST routes (no HTTP loopback).
Mount: GET/POST /api/mcp (Streamable HTTP). Disable with WORLDBASE_MCP=0.
Write tools (briefing generate) gated by WORLDBASE_MCP_WRITE=1 (default on).
"""

from __future__ import annotations

import contextvars
import hmac
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from structured_log import get_logger

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from auth.security import API_KEY, INGEST_TOKEN, lan_auth_required
from mcp.server.fastmcp import FastMCP

import mcp_jmespath
import mcp_schema

try:
    from auth.audit import record_audit_event
except Exception:

    def record_audit_event(*, action: str, **kw) -> None:  # type: ignore[misc]
        pass


log = get_logger(__name__)

# Feeds allowed for worldbase_feed_sample (cache key or live bridge id).
FEED_SAMPLE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "aircraft",
        "airquality",
        "earthquakes",
        "eonet",
        "gdacs",
        "gdacs_v2",
        "geopolitics",
        "markets",
        "military",
        "outages",
        "pegel",
        "reliefweb",
        "spaceweather",
        "wildfires",
        "energy_de",
        "newsdata",
    }
)

_TEXT_PREVIEW_CHARS = 4000
_mcp_session_cm = None

# Context var: role of the current MCP caller (set by _MCPAuthMiddleware).
_mcp_role: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_mcp_role", default=None
)

# Default per-tool RBAC policy: tool short name (without worldbase_ prefix) → required role.
# "none" = no role check. Read tools default to "readonly", write tools to "operator".
_DEFAULT_MCP_TOOL_POLICY: dict[str, str] = {
    "health": "readonly",
    "briefing_latest": "readonly",
    "nodes": "readonly",
    "situations": "readonly",
    "fusion_hotspots": "readonly",
    "intel_subgraph": "readonly",
    "feed_sample": "readonly",
    "feed_allowlist": "readonly",
    "feed_status": "readonly",
    "entity_search": "readonly",
    "agent_status": "readonly",
    "globe_get_camera": "readonly",
    "globe_layers": "readonly",
    "briefing_generate": "operator",
    "globe_fly_to": "operator",
    "globe_toggle_layer": "operator",
    "darkweb_search": "readonly",
    "domain_intel": "readonly",
    "breach_status": "readonly",
    "breach_check_password": "readonly",
    "orchestrate": "readonly",
    "chat": "readonly",
    "describe_tool": "readonly",
    "list_tools": "readonly",
}

_ROLE_LEVELS: dict[str, int] = {
    "admin": 4,
    "operator": 3,
    "viewer": 1,
    "readonly": 1,
    "node": 1,
}


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def mcp_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MCP", "1"))


def mcp_write_enabled() -> bool:
    return mcp_enabled() and _truthy(os.getenv("WORLDBASE_MCP_WRITE", "1"))


def mcp_globe_enabled() -> bool:
    if not mcp_write_enabled():
        return False
    import agent_bus

    return agent_bus.agent_bus_enabled()


def mcp_policy_enabled() -> bool:
    """Per-tool RBAC policy enforcement (opt-in via WORLDBASE_MCP_POLICY=1)."""
    try:
        from config import get_config

        return get_config().mcp_policy_enabled
    except Exception:
        return _truthy(os.getenv("WORLDBASE_MCP_POLICY", "0"))


def _tool_short_name(tool_name: str) -> str:
    """Strip the 'worldbase_' prefix from a tool name."""
    if tool_name.startswith("worldbase_"):
        return tool_name[len("worldbase_") :]
    return tool_name


def _get_mcp_tool_required_role(tool_name: str) -> str:
    """Look up required role for a tool: env override → default policy → 'none'."""
    short = _tool_short_name(tool_name)
    env_val = os.getenv(f"WORLDBASE_MCP_POLICY_{short}", "").strip().lower()
    if env_val in ("operator", "viewer", "readonly", "node", "admin", "none"):
        return env_val
    return _DEFAULT_MCP_TOOL_POLICY.get(short, "none")


def _normalize_briefing_lang(lang: str | None) -> str | None:
    if lang is None or not str(lang).strip():
        return None
    norm = str(lang).strip().lower()
    if norm.startswith("de"):
        return "de"
    if norm.startswith("en"):
        return "en"
    raise ValueError(f"lang must be 'en' or 'de', got {lang!r}")


def mcp_auth_required() -> bool:
    """Require X-API-Key when LAN-bound or when WORLDBASE_API_KEY is set."""
    return lan_auth_required()


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _trim_payload(data: dict | list | None, limit: int) -> dict | list | None:
    if data is None:
        return None
    if isinstance(data, list):
        return data[:limit]
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for key in (
        "items",
        "alerts",
        "states",
        "earthquakes",
        "articles",
        "nodes",
        "cells",
    ):
        if key in out and isinstance(out[key], list):
            out[key] = out[key][:limit]
    return out


async def fetch_health() -> dict[str, Any]:
    """Fast stack liveness (no full /api/health feed parse)."""
    ftm_ready = False
    try:
        import ftm_store

        ftm_ready = bool((ftm_store.store_status() or {}).get("ready"))
    except Exception:
        pass

    feed_count = 0
    try:
        conn = sqlite3.connect(_db_path(), timeout=2.0)
        feed_count = int(conn.execute("SELECT COUNT(*) FROM feed_cache").fetchone()[0])
        conn.close()
    except Exception:
        pass

    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "ftm_ready": ftm_ready,
        "feed_cache_count": feed_count,
        "mcp_auth_required": mcp_auth_required(),
    }


async def fetch_briefing_latest(*, include_full_text: bool = False) -> dict[str, Any]:
    import node_sync

    brief = await node_sync.latest_briefing()
    text = brief.get("text") or ""
    digest = brief.get("digest") or {}
    intel = brief.get("intel") or {}
    out: dict[str, Any] = {
        "created_at": brief.get("created_at"),
        "style": brief.get("style"),
        "alert_count": len(brief.get("alerts") or []),
        "fusion_hotspot_count": len(brief.get("fusion_hotspots") or []),
        "digest": digest,
        "intel": {
            "enabled": intel.get("enabled"),
            "count": intel.get("count", 0),
            "by_bucket": intel.get("by_bucket") or {},
            "window_hours": intel.get("window_hours"),
        },
        "text_preview": text[:_TEXT_PREVIEW_CHARS],
        "text_truncated": len(text) > _TEXT_PREVIEW_CHARS,
    }
    if include_full_text:
        out["text"] = text
    return out


async def trigger_briefing_generate(
    *,
    lang: str | None = None,
    include_full_text: bool = False,
) -> dict[str, Any]:
    """Run full 24h briefing pipeline (Ollama + SQLite store). MCP write path."""
    if not mcp_write_enabled():
        raise PermissionError("MCP write tools disabled (set WORLDBASE_MCP_WRITE=1)")

    resolved_lang = _normalize_briefing_lang(lang)
    import node_sync

    result = await node_sync.generate_briefing_internal(lang=resolved_lang)
    text = result.get("text") or ""
    digest = result.get("digest") or {}
    out: dict[str, Any] = {
        "generated": True,
        "created_at": result.get("created_at"),
        "style": "security_advisor_24h",
        "lang": digest.get("lang"),
        "alert_count": len(result.get("alerts") or []),
        "fusion_hotspot_count": len(result.get("fusion_hotspots") or []),
        "digest": digest,
        "text_preview": text[:_TEXT_PREVIEW_CHARS],
        "text_truncated": len(text) > _TEXT_PREVIEW_CHARS,
        "text_length": len(text),
    }
    if include_full_text:
        out["text"] = text
    return out


async def fetch_nodes() -> dict[str, Any]:
    import node_sync

    return await node_sync.list_nodes()


async def fetch_situations(*, limit: int = 20) -> dict[str, Any]:
    from situations import unified_situations

    result = await unified_situations()
    items = (result.get("items") or [])[: max(1, min(limit, 50))]
    return {
        "count": result.get("count"),
        "returned": len(items),
        "generated_at": result.get("generated_at"),
        "items": items,
    }


async def fetch_fusion_hotspots(*, top: int = 10) -> dict[str, Any]:
    import fusion_heatmap

    top = max(1, min(top, 25))
    hotspots, summary, _deltas = await fusion_heatmap.top_hotspots_for_llm(top=top)
    return {
        "top": top,
        "hotspots": hotspots,
        "summary": summary,
    }


async def fetch_feed_sample(feed_id: str, limit: int = 5) -> dict[str, Any]:
    feed_id = (feed_id or "").strip().lower()
    if feed_id not in FEED_SAMPLE_ALLOWLIST:
        allowed = sorted(FEED_SAMPLE_ALLOWLIST)
        raise ValueError(f"Unknown feed_id {feed_id!r}. Allowed: {', '.join(allowed)}")
    limit = max(1, min(limit, 25))

    import feed_registry

    cached = await feed_registry.async_read_sqlite(feed_id)
    if cached is not None:
        return {
            "feed_id": feed_id,
            "source": "feed_cache",
            "sample": _trim_payload(cached, limit),
        }

    live = await _fetch_feed_live(feed_id, limit)
    return {
        "feed_id": feed_id,
        "source": "live_bridge",
        "sample": live,
    }


async def _fetch_feed_live(feed_id: str, limit: int) -> dict[str, Any]:
    if feed_id == "earthquakes":
        from routes.core_feeds import get_earthquakes

        data = await get_earthquakes(period="day", magnitude="2.5")
        return _trim_payload(data, limit) or {}

    if feed_id in ("gdacs", "gdacs_v2"):
        import feeds_extra

        data = await feeds_extra.gdacs_alerts()
        return _trim_payload(data, limit) or {}

    if feed_id == "aircraft":
        import aircraft_provider

        data, source = await aircraft_provider.fetch_live_states(timeout=12.0)
        trimmed = _trim_payload(data, limit) or {}
        if isinstance(trimmed, dict):
            trimmed["source"] = source
        return trimmed

    if feed_id == "wildfires":
        import nasa_firms

        entry = await nasa_firms._load_firms_cache()
        fires = nasa_firms._all_fires_from_cache(entry)[:limit]
        return {
            "count": len(fires),
            "fires": fires,
            "source": entry.get("source"),
            "updated": entry.get("updated"),
        }

    if feed_id == "pegel":
        import pegel_bridge

        data = await pegel_bridge.get_pegel()
        return _trim_payload(data, limit) or {}

    if feed_id == "newsdata":
        import newsdata_bridge

        data = await newsdata_bridge.get_newsdata(limit=limit)
        return _trim_payload(data, limit) or {}

    feeds_extra_map = {
        "markets": "markets",
        "military": "military_aircraft",
        "geopolitics": "geopolitics",
        "spaceweather": "space_weather",
        "airquality": "air_quality",
    }
    if feed_id in feeds_extra_map:
        import feeds_extra

        fn = getattr(feeds_extra, feeds_extra_map[feed_id])
        data = await fn()
        return _trim_payload(data, limit) or {}

    return {
        "error": "not_cached",
        "feed_id": feed_id,
        "hint": "Hit the REST feed once or wait for background refresh; cache is empty.",
    }


# ---------------------------------------------------------------------------
# FastMCP tool registration
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "WorldBase",
    instructions=(
        "WorldBase intelligence API: briefing read/generate, Pi nodes, situations, "
        "fusion hotspots, feed samples, and optional globe control (Agent Bus). "
        "Globe fly_to/toggle_layer require WORLDBASE_AGENT_BUS=1 and an open HUD tab."
    ),
    streamable_http_path="/",
    stateless_http=True,
    transport_security=None,
)


@mcp.tool(name="worldbase_health")
@mcp_jmespath.with_jmespath
async def worldbase_health() -> dict[str, Any]:
    """WorldBase liveness: time, FtM readiness, feed cache count."""
    await _gate_mcp_tool("worldbase_health", {}, write=False)
    return await fetch_health()


@mcp.tool(name="worldbase_briefing_latest")
@mcp_jmespath.with_jmespath
async def worldbase_briefing_latest(include_full_text: bool = False) -> dict[str, Any]:
    """Latest 24h security briefing (digest, intel summary, text preview)."""
    await _gate_mcp_tool("worldbase_briefing_latest", {}, write=False)
    return await fetch_briefing_latest(include_full_text=include_full_text)


@mcp.tool(name="worldbase_nodes")
@mcp_jmespath.with_jmespath
async def worldbase_nodes() -> dict[str, Any]:
    """Edge nodes (Pi online state, mesh GPS, sensors snapshot)."""
    await _gate_mcp_tool("worldbase_nodes", {}, write=False)
    return await fetch_nodes()


@mcp.tool(name="worldbase_situations")
@mcp_jmespath.with_jmespath
async def worldbase_situations(limit: int = 20) -> dict[str, Any]:
    """Unified situation board (correlations, anomalies, GDACS, pegel, sensors)."""
    await _gate_mcp_tool("worldbase_situations", {"limit": limit}, write=False)
    return await fetch_situations(limit=limit)


@mcp.tool(name="worldbase_fusion_hotspots")
@mcp_jmespath.with_jmespath
async def worldbase_fusion_hotspots(top: int = 10) -> dict[str, Any]:
    """Top fusion heatmap cells ranked for situational awareness."""
    await _gate_mcp_tool("worldbase_fusion_hotspots", {"top": top}, write=False)
    return await fetch_fusion_hotspots(top=top)


@mcp.tool(name="worldbase_intel_subgraph")
@mcp_jmespath.with_jmespath
async def worldbase_intel_subgraph(
    hops: int = 2,
    window_hours: int = 24,
    bbox: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """2-hop FtM subgraph around operator bbox (who/what links near home region)."""
    await _gate_mcp_tool(
        "worldbase_intel_subgraph",
        {"hops": hops, "window_hours": window_hours, "bbox": bbox, "region": region},
        write=False,
    )
    import intel_subgraph

    parsed = intel_subgraph.parse_bbox(bbox)
    try:
        return intel_subgraph.build_subgraph(
            bbox=parsed,
            region=region,
            hops=hops,
            window_hours=window_hours,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": str(exc)[:200],
            "error": str(exc)[:200],
            "nodes": [],
            "edges": [],
            "seeds": [],
        }


@mcp.tool(name="worldbase_feed_sample")
@mcp_jmespath.with_jmespath
async def worldbase_feed_sample(feed_id: str, limit: int = 5) -> dict[str, Any]:
    """Sample rows from an allowlisted feed (cache first, then live bridge)."""
    await _gate_mcp_tool(
        "worldbase_feed_sample", {"feed_id": feed_id, "limit": limit}, write=False
    )
    return await fetch_feed_sample(feed_id, limit=limit)


@mcp.tool(name="worldbase_feed_allowlist")
@mcp_jmespath.with_jmespath
async def worldbase_feed_allowlist() -> dict[str, Any]:
    """List feed_id values valid for worldbase_feed_sample."""
    await _gate_mcp_tool("worldbase_feed_allowlist", {}, write=False)
    return {"feeds": sorted(FEED_SAMPLE_ALLOWLIST)}


@mcp.tool(name="worldbase_orchestrate")
@mcp_jmespath.with_jmespath
async def worldbase_orchestrate(
    query: str,
    route: str | None = None,
) -> dict[str, Any]:
    """Run the P3+ multi-agent orchestrator (coverage → retrieval → spatial → corroboration → synthesis).

    Rule-based dispatcher, 0 VRAM. Set WORLDBASE_AGENT_ORCHESTRATOR=1 to enable.
    """
    await _gate_mcp_tool(
        "worldbase_orchestrate", {"query": query, "route": route}, write=False
    )
    import agent_orchestrator

    return await agent_orchestrator.orchestrate(query, route=route)


@mcp.tool(name="worldbase_agent_status")
@mcp_jmespath.with_jmespath
async def worldbase_agent_status() -> dict[str, Any]:
    """Status of the multi-agent orchestrator and the Agent Bus."""
    await _gate_mcp_tool("worldbase_agent_status", {}, write=False)
    import agent_orchestrator

    return await agent_orchestrator.agent_status()


@mcp.tool(name="worldbase_entity_search")
@mcp_jmespath.with_jmespath
async def worldbase_entity_search(
    entity_id: str | None = None,
    schema: str | None = None,
    dataset: str | None = None,
    limit: int = 50,
    full: bool = False,
) -> dict[str, Any]:
    """Search FollowTheMoney entities by ID, schema, or dataset. Returns recent entities when no filter given.

    Args:
        entity_id: Exact entity ID lookup (returns single entity with statements + edges when full=True).
        schema: Filter by FtM schema (e.g. Person, Organization, Address, Mention).
        dataset: Filter by dataset name (e.g. gdelt, darkweb, domain_intel).
        limit: Max entities to return (1–500, default 50).
        full: Include statements, edges, and neighbours (only for entity_id lookup).
    """
    await _gate_mcp_tool(
        "worldbase_entity_search",
        {
            "entity_id": entity_id,
            "schema": schema,
            "dataset": dataset,
            "limit": limit,
            "full": full,
        },
        write=False,
    )
    import ftm_query

    limit = max(1, min(limit, 500))

    if entity_id:
        if full:
            ent = ftm_query.get_entity_full(entity_id)
        else:
            ent = ftm_query.get_entity(entity_id)
        if not ent:
            return {"found": False, "entity_id": entity_id}
        return {"found": True, "entity": ent}

    if schema:
        entities = ftm_query.list_entities_for_resolution(
            schemas=[schema], limit=limit, dataset=dataset
        )
        return {
            "count": len(entities),
            "entities": entities[:limit],
            "schema": schema,
            "dataset": dataset,
        }

    result = ftm_query.list_entities_recent(limit=limit, dataset=dataset)
    return {
        "count": result["count"],
        "entities": result["entities"],
        "dataset": dataset,
    }


@mcp.tool(name="worldbase_chat")
@mcp_jmespath.with_jmespath
async def worldbase_chat(
    message: str,
    context: bool = True,
    use_tools: bool = True,
    model: str | None = None,
    provider: str = "nvidia",
) -> dict[str, Any]:
    """Chat with WorldBase RAG pipeline (NVIDIA step-ai default). Returns assistant response with optional tool actions.

    Args:
        message: User message / query.
        context: Inject live WorldBase state as system context (default True).
        use_tools: Enable tool use (geocode, verify_claim, etc.) for Ollama (default True).
        model: Override chat model (default: stepfun-ai/step-3.7-flash via NVIDIA NIM).
        provider: LLM provider (nvidia, ollama, openai, groq, openrouter).
    """
    await _gate_mcp_tool(
        "worldbase_chat", {"message": message, "provider": provider}, write=False
    )
    import chat_routing
    from chat_context import OLLAMA_HOSTS

    resolved_model = model or os.getenv(
        "WORLDBASE_MCP_MODEL", "stepfun-ai/step-3.7-flash"
    )
    payload = {
        "messages": [{"role": "user", "content": message}],
        "context": context,
        "use_tools": use_tools,
        "provider": provider,
        "model": resolved_model,
        "stream": False,
    }

    try:
        from chat_proxy import _prepare_chat_messages
    except Exception:
        # Fallback: simple message prep without firewall/context
        import httpx
        from ollama_config import chat_timeout, keep_alive

        host = OLLAMA_HOSTS[0].strip()
        body = chat_routing.build_ollama_chat_body(
            resolved_model,
            [{"role": "user", "content": message}],
            stream=False,
            force_fast=not context,
            keep_alive=keep_alive(),
        )
        async with httpx.AsyncClient(timeout=chat_timeout()) as client:
            r = await client.post(f"http://{host}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
            return {
                "message": data.get("message", {}),
                "done": True,
                "model": resolved_model,
                "provider": provider,
            }

    (
        messages,
        firewall_meta,
        block_msg,
        user_text,
        context_blocks,
    ) = await _prepare_chat_messages(payload)
    if block_msg:
        return {"error": block_msg, "model": resolved_model, "provider": provider}

    if use_tools and provider == "ollama":
        import chat_tools

        last_err = "no host tried"
        for host in OLLAMA_HOSTS:
            host = host.strip()
            try:
                final_msgs, actions = await chat_tools.run_ollama_with_tools(
                    host, resolved_model, messages, max_rounds=4
                )
                text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                return {
                    "message": {"role": "assistant", "content": text},
                    "client_actions": actions,
                    "done": True,
                    "model": resolved_model,
                    "provider": provider,
                    **({"firewall_result": firewall_meta} if firewall_meta else {}),
                }
            except Exception as exc:
                last_err = str(exc)
                continue
        return {
            "error": f"Ollama not reachable: {last_err}",
            "model": resolved_model,
            "provider": provider,
        }

    # Non-tool path (any provider)
    import httpx
    from ollama_config import chat_timeout, keep_alive

    if provider == "ollama":
        host = OLLAMA_HOSTS[0].strip()
        body = chat_routing.build_ollama_chat_body(
            resolved_model,
            messages,
            stream=False,
            force_fast=False,
            keep_alive=keep_alive(),
        )
        async with httpx.AsyncClient(timeout=chat_timeout()) as client:
            r = await client.post(f"http://{host}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
            return {
                "message": data.get("message", {}),
                "done": True,
                "model": resolved_model,
                "provider": provider,
            }

    # OpenAI-compatible providers (groq, openrouter, nvidia, openai)
    env_key = chat_routing.PROVIDER_ENV_KEYS.get(provider)
    env_base_key = chat_routing.PROVIDER_ENV_BASE_URLS.get(provider)
    api_key = os.getenv(env_key) if env_key else None
    if not api_key:
        return {
            "error": f"No API key configured for provider '{provider}' (set {env_key})",
            "model": resolved_model,
            "provider": provider,
        }
    base_url = chat_routing.select_base_url(
        provider,
        None,
        os.getenv(env_base_key) if env_base_key else None,
        chat_routing.DEFAULT_BASE_URLS.get(provider, ""),
    )
    url = chat_routing.openai_chat_completions_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": resolved_model,
        "messages": messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, json=body, headers=headers)
        r.raise_for_status()
        data = r.json()
        content = (data.get("choices", [{}])[0].get("message", {})).get("content", "")
        return {
            "message": {"role": "assistant", "content": content},
            "done": True,
            "model": resolved_model,
            "provider": provider,
        }


@mcp.tool(name="worldbase_feed_status")
@mcp_jmespath.with_jmespath
async def worldbase_feed_status(feed_id: str | None = None) -> dict[str, Any]:
    """Freshness status of all cached feeds (age, TTL, fresh/stale/error classification).

    Args:
        feed_id: Optional — return status for a single feed only.
    """
    await _gate_mcp_tool("worldbase_feed_status", {"feed_id": feed_id}, write=False)
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    from connector_registry import feed_ttl_sec as _feed_ttl_sec
    from freshness import classify_freshness

    db = _db_path()

    def _build() -> dict[str, Any]:
        now = _dt.now(_tz.utc)
        feeds: dict[str, Any] = {}
        try:
            conn = sqlite3.connect(db, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")
            c = conn.cursor()
            if feed_id:
                c.execute(
                    "SELECT key, value, cached_at FROM feed_cache WHERE key = ? ORDER BY key",
                    [feed_id],
                )
            else:
                c.execute("SELECT key, value, cached_at FROM feed_cache ORDER BY key")
            for key, value_json, cached_at in c.fetchall():
                meta: dict = {}
                if value_json and len(value_json) < 120_000:
                    try:
                        val = _json.loads(value_json)
                        if isinstance(val, dict):
                            from feeds.envelope import extract_health_feed_meta

                            meta.update(extract_health_feed_meta(val))
                    except Exception:
                        pass
                try:
                    age = (now - _dt.fromisoformat(cached_at)).total_seconds()
                    ttl = _feed_ttl_sec(key)
                    status = classify_freshness(
                        age,
                        ttl,
                        error=meta.get("error"),
                        stale_flag=bool(meta.get("stale")),
                        vocab="health",
                    )
                    feeds[key] = {
                        "cached_at": cached_at,
                        "age_sec": round(age, 1),
                        "ttl_sec": ttl,
                        "fresh": age < ttl
                        and not meta.get("error")
                        and not meta.get("stale"),
                        "status": status,
                        **meta,
                    }
                except Exception:
                    feeds[key] = {
                        "cached_at": cached_at,
                        "age_sec": None,
                        "fresh": None,
                        "status": "unknown",
                        **meta,
                    }
            conn.close()
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200], "feeds": {}}

        fresh_n = sum(1 for f in feeds.values() if f.get("fresh"))
        stale_n = sum(1 for f in feeds.values() if f.get("status") == "stale")
        err_n = sum(1 for f in feeds.values() if f.get("error"))
        return {
            "status": "ok",
            "feeds": feeds,
            "feed_count": len(feeds),
            "feeds_fresh": fresh_n,
            "feeds_stale": stale_n,
            "feeds_error": err_n,
        }

    import asyncio

    result = await asyncio.to_thread(_build)
    if feed_id:
        result["feed_id"] = feed_id
    return result


@mcp.tool(name="worldbase_darkweb_search")
@mcp_jmespath.with_jmespath
async def worldbase_darkweb_search(
    query: str,
    engines: list[str] | None = None,
    limit: int = 10,
    mode: str = "auto",
    ingest: bool = False,
) -> dict[str, Any]:
    """Search dark web engines for a query (Ahmia, Darksearch, Tor engines). Optional FtM ingestion.

    Args:
        query: Search term.
        engines: List of engine names (default: configured engines).
        limit: Max results (1–50, default 10).
        mode: "auto" (clearnet+Tor as configured), "clear" (clearnet only), "tor" (all via Tor proxy).
        ingest: Ingest results as FtM Mention entities (requires WORLDBASE_MCP_WRITE=1).
    """
    await _gate_mcp_tool(
        "worldbase_darkweb_search", {"query": query, "ingest": ingest}, write=ingest
    )
    import darkweb_bridge

    limit = max(1, min(limit, 50))
    result = await darkweb_bridge.search_darkweb(
        query=query, engines=engines, limit=limit, mode=mode
    )

    if ingest and result.get("results"):
        if not mcp_write_enabled():
            raise PermissionError(
                "MCP write tools disabled (set WORLDBASE_MCP_WRITE=1)"
            )
        await _gate_mcp_write(
            "worldbase_darkweb_search",
            {"query": query, "ingest": True, "count": len(result["results"])},
        )
        ingest_result = darkweb_bridge.ingest_results(
            result["results"], dataset="darkweb_mcp"
        )
        result["ingest"] = ingest_result

    return result


@mcp.tool(name="worldbase_domain_intel")
@mcp_jmespath.with_jmespath
async def worldbase_domain_intel(
    domain: str,
    wayback_limit: int = 50,
    refresh: bool = False,
    organization_id: str | None = None,
) -> dict[str, Any]:
    """Domain intelligence: CT logs (crt.sh), Wayback CDX snapshots, RDAP registration data. Optional FtM ingest.

    Args:
        domain: Domain to investigate (e.g. example.com).
        wayback_limit: Max Wayback snapshots (1–200, default 50).
        refresh: Bypass cache (default False).
        organization_id: FtM Organization entity ID — if provided, ingest Domain + sub-domains and link via 'owns' edge (requires WORLDBASE_MCP_WRITE=1).
    """
    await _gate_mcp_tool(
        "worldbase_domain_intel",
        {"domain": domain, "organization_id": organization_id},
        write=bool(organization_id),
    )
    import domain_intel

    domain = domain.strip().lower().lstrip("*.")
    if not domain or "." not in domain:
        return {"error": "invalid domain", "domain": domain}

    wayback_limit = max(1, min(wayback_limit, 200))

    # Check cache first (unless refresh)
    if not refresh:
        cached = domain_intel._domain_cache_get(domain)
        if cached is not None:
            result = cached
        else:
            result = await domain_intel._gather_domain_intel(
                domain, wayback_limit=wayback_limit
            )
            domain_intel._domain_cache_set(domain, result)
    else:
        result = await domain_intel._gather_domain_intel(
            domain, wayback_limit=wayback_limit
        )
        domain_intel._domain_cache_set(domain, result)

    if organization_id:
        if not mcp_write_enabled():
            raise PermissionError(
                "MCP write tools disabled (set WORLDBASE_MCP_WRITE=1)"
            )
        await _gate_mcp_write(
            "worldbase_domain_intel",
            {"domain": domain, "organization_id": organization_id},
        )
        enrich_result = domain_intel._enrich_ftm(organization_id, result)
        result["ftm_ingest"] = enrich_result

    return result


@mcp.tool(name="worldbase_breach_status")
@mcp_jmespath.with_jmespath
async def worldbase_breach_status() -> dict[str, Any]:
    """Breach / credential-leak monitor status: enabled flags, HIBP key state, monitor count and list."""
    await _gate_mcp_tool("worldbase_breach_status", {}, write=False)
    import breach_bridge

    cfg = breach_bridge.get_config()
    monitors = breach_bridge.list_monitors() if cfg.breach_enabled else []
    provider = "hibp" if cfg.hibp_api_key else "xposedornot"
    return {
        "enabled": cfg.breach_enabled,
        "briefing_enabled": cfg.briefing_breach,
        "hibp_key_configured": bool(cfg.hibp_api_key),
        "provider": provider,
        "cache_sec": cfg.breach_cache_sec,
        "monitor_count": len(monitors),
        "monitors": monitors,
    }


@mcp.tool(name="worldbase_breach_check_password")
@mcp_jmespath.with_jmespath
async def worldbase_breach_check_password(password: str) -> dict[str, Any]:
    """Check if a password has been found in known data breaches using HIBP Pwned Passwords k-anonymity API.

    The password is never sent to the server — only the first 5 chars of its SHA1 hash
    are transmitted (k-anonymity). No API key required.

    Args:
        password: The password to check (plain text, never transmitted in full).
    """
    await _gate_mcp_tool(
        "worldbase_breach_check_password", {"password": "***"}, write=False
    )
    import hashlib

    import breach_bridge

    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest()
    return await breach_bridge.check_password_hash(sha1)


# ---------------------------------------------------------------------------
# Cyber intelligence tools (Shodan InternetDB + ontology expansion)
# ---------------------------------------------------------------------------


@mcp.tool(name="worldbase_cyber_ip_lookup")
@mcp_jmespath.with_jmespath
async def worldbase_cyber_ip_lookup(ip: str) -> dict[str, Any]:
    """Look up passive IP intelligence from Shodan InternetDB (keyless, no API key).

    Returns ports, hostnames, domains, tags, CVEs, ISP, and org for the given IP.
    Results are cached for 1 hour.

    Args:
        ip: IPv4 or IPv6 address (e.g. 8.8.8.8, 2001:db8::1).
    """
    await _gate_mcp_tool("worldbase_cyber_ip_lookup", {"ip": ip}, write=False)
    import cyber_bridge

    if not cyber_bridge._enabled():
        return {
            "enabled": False,
            "error": "Cyber bridge disabled (WORLDBASE_CYBER_BRIDGE=0)",
        }
    return await cyber_bridge.fetch_ip_intel(ip)


@mcp.tool(name="worldbase_intel_entities")
@mcp_jmespath.with_jmespath
async def worldbase_intel_entities(
    schema: str,
    limit: int = 50,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Query FtM entities by schema name. Supports cyber/financial ontology types.

    Args:
        schema: FtM schema name (e.g. IpAddress, Domain, Url, Organization, Person, Asset).
        limit: Max entities to return (1–500, default 50).
        dataset: Filter by provenance dataset tag (e.g. cyber_shodan, intel-ingest).
    """
    await _gate_mcp_tool(
        "worldbase_intel_entities",
        {"schema": schema, "limit": limit, "dataset": dataset},
        write=False,
    )
    import ftm_query

    limit = max(1, min(limit, 500))
    return ftm_query.list_entities_by_schema(schema, limit=limit, dataset=dataset)


@mcp.tool(name="worldbase_intel_edges")
@mcp_jmespath.with_jmespath
async def worldbase_intel_edges(
    type: str,
    limit: int = 100,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Query intel edges by edge kind. Supports cyber ontology edge types.

    Args:
        type: Edge kind (e.g. ownsAsset, linkedTo, mentionedIn, worksFor, locatedAt, partOf).
        limit: Max edges to return (1–500, default 100).
        dataset: Filter by provenance dataset tag.
    """
    await _gate_mcp_tool(
        "worldbase_intel_edges",
        {"type": type, "limit": limit, "dataset": dataset},
        write=False,
    )
    import ftm_query

    limit = max(1, min(limit, 500))
    return ftm_query.list_edges_by_type(type, limit=limit, dataset=dataset)


@mcp.tool(name="worldbase_extract_iocs")
@mcp_jmespath.with_jmespath
async def worldbase_extract_iocs(text: str) -> dict[str, Any]:
    """Extract Indicators of Compromise (IOCs) from text via regex.

    Detects: IPv4, IPv6, domains, URLs, SHA256/SHA1/MD5 hashes, and email addresses.
    No ML required — pure regex. Returns deduplicated matches grouped by IOC type.

    Args:
        text: Input text to scan for IOCs.
    """
    await _gate_mcp_tool("worldbase_extract_iocs", {"text": text[:200]}, write=False)
    from intel_ingest import extract_iocs

    iocs = extract_iocs(text)
    return {
        "ioc_count": sum(len(v) for v in iocs.values()),
        "ioc_types": list(iocs.keys()),
        "iocs": iocs,
    }


async def _gate_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    write: bool = True,
) -> None:
    """Gate MCP tool call: firewall check (write only) + RBAC per-tool policy.

    When *write* is True, the slim/HAK_GAL firewall scan runs.
    When mcp_policy_enabled is True, the caller's role (from context var)
    is checked against the per-tool policy dict.
    """
    if write:
        from firewall_bridge import ensure_mcp_tool_allowed

        await ensure_mcp_tool_allowed(tool_name, arguments)

    # Per-tool RBAC policy check
    try:
        if mcp_policy_enabled():
            role = _mcp_role.get()
            required = _get_mcp_tool_required_role(tool_name)
            if required != "none" and role is not None:
                if _ROLE_LEVELS.get(role, 0) < _ROLE_LEVELS.get(required, 0):
                    record_audit_event(
                        action="mcp_policy_denied",
                        tool=tool_name,
                        success=False,
                        error=f"Requires role '{required}' (current: '{role}')",
                    )
                    raise PermissionError(
                        f"MCP tool '{tool_name}' requires role '{required}' "
                        f"(current: '{role}')"
                    )
            record_audit_event(
                action="mcp_write" if write else "mcp_read",
                tool=tool_name,
                success=True,
            )
        elif write:
            # Backward compat: audit write tools when RBAC is enabled but policy is off
            try:
                from middleware.rbac import rbac_enabled

                if rbac_enabled():
                    record_audit_event(
                        action="mcp_write",
                        tool=tool_name,
                        success=True,
                    )
            except Exception:
                pass
    except PermissionError:
        raise
    except Exception:
        pass


# Backward-compatible alias
_gate_mcp_write = _gate_mcp_tool


if mcp_write_enabled():

    @mcp.tool(name="worldbase_briefing_generate")
    @mcp_jmespath.with_jmespath
    async def worldbase_briefing_generate(
        lang: str | None = None,
        include_full_text: bool = False,
    ) -> dict[str, Any]:
        """Generate a new 24h security briefing (Ollama + SQLite). Optional lang: en or de."""
        await _gate_mcp_write(
            "worldbase_briefing_generate",
            {"lang": lang, "include_full_text": include_full_text},
        )
        return await trigger_briefing_generate(
            lang=lang, include_full_text=include_full_text
        )


if mcp_globe_enabled():

    @mcp.tool(name="worldbase_globe_fly_to")
    @mcp_jmespath.with_jmespath
    async def worldbase_globe_fly_to(
        lat: float | None = None,
        lon: float | None = None,
        place: str | None = None,
        height: float | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Fly the open HUD globe to lat/lon or a named place (geocoded via OpenStreetMap). Requires HUD at :5176."""
        if lat is None or lon is None:
            if not place:
                return {"ok": False, "error": "Provide either lat+lon or place"}
            from chat_tools import _geocode_place

            geo = await _geocode_place(place)
            if geo is None:
                return {"ok": False, "error": f"Geocoding failed for '{place}'"}
            lat = geo["lat"]
            lon = geo["lon"]
            if title is None:
                title = geo.get("display_name", place)
        await _gate_mcp_write(
            "worldbase_globe_fly_to",
            {"lat": lat, "lon": lon, "height": height, "title": title},
        )
        import agent_bus

        return await agent_bus.publish_fly_to(
            lat=lat, lon=lon, height=height, title=title
        )

    @mcp.tool(name="worldbase_globe_toggle_layer")
    @mcp_jmespath.with_jmespath
    async def worldbase_globe_toggle_layer(
        layer: str, enabled: bool | None = None
    ) -> dict[str, Any]:
        """Toggle a globe feed layer on the open HUD (see worldbase_globe_layers for keys)."""
        await _gate_mcp_write(
            "worldbase_globe_toggle_layer",
            {"layer": layer, "enabled": enabled},
        )
        import agent_bus

        return await agent_bus.publish_toggle_layer(layer=layer, enabled=enabled)

    @mcp.tool(name="worldbase_globe_get_camera")
    @mcp_jmespath.with_jmespath
    async def worldbase_globe_get_camera() -> dict[str, Any]:
        """Last camera position synced from the open HUD globe session."""
        await _gate_mcp_tool("worldbase_globe_get_camera", {}, write=False)
        import agent_bus

        cam = agent_bus.get_camera_state()
        return {"camera": cam or None, "subscribers": agent_bus.subscriber_count()}

    @mcp.tool(name="worldbase_globe_layers")
    @mcp_jmespath.with_jmespath
    async def worldbase_globe_layers() -> dict[str, Any]:
        """Valid layer_id values for worldbase_globe_toggle_layer."""
        await _gate_mcp_tool("worldbase_globe_layers", {}, write=False)
        import agent_bus

        return {"layers": sorted(agent_bus.GLOBE_LAYER_KEYS)}


# ---------------------------------------------------------------------------
# V4-44: describe_tool + list_tools meta-tools
# ---------------------------------------------------------------------------


@mcp.tool(name="worldbase_describe_tool")
@mcp_jmespath.with_jmespath
async def worldbase_describe_tool(tool_name: str) -> dict[str, Any]:
    """Return the full uncompressed tool definition (input + output schema).

    Useful when the compressed tools/list description is ambiguous.
    Pass a tool name like 'worldbase_health' or 'worldbase_briefing_latest'.
    """
    await _gate_mcp_tool(
        "worldbase_describe_tool", {"tool_name": tool_name}, write=False
    )
    return mcp_schema.describe_tool(tool_name, mcp_instance=mcp)


@mcp.tool(name="worldbase_list_tools")
@mcp_jmespath.with_jmespath
async def worldbase_list_tools() -> dict[str, Any]:
    """List all WorldBase MCP tools with their output schema availability."""
    await _gate_mcp_tool("worldbase_list_tools", {}, write=False)
    names = mcp_schema.list_tool_names()
    return {
        "count": len(names),
        "tools": [
            {
                "name": n,
                "output_schema_available": mcp_schema.get_output_schema(n) is not None,
                "jmespath_supported": True,
            }
            for n in names
        ],
    }


def _patch_output_schemas() -> None:
    """Patch curated output schemas onto registered FastMCP tools."""
    if not mcp_schema.output_schema_enabled():
        return
    schemas = mcp_schema.all_output_schemas()
    for tool_name, schema in schemas.items():
        try:
            tool = mcp._tool_manager.get_tool(tool_name)
            # cached_property stores in instance __dict__; bypass via object.__setattr__
            object.__setattr__(tool, "output_schema", schema)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Mount + auth + session lifecycle
# ---------------------------------------------------------------------------


def _role_from_scope(scope: Scope) -> str | None:
    """Extract RBAC role from ASGI scope headers (JWT, API key, or node token)."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}

    # 1. Try JWT bearer token
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from auth.jwt import decode_token

            token = auth_header[7:]
            payload = decode_token(token)
            if payload and payload.get("type") == "access":
                role = payload.get("role", "viewer")
                if role in _ROLE_LEVELS:
                    return role
        except Exception:
            pass

    # 2. Try X-API-Key
    api_key = headers.get("x-api-key", "")
    if API_KEY and api_key and hmac.compare_digest(API_KEY, api_key):
        return "operator"

    # 3. Try X-Node-Token
    node_token = headers.get("x-node-token", "")
    if INGEST_TOKEN and node_token and hmac.compare_digest(INGEST_TOKEN, node_token):
        return "node"

    return None


class _MCPAuthMiddleware:
    """Optional X-API-Key gate for the MCP mount path."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = scope.get("client", ("", 0))[0] if scope.get("client") else ""
        is_loopback = client_ip in ("127.0.0.1", "::1", "localhost")

        if not mcp_auth_required() or is_loopback:
            # Auth not required (or localhost) — still extract role from headers
            _mcp_role.set(_role_from_scope(scope))
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        provided = headers.get("x-api-key") or ""
        client_ip = scope.get("client", ("", 0))[0] if scope.get("client") else ""
        path = scope.get("path", "")
        if not provided or not API_KEY or not hmac.compare_digest(API_KEY, provided):
            record_audit_event(
                action="mcp_auth",
                client=client_ip,
                endpoint=path,
                success=False,
                error="Invalid or missing X-API-Key for MCP",
            )
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-API-Key for WorldBase MCP"},
            )
            await response(scope, receive, send)
            return
        record_audit_event(
            action="mcp_auth",
            client=client_ip,
            endpoint=path,
            success=True,
        )
        # Set role context var for per-tool policy enforcement
        _mcp_role.set(_role_from_scope(scope))
        await self.app(scope, receive, send)


def _get_mcp_asgi() -> ASGIApp:
    asgi = mcp.streamable_http_app()
    # Always wrap with middleware — when auth is not required, it still
    # extracts the role from headers for per-tool policy enforcement.
    return _MCPAuthMiddleware(asgi)


def mount_worldbase_mcp(app) -> None:
    """Attach MCP Streamable HTTP at /api/mcp when WORLDBASE_MCP=1."""
    if not mcp_enabled():
        log.info("mcp_disabled")
        return

    mcp.streamable_http_app()
    wrapped = _get_mcp_asgi()
    app.mount("/api/mcp", wrapped)
    _patch_output_schemas()
    auth_note = (
        "X-API-Key required" if mcp_auth_required() else "open (localhost, no API key)"
    )
    write_note = "write on" if mcp_write_enabled() else "write off"
    globe_note = "globe on" if mcp_globe_enabled() else "globe off"
    log.info("mcp_mounted", auth=auth_note, write=write_note, globe=globe_note)

    @app.on_event("startup")
    async def _mcp_startup() -> None:
        global _mcp_session_cm
        _mcp_session_cm = mcp.session_manager.run()
        await _mcp_session_cm.__aenter__()

    @app.on_event("shutdown")
    async def _mcp_shutdown() -> None:
        global _mcp_session_cm
        if _mcp_session_cm is not None:
            await _mcp_session_cm.__aexit__(None, None, None)
            _mcp_session_cm = None
