"""SMARD — Bundesnetzagentur Strommarktdaten Deutschland.
JSON API, no auth, 15min resolution for some series, daily for others.
"""

import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

import feed_registry

router = APIRouter(prefix="/api", tags=["energy"])

_SMARD_BASE = "https://www.smard.de/app/chart_data"
_SMARD_FILTER = "https://www.smard.de/app/filter"

# Series IDs for Germany (region=DE)
# See: https://www.smard.de/page/en/wiki-article/4464
# SMARD filter IDs (bundesAPI/smard-api, 2024+)
_SERIES = {
    "wind_onshore": 4067,
    "wind_offshore": 1226,
    "solar": 4068,
    "biomass": 4066,
    "hydro": 1227,
    "brown_coal": 4072,
    "hard_coal": 4069,
    "natural_gas": 4071,
    "pumped_storage": 4070,
    "other_conventional": 4073,
    "total_load": 410,
    "day_ahead_price": 4169,
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
    """Fetch one SMARD series via index + timestamp URL (official SMARD web API)."""
    resolution = "hour" if series_id in (4169, 410) else "quarterhour"
    index_url = f"{_SMARD_BASE}/{series_id}/{region}/index_{resolution}.json"
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(index_url)
            r.raise_for_status()
            timestamps = r.json().get("timestamps") or []
            if not timestamps:
                return None
            # Latest bucket may be incomplete (null tail) — try last 3 indices
            for ts in reversed(timestamps[-3:]):
                data_url = (
                    f"{_SMARD_BASE}/{series_id}/{region}/"
                    f"{series_id}_{region}_{resolution}_{ts}.json"
                )
                r2 = await client.get(data_url)
                if r2.status_code != 200:
                    continue
                raw = r2.json().get("series", [])
                out = []
                for item in raw:
                    if (
                        isinstance(item, list)
                        and len(item) == 2
                        and item[1] is not None
                    ):
                        out.append({"timestamp": item[0], "value": float(item[1])})
                if out:
                    return out
    except Exception:
        return None
    return None


@router.get("/energy/de")
async def get_german_energy():
    """German electricity generation mix + load + day-ahead price.
    Cached 15 minutes. No key.
    """
    now = datetime.now(timezone.utc).timestamp()
    cached = _smard_cache.get("de_energy")
    if cached and (now - cached["ts"]) < _SMARD_TTL:
        return cached["data"]

    gen_keys = [k for k in _SERIES if k not in ("total_load", "day_ahead_price")]
    fetched = await asyncio.gather(
        *[_fetch_smard_series(_SERIES[k]) for k in gen_keys],
        _fetch_smard_series(_SERIES["total_load"]),
        _fetch_smard_series(_SERIES["day_ahead_price"]),
    )
    gen_series = fetched[: len(gen_keys)]
    load_series = fetched[len(gen_keys)]
    price_series = fetched[len(gen_keys) + 1]

    generation = {}
    total_gen_mw = 0
    for key, series in zip(gen_keys, gen_series):
        if series:
            latest = series[-1]
            generation[key] = {
                "latest_mw": latest["value"],
                "timestamp": latest["timestamp"],
                "history": series[-12:],
            }
            total_gen_mw += latest["value"]

    # Calculate CO2 intensity
    co2_total_g = 0
    for key, info in generation.items():
        factor = _CO2_FACTORS.get(key, 500)
        co2_total_g += info["latest_mw"] * factor

    co2_per_kwh = (
        round(co2_total_g / (total_gen_mw or 1) / 1000, 2) if total_gen_mw else None
    )

    series_ok = (
        sum(1 for s in gen_series if s)
        + (1 if load_series else 0)
        + (1 if price_series else 0)
    )
    error = None
    if series_ok == 0:
        error = "SMARD upstream returned no series"

    result = {
        "region": "DE",
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "smard.de",
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
        "active_series": series_ok,
        "error": error,
        "stale": False,
    }

    if series_ok == 0:
        stale = feed_registry.read("energy_de")
        if stale:
            stale = dict(stale)
            stale["stale"] = True
            stale["error"] = error
            _smard_cache["de_energy"] = {"ts": now, "data": stale}
            return stale

    _smard_cache["de_energy"] = {"ts": now, "data": result}
    feed_registry.write_auto("energy_de", result)
    return result


# Representative sites for globe visualization (not exact plant locations — regional proxies)
_GLOBE_SITES = [
    {
        "key": "wind_onshore",
        "label": "Wind Onshore",
        "lon": 9.2,
        "lat": 54.2,
        "color": "#7ee787",
    },
    {
        "key": "wind_offshore",
        "label": "Wind Offshore",
        "lon": 7.8,
        "lat": 54.8,
        "color": "#56d364",
    },
    {"key": "solar", "label": "Solar", "lon": 11.8, "lat": 49.1, "color": "#ffd23f"},
    {
        "key": "biomass",
        "label": "Biomass",
        "lon": 12.1,
        "lat": 53.5,
        "color": "#8bc34a",
    },
    {"key": "hydro", "label": "Hydro", "lon": 11.0, "lat": 47.7, "color": "#4fc3f7"},
    {
        "key": "brown_coal",
        "label": "Brown Coal",
        "lon": 14.3,
        "lat": 51.5,
        "color": "#8b6914",
    },
    {
        "key": "hard_coal",
        "label": "Hard Coal",
        "lon": 7.0,
        "lat": 51.4,
        "color": "#6f8c84",
    },
    {
        "key": "natural_gas",
        "label": "Natural Gas",
        "lon": 9.9,
        "lat": 53.5,
        "color": "#ff9f43",
    },
    {
        "key": "pumped_storage",
        "label": "Pumped Storage",
        "lon": 8.9,
        "lat": 47.6,
        "color": "#a78bfa",
    },
    {
        "key": "other_conventional",
        "label": "Other",
        "lon": 10.0,
        "lat": 51.0,
        "color": "#b0c4b1",
    },
]


@router.get("/energy/de/globe")
async def get_german_energy_globe():
    """SMARD generation mix as pulsing points over Germany for Cesium."""
    data = await get_german_energy()
    gen = data.get("generation") or {}
    price = (data.get("day_ahead_price") or {}).get("latest_eur_mwh")
    load_mw = (data.get("load") or {}).get("latest_mw")
    points = []
    max_mw = 1.0
    for site in _GLOBE_SITES:
        info = gen.get(site["key"]) or {}
        mw = info.get("latest_mw") or 0
        max_mw = max(max_mw, mw)

    for site in _GLOBE_SITES:
        info = gen.get(site["key"]) or {}
        mw = float(info.get("latest_mw") or 0)
        if mw <= 0:
            continue
        # pixel radius 8–28 scaled by share of max
        scale = mw / max_mw
        points.append(
            {
                "id": site["key"],
                "label": site["label"],
                "lon": site["lon"],
                "lat": site["lat"],
                "mw": round(mw, 1),
                "color": site["color"],
                "radius": round(8 + scale * 20, 1),
                "co2_factor": _CO2_FACTORS.get(site["key"], 500),
                "timestamp": info.get("timestamp"),
            }
        )

    return {
        "region": "DE",
        "updated": data.get("updated"),
        "source": "smard.de",
        "proxy_note": "Globe markers are regional proxies, not plant GPS",
        "total_generation_mw": data.get("total_generation_mw"),
        "co2_g_per_kwh": data.get("co2_g_per_kwh"),
        "load_mw": load_mw,
        "day_ahead_price_eur_mwh": price,
        "negative_price": price is not None and price < 0,
        "points": points,
        "count": len(points),
        "active_sources": len(
            [s for s in _GLOBE_SITES if (gen.get(s["key"]) or {}).get("latest_mw")]
        ),
        "stale": data.get("stale"),
        "error": data.get("error"),
    }
