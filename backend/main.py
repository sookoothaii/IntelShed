"""WorldBase API — FastAPI backend, SQLite cache, no Docker."""

import asyncio
import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders

from middleware.rate_limit import setup_rate_limiting

import globe_snapshot
import feeds_extra
import node_sync
import trust_router
import osint_tools
import nasa_firms
import blitzortung_bridge
import smard_bridge
import stock_bridge
import gtfs_ingestor
import ais_bridge
import cams_bridge
import humanitarian_bridge
import entsoe_bridge
import firewall_bridge
import webcam_bridge
import windy_bridge
import cve_bridge
import pegel_bridge
import flowsint_bridge
import entity_store
import ftm_store
import situations
import gdelt_bridge
import cap_bridge
import anomaly_river
import rag_memory
import duckdb_fusion
import gibs_bridge
import outages_bridge
import volcano_bridge
import pmtiles_bridge
import stac_bridge
import sanctions_bridge
import markets_bridge
import aircraft_trails
import fusion_heatmap
import intel_ingest
import entity_resolution
import feed_ingest
import credentials.router as credentials_router
import connectors.router as connectors_router
import traffic_bridge
import mcp_server

DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
entity_store.set_db_path(DB_PATH)
ftm_store.set_db_path()


def _load_env():
    """Minimal .env loader (no extra dependency). Does not override real env vars."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_env()


def _truthy(val: str) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def _log_security_startup():
    ingest = os.getenv("NODE_INGEST_TOKEN", "")
    require = _truthy(os.getenv("WORLDBASE_REQUIRE_NODE_TOKEN", ""))
    if not ingest:
        msg = (
            "NODE_INGEST_TOKEN not set — /api/node/* is open on the bind address. "
            "Run scripts/setup-node-security.ps1 (PC) and sync token to the Pi."
        )
        if require:
            # Fail fast: refuse to serve a LAN-exposed deployment without a token.
            raise RuntimeError(
                "[SECURITY] WORLDBASE_REQUIRE_NODE_TOKEN is set but NODE_INGEST_TOKEN is empty. "
                "Refusing to start. " + msg
            )
        print("[SECURITY] " + msg, flush=True)
    else:
        print("[SECURITY] Node ingest/admin API protected (NODE_INGEST_TOKEN set).", flush=True)


_log_security_startup()

app = FastAPI(title="WorldBase API", version="0.1.0", redirect_slashes=False)

# Allowed browser origins. Dev (Vite :5173/:5176) plus any extra origins the
# operator configures (e.g. the Caddy HTTPS front: https://localhost,
# https://192.168.1.111). Comma-separated in WORLDBASE_CORS_ORIGINS.
_CORS_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5176", "http://127.0.0.1:5176",
    "https://localhost", "https://127.0.0.1",
]
_extra_origins = os.getenv("WORLDBASE_CORS_ORIGINS", "")
if _extra_origins:
    _CORS_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SecurityHeadersMiddleware:
    """Pure-ASGI hardening headers — streaming-safe (unlike BaseHTTPMiddleware,
    which buffers and breaks StreamingResponse/SSE such as the chat endpoint)."""

    _HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Permitted-Cross-Domain-Policies": "none",
        "Permissions-Policy": "geolocation=(self), microphone=(), camera=()",
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in self._HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_wrapper)


app.add_middleware(SecurityHeadersMiddleware)

# Setup Rate Limiting (slowapi)
setup_rate_limiting(app)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS aircraft (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24 TEXT,
                callsign TEXT,
                origin_country TEXT,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                velocity REAL,
                heading REAL,
                recorded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS satellites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                tle1 TEXT,
                tle2 TEXT,
                recorded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS feed_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                cached_at TEXT
            );
        """)
        conn.commit()


# Feeds not refreshed within this window are treated as abandoned (renamed/retired
# cache keys like gdacs->gdacs_v3, or one-off location queries) and pruned so that
# /api/health reflects live feeds only. Live feeds rewrite within their TTL.
_FEED_CACHE_MAX_AGE_SEC = float(os.getenv("WORLDBASE_FEED_CACHE_MAX_AGE_SEC", 7 * 24 * 3600))


