"""CAMS-derived haze / air-quality signals via Open-Meteo (no API key).

Open-Meteo air-quality API uses Copernicus CAMS ensemble data globally.
Surfaces PM2.5, dust, and aerosol optical depth for operator + ASEAN cities.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

import feed_registry

router = APIRouter(prefix="/api/cams", tags=["cams"])

_UA = {"User-Agent": "WorldBase/1.0 (CAMS haze via Open-Meteo)"}
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = float(os.getenv("WORLDBASE_CAMS_CACHE_SEC", "3600"))
_FETCH_TIMEOUT = 18.0
_REFRESH_LOCK = asyncio.Lock()

# Thailand + ASEAN reference cities (burning season / transboundary haze)
_HAZE_CITIES: tuple[tuple[str, float, float], ...] = (
    ("Bangkok", 13.75, 100.5),
    ("Chiang Mai", 18.79, 98.98),
    ("Phuket", 7.88, 98.39),
    ("Hat Yai", 7.01, 100.47),
    ("Kuala Lumpur", 3.14, 101.69),
    ("Singapore", 1.35, 103.82),
    ("Jakarta", -6.21, 106.85),
    ("Yangon", 16.87, 96.20),
)


def _haze_severity(pm25: float | None, dust: float | None, aod: float | None) -> str:
    if pm25 is not None and pm25 >= 75:
        return "high"
    if dust is not None and dust >= 80:
        return "high"
    if aod is not None and aod >= 0.8:
        return "high"
    if pm25 is not None and pm25 >= 35:
        return "medium"
    if dust is not None and dust >= 40:
        return "medium"
    if aod is not None and aod >= 0.45:
        return "medium"
    return "low"


async def _fetch_city(
    client: httpx.AsyncClient, name: str, lat: float, lon: float
) -> dict | None:
    try:
        r = await client.get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "pm10,pm2_5,dust,aerosol_optical_depth,uv_index",
                "timezone": "UTC",
            },
        )
        r.raise_for_status()
        cur = r.json().get("current") or {}
    except Exception:
        return None
    pm25 = cur.get("pm2_5")
    dust = cur.get("dust")
    aod = cur.get("aerosol_optical_depth")
    return {
        "city": name,
        "lat": lat,
        "lon": lon,
        "pm25": pm25,
        "pm10": cur.get("pm10"),
        "dust": dust,
        "aerosol_optical_depth": aod,
        "uv_index": cur.get("uv_index"),
        "time": cur.get("time"),
        "severity": _haze_severity(
            float(pm25) if pm25 is not None else None,
            float(dust) if dust is not None else None,
            float(aod) if aod is not None else None,
        ),
        "source": "open-meteo/cams",
    }


async def fetch_haze_data() -> dict:
    """Pull CAMS-derived haze metrics for configured cities."""
    cities: list[dict] = []
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, headers=_UA) as client:
        results = await asyncio.gather(
            *(_fetch_city(client, name, lat, lon) for name, lat, lon in _HAZE_CITIES)
        )
    for row in results:
        if row:
            cities.append(row)

    elevated = [c for c in cities if c.get("severity") in ("high", "medium")]
    out = {
        "count": len(cities),
        "elevated_count": len(elevated),
        "cities": cities,
        "source": "open-meteo/cams",
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    if not cities:
        out["error"] = "no CAMS haze data returned"
    return out


async def get_haze(*, refresh: bool = False) -> dict:
    cache_key = "cams_haze"
    if not refresh:
        hit = _CACHE.get(cache_key)
        if hit and (time.time() - hit[0]) < _TTL:
            return hit[1]

    async with _REFRESH_LOCK:
        hit = _CACHE.get(cache_key)
        if not refresh and hit and (time.time() - hit[0]) < _TTL:
            return hit[1]

        stale = hit[1] if hit else None
        try:
            out = await asyncio.wait_for(fetch_haze_data(), timeout=_FETCH_TIMEOUT + 4)
        except asyncio.TimeoutError:
            if stale:
                s = dict(stale)
                s["stale"] = True
                s["error"] = "upstream timeout — serving stale cache"
                return s
            out = {"count": 0, "cities": [], "error": "upstream timeout"}

        if out.get("cities"):
            feed_registry.write_auto(cache_key, out)
            _CACHE[cache_key] = (time.time(), out)
        elif stale:
            s = dict(stale)
            s["stale"] = True
            return s
        else:
            _CACHE[cache_key] = (time.time(), out)
        return out


@router.get("/haze")
async def cams_haze(refresh: bool = False):
    """CAMS-derived haze metrics (PM2.5, dust, AOD) for Thailand + ASEAN cities."""
    return await get_haze(refresh=refresh)
