"""GDELT DOC API — global news pulse (no key; respect 5s rate limit via cache)."""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter, Query

from stac_bridge import REGION_PRESETS

router = APIRouter(prefix="/api/gdelt", tags=["gdelt"])

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT)"}
_CACHE: dict[str, tuple[float, dict]] = {}

# Rotating civic queries — one per cache refresh (global pulse)
_QUERIES = [
    "(earthquake OR flood OR wildfire)",
    "(protest OR conflict OR violence)",
    "(cyberattack OR outage OR blackout)",
]

# Operator-home DOC queries for briefing LOCAL block (GDELT DOC 2.0 syntax)
_REGION_DOC_QUERIES: dict[str, str] = {
    "thailand": (
        '(thailand OR bangkok OR phuket OR chiangmai OR "chiang mai" OR thai OR andaman)'
    ),
    "bangkok": '(bangkok OR "greater bangkok" OR thailand) sourcecountry:TH',
    "phuket": '(phuket OR andaman OR krabi OR thailand)',
    "mekong-delta": '(mekong OR "mekong delta" OR vietnam OR cambodia OR laos OR thailand)',
    "germany": '(germany OR deutschland OR berlin OR munich OR hamburg OR rhein)',
    "rhein": '(rhein OR rhine OR germany OR deutschland OR "north rhine")',
}

_REGION_GEO_QUERIES: dict[str, str] = {
    "thailand": "(thailand OR bangkok OR myanmar OR cambodia) (conflict OR protest OR earthquake OR flood OR storm)",
    "bangkok": "(bangkok OR thailand) (flood OR protest OR earthquake OR fire)",
    "germany": "(germany OR deutschland) (flood OR protest OR earthquake OR storm)",
    "rhein": "(germany OR rhein OR rhine) (flood OR storm OR earthquake)",
}


def _operator_region() -> str:
    return os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()


def _region_bbox(region: str) -> list[float] | None:
    preset = REGION_PRESETS.get(region)
    if not preset:
        return None
    return list(preset["bbox"])


def _in_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


async def _fetch_doc_articles(query: str, maxrecords: int = 40) -> tuple[list[dict], str | None]:
    try:
        async with httpx.AsyncClient(timeout=45.0, headers=_UA) as client:
            r = await client.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "maxrecords": maxrecords,
                    "format": "json",
                },
            )
            if r.status_code == 429:
                return [], "GDELT rate limit (retry in ~5s)"
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return [], str(e)

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
    return articles, None


async def _fetch_geo_events(
    query: str,
    timespan: str,
    maxrecords: int,
    bbox: list[float] | None = None,
) -> tuple[list[dict], str | None]:
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
                return [], "GDELT rate limit"
            r.raise_for_status()
            gj = r.json()
    except Exception as e:
        return [], str(e)

    events = []
    for f in gj.get("features") or []:
        props = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        lat_f, lon_f = float(lat), float(lon)
        if bbox and not _in_bbox(lat_f, lon_f, bbox):
            continue
        events.append({
            "name": (props.get("name") or props.get("html") or "")[:200],
            "url": props.get("url") or props.get("shareimage"),
            "count": props.get("count"),
            "lat": lat_f,
            "lon": lon_f,
            "date": props.get("date"),
        })
    return events, None


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
    articles, err = await _fetch_doc_articles(query, maxrecords=40)
    if err and not articles:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            out["error"] = err
            return out
        return {"count": 0, "articles": [], "query": query, "error": err}

    out = {
        "count": len(articles),
        "query": query,
        "articles": articles,
        "cached_at": time.time(),
        "hint": "Headlines for Situation Board / chat context — geo layer uses GDACS + crises",
    }
    if err:
        out["error"] = err
        out["stale"] = True
    _CACHE[key] = (time.time(), out)
    return out


@router.get("/pulse/local")
async def gdelt_pulse_local(region: str | None = Query(None, description="Operator region preset")):
    """
    Headlines scoped to the operator home region (for briefing LOCAL block).
    Cached 10 minutes. Uses WORLDBASE_OPERATOR_REGION when region is omitted.
    """
    reg = (region or _operator_region()).lower()
    query = _REGION_DOC_QUERIES.get(reg) or f"({reg.replace('_', ' ')})"
    key = f"pulse:local:{reg}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 600:
        return cached[1]

    articles, err = await _fetch_doc_articles(query, maxrecords=25)
    if err and not articles:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            out["error"] = err
            return out
        return {
            "count": 0,
            "articles": [],
            "query": query,
            "region": reg,
            "error": err,
        }

    out = {
        "count": len(articles),
        "query": query,
        "region": reg,
        "articles": articles,
        "cached_at": time.time(),
        "hint": "Region-scoped headlines for security digest LOCAL section",
    }
    if err:
        out["error"] = err
        out["stale"] = True
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
    bbox = None
    events, err = await _fetch_geo_events(query, timespan, maxrecords, bbox)
    if err and not events:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            return out
        return {"count": 0, "events": [], "error": err}

    out = {
        "count": len(events),
        "query": query,
        "timespan": timespan,
        "events": events,
        "cached_at": time.time(),
    }
    if err:
        out["error"] = err
        out["stale"] = True
    _CACHE[key] = (time.time(), out)
    return out


@router.get("/geo/local")
async def gdelt_geo_local(
    region: str | None = Query(None),
    timespan: str = "1d",
    maxrecords: int = 50,
):
    """
    GDELT GEO points filtered to the operator region bbox.
    Cached 15 minutes. For briefing LOCAL / REGION buckets.
    """
    reg = (region or _operator_region()).lower()
    bbox = _region_bbox(reg)
    query = _REGION_GEO_QUERIES.get(reg) or "(conflict OR protest OR earthquake OR flood)"
    key = f"geo:local:{reg}:{timespan}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 900:
        return cached[1]

    events, err = await _fetch_geo_events(query, timespan, maxrecords, bbox)
    if err and not events:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            return out
        return {"count": 0, "events": [], "region": reg, "query": query, "error": err}

    out = {
        "count": len(events),
        "query": query,
        "region": reg,
        "timespan": timespan,
        "events": events,
        "cached_at": time.time(),
        "bbox": bbox,
    }
    if err:
        out["error"] = err
        out["stale"] = True
    _CACHE[key] = (time.time(), out)
    return out
