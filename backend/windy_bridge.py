"""Windy.com Point Forecast + Map config proxy.

Point Forecast key stays server-side. Map/Plugins keys are exposed via /config for
client-side libBoot.js (Windy Map Forecast API requires browser init).
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/windy", tags=["windy"])

POINT_URL = "https://api.windy.com/api/point-forecast/v2"

REGION_BBOX: dict[str, tuple[float, float, float, float, float]] = {
    # west, south, east, north, step_deg
    "thailand": (97.3, 5.6, 105.65, 20.46, 2.5),
    "asean": (92.0, -8.0, 141.0, 28.0, 4.0),
    "operator": (98.0, 7.0, 103.0, 12.0, 1.5),
}

_CACHE: dict[str, tuple[float, dict]] = {}
POINT_TTL = 600.0
GRID_TTL = 900.0


def _point_key() -> str:
    return os.getenv("WINDY_POINT_API_KEY", "").strip()


def _map_key() -> str:
    return os.getenv("WINDY_MAP_API_KEY", "").strip()


def _plugins_key() -> str:
    return os.getenv("WINDY_PLUGINS_API_KEY", "").strip()


def operator_lat() -> float:
    return float(os.getenv("WORLDBASE_OPERATOR_LAT", "9.55"))


def operator_lon() -> float:
    return float(os.getenv("WORLDBASE_OPERATOR_LON", "100.05"))


def _default_model() -> str:
    return os.getenv("WINDY_POINT_MODEL", "gfs").strip() or "gfs"


def _default_parameters() -> list[str]:
    raw = os.getenv("WINDY_POINT_PARAMETERS", "wind,temp,precip,rh,pressure")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _ts_to_iso(raw: int | float) -> str:
    sec = float(raw)
    if sec > 1e12:
        sec /= 1000.0
    return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()


def _cache_get(key: str, ttl: float) -> dict | None:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key: str, val: dict) -> None:
    _CACHE[key] = (time.time(), val)


def _wind_from_uv(u: float | None, v: float | None) -> tuple[float | None, float | None]:
    if u is None or v is None:
        return None, None
    speed = math.sqrt(u * u + v * v)
    # meteorological direction (where wind comes from)
    direction = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
    return round(speed, 1), round(direction, 0)


def _normalize_point(lat: float, lon: float, data: dict, model: str) -> dict:
    ts = data.get("ts") or []
    times = [_ts_to_iso(t) for t in ts[:24]]

    u0 = (data.get("wind_u-surface") or [None])[0]
    v0 = (data.get("wind_v-surface") or [None])[0]
    temp_k = (data.get("temp-surface") or [None])[0]
    rh = (data.get("rh-surface") or [None])[0]
    precip_m = (data.get("past3hprecip-surface") or [None])[0]
    pressure_pa = (data.get("pressure-surface") or [None])[0]
    wind_ms, wind_deg = _wind_from_uv(u0, v0)

    temp_c = round(temp_k - 273.15, 1) if temp_k is not None else None
    precip_mm = round(float(precip_m) * 1000.0, 2) if precip_m is not None else None
    pressure_hpa = round(float(pressure_pa) / 100.0, 1) if pressure_pa is not None else None

    hourly = []
    temps = data.get("temp-surface") or []
    us = data.get("wind_u-surface") or []
    vs = data.get("wind_v-surface") or []
    for i, t in enumerate(ts[:24]):
        tk = temps[i] if i < len(temps) else None
        sp, dg = _wind_from_uv(us[i] if i < len(us) else None, vs[i] if i < len(vs) else None)
        hourly.append({
            "time": _ts_to_iso(t),
            "temperature_c": round(tk - 273.15, 1) if tk is not None else None,
            "wind_speed_ms": sp,
            "wind_direction_deg": dg,
        })

    return {
        "lat": lat,
        "lon": lon,
        "source": "windy",
        "model": model,
        "timezone": "UTC",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "time": times[0] if times else None,
            "temperature_c": temp_c,
            "humidity_pct": round(rh, 0) if rh is not None else None,
            "wind_speed_ms": wind_ms,
            "wind_direction_deg": wind_deg,
            "precip_mm_3h": precip_mm,
            "pressure_hpa": pressure_hpa,
        },
        "hourly": hourly,
        "units": data.get("units"),
        "warning": data.get("warning"),
    }


async def fetch_windy_point(
    lat: float,
    lon: float,
    *,
    model: str | None = None,
    parameters: list[str] | None = None,
) -> dict | None:
    key = _point_key()
    if not key:
        return None
    model = model or _default_model()
    parameters = parameters or _default_parameters()
    cache_key = f"pt:{round(lat, 2)}:{round(lon, 2)}:{model}"
    cached = _cache_get(cache_key, POINT_TTL)
    if cached is not None:
        return cached

    body = {
        "lat": lat,
        "lon": lon,
        "model": model,
        "parameters": parameters,
        "levels": ["surface"],
        "key": key,
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(POINT_URL, json=body)
            r.raise_for_status()
            data = r.json()
        out = _normalize_point(lat, lon, data, model)
        _cache_set(cache_key, out)
        return out
    except Exception:
        stale = _cache_get(cache_key, POINT_TTL * 24)
        return stale


async def fetch_open_meteo_point(lat: float, lon: float) -> dict:
    """Open-Meteo fallback when Windy Point key is missing or fails."""
    cache_key = f"om:{round(lat, 2)}:{round(lon, 2)}"
    cached = _cache_get(cache_key, POINT_TTL)
    if cached is not None:
        return cached

    headers = {"User-Agent": "WorldBase/1.0 (weather)"}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                    "wind_direction_10m,weather_code,pressure_msl,precipitation",
                    "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
                    "forecast_days": 2,
                    "timezone": "auto",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"lat": lat, "lon": lon, "source": "open-meteo", "current": {}, "error": str(e)}

    cur = data.get("current") or {}
    hourly_raw = data.get("hourly") or {}
    hourly = []
    ht = hourly_raw.get("time") or []
    for i, t in enumerate(ht[:24]):
        hourly.append({
            "time": t,
            "temperature_c": (hourly_raw.get("temperature_2m") or [None])[i],
            "wind_speed_ms": (hourly_raw.get("wind_speed_10m") or [None])[i],
            "precip_prob_pct": (hourly_raw.get("precipitation_probability") or [None])[i],
        })

    out = {
        "lat": lat,
        "lon": lon,
        "source": "open-meteo",
        "timezone": data.get("timezone"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "current": {
            "time": cur.get("time"),
            "temperature_c": cur.get("temperature_2m"),
            "humidity_pct": cur.get("relative_humidity_2m"),
            "wind_speed_ms": cur.get("wind_speed_10m"),
            "wind_direction_deg": cur.get("wind_direction_10m"),
            "pressure_hpa": cur.get("pressure_msl"),
            "precip_mm_3h": cur.get("precipitation"),
            "weather_code": cur.get("weather_code"),
        },
        "hourly": hourly,
        "units": data.get("current_units", {}),
    }
    _cache_set(cache_key, out)
    return out


async def fetch_point_weather(lat: float, lon: float, *, model: str | None = None) -> dict:
    windy = await fetch_windy_point(lat, lon, model=model)
    if windy and windy.get("current", {}).get("temperature_c") is not None:
        return windy
    fallback = await fetch_open_meteo_point(lat, lon)
    if windy:
        fallback["windy_error"] = True
    return fallback


def _grid_points(west: float, south: float, east: float, north: float, step: float) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    lat = south
    while lat <= north + 1e-9:
        lon = west
        while lon <= east + 1e-9:
            pts.append((round(lat, 3), round(lon, 3)))
            lon += step
        lat += step
    return pts[:36]


@router.get("/config")
def windy_config():
    """Client map init keys + defaults (Point Forecast key never exposed)."""
    return {
        "point_configured": bool(_point_key()),
        "map_configured": bool(_map_key()),
        "plugins_configured": bool(_plugins_key()),
        "map_key": _map_key() or None,
        "plugins_key": _plugins_key() or None,
        "default_lat": operator_lat(),
        "default_lon": operator_lon(),
        "default_model": _default_model(),
        "regions": list(REGION_BBOX.keys()),
        "map_tier": os.getenv("WINDY_MAP_TIER", "testing").strip().lower() or "testing",
        "map_layers_testing": ["wind", "temp", "pressure"],
        "map_layers_pro_note": "Professional Map Forecast unlocks rain, clouds, CAPE, satellite, and 40+ layers.",
    }


@router.get("/point")
async def windy_point(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    model: str = "",
):
    out = await fetch_point_weather(lat, lon, model=model or None)
    if not out.get("current"):
        raise HTTPException(status_code=503, detail=out.get("error") or "Forecast unavailable")
    return out


@router.get("/grid")
async def windy_grid(
    region: str = "thailand",
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    step: float | None = None,
):
    """Sample grid of surface temp/wind for globe labels (max 36 points)."""
    if not _point_key():
        raise HTTPException(status_code=503, detail="WINDY_POINT_API_KEY not configured")

    if west is None and region in REGION_BBOX:
        west, south, east, north, step = REGION_BBOX[region]
    if west is None or south is None or east is None or north is None:
        raise HTTPException(status_code=400, detail="Provide region or bbox (west,south,east,north)")
    step = step or 2.5

    cache_key = f"grid:{region}:{west}:{south}:{east}:{north}:{step}"
    cached = _cache_get(cache_key, GRID_TTL)
    if cached is not None:
        return cached

    points = _grid_points(west, south, east, north, step)
    sem = asyncio.Semaphore(4)

    async def one(lat: float, lon: float) -> dict | None:
        async with sem:
            pt = await fetch_windy_point(lat, lon)
            if not pt:
                return None
            cur = pt.get("current") or {}
            return {
                "lat": lat,
                "lon": lon,
                "temperature_c": cur.get("temperature_c"),
                "wind_speed_ms": cur.get("wind_speed_ms"),
                "wind_direction_deg": cur.get("wind_direction_deg"),
                "humidity_pct": cur.get("humidity_pct"),
                "precip_mm_3h": cur.get("precip_mm_3h"),
                "pressure_hpa": cur.get("pressure_hpa"),
            }

    results = await asyncio.gather(*(one(lat, lon) for lat, lon in points))
    cells = [c for c in results if c and c.get("temperature_c") is not None]
    out = {
        "region": region,
        "bbox": {"west": west, "south": south, "east": east, "north": north, "step": step},
        "count": len(cells),
        "model": _default_model(),
        "cells": cells,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(cache_key, out)
    return out
