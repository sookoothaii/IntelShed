"""Core feed endpoints — satellites, earthquakes, NASA EONET events, ISS, world.

Extracted from main.py (Phase 1 decortication). Paths are unchanged
(``/api/satellites`` etc.). These share the process-local TTL cache in
runtime_cache so chat context and globe snapshots keep seeing the same data.
"""

from __future__ import annotations

import os
import re

import httpx
from fastapi import APIRouter, HTTPException

import feed_registry
from runtime_cache import cache_get, cache_get_stale, cache_set

router = APIRouter(tags=["core-feeds"])

# CelesTrak GROUP names only — blocks path traversal via ``group`` (e.g. ../../../tmp).
SATELLITE_GROUPS = frozenset({
    "active",
    "stations",
    "starlink",
    "gps-ops",
    "weather",
    "science",
    "geo",
    "iridium",
    "iridium-next",
    "oneweb",
    "galileo",
    "gnss",
    "noaa",
    "resource",
    "sarsat",
    "tdrss",
    "argos",
    "planet",
    "spire",
})


def _validate_satellite_group(group: str) -> str:
    g = (group or "").strip().lower()
    if not g or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", g):
        raise HTTPException(status_code=400, detail="Invalid satellite group")
    if g not in SATELLITE_GROUPS:
        raise HTTPException(status_code=400, detail=f"Unknown satellite group: {g}")
    return g


def _safe_tle_disk_path(tle_dir: str, group: str) -> str:
    """Resolve TLE cache path under ``tle_dir`` (defense-in-depth after allowlist)."""
    disk_path = os.path.join(tle_dir, f"{group}.tle")
    real_dir = os.path.realpath(tle_dir)
    real_path = os.path.realpath(disk_path)
    if real_path != real_dir and not real_path.startswith(real_dir + os.sep):
        raise HTTPException(status_code=400, detail="Invalid satellite group path")
    return real_path


@router.get("/api/satellites")
async def get_satellites(limit: int = 400, group: str = "active"):
    """Fetch satellite TLEs from CelesTrak (cached 6h).

    Useful groups: active, stations, starlink, gps-ops, weather, science, geo.
    """
    group = _validate_satellite_group(group)
    cache_key = f"sat:{group}"
    tle_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tle")
    os.makedirs(tle_dir, exist_ok=True)
    disk_path = _safe_tle_disk_path(tle_dir, group)

    tle_text = cache_get(cache_key, ttl=6 * 3600.0)
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
            cache_set(cache_key, tle_text)
            # Persist to disk for resilience across reloads / 403s
            with open(disk_path, "w", encoding="utf-8") as f:
                f.write(tle_text)
        except Exception as e:
            # Fallback chain: in-memory stale -> disk cache -> empty
            stale = cache_get_stale(cache_key)
            if stale is not None:
                tle_text = stale
            elif os.path.exists(disk_path):
                with open(disk_path, "r", encoding="utf-8") as f:
                    tle_text = f.read()
                cache_set(cache_key, tle_text)
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


@router.get("/api/earthquakes")
async def get_earthquakes(period: str = "day", magnitude: str = "2.5"):
    """USGS earthquakes feed (cached 5min).

    period: hour, day, week, month. magnitude: significant, 4.5, 2.5, 1.0, all.
    """
    key = f"quakes:{period}:{magnitude}"
    data = cache_get(key, ttl=300.0)
    upstream_err = None
    stale = False
    if data is None:
        url = f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{magnitude}_{period}.geojson"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
            cache_set(key, data)
        except Exception as e:
            upstream_err = str(e)
            cached = cache_get_stale(key)
            if cached is not None:
                data = cached
                stale = True
            else:
                return {
                    "count": 0,
                    "earthquakes": [],
                    "error": upstream_err,
                    "stale": False,
                    "source": "earthquake.usgs.gov",
                }

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
    result = {
        "count": len(quakes),
        "earthquakes": quakes,
        "source": "earthquake.usgs.gov",
        "stale": stale,
        "error": upstream_err,
    }
    try:
        import feed_registry

        feed_registry.write_auto(key, result)
    except Exception:
        pass
    return result


@router.get("/api/events")
async def get_events(limit: int = 100):
    """NASA EONET natural events: wildfires, storms, volcanoes, ice (cached 30min)."""
    data = cache_get("eonet", ttl=1800.0)
    upstream_err = None
    stale = False
    if data is None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(
                    "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200"
                )
                r.raise_for_status()
                data = r.json()
            cache_set("eonet", data)
        except Exception as e:
            upstream_err = str(e)
            cached = cache_get_stale("eonet")
            if cached is not None:
                data = cached
                stale = True
            else:
                return {"count": 0, "events": [], "error": upstream_err, "stale": False}

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
    out = {"count": len(events), "events": events}
    if upstream_err:
        out["error"] = upstream_err
        out["stale"] = stale
    return out


@router.get("/api/iss")
async def get_iss():
    """Precise ISS position (cached 4s)."""
    data = cache_get("iss", ttl=4.0)
    if data is None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get("https://api.wheretheiss.at/v1/satellites/25544")
            r.raise_for_status()
            data = r.json()
        cache_set("iss", data)
    return data


@router.get("/api/world")
async def get_world():
    """Stub for world.json aggregation (markets, geo threats)."""
    data = feed_registry.read("world")
    if data:
        return data
    return {
        "status": "empty",
        "message": "Run world-sync to populate.",
        "currencies": {},
        "geo": {},
        "news": [],
    }
