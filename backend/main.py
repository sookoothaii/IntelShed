"""WorldBase API — FastAPI backend, SQLite cache, no Docker."""

import os
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")

app = FastAPI(title="WorldBase API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


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


@app.get("/api/aircraft")
async def get_aircraft(limit: int = 800):
    """Fetch live aircraft from OpenSky Network (cached 15s).

    OpenSky's anonymous API is heavily rate-limited (HTTP 429). On any upstream
    failure we serve the last good snapshot (stale cache) instead of erroring,
    so the globe keeps showing aircraft.
    """
    cache_key = "aircraft"
    cached = _cache_get(cache_key, ttl=15.0)
    if cached is None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get("https://opensky-network.org/api/states/all")
                r.raise_for_status()
                cached = r.json()
            _cache_set(cache_key, cached)
        except Exception as e:
            stale = _CACHE.get(cache_key)
            if stale:
                cached = stale[1]
            else:
                return {
                    "count": 0,
                    "timestamp": None,
                    "states": [],
                    "error": f"OpenSky unavailable ({e.__class__.__name__}); no cached data yet.",
                }

    states = cached.get("states", []) or []
    with_pos = [s for s in states if len(s) > 6 and s[5] is not None and s[6] is not None]
    return {
        "count": len(with_pos),
        "timestamp": cached.get("time"),
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

OLLAMA_HOSTS = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")


@app.get("/api/models")
async def list_models():
    """List available Ollama models."""
    for host in OLLAMA_HOSTS:
        host = host.strip()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"http://{host}/api/tags")
                r.raise_for_status()
                data = r.json()
                models = data.get("models", [])
                return {
                    "host": host,
                    "count": len(models),
                    "models": [
                        {"name": m.get("name"), "size": m.get("size"), "parameter_size": m.get("details", {}).get("parameter_size")}
                        for m in models
                    ],
                }
        except Exception:
            continue
    return {"error": "Ollama not reachable", "hosts_tried": OLLAMA_HOSTS}


@app.post("/api/chat")
async def chat_proxy(payload: dict):
    """Proxy chat requests to local Ollama."""
    model = payload.get("model", "llama3.2")
    last_err = None

    for host in OLLAMA_HOSTS:
        host = host.strip()
        url = f"http://{host}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    url,
                    json={
                        "model": model,
                        "messages": payload.get("messages", []),
                        "stream": False,
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
