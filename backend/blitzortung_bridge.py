"""Blitzortung.org — Real-time lightning strike data.
Community-driven lightning detection network. Free for non-commercial use.
"""
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["lightning"])

_BLITZ_CACHE = {}
_BLITZ_TTL = 60  # 1 minute — lightning is very dynamic


@router.get("/lightning")
async def get_lightning():
    """Recent lightning strikes worldwide from Blitzortung.org.
    Cached 1 minute. No key. Data covers roughly last 10-20 minutes.
    """
    now = datetime.now(timezone.utc).timestamp()
    cached = _BLITZ_CACHE.get("strikes")
    if cached and (now - cached["ts"]) < _BLITZ_TTL:
        return cached["data"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Blitzortung JSON endpoint — strikes from last ~10 minutes
            r = await client.get(
                "https://map.blitzortung.org/GeoJson/getData?f=std",
                headers={"User-Agent": "WorldBase/1.0 (research)"},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"count": 0, "updated": datetime.now(timezone.utc).isoformat(), "strikes": [], "error": str(e)}

    strikes = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        geom = feat.get("geometry", {})
        coords = geom.get("coordinates", [0, 0])
        try:
            strikes.append({
                "lon": coords[0],
                "lat": coords[1],
                "time": props.get("time"),
                "deviation": props.get("deviation"),
                "status": props.get("status"),
                "max_values": props.get("max_values"),
                "stations": props.get("stations"),
                "participants": props.get("participants"),
            })
        except (IndexError, TypeError):
            continue

    result = {
        "count": len(strikes),
        "updated": datetime.now(timezone.utc).isoformat(),
        "strikes": strikes,
    }

    _BLITZ_CACHE["strikes"] = {"ts": now, "data": result}
    return result
