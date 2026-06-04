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