def prune_feed_cache(max_age_sec: float = _FEED_CACHE_MAX_AGE_SEC) -> int:
    """Drop feed_cache rows older than max_age_sec. Fail-soft (never raises)."""
    removed: list[str] = []
    try:
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            rows = conn.execute("SELECT key, cached_at FROM feed_cache").fetchall()
            for r in rows:
                try:
                    age = (now - datetime.fromisoformat(r["cached_at"])).total_seconds()
                except Exception:
                    continue
                if age > max_age_sec:
                    removed.append(r["key"])
            for key in removed:
                conn.execute("DELETE FROM feed_cache WHERE key = ?", (key,))
            conn.commit()
        if removed:
            print(f"[CACHE] pruned {len(removed)} abandoned feed_cache keys "
                  f"(> {max_age_sec / 3600:.0f}h): {removed}", flush=True)
    except Exception as e:
        print(f"[CACHE] prune skipped: {e}", flush=True)
    return len(removed)


import agent_bus
from routes import aircraft as aircraft_routes
from routes import chat as chat_routes
from routes import core_feeds
from routes import health as health_routes

app.include_router(agent_bus.router)
app.include_router(core_feeds.router)
app.include_router(chat_routes.router)
app.include_router(health_routes.router)
app.include_router(aircraft_routes.router)
app.include_router(globe_snapshot.router)
app.include_router(feeds_extra.router)
app.include_router(node_sync.router)
app.include_router(trust_router.router)
app.include_router(osint_tools.router)
app.include_router(nasa_firms.router)
app.include_router(blitzortung_bridge.router)
app.include_router(smard_bridge.router)
app.include_router(stock_bridge.router)
app.include_router(gtfs_ingestor.router)
app.include_router(ais_bridge.router)
app.include_router(cams_bridge.router)
app.include_router(humanitarian_bridge.router)
app.include_router(entsoe_bridge.router)
app.include_router(firewall_bridge.router)
app.include_router(webcam_bridge.router)
app.include_router(windy_bridge.router)
app.include_router(cve_bridge.router)
app.include_router(pegel_bridge.router)
app.include_router(flowsint_bridge.router)
app.include_router(gdelt_bridge.router)
app.include_router(cap_bridge.router)
app.include_router(anomaly_river.router)
app.include_router(rag_memory.router)
app.include_router(duckdb_fusion.router)
app.include_router(gibs_bridge.router)
app.include_router(outages_bridge.router)
app.include_router(volcano_bridge.router)
app.include_router(pmtiles_bridge.router)
app.include_router(stac_bridge.router)
app.include_router(sanctions_bridge.router)
app.include_router(markets_bridge.router)
app.include_router(aircraft_trails.router)
app.include_router(fusion_heatmap.router)
app.include_router(situations.router)
app.include_router(ftm_store.router)
app.include_router(intel_ingest.router)
app.include_router(entity_resolution.router)
app.include_router(feed_ingest.router)
app.include_router(credentials_router.router)
app.include_router(connectors_router.router)
app.include_router(traffic_bridge.router)

mcp_server.mount_worldbase_mcp(app)


# Disable trailing-slash redirects globally (prevents CORS errors on 307 redirects)
for r in app.routes:
    if hasattr(r, "redirect_slashes"):
        r.redirect_slashes = False

# ---------------------------------------------------------------------------
# Autopilot: generate LLM briefing every 6 h in the background (override via .env)
# ---------------------------------------------------------------------------
_BRIEFING_AUTOPILOT_TASK = None
_BRIEFING_INTERVAL = int(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "21600"))  # 6 h default


