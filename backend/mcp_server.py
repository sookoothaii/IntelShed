"""WorldBase MCP surface — Streamable HTTP read + write tools for Cursor / Claude.

Reuses the same Python paths as chat_tools and REST routes (no HTTP loopback).
Mount: GET/POST /api/mcp (Streamable HTTP). Disable with WORLDBASE_MCP=0.
Write tools (briefing generate) gated by WORLDBASE_MCP_WRITE=1 (default on).
"""

from __future__ import annotations

import hmac
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from structured_log import get_logger

log = get_logger(__name__)

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from auth.security import API_KEY, lan_auth_required
from mcp.server.fastmcp import FastMCP

# Feeds allowed for worldbase_feed_sample (cache key or live bridge id).
FEED_SAMPLE_ALLOWLIST: frozenset[str] = frozenset({
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
})

_TEXT_PREVIEW_CHARS = 4000
_mcp_session_cm = None


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
    for key in ("items", "alerts", "states", "earthquakes", "articles", "nodes", "cells"):
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
        raise ValueError(
            f"Unknown feed_id {feed_id!r}. Allowed: {', '.join(allowed)}"
        )
    limit = max(1, min(limit, 25))

    import feed_registry

    cached = feed_registry.read(feed_id)
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
async def worldbase_health() -> dict[str, Any]:
    """WorldBase liveness: time, FtM readiness, feed cache count."""
    return await fetch_health()


@mcp.tool(name="worldbase_briefing_latest")
async def worldbase_briefing_latest(include_full_text: bool = False) -> dict[str, Any]:
    """Latest 24h security briefing (digest, intel summary, text preview)."""
    return await fetch_briefing_latest(include_full_text=include_full_text)


@mcp.tool(name="worldbase_nodes")
async def worldbase_nodes() -> dict[str, Any]:
    """Edge nodes (Pi online state, mesh GPS, sensors snapshot)."""
    return await fetch_nodes()


@mcp.tool(name="worldbase_situations")
async def worldbase_situations(limit: int = 20) -> dict[str, Any]:
    """Unified situation board (correlations, anomalies, GDACS, pegel, sensors)."""
    return await fetch_situations(limit=limit)


@mcp.tool(name="worldbase_fusion_hotspots")
async def worldbase_fusion_hotspots(top: int = 10) -> dict[str, Any]:
    """Top fusion heatmap cells ranked for situational awareness."""
    return await fetch_fusion_hotspots(top=top)


@mcp.tool(name="worldbase_intel_subgraph")
async def worldbase_intel_subgraph(
    hops: int = 2,
    window_hours: int = 24,
    bbox: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """2-hop FtM subgraph around operator bbox (who/what links near home region)."""
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
async def worldbase_feed_sample(feed_id: str, limit: int = 5) -> dict[str, Any]:
    """Sample rows from an allowlisted feed (cache first, then live bridge)."""
    return await fetch_feed_sample(feed_id, limit=limit)


@mcp.tool(name="worldbase_feed_allowlist")
async def worldbase_feed_allowlist() -> dict[str, Any]:
    """List feed_id values valid for worldbase_feed_sample."""
    return {"feeds": sorted(FEED_SAMPLE_ALLOWLIST)}


async def _gate_mcp_write(tool_name: str, arguments: dict[str, Any]) -> None:
    """Slim guard + optional HAK_GAL — see firewall_bridge.ensure_mcp_tool_allowed."""
    from firewall_bridge import ensure_mcp_tool_allowed

    await ensure_mcp_tool_allowed(tool_name, arguments)


if mcp_write_enabled():

    @mcp.tool(name="worldbase_briefing_generate")
    async def worldbase_briefing_generate(
        lang: str | None = None,
        include_full_text: bool = False,
    ) -> dict[str, Any]:
        """Generate a new 24h security briefing (Ollama + SQLite). Optional lang: en or de."""
        await _gate_mcp_write(
            "worldbase_briefing_generate",
            {"lang": lang, "include_full_text": include_full_text},
        )
        return await trigger_briefing_generate(lang=lang, include_full_text=include_full_text)


if mcp_globe_enabled():

    @mcp.tool(name="worldbase_globe_fly_to")
    async def worldbase_globe_fly_to(
        lat: float,
        lon: float,
        height: float | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Fly the open HUD globe to lat/lon (Agent Bus → browser stream). Requires HUD at :5176."""
        await _gate_mcp_write(
            "worldbase_globe_fly_to",
            {"lat": lat, "lon": lon, "height": height, "title": title},
        )
        import agent_bus
        return await agent_bus.publish_fly_to(lat=lat, lon=lon, height=height, title=title)

    @mcp.tool(name="worldbase_globe_toggle_layer")
    async def worldbase_globe_toggle_layer(layer: str, enabled: bool | None = None) -> dict[str, Any]:
        """Toggle a globe feed layer on the open HUD (see worldbase_globe_layers for keys)."""
        await _gate_mcp_write(
            "worldbase_globe_toggle_layer",
            {"layer": layer, "enabled": enabled},
        )
        import agent_bus
        return await agent_bus.publish_toggle_layer(layer=layer, enabled=enabled)

    @mcp.tool(name="worldbase_globe_get_camera")
    async def worldbase_globe_get_camera() -> dict[str, Any]:
        """Last camera position synced from the open HUD globe session."""
        import agent_bus
        cam = agent_bus.get_camera_state()
        return {"camera": cam or None, "subscribers": agent_bus.subscriber_count()}

    @mcp.tool(name="worldbase_globe_layers")
    async def worldbase_globe_layers() -> dict[str, Any]:
        """Valid layer_id values for worldbase_globe_toggle_layer."""
        import agent_bus
        return {"layers": sorted(agent_bus.GLOBE_LAYER_KEYS)}


# ---------------------------------------------------------------------------
# Mount + auth + session lifecycle
# ---------------------------------------------------------------------------

class _MCPAuthMiddleware:
    """Optional X-API-Key gate for the MCP mount path."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not mcp_auth_required():
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        provided = headers.get("x-api-key") or ""
        if not provided or not API_KEY or not hmac.compare_digest(API_KEY, provided):
            response = JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing X-API-Key for WorldBase MCP"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _get_mcp_asgi() -> ASGIApp:
    asgi = mcp.streamable_http_app()
    if mcp_auth_required():
        return _MCPAuthMiddleware(asgi)
    return asgi


def mount_worldbase_mcp(app) -> None:
    """Attach MCP Streamable HTTP at /api/mcp when WORLDBASE_MCP=1."""
    if not mcp_enabled():
        log.info("mcp_disabled")
        return

    mcp.streamable_http_app()
    wrapped = _get_mcp_asgi()
    app.mount("/api/mcp", wrapped)
    auth_note = "X-API-Key required" if mcp_auth_required() else "open (localhost, no API key)"
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
