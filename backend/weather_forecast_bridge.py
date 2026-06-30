"""Open-Meteo multi-day weather forecast for Thailand/ASEAN (no API key).

Free, key-less 7-day forecast with daily temperature, precipitation, wind,
and severe-weather detection for operator home region situational awareness.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter, Query

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/weather", tags=["weather-forecast"])

_UA = {"User-Agent": "WorldBase/1.0 (Open-Meteo forecast)"}
_TTL = float(os.getenv("WORLDBASE_WEATHER_FORECAST_CACHE_SEC", "3600"))
_FETCH_TIMEOUT = 18.0
_REFRESH_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector(
    "weather_forecast", ttl_sec=_TTL, default_source="open-meteo/forecast"
)

_FORECAST_CITIES: tuple[tuple[str, float, float], ...] = (
    ("Bangkok", 13.75, 100.5),
    ("Chiang Mai", 18.79, 98.98),
    ("Phuket", 7.88, 98.39),
    ("Hat Yai", 7.01, 100.47),
    ("Udon Thani", 17.42, 102.79),
    ("Kuala Lumpur", 3.14, 101.69),
    ("Singapore", 1.35, 103.82),
    ("Jakarta", -6.21, 106.85),
    ("Yangon", 16.87, 96.20),
    ("Hanoi", 21.03, 105.85),
    ("Manila", 14.60, 120.98),
    ("Ho Chi Minh City", 10.82, 106.63),
)

_WMO_CODE_MAP: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

_SEVERE_CODES = {65, 67, 75, 82, 86, 95, 96, 99}


def _wmo_label(code: int | None) -> str:
    if code is None:
        return "Unknown"
    return _WMO_CODE_MAP.get(code, f"Code {code}")


def _is_severe(code: int | None, wind_max: float | None, precip: float | None) -> bool:
    if code is not None and code in _SEVERE_CODES:
        return True
    if wind_max is not None and wind_max >= 62:  # ~Beaufort 10+
        return True
    if precip is not None and precip >= 50:  # mm/day — very heavy
        return True
    return False


def _severity_level(
    code: int | None, wind_max: float | None, precip: float | None
) -> str:
    if code is not None and code in {82, 95, 96, 99}:
        return "high"
    if wind_max is not None and wind_max >= 89:  # ~Beaufort 12+
        return "high"
    if _is_severe(code, wind_max, precip):
        return "medium"
    return "low"


async def _fetch_city(
    client: httpx.AsyncClient, name: str, lat: float, lon: float
) -> dict | None:
    try:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                    "weathercode,windspeed_10m_max,windgusts_10m_max"
                ),
                "timezone": "Asia/Bangkok",
                "forecast_days": 7,
            },
        )
        r.raise_for_status()
        data = r.json().get("daily") or {}
    except Exception:
        return None

    dates = data.get("time") or []
    t_max = data.get("temperature_2m_max") or []
    t_min = data.get("temperature_2m_min") or []
    precip = data.get("precipitation_sum") or []
    codes = data.get("weathercode") or []
    wind_max = data.get("windspeed_10m_max") or []
    gusts_max = data.get("windgusts_10m_max") or []

    days: list[dict] = []
    severe_count = 0
    for i, d in enumerate(dates):
        wmo = codes[i] if i < len(codes) else None
        w = wind_max[i] if i < len(wind_max) else None
        p = precip[i] if i < len(precip) else None
        severe = _is_severe(wmo, w, p)
        if severe:
            severe_count += 1
        days.append(
            {
                "date": d,
                "temp_max": t_max[i] if i < len(t_max) else None,
                "temp_min": t_min[i] if i < len(t_min) else None,
                "precipitation_mm": p,
                "weathercode": wmo,
                "weather_label": _wmo_label(wmo),
                "wind_max_kmh": w,
                "wind_gusts_kmh": gusts_max[i] if i < len(gusts_max) else None,
                "severe": severe,
                "severity": _severity_level(wmo, w, p),
            }
        )

    return {
        "city": name,
        "lat": lat,
        "lon": lon,
        "days": days,
        "severe_days": severe_count,
    }


async def fetch_forecast() -> dict:
    """Pull 7-day forecast for configured cities."""
    cities: list[dict] = []
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, headers=_UA) as client:
        results = await asyncio.gather(
            *(
                _fetch_city(client, name, lat, lon)
                for name, lat, lon in _FORECAST_CITIES
            )
        )
    for row in results:
        if row:
            cities.append(row)

    severe_cities = [c for c in cities if c.get("severe_days", 0) > 0]
    out = {
        "count": len(cities),
        "severe_count": len(severe_cities),
        "cities": cities,
        "source": "open-meteo/forecast",
        "updated": utc_now_iso(),
    }
    if not cities:
        out["error"] = "no forecast data returned"
    return out


def _wrap_forecast_payload(
    raw: dict, *, stale: bool = False, error: str | None = None
) -> dict:
    return _CONNECTOR.build(
        FeedEnvelope(
            count=int(raw.get("count") or len(raw.get("cities") or [])),
            stale=stale,
            error=error or raw.get("error"),
        ),
        persist=bool(raw.get("cities")) and not stale and not error,
        cities=raw.get("cities") or [],
        severe_count=raw.get("severe_count") or 0,
    )


async def get_forecast(*, refresh: bool = False) -> dict:
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
            raw = await asyncio.wait_for(fetch_forecast(), timeout=_FETCH_TIMEOUT + 4)
        except asyncio.TimeoutError:
            if stale_hit:
                return _wrap_forecast_payload(
                    stale_hit,
                    stale=True,
                    error="upstream timeout — serving stale cache",
                )
            return _CONNECTOR.build(
                FeedEnvelope(count=0, error="upstream timeout"),
                persist=False,
                cities=[],
                severe_count=0,
            )

        if raw.get("cities"):
            return _wrap_forecast_payload(raw)
        if stale_hit:
            return _wrap_forecast_payload(stale_hit, stale=True)
        return _wrap_forecast_payload(raw)


def gather_forecast_weather_digest() -> dict:
    """Synchronous digest for briefing integration (reads memory cache)."""
    cached = _CONNECTOR.peek_memory()
    if not cached:
        return {"enabled": False, "count": 0, "lines": []}
    cities = cached.get("cities") or []
    lines: list[str] = []
    for city in cities:
        severe_days = city.get("severe_days", 0)
        if severe_days == 0:
            continue
        name = city.get("city", "Unknown")
        for day in city.get("days") or []:
            if day.get("severe"):
                lines.append(
                    f"{name} {day.get('date')}: {day.get('weather_label')}, "
                    f"max {day.get('temp_max')}°C, "
                    f"precip {day.get('precipitation_mm')}mm, "
                    f"wind {day.get('wind_max_kmh')} km/h"
                )
    if not lines:
        for city in cities[:3]:
            name = city.get("city", "Unknown")
            first_day = (city.get("days") or [{}])[0]
            if first_day:
                lines.append(
                    f"{name} {first_day.get('date')}: {first_day.get('weather_label')}, "
                    f"max {first_day.get('temp_max')}°C"
                )
    return {
        "enabled": True,
        "count": len(lines),
        "lines": lines[:10],
        "severe_count": cached.get("severe_count", 0),
    }


@router.get("/forecast")
async def weather_forecast(
    refresh: bool = Query(False, description="Force refresh bypassing cache"),
):
    """7-day weather forecast for Thailand + ASEAN cities (Open-Meteo, no key)."""
    return await get_forecast(refresh=refresh)
