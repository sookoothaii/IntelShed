"""CAMS-derived haze / air-quality signals via Open-Meteo (no API key).

Open-Meteo air-quality API uses Copernicus CAMS ensemble data globally.
Surfaces PM2.5, dust, and aerosol optical depth for operator + ASEAN cities.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/cams", tags=["cams"])

_UA = {"User-Agent": "WorldBase/1.0 (CAMS haze via Open-Meteo)"}
_TTL = float(os.getenv("WORLDBASE_CAMS_CACHE_SEC", "3600"))
_FETCH_TIMEOUT = 18.0
_REFRESH_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector("cams_haze", ttl_sec=_TTL, default_source="open-meteo/cams")

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
        "updated": utc_now_iso(),
    }
    if not cities:
        out["error"] = "no CAMS haze data returned"
    return out


def _wrap_haze_payload(raw: dict, *, stale: bool = False, error: str | None = None) -> dict:
    elevated = raw.get("elevated_count")
    if elevated is None and raw.get("cities"):
        elevated = sum(
            1 for c in raw["cities"] if c.get("severity") in ("high", "medium")
        )
    return _CONNECTOR.build(
        FeedEnvelope(
            count=int(raw.get("count") or len(raw.get("cities") or [])),
            stale=stale,
            error=error or raw.get("error"),
        ),
        persist=bool(raw.get("cities")) and not stale and not error,
        cities=raw.get("cities") or [],
        elevated_count=elevated or 0,
    )


async def get_haze(*, refresh: bool = False) -> dict:
    if not refresh:
        hit = _CONNECTOR.get_cached()
        if hit is not None:
            return hit

    async with _REFRESH_LOCK:
        if not refresh:
            hit = _CONNECTOR.get_cached()
            if hit is not None:
                return hit

        stale_hit = _CONNECTOR.peek_memory()
        try:
            raw = await asyncio.wait_for(fetch_haze_data(), timeout=_FETCH_TIMEOUT + 4)
        except asyncio.TimeoutError:
            if stale_hit:
                return _wrap_haze_payload(stale_hit, stale=True, error="upstream timeout — serving stale cache")
            return _CONNECTOR.build(
                FeedEnvelope(count=0, error="upstream timeout"),
                persist=False,
                cities=[],
            )

        if raw.get("cities"):
            return _wrap_haze_payload(raw)
        if stale_hit:
            return _wrap_haze_payload(stale_hit, stale=True)
        return _wrap_haze_payload(raw)


@router.get("/haze")
async def cams_haze(refresh: bool = False):
    """CAMS-derived haze metrics (PM2.5, dust, AOD) for Thailand + ASEAN cities."""
    return await get_haze(refresh=refresh)
