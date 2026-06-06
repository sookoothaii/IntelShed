"""WorldBase API — FastAPI backend, SQLite cache, no Docker."""

import asyncio
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.datastructures import MutableHeaders

import feeds_extra
import node_sync
import osint_tools
import nasa_firms
import blitzortung_bridge
import smard_bridge
import stock_bridge
import gtfs_ingestor
import ais_bridge
import entsoe_bridge
import firewall_bridge
import webcam_bridge
import cve_bridge
import pegel_bridge
import flowsint_bridge
import entity_store
import situations
import chat_tools
import opensky_client
import aircraft_provider
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
import aircraft_trails
import fusion_heatmap

DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
entity_store.set_db_path(DB_PATH)


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


app.include_router(feeds_extra.router)
app.include_router(node_sync.router)
app.include_router(osint_tools.router)
app.include_router(nasa_firms.router)
app.include_router(blitzortung_bridge.router)
app.include_router(smard_bridge.router)
app.include_router(stock_bridge.router)
app.include_router(gtfs_ingestor.router)
app.include_router(ais_bridge.router)
app.include_router(entsoe_bridge.router)
app.include_router(firewall_bridge.router)
app.include_router(webcam_bridge.router)
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
app.include_router(aircraft_trails.router)
app.include_router(fusion_heatmap.router)
app.include_router(situations.router)


# Disable trailing-slash redirects globally (prevents CORS errors on 307 redirects)
for r in app.routes:
    if hasattr(r, "redirect_slashes"):
        r.redirect_slashes = False

# ---------------------------------------------------------------------------
# Autopilot: generate LLM briefing every 10 min in the background
# ---------------------------------------------------------------------------
_BRIEFING_AUTOPILOT_TASK = None
_BRIEFING_INTERVAL = int(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "600"))  # 10 min default


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


@app.on_event("startup")
def on_startup():
    init_db()
    entity_store.init_entity_db()
    node_sync.init_node_db()
    node_sync.init_command_db()
    anomaly_river.init_river_db()
    rag_memory.init_memory_db()
    aircraft_trails.init_trail_db()
    from ollama_config import briefing_autopilot_on

    global _BRIEFING_AUTOPILOT_TASK
    if briefing_autopilot_on():
        _BRIEFING_AUTOPILOT_TASK = asyncio.create_task(_briefing_autopilot())
    else:
        print("[AUTOPILOT] Briefing autopilot disabled (WORLDBASE_BRIEFING_AUTOPILOT=0)", flush=True)
    asyncio.create_task(_phase1_background_tasks())
    asyncio.create_task(_aircraft_trail_loop())
    asyncio.create_task(_situations_prewarm())


@app.on_event("shutdown")
def on_shutdown():
    if _BRIEFING_AUTOPILOT_TASK:
        _BRIEFING_AUTOPILOT_TASK.cancel()


# Per-feed max age (seconds) before marked stale in /api/health
_FEED_TTL_SEC: dict[str, float] = {
    "airquality": 3600,
    "gdacs": 900,
    "pegel": 900,
    "markets": 120,
    "military": 60,
    "spaceweather": 300,
    "geopolitics": 600,
    "reliefweb": 600,
    "eonet": 1800,
}


def _feed_ttl_sec(key: str) -> float:
    if key in _FEED_TTL_SEC:
        return _FEED_TTL_SEC[key]
    if key.startswith("weather:"):
        return 1800
    if key.startswith("quakes:"):
        return 300
    return 600


def _feed_status(age_sec: float | None) -> str:
    """fresh | warn | stale | unknown"""
    if age_sec is None:
        return "unknown"
    if age_sec < 300:
        return "fresh"
    if age_sec < 3600:
        return "warn"
    return "stale"


@app.get("/api/health")
def health():
    now = datetime.now(timezone.utc)
    feeds = {}
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key, cached_at FROM feed_cache ORDER BY key")
        for row in c.fetchall():
            key, cached_at = row
            try:
                age = (now - datetime.fromisoformat(cached_at)).total_seconds()
                ttl = _feed_ttl_sec(key)
                feeds[key] = {
                    "cached_at": cached_at,
                    "age_sec": round(age, 1),
                    "ttl_sec": ttl,
                    "fresh": age < ttl,
                    "status": _feed_status(age),
                }
            except Exception:
                feeds[key] = {"cached_at": cached_at, "age_sec": None, "fresh": None, "status": "unknown"}
        conn.close()
    except Exception:
        pass
    return {
        "status": "ok",
        "time": now.isoformat(),
        "feeds": feeds,
        "feed_count": len(feeds),
    }