async def _phase1_background_tasks():
    """River anomaly scan + GDELT/RAG indexing (best-effort, no crash on missing Ollama)."""
    from ollama_config import rag_autopilot_on

    await asyncio.sleep(90)
    while True:
        try:
            await anomaly_river.scan_feeds()
        except Exception as e:
            print(f"[PHASE1] River scan failed: {e}", flush=True)
        if rag_autopilot_on():
            try:
                await rag_memory.ingest_pulse()
                await rag_memory.ingest_hazards()
                await rag_memory.ingest_situations()
                await rag_memory.ingest_volcanoes()
            except Exception as e:
                print(f"[PHASE1] RAG pulse index failed: {e}", flush=True)
        # Phase 2 — STAC + Sanctions augment the RAG corpus
        try:
            items = await stac_bridge.fetch_recent_thailand_items(limit=6)
            await rag_memory.ingest_stac_items(items)
        except Exception as e:
            print(f"[PHASE2] STAC ingest failed: {e}", flush=True)
        try:
            screen = await sanctions_bridge.sanctions_screen_vessels(min_score=0.85, limit=200)
            hits = [m.get("sanction") for m in (screen.get("matches") or []) if m.get("sanction")]
            if hits:
                await rag_memory.ingest_sanctions_hits(hits)
        except Exception as e:
            print(f"[PHASE2] Sanctions ingest failed: {e}", flush=True)
        if feed_ingest.autopilot_on():
            try:
                result = await feed_ingest.run_feed_ingest()
                t = result.get("totals") or {}
                print(
                    f"[PHASE2] Feed ingest: +{t.get('entities', 0)} entities "
                    f"({t.get('records', 0)} records)",
                    flush=True,
                )
            except Exception as e:
                print(f"[PHASE2] Feed ingest failed: {e}", flush=True)
        await asyncio.sleep(600)


async def _aircraft_trail_loop():
    """Snapshot aircraft positions into the trail table every ~30s."""
    await asyncio.sleep(45)
    while True:
        try:
            await aircraft_trails.snapshot_now()
        except Exception as e:
            print(f"[TRAIL] aircraft snapshot failed: {e}", flush=True)
        await asyncio.sleep(30)


async def _situations_prewarm():
    """Warm the Situation Board + River cache so first-load is instant."""
    await asyncio.sleep(20)
    try:
        await anomaly_river.scan_feeds()
    except Exception:
        pass
    try:
        await situations.unified_situations()
    except Exception:
        pass
    try:
        await fusion_heatmap.fusion_heatmap(cell_deg=2.0, top=60, include_geojson=0)
    except Exception:
        pass


async def _stack_warmup():
    """Warm operator-critical feeds after boot (GDELT local, maritime, traffic, haze)."""
    await asyncio.sleep(6)
    try:
        import gdelt_bridge

        out = await gdelt_bridge.warmup_local_pulse()
        n = int((out or {}).get("count") or 0)
        print(f"[WARMUP] GDELT local pulse: {n} articles", flush=True)
    except Exception as e:
        print(f"[WARMUP] GDELT local failed: {e}", flush=True)
    try:
        from traffic_bridge import warm_traffic_cams

        await warm_traffic_cams(force=True)
        print("[WARMUP] Traffic cams refreshed (regional/global/all)", flush=True)
    except Exception as e:
        print(f"[WARMUP] Traffic cams failed: {e}", flush=True)
    try:
        import ais_bridge

        m = await ais_bridge.warm_maritime()
        if m:
            print(f"[WARMUP] Maritime: {m.get('count')} vessels demo={m.get('demo_mode')}", flush=True)
    except Exception as e:
        print(f"[WARMUP] Maritime failed: {e}", flush=True)
    try:
        import cams_bridge

        h = await cams_bridge.get_haze(refresh=True)
        print(f"[WARMUP] CAMS haze: {h.get('count')} cities", flush=True)
    except Exception as e:
        print(f"[WARMUP] CAMS haze failed: {e}", flush=True)
    try:
        from feeds_extra import air_quality

        await air_quality()
        print("[WARMUP] Air quality refreshed", flush=True)
    except Exception as e:
        print(f"[WARMUP] Air quality failed: {e}", flush=True)
    try:
        from windy_bridge import fetch_point_weather
        import feed_registry

        pt = await fetch_point_weather(13.75, 100.5)
        if pt.get("current"):
            feed_registry.write_auto("weather:13.75:100.5", pt)
            print(f"[WARMUP] Bangkok weather: source={pt.get('source')}", flush=True)
    except Exception as e:
        print(f"[WARMUP] Weather failed: {e}", flush=True)


