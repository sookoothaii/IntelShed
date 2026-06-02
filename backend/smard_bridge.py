"""SMARD — Bundesnetzagentur Strommarktdaten Deutschland.
JSON API, no auth, 15min resolution for some series, daily for others.
"""
from datetime import datetime, timezone, timedelta

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["energy"])

_SMARD_BASE = "https://www.smard.de/app/chart_data"
_SMARD_FILTER = "https://www.smard.de/app/filter"

# Series IDs for Germany (region=DE)
# See: https://www.smard.de/page/en/wiki-article/4464
_SERIES = {
    "wind_onshore": 4066,
    "wind_offshore": 122,
    "solar": 5096,
    "biomass": 4067,
    "hydro": 4068,
    "brown_coal": 4069,
    "hard_coal": 4070,
    "natural_gas": 4071,
    "pumped_storage": 4072,
    "other_conventional": 4073,
    "total_load": 410,
    "day_ahead_price": 6139,
}

# CO2 factors (g/kWh) — rough averages for DE
_CO2_FACTORS = {
    "brown_coal": 820,
    "hard_coal": 720,
    "natural_gas": 350,
    "biomass": 0,  # considered neutral in most accounting
    "hydro": 0,
    "pumped_storage": 0,
    "wind_onshore": 0,
    "wind_offshore": 0,
    "solar": 0,
    "other_conventional": 500,
}

_smard_cache: dict = {}
_SMARD_TTL = 900  # 15 minutes


async def _fetch_smard_series(series_id: int, region: str = "DE"):
    """Fetch one SMARD series. Returns list of {timestamp, value} or None."""
    # Determine resolution from series_id
    resolution = "hour" if series_id == 6139 else "quarterhour"
    url = f"{_SMARD_BASE}/{series_id}/{region}/{resolution}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return None

    # data["series"] is list of [timestamp_ms, value]
    raw = data.get("series", [])
    out = []
    for item in raw:
        if isinstance(item, list) and len(item) == 2:
            ts, val = item
            # value can be null
            if val is not None:
                out.append({"timestamp": ts, "value": float(val)})
    return out


@router.get("/energy/de")
async def get_german_energy():
    """German electricity generation mix + load + day-ahead price.
    Cached 15 minutes. No key.
    """
    now = datetime.now(timezone.utc).timestamp()
    cached = _smard_cache.get("de_energy")
    if cached and (now - cached["ts"]) < _SMARD_TTL:
        return cached["data"]

    # Fetch latest data for all generation sources
    generation = {}
    total_gen_mw = 0
    for key, sid in _SERIES.items():
        if key in ("total_load", "day_ahead_price"):
            continue
        series = await _fetch_smard_series(sid)
        if series:
            latest = series[-1]
            generation[key] = {
                "latest_mw": latest["value"],
                "timestamp": latest["timestamp"],
                "history": series[-12:],  # last 12 points
            }
            total_gen_mw += latest["value"]

    # Fetch load and price
    load_series = await _fetch_smard_series(_SERIES["total_load"])
    price_series = await _fetch_smard_series(_SERIES["day_ahead_price"])

    # Calculate CO2 intensity
    co2_total_g = 0
    for key, info in generation.items():
        factor = _CO2_FACTORS.get(key, 500)
        co2_total_g += info["latest_mw"] * factor

    co2_per_kwh = round(co2_total_g / (total_gen_mw or 1) / 1000, 2) if total_gen_mw else None

    result = {
        "region": "DE",
        "updated": datetime.now(timezone.utc).isoformat(),
        "total_generation_mw": round(total_gen_mw, 2),
        "co2_g_per_kwh": co2_per_kwh,
        "generation": generation,
        "load": {
            "latest_mw": load_series[-1]["value"] if load_series else None,
            "history": load_series[-12:] if load_series else [],
        },
        "day_ahead_price": {
            "latest_eur_mwh": price_series[-1]["value"] if price_series else None,
            "history": price_series[-24:] if price_series else [],
        },
    }

    _smard_cache["de_energy"] = {"ts": now, "data": result}
    return result