# Simple in-memory TTL cache to avoid upstream rate limits
_CACHE: dict = {}


def _cache_get(key: str, ttl: float):
    import time
    item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    return None


def _cache_set(key: str, value):
    import time
    _CACHE[key] = (time.time(), value)


# ---------------------------------------------------------------------------
# Chat context: inject live world state into LLM prompts
# ---------------------------------------------------------------------------
async def build_chat_context() -> str:
    """Fuse briefing + nodes + feed counts into a concise system context."""
    parts = []

    # Briefing
    try:
        brief = node_sync.latest_briefing()
        if brief and brief.get("text"):
            parts.append(f"SITUATION BRIEFING ({brief.get('created_at', 'unknown')}):")
            parts.append(brief["text"][:500])
    except Exception:
        pass

    # Nodes (Pi status)
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT node_id, name, lat, lon, updated_at, payload FROM node_state"
            ).fetchall()
        if rows:
            parts.append("\nNODES:")
            for r in rows:
                p = json.loads(r["payload"] or "{}")
                h = p.get("health", {})
                parts.append(
                    f"  {r['name']} ({r['node_id']}): "
                    f"lat={r['lat']}, lon={r['lon']}, "
                    f"temp={h.get('cpu_temp_c', '?')}C, "
                    f"services={len(h.get('services', {}))}, "
                    f"mesh={len(p.get('mesh', []))}"
                )
    except Exception:
        pass

    # Feed counts (from cache if available)
    ac = _cache_get("aircraft", ttl=999999)
    qu = _cache_get("quakes:day:2.5", ttl=999999)
    ev = _cache_get("eonet", ttl=999999)
    if ac or qu or ev:
        parts.append("\nFEEDS:")
        if ac:
            parts.append(f"  Aircraft: {len(ac.get('states', []) or [])}")
        if qu:
            parts.append(f"  Earthquakes(24h): {len(qu.get('features', []) or [])}")
        if ev:
            parts.append(f"  Natural events: {len(ev.get('events', []) or [])}")

    # ReliefWeb humanitarian crises
    try:
        rw = _cache_get("reliefweb", ttl=999999)
        if not rw:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://api.reliefweb.int/v1/disasters",
                    params={"appname": "worldbase", "profile": "list", "preset": "latest", "limit": 10},
                )
                rw = r.json()
                _cache_set("reliefweb", rw)
        disasters = rw.get("data", [])
        if disasters:
            parts.append("\nACTIVE CRISES (ReliefWeb):")
            for d in disasters[:5]:
                f = d.get("fields", {})
                parts.append(f"  {f.get('name', 'Unknown')} — {f.get('status', 'unknown')}")
    except Exception:
        pass

    # RSS news headlines
    try:
        news = _cache_get("rss_news", ttl=999999)
        if not news:
            headlines = []
            feeds = [
                ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
                ("Reuters", "https://www.reutersagency.com/feed/?best-topics=business-finance"),
                ("Tagesschau", "https://www.tagesschau.de/xml/rss2/"),
            ]
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                for name, url in feeds:
                    try:
                        r = await client.get(url, headers={"User-Agent": "WorldBase/1.0"})
                        text = r.text
                        # Simple regex extraction for <title> inside <item>
                        titles = re.findall(r'<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?</item>', text, re.DOTALL)[:3]
                        for t in titles:
                            clean = re.sub(r'<[^>]+>', '', t).strip()
                            if clean and clean not in [h["text"] for h in headlines]:
                                headlines.append({"source": name, "text": clean})
                    except Exception:
                        continue
            news = headlines[:8]
            _cache_set("rss_news", news)
        if news:
            parts.append("\nHEADLINES:")
            for h in news:
                parts.append(f"  [{h['source']}] {h['text']}")
    except Exception:
        pass

    # CISA KEV (exploited CVEs)
    try:
        base = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/api/cve?limit=8")
            if r.status_code == 200:
                cve = r.json()
                vulns = cve.get("vulnerabilities", [])[:5]
                if vulns:
                    parts.append("\nCISA KEV (actively exploited):")
                    for v in vulns:
                        parts.append(
                            f"  {v.get('cve_id')}: {v.get('vendor')} {v.get('product')} "
                            f"(due {v.get('due_date', '?')})"
                        )
    except Exception:
        pass

    # River gauges (Germany)
    try:
        base = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(f"{base}/api/pegel")
            if r.status_code == 200:
                peg = r.json()
                elevated = [g for g in (peg.get("gauges") or []) if g.get("severity") in ("critical", "high")]
                if elevated:
                    parts.append("\nRIVER GAUGES (elevated, DE):")
                    for g in elevated[:6]:
                        parts.append(
                            f"  {g.get('name')} / {g.get('water')}: {g.get('value')} {g.get('unit')} ({g.get('severity')})"
                        )
    except Exception:
        pass

    return "\n".join(parts) if parts else "No live context available."