async def _entity_resolution_autopilot():
    """Nightly Splink entity resolution -> sameAs edges in the FtM graph."""
    await asyncio.sleep(120)
    interval = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_INTERVAL", "86400"))
    while True:
        try:
            result = await asyncio.to_thread(entity_resolution.run_resolution)
            print(
                f"[AUTOPILOT] Entity resolution: +{result.get('edges_added', 0)} edges "
                f"({result.get('exact_edges', 0)} exact, {result.get('splink_edges', 0)} splink)",
                flush=True,
            )
        except Exception as e:
            print(f"[AUTOPILOT] Entity resolution failed: {e}", flush=True)
        await asyncio.sleep(interval)


async def _briefing_autopilot():
    """Background loop that fuses feeds + LLM into a new briefing periodically."""
    await asyncio.sleep(30)  # Let the server warm up on first boot
    while True:
        try:
            await node_sync.generate_briefing_internal()
            print(f"[AUTOPILOT] Briefing generated at {datetime.now(timezone.utc).isoformat()}")
        except Exception as e:
            print(f"[AUTOPILOT] Briefing generation failed: {e}")
        await asyncio.sleep(_BRIEFING_INTERVAL)


# Aircraft cache warmup/refresh + /api/aircraft moved to routes/aircraft.py.
# aircraft_routes.aircraft_warmup() is scheduled in on_startup() below.


@app.on_event("startup")
def on_startup():
    init_db()
    prune_feed_cache()
    entity_store.init_entity_db()
    if not ftm_store.init_store():
        print(
            "[FTM] Intel graph offline — DuckDB locked or missing. "
            "/api/intel/* and briefing FtM block may be empty until restart.",
            flush=True,
        )
    node_sync.init_node_db()
    node_sync.init_command_db()
    anomaly_river.init_river_db()
    rag_memory.init_memory_db()
    import feed_drift

    feed_drift.init_drift_db()
    aircraft_trails.init_trail_db()
    from ollama_config import briefing_autopilot_on

    global _BRIEFING_AUTOPILOT_TASK
    if briefing_autopilot_on():
        _BRIEFING_AUTOPILOT_TASK = asyncio.create_task(_briefing_autopilot())
    else:
        print("[AUTOPILOT] Briefing autopilot disabled (WORLDBASE_BRIEFING_AUTOPILOT=0)", flush=True)
    if entity_resolution.autopilot_on():
        asyncio.create_task(_entity_resolution_autopilot())
    else:
        print("[AUTOPILOT] Entity resolution autopilot disabled (WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT=0)", flush=True)
    asyncio.create_task(aircraft_routes.aircraft_warmup())
    asyncio.create_task(_phase1_background_tasks())
    asyncio.create_task(_aircraft_trail_loop())
    asyncio.create_task(_situations_prewarm())
    asyncio.create_task(_stack_warmup())
    import ais_bridge

    ais_bridge.start_aisstream_collector()


@app.on_event("shutdown")
def on_shutdown():
    if _BRIEFING_AUTOPILOT_TASK:
        _BRIEFING_AUTOPILOT_TASK.cancel()
    import ais_bridge

    ais_bridge.stop_aisstream_collector()


# Health endpoints (/api/health/ping, /api/health) moved to routes/health.py.
# build_chat_context() and the chat/LLM proxy endpoints moved to routes/chat.py.
# The live aircraft endpoint (/api/aircraft) and its cache warmup/refresh moved
# to routes/aircraft.py (warmup scheduled in on_startup). All registered via
# app.include_router(...) in the include block above.


# Core feed endpoints (/api/satellites, /api/earthquakes, /api/events, /api/iss,
# /api/world) moved to routes/core_feeds.py. Re-exported here so existing callers
# (globe_snapshot, mcp_server, fusion_heatmap → main.get_earthquakes/get_events)
# keep working unchanged. Router is registered in the include_router block above.
from routes.core_feeds import (  # noqa: E402  (compat re-export)
    get_earthquakes,
    get_events,
    get_iss,
    get_satellites,
    get_world,
)


# Chat endpoints (/api/search, /api/models, /api/chat, /api/providers) and the
# chat-context builder moved to routes/chat.py, registered via
# app.include_router(chat.router) in the include block above.


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
