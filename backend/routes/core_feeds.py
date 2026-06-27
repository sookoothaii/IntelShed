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
from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector
from runtime_cache import cache_get, cache_get_stale, cache_set

router = APIRouter(tags=["core-feeds"])

_TLE_GROUP_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_QUAKES_CONNECTOR = FeedConnector(
    "quakes:day", ttl_sec=300.0, default_source="earthquake.usgs.gov"
)
_EONET_CONNECTOR = FeedConnector(
    "eonet", ttl_sec=1800.0, default_source="eonet.gsfc.nasa.gov"
)


def _sanitize_tle_group(group: str) -> str:
    g = (group or "active").strip()
    if not _TLE_GROUP_RE.match(g):
        raise HTTPException(status_code=400, detail="Invalid TLE group name")
    return g


@router.get("/api/satellites")
async def get_satellites(limit: int = 400, group: str = "active"):
    """Fetch satellite TLEs from CelesTrak (cached 6h).

    Useful groups: active, stations, starlink, gps-ops, weather, science, geo.
    """
    group = _sanitize_tle_group(group)
    cache_key = f"sat:{group}"
    tle_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "tle")
    os.makedirs(tle_dir, exist_ok=True)
    disk_path = os.path.join(tle_dir, f"{group}.tle")

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

    lines = [ln.strip() for ln in tle_text.splitlines() if ln.strip()]
    satellites = []
    i = 0
    cap = max(0, min(limit, 2000))
    while i < len(lines) - 2:
        if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            satellites.append(
                {
                    "name": lines[i],
                    "tle1": lines[i + 1],
                    "tle2": lines[i + 2],
                }
            )
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
    subkey = f"quakes:{period}:{magnitude}"

    async def _fetch():
        url = f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{magnitude}_{period}.geojson"
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        quakes = []
        for f in data.get("features", []):
            props = f.get("properties", {})
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [None, None, None])
            quakes.append(
                {
                    "id": f.get("id"),
                    "place": props.get("place"),
                    "mag": props.get("mag"),
                    "time": props.get("time"),
                    "depth": coords[2],
                    "lon": coords[0],
                    "lat": coords[1],
                    "tsunami": props.get("tsunami"),
                    "url": props.get("url"),
                }
            )
        return FeedEnvelope(
            count=len(quakes),
            source="earthquake.usgs.gov",
        ).merge(earthquakes=quakes)

    return await _QUAKES_CONNECTOR.run(_fetch, subkey=subkey)


@router.get("/api/events")
async def get_events(limit: int = 100):
    """NASA EONET natural events: wildfires, storms, volcanoes, ice (cached 30min)."""

    async def _fetch():
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200"
            )
            r.raise_for_status()
            data = r.json()
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
            events.append(
                {
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
                }
            )
        return FeedEnvelope(
            count=len(events),
            source="eonet.gsfc.nasa.gov",
        ).merge(events=events)

    return await _EONET_CONNECTOR.run(_fetch)


@router.get("/api/iss")
async def get_iss():
    """Precise ISS position (cached 4s)."""
    data = cache_get("iss", ttl=4.0)
    if data is None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get("https://api.wheretheiss.at/v1/satellites/25544")
                r.raise_for_status()
                data = r.json()
            cache_set("iss", data)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=503, detail=f"ISS upstream timeout: {exc}")
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=502, detail=f"ISS upstream unreachable: {exc}"
            )
    return data


@router.get("/api/world")
async def get_world():
    """Stub for world.json aggregation (markets, geo threats)."""
    data = await feed_registry.async_read_sqlite("world")
    if data:
        return data
    return {
        "status": "empty",
        "message": "Run world-sync to populate.",
        "currencies": {},
        "geo": {},
        "news": [],
    }