@app.get("/api/aircraft")
async def get_aircraft(limit: int = 800):
    """Live aircraft: OpenSky (OAuth) when configured, else adsb.lol grid (free, ODbL)."""
    cache_key = "aircraft"
    cached = _cache_get(cache_key, ttl=15.0)
    source = "cache"
    if cached is None:
        try:
            cached, source = await aircraft_provider.fetch_live_states()
            _cache_set(cache_key, cached)
        except Exception as e:
            stale = _CACHE.get(cache_key)
            if stale:
                cached = stale[1]
                source = cached.get("source", "stale")
            else:
                return {
                    "count": 0,
                    "timestamp": None,
                    "states": [],
                    "source": None,
                    "error": (
                        f"Aircraft feeds unavailable ({e.__class__.__name__}). "
                        "Optional: OPENSKY_CLIENT_ID/SECRET in backend/.env; "
                        "otherwise adsb.lol is used automatically."
                    ),
                }
    else:
        source = cached.get("source", "cache")

    states = cached.get("states", []) or []
    with_pos = [s for s in states if len(s) > 6 and s[5] is not None and s[6] is not None]
    return {
        "count": len(with_pos),
        "timestamp": cached.get("time"),
        "source": source,
        "states": with_pos[: max(0, min(limit, 5000))],
    }


@app.get("/api/satellites")
async def get_satellites(limit: int = 400, group: str = "active"):
    """Fetch satellite TLEs from CelesTrak (cached 6h).

    Useful groups: active, stations, starlink, gps-ops, weather, science, geo.
    """
    import os
    cache_key = f"sat:{group}"
    tle_dir = os.path.join(os.path.dirname(__file__), "data", "tle")
    os.makedirs(tle_dir, exist_ok=True)
    disk_path = os.path.join(tle_dir, f"{group}.tle")

    tle_text = _cache_get(cache_key, ttl=6 * 3600.0)
    if tle_text is None:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(
                    f"https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle",
                    headers={"User-Agent": "WorldBase/1.0 (research dashboard)"},
                )
                r.raise_for_status()
                tle_text = r.text
            if not tle_text or "<" in tle_text[:50] or "1 " not in tle_text[:200]:
                raise ValueError("Invalid TLE payload (likely rate-limited)")
            _cache_set(cache_key, tle_text)
            # Persist to disk for resilience across reloads / 403s
            with open(disk_path, "w", encoding="utf-8") as f:
                f.write(tle_text)
        except Exception as e:
            # Fallback chain: in-memory stale -> disk cache -> empty
            stale = _CACHE.get(cache_key)
            if stale:
                tle_text = stale[1]
            elif os.path.exists(disk_path):
                with open(disk_path, "r", encoding="utf-8") as f:
                    tle_text = f.read()
                _cache_set(cache_key, tle_text)
            else:
                return {"count": 0, "group": group, "satellites": [], "error": str(e)}

    lines = [l.strip() for l in tle_text.splitlines() if l.strip()]
    satellites = []
    i = 0
    cap = max(0, min(limit, 2000))
    while i < len(lines) - 2:
        if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            satellites.append({
                "name": lines[i],
                "tle1": lines[i + 1],
                "tle2": lines[i + 2],
            })
            i += 3
            if len(satellites) >= cap:
                break
        else:
            i += 1

    return {"count": len(satellites), "group": group, "satellites": satellites}


