"""GDELT DOC API — global news pulse (no key; respect 5s rate limit via cache)."""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/gdelt", tags=["gdelt"])

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT)"}
_CACHE: dict[str, tuple[float, dict]] = {}

# Rotating civic queries — one per cache refresh
_QUERIES = [
    "(earthquake OR flood OR wildfire)",
    "(protest OR conflict OR violence)",
    "(cyberattack OR outage OR blackout)",
]


@router.get("/pulse")
async def gdelt_pulse():
    """
    Recent global news themes with source countries (GDELT DOC 2.0).
    Cached 10 minutes to stay under GDELT rate limits.
    """
    key = "pulse"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 600:
        return cached[1]

    slot = int(time.time() // 600) % len(_QUERIES)
    query = _QUERIES[slot]
    try:
        async with httpx.AsyncClient(timeout=45.0, headers=_UA) as client:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "maxrecords": 40,
                    "format": "json",
                },
            )
            if r.status_code == 429:
                stale = _CACHE.get(key)
                if stale:
                    out = stale[1].copy()
                    out["stale"] = True
                    out["error"] = "GDELT rate limit — serving cache"
                    return out
                return {
                    "count": 0,
                    "articles": [],
                    "query": query,
                    "error": "GDELT rate limit (retry in ~5s)",
                }
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            return out
        return {"count": 0, "articles": [], "error": str(e)}

    articles = []
    for art in data.get("articles") or []:
        articles.append({
            "title": art.get("title"),
            "url": art.get("url"),
            "seendate": art.get("seendate"),
            "domain": art.get("domain"),
            "language": art.get("language"),
            "sourcecountry": art.get("sourcecountry"),
        })

    out = {
        "count": len(articles),
        "query": query,
        "articles": articles,
        "cached_at": time.time(),
        "hint": "Headlines for Situation Board / chat context — geo layer uses GDACS + crises",
    }
    _CACHE[key] = (time.time(), out)
    return out


@router.get("/geo")
async def gdelt_geo(timespan: str = "1d", maxrecords: int = 60):
    """
    GDELT GEO 2.0 — geocoded event points (conflict/disaster themes).
    Cached 15 minutes. No API key.
    """
    key = f"geo:{timespan}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 900:
        return cached[1]

    query = "(conflict OR protest OR earthquake OR flood OR explosion)"
    try:
        async with httpx.AsyncClient(timeout=60.0, headers=_UA) as client:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/geo/geo",
                params={
                    "query": query,
                    "mode": "PointData",
                    "format": "GeoJSON",
                    "timespan": timespan,
                    "maxrecords": min(maxrecords, 120),
                },
            )
            if r.status_code == 429:
                stale = _CACHE.get(key)
                if stale:
                    out = stale[1].copy()
                    out["stale"] = True
                    return out
                return {"count": 0, "events": [], "error": "GDELT rate limit"}
            r.raise_for_status()
            gj = r.json()
    except Exception as e:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            return out
        return {"count": 0, "events": [], "error": str(e)}

    events = []
    for f in gj.get("features") or []:
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        events.append({
            "name": (props.get("name") or props.get("html") or "")[:200],
            "url": props.get("url") or props.get("shareimage"),
            "count": props.get("count"),
            "lat": float(lat),
            "lon": float(lon),
            "date": props.get("date"),
        })

    out = {
        "count": len(events),
        "query": query,
        "timespan": timespan,
        "events": events,
        "cached_at": time.time(),
    }
    _CACHE[key] = (time.time(), out)
    return out