@app.get("/api/earthquakes")
async def get_earthquakes(period: str = "day", magnitude: str = "2.5"):
    """USGS earthquakes feed (cached 5min).

    period: hour, day, week, month. magnitude: significant, 4.5, 2.5, 1.0, all.
    """
    key = f"quakes:{period}:{magnitude}"
    data = _cache_get(key, ttl=300.0)
    if data is None:
        url = f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{magnitude}_{period}.geojson"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        _cache_set(key, data)

    quakes = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        geom = f.get("geometry", {})
        coords = geom.get("coordinates", [None, None, None])
        quakes.append({
            "id": f.get("id"),
            "place": props.get("place"),
            "mag": props.get("mag"),
            "time": props.get("time"),
            "depth": coords[2],
            "lon": coords[0],
            "lat": coords[1],
            "tsunami": props.get("tsunami"),
            "url": props.get("url"),
        })
    return {"count": len(quakes), "earthquakes": quakes}


@app.get("/api/events")
async def get_events(limit: int = 100):
    """NASA EONET natural events: wildfires, storms, volcanoes, ice (cached 30min)."""
    data = _cache_get("eonet", ttl=1800.0)
    if data is None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200"
            )
            r.raise_for_status()
            data = r.json()
        _cache_set("eonet", data)

    events = []
    for ev in data.get("events", [])[:limit]:
        cats = [c.get("title") for c in ev.get("categories", [])]
        geo = ev.get("geometry", [])
        if not geo:
            continue
        last = geo[-1]
        coords = last.get("coordinates")
        if not coords or not isinstance(coords, list) or len(coords) < 2:
            continue
        sources = [s.get("url") for s in ev.get("sources", []) if s.get("url")]
        events.append({
            "id": ev.get("id"),
            "title": ev.get("title"),
            "category": cats[0] if cats else "Unknown",
            "categories": cats,
            "date": last.get("date"),
            "lon": coords[0],
            "lat": coords[1],
            "magnitude": last.get("magnitudeValue"),
            "unit": last.get("magnitudeUnit"),
            "closed": ev.get("closed"),
            "link": ev.get("link"),
            "sources": sources,
            "points": len(geo),
        })
    return {"count": len(events), "events": events}


@app.get("/api/iss")
async def get_iss():
    """Precise ISS position (cached 4s)."""
    data = _cache_get("iss", ttl=4.0)
    if data is None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.wheretheiss.at/v1/satellites/25544")
            r.raise_for_status()
            data = r.json()
        _cache_set("iss", data)
    return data


@app.get("/api/world")
async def get_world():
    """Stub for world.json aggregation (markets, geo threats)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM feed_cache WHERE key = 'world'"
        ).fetchone()
    if row:
        import json
        return json.loads(row["value"])
    return {
        "status": "empty",
        "message": "Run world-sync to populate.",
        "currencies": {},
        "geo": {},
        "news": [],
    }


import os
import time

_models_cache: dict = {"ts": 0.0, "data": None}
_MODELS_CACHE_TTL = 20.0


def _ollama_hosts() -> list[str]:
    """Resolve Ollama host(s) with Windows-friendly loopback fallbacks."""
    raw = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    expanded: list[str] = []
    for h in hosts:
        expanded.append(h)
        if h.startswith("localhost:"):
            expanded.append(h.replace("localhost:", "127.0.0.1:", 1))
        elif h.startswith("127.0.0.1:"):
            port = h.split(":", 1)[1]
            expanded.append(f"localhost:{port}")
    seen: set[str] = set()
    out: list[str] = []
    for h in expanded:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out or ["127.0.0.1:11434"]


OLLAMA_HOSTS = _ollama_hosts()


def _is_embed_model(name: str) -> bool:
    embed_base = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").split(":")[0].lower()
    n = (name or "").lower()
    return n.startswith(embed_base) or "embed" in n


@app.get("/api/search")
async def search_web(q: str, n: int = 5):
    """Web search via DuckDuckGo HTML (no API key required).

    Returns top-n results with title, url, and snippet.
    """
    from bs4 import BeautifulSoup
    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.post(
                url,
                data={"q": q, "b": ""},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
                    "Accept": "text/html",
                },
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return {"query": q, "count": 0, "results": [], "error": str(e)}

    results = []
    for row in soup.select(".result")[:n]:
        a = row.select_one(".result__a")
        snippet = row.select_one(".result__snippet")
        if a:
            results.append({
                "title": a.get_text(strip=True),
                "url": a.get("href", ""),
                "snippet": snippet.get_text(strip=True) if snippet else "",
            })

    return {"query": q, "count": len(results), "results": results}


@app.get("/api/models")
async def list_models():
    """List available Ollama chat models (embed models excluded from chat picker)."""
    now = time.time()
    if _models_cache["data"] and now - _models_cache["ts"] < _MODELS_CACHE_TTL:
        return _models_cache["data"]

    last_err = None
    for host in OLLAMA_HOSTS:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(f"http://{host}/api/tags")
                r.raise_for_status()
                data = r.json()
                all_models = data.get("models", [])
                chat_models = [m for m in all_models if not _is_embed_model(m.get("name", ""))]
                default_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
                chat_names = [m.get("name") for m in chat_models]
                all_names = [m.get("name") for m in all_models]
                if default_model not in chat_names:
                    for n in chat_names:
                        if n and n.split(":")[0] == default_model.split(":")[0]:
                            default_model = n
                            break
                payload = {
                    "host": host,
                    "count": len(chat_models),
                    "default": default_model if default_model in chat_names else (chat_names[0] if chat_names else None),
                    "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                    "embed_available": any(_is_embed_model(n or "") for n in all_names),
                    "models": [
                        {
                            "name": m.get("name"),
                            "size": m.get("size"),
                            "parameter_size": m.get("details", {}).get("parameter_size"),
                        }
                        for m in chat_models
                    ],
                }
                if not chat_models and all_models:
                    payload["warning"] = (
                        "Only embedding models found. Run: ollama pull qwen3:8b"
                    )
                _models_cache["ts"] = now
                _models_cache["data"] = payload
                return payload
        except Exception as e:
            last_err = str(e)
            continue
    err = {
        "error": "Ollama not reachable",
        "detail": last_err,
        "hosts_tried": OLLAMA_HOSTS,
        "hint": (
            "1) Start Ollama (ollama.com)  2) ollama pull qwen3:8b  "
            "3) backend/.env → OLLAMA_HOST=127.0.0.1:11434  4) .\\start.ps1"
        ),
    }
    return err


@app.post("/api/chat")
async def chat_proxy(payload: dict):
    """Proxy chat requests to LLM providers. Supports SSE streaming.

    Providers: ollama (default), openai, anthropic, groq, openrouter.
    Set payload['context'] = True to inject live WorldBase state as a system message.
    Set payload['firewall'] = True to route user messages through the LLM-Security-Firewall.
    """
    from ollama_config import keep_alive

    provider = payload.get("provider", "ollama")
    model = payload.get("model", os.getenv("OLLAMA_MODEL", "qwen3:8b"))
    use_stream = payload.get("stream", False)
    firewall_meta = None

    # Optional: LLM-Security-Firewall scan (only if explicitly requested)
    if payload.get("firewall"):
        from firewall_bridge import firewall_scan, _extract_user_text
        user_text = _extract_user_text(payload.get("messages", []))
        if user_text:
            scan = await firewall_scan(user_text)
            firewall_meta = scan.get("data")
            if firewall_meta and (firewall_meta.get("should_block") or firewall_meta.get("risk_score", 0) > 0.7):
                block_msg = {
                    "message": {
                        "role": "assistant",
                        "content": (
                            "⚠️ **FIREWALL BLOCK**\n\n"
                            "This message was flagged by the LLM-Security-Firewall.\n"
                            f"Risk Score: {firewall_meta.get('risk_score', '—')}\n"
                            f"Matched: {', '.join(firewall_meta.get('matched_patterns', [])[:3]) or '—'}\n\n"
                            "Set `firewall: false` to bypass (not recommended)."
                        ),
                    },
                    "done": True,
                    "firewall_blocked": True,
                    "firewall_meta": firewall_meta,
                }
                if use_stream:
                    return StreamingResponse(
                        (f"data: {json.dumps(block_msg)}\n\n" async for _ in [1]),
                        media_type="text/event-stream",
                    )
                return block_msg

    # Build messages, optionally injecting live context + web search results
    messages = list(payload.get("messages", []))
    if payload.get("context"):
        ctx = await build_chat_context()
        search_results = payload.get("search_results", "")
        parts = []
        if ctx:
            parts.append("=== INTERNAL TELEMETRY ===\n" + ctx)
        if search_results:
            parts.append("=== WEB SEARCH RESULTS ===\n" + search_results)
        if parts:
            system_msg = {
                "role": "system",
                "content": (
                    "You are WorldBase AI — a hard-nosed intelligence analyst. "
                    "NO greeting. NO 'es scheint'. NO hedging. Just facts.\n\n"
                    "RULES:\n"
                    "1. Start directly with findings. No intro like 'Basierend auf...'\n"
                    "2. Use EVERY data source provided. If web results exist, quote them.\n"
                    "3. Structure: KEY FINDINGS → DETAILS → SOURCES\n"
                    "4. If data is missing, say 'DATA GAP: [topic]' — do not guess\n"
                    "5. Keep it terse. Bullet points. Military briefing style.\n\n"
                    + "\n\n".join(parts)
                ),
            }
            messages = [system_msg] + messages

    # ------------------------------------------------------------------
    # OLLAMA (local, default)
    # ------------------------------------------------------------------
    use_tools = payload.get("use_tools", provider == "ollama")

    if provider == "ollama":
        if use_stream:
            async def ollama_stream():
                if firewall_meta:
                    yield f"data: {json.dumps({'firewall_result': firewall_meta})}\n\n"
                last_err = None
                for host in OLLAMA_HOSTS:
                    host = host.strip()
                    try:
                        if use_tools:
                            final_msgs, actions = await chat_tools.run_ollama_with_tools(
                                host, model, messages, max_rounds=4
                            )
                            for act in actions:
                                yield f"data: {json.dumps({'client_action': act})}\n\n"
                            text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                            if text:
                                chunk = 48
                                for i in range(0, len(text), chunk):
                                    yield f"data: {json.dumps({'token': text[i:i + chunk]})}\n\n"
                            yield f"data: {json.dumps({'done': True})}\n\n"
                            return
                        url = f"http://{host}/api/chat"
                        async with httpx.AsyncClient(timeout=60.0) as client:
                            async with client.stream(
                                "POST",
                                url,
                                json={
                                    "model": model,
                                    "messages": messages,
                                    "stream": True,
                                    "keep_alive": keep_alive(),
                                },
                            ) as r:
                                r.raise_for_status()
                                async for line in r.aiter_lines():
                                    if not line.strip():
                                        continue
                                    try:
                                        data = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    if data.get("done"):
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    content = data.get("message", {}).get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                        return
                    except httpx.ConnectError:
                        last_err = f"Ollama not reachable at {host}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
                yield f"data: {json.dumps({'error': last_err or 'Ollama not reachable'})}\n\n"

            return StreamingResponse(ollama_stream(), media_type="text/event-stream")

        last_err = None
        for host in OLLAMA_HOSTS:
            host = host.strip()
            try:
                if use_tools:
                    final_msgs, actions = await chat_tools.run_ollama_with_tools(
                        host, model, messages, max_rounds=4
                    )
                    text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                    return {
                        "message": {"role": "assistant", "content": text},
                        "client_actions": actions,
                        "done": True,
                    }
                url = f"http://{host}/api/chat"
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.post(
                        url,
                        json={
                            "model": model,
                            "messages": messages,
                            "stream": False,
                            "keep_alive": keep_alive(),
                        },
                    )
                    r.raise_for_status()
                    return r.json()
            except httpx.ConnectError:
                last_err = f"Ollama not reachable at {host}"
                continue
            except httpx.HTTPStatusError as e:
                detail = ""
                try:
                    detail = e.response.text[:200]
                except Exception:
                    pass
                status = e.response.status_code
                if status == 404:
                    return {
                        "error": f"Model '{model}' not found. Run: ollama pull {model}",
                        "host": host,
                        "status": status,
                    }
                return {
                    "error": f"Ollama HTTP {status} at {host}",
                    "detail": detail,
                }
            except Exception as e:
                last_err = str(e)
                continue

        return {
            "error": last_err or "Ollama not running. Install from ollama.com",
            "hosts_tried": OLLAMA_HOSTS,
        }

    # ------------------------------------------------------------------
    # EXTERNAL PROVIDERS (OpenAI-compatible or Anthropic)
    # ------------------------------------------------------------------
    PROVIDER_CONFIG = {
        "openai": {
            "url": "https://api.openai.com/v1/chat/completions",
            "key": os.getenv("OPENAI_API_KEY"),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "groq": {
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "key": os.getenv("GROQ_API_KEY"),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "openrouter": {
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "key": os.getenv("OPENROUTER_API_KEY"),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
    }

    if provider in PROVIDER_CONFIG:
        cfg = PROVIDER_CONFIG[provider]
        api_key = cfg["key"]
        if not api_key:
            return {
                "error": f"No API key for {provider}. Set {provider.upper()}_API_KEY in .env",
                "provider": provider,
            }

        headers = {
            "Content-Type": "application/json",
            cfg["header"]: cfg["prefix"] + api_key,
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://worldbase.local"
            headers["X-Title"] = "WorldBase"

        body = {
            "model": model,
            "messages": messages,
            "stream": use_stream,
            "temperature": 0.7,
        }

        if use_stream:
            async def openai_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream("POST", cfg["url"], headers=headers, json=body) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    if payload_text.strip() == "[DONE]":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'{provider} stream error: {e}'})}\n\n"

            return StreamingResponse(openai_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(cfg["url"], headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                choice = data.get("choices", [{}])[0]
                return {
                    "message": {
                        "role": "assistant",
                        "content": choice.get("message", {}).get("content", "") or choice.get("text", ""),
                    },
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"{provider} HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"{provider} request failed: {e}", "provider": provider}

    # ------------------------------------------------------------------
    # ANTHROPIC (Messages API, non-OpenAI format)
    # ------------------------------------------------------------------
    if provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return {
                "error": "No API key for anthropic. Set ANTHROPIC_API_KEY in .env",
                "provider": provider,
            }

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        # Extract system message if present
        system_text = ""
        chat_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text = m.get("content", "")
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": 4096,
            "stream": use_stream,
        }
        if system_text:
            body["system"] = system_text

        if use_stream:
            async def anthropic_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream("POST", url, headers=headers, json=body) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    t = chunk.get("type", "")
                                    if t == "content_block_delta":
                                        text = chunk.get("delta", {}).get("text", "")
                                        if text:
                                            yield f"data: {json.dumps({'token': text})}\n\n"
                                    elif t == "message_stop":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'anthropic stream error: {e}'})}\n\n"

            return StreamingResponse(anthropic_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                content_blocks = data.get("content", [])
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return {
                    "message": {"role": "assistant", "content": text},
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"anthropic HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"anthropic request failed: {e}", "provider": provider}

    return {"error": f"Unknown provider '{provider}'", "available": ["ollama", "openai", "anthropic", "groq", "openrouter"]}


@app.get("/api/providers")
def list_providers():
    """Return available LLM providers based on configured API keys."""
    providers = [{"id": "ollama", "name": "Ollama (Local)", "models": [], "requires_key": False}]
    if os.getenv("OPENAI_API_KEY"):
        providers.append({"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"], "requires_key": True})
    if os.getenv("ANTHROPIC_API_KEY"):
        providers.append({"id": "anthropic", "name": "Anthropic", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"], "requires_key": True})
    if os.getenv("GROQ_API_KEY"):
        providers.append({"id": "groq", "name": "Groq", "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"], "requires_key": True})
    if os.getenv("OPENROUTER_API_KEY"):
        providers.append({"id": "openrouter", "name": "OpenRouter", "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"], "requires_key": True})
    return {"providers": providers}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
