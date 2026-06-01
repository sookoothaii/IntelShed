"""WorldBase — additional no-key data feeds.

Every feed is fail-soft: on any upstream error it serves the last good value
(stale cache) or an empty payload, so the globe never breaks. No API keys
required for any source here.
"""

import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["feeds-extra"])

# Module-local TTL cache (independent of main.py)
_CACHE: dict = {}


def _get(key: str, ttl: float):
    item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    return None


def _set(key: str, value):
    _CACHE[key] = (time.time(), value)


def _stale(key: str):
    item = _CACHE.get(key)
    return item[1] if item else None


_UA = {"User-Agent": "WorldBase/1.0 (spatial intelligence dashboard)"}


# ---------------------------------------------------------------------------
# Space weather — NOAA SWPC (radio propagation, GPS, aurora; off-grid relevant)
# ---------------------------------------------------------------------------
@router.get("/spaceweather")
async def space_weather():
    """Planetary K-index + solar wind summary (cached 5 min). No key."""
    key = "spaceweather"
    cached = _get(key, ttl=300.0)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
            kp = await client.get(
                "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
            )
            kp.raise_for_status()
            rows = kp.json()  # list of {"time_tag":..,"Kp":..,"a_running":..,...}

        def _row(r):
            """Normalize a row (dict or list+header) to (time_tag, kp)."""
            if isinstance(r, dict):
                return r.get("time_tag"), r.get("Kp")
            if isinstance(r, list) and len(r) >= 2:
                return r[0], r[1]
            return None, None

        # drop a possible header row (list-of-lists variant)
        data_rows = [r for r in rows if not (isinstance(r, list) and r and r[1] == "Kp")]
        latest = data_rows[-1] if data_rows else None
        _, kp_raw = _row(latest) if latest else (None, None)
        try:
            kp_val = float(kp_raw) if kp_raw not in (None, "null") else None
        except (TypeError, ValueError):
            kp_val = None
        # storm scale interpretation
        scale = "quiet"
        if kp_val is not None:
            if kp_val >= 8:
                scale = "severe storm (G4-G5)"
            elif kp_val >= 7:
                scale = "strong storm (G3)"
            elif kp_val >= 5:
                scale = "minor-moderate storm (G1-G2)"
            elif kp_val >= 4:
                scale = "active"
        history = []
        for r in data_rows[-24:]:
            t, k = _row(r)
            try:
                history.append({"time": t, "kp": float(k)})
            except (TypeError, ValueError):
                continue
        out = {
            "kp_index": kp_val,
            "scale": scale,
            "time": _row(latest)[0] if latest else None,
            "aurora_visible_midlat": (kp_val or 0) >= 6,
            "hf_radio_impact": (kp_val or 0) >= 5,
            "history": history,
        }
        _set(key, out)
        return out
    except Exception as e:
        stale = _stale(key)
        if stale:
            return stale
        return {"kp_index": None, "scale": "unknown", "error": str(e)}


# ---------------------------------------------------------------------------
# Markets — crypto (CoinGecko) + forex (ECB via Frankfurter). No key.
# ---------------------------------------------------------------------------
@router.get("/markets")
async def markets():
    """Crypto prices + major forex rates + key macro (cached 60s). No key."""
    key = "markets"
    cached = _get(key, ttl=60.0)
    if cached is not None:
        return cached
    out = {"crypto": {}, "forex": {}, "updated": datetime.now(timezone.utc).isoformat()}
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
            try:
                cg = await client.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={
                        "ids": "bitcoin,ethereum,monero,solana",
                        "vs_currencies": "usd,eur",
                        "include_24hr_change": "true",
                    },
                )
                if cg.status_code == 200:
                    out["crypto"] = cg.json()
            except Exception:
                pass
            try:
                fx = await client.get(
                    "https://api.frankfurter.app/latest",
                    params={"from": "USD", "to": "EUR,GBP,CHF,JPY,CNY,RUB"},
                )
                if fx.status_code == 200:
                    out["forex"] = fx.json()
            except Exception:
                pass
        _set(key, out)
        return out
    except Exception as e:
        stale = _stale(key)
        if stale:
            return stale
        out["error"] = str(e)
        return out


# ---------------------------------------------------------------------------
# Military / interesting aircraft — adsb.fi open data (no key, no rate wall).
# ---------------------------------------------------------------------------
@router.get("/military")
async def military_aircraft():
    """Military + interesting aircraft worldwide via adsb.fi (cached 20s). No key."""
    key = "military"
    cached = _get(key, ttl=20.0)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get("https://opendata.adsb.fi/api/v2/mil")
            r.raise_for_status()
            data = r.json()
        ac = data.get("ac", []) or []
        out = {
            "count": len(ac),
            "aircraft": [
                {
                    "hex": a.get("hex"),
                    "flight": (a.get("flight") or "").strip(),
                    "type": a.get("t"),
                    "lat": a.get("lat"),
                    "lon": a.get("lon"),
                    "alt": a.get("alt_baro"),
                    "speed": a.get("gs"),
                    "track": a.get("track"),
                    "squawk": a.get("squawk"),
                }
                for a in ac
                if a.get("lat") is not None and a.get("lon") is not None
            ],
        }
        _set(key, out)
        return out
    except Exception as e:
        stale = _stale(key)
        if stale:
            return stale
        return {"count": 0, "aircraft": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Point weather — Open-Meteo (no key). Great for click-to-locate + node site.
# ---------------------------------------------------------------------------
@router.get("/weather")
async def point_weather(lat: float, lon: float):
    """Current weather + 24h outlook for any coordinate (cached 10 min). No key."""
    key = f"weather:{round(lat, 2)}:{round(lon, 2)}"
    cached = _get(key, ttl=600.0)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
            r = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                    "wind_direction_10m,weather_code,pressure_msl",
                    "hourly": "temperature_2m,precipitation_probability",
                    "forecast_days": 1,
                    "timezone": "auto",
                },
            )
            r.raise_for_status()
            data = r.json()
        out = {
            "lat": lat,
            "lon": lon,
            "current": data.get("current", {}),
            "units": data.get("current_units", {}),
            "timezone": data.get("timezone"),
        }
        _set(key, out)
        return out
    except Exception as e:
        stale = _stale(key)
        if stale:
            return stale
        return {"lat": lat, "lon": lon, "current": {}, "error": str(e)}


# ---------------------------------------------------------------------------
# Geopolitics — ReliefWeb (UN OCHA) active disasters worldwide. No key.
# ---------------------------------------------------------------------------
@router.get("/geopolitics")
async def geopolitics(limit: int = 40):
    """Current humanitarian disasters/crises worldwide (cached 30 min). No key."""
    key = "geopolitics"
    cached = _get(key, ttl=1800.0)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get(
                "https://api.reliefweb.int/v1/disasters",
                params={
                    "appname": "worldbase",
                    "profile": "list",
                    "preset": "latest",
                    "limit": min(limit, 100),
                },
            )
            r.raise_for_status()
            data = r.json()
        items = []
        for d in data.get("data", []):
            f = d.get("fields", {})
            items.append({
                "id": d.get("id"),
                "name": f.get("name"),
                "status": f.get("status"),
                "url": f.get("url"),
            })
        out = {"count": len(items), "disasters": items}
        _set(key, out)
        return out
    except Exception as e:
        stale = _stale(key)
        if stale:
            return stale
        return {"count": 0, "disasters": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Aircraft anomaly detection — flags unusual patterns in real-time ADS-B data
# ---------------------------------------------------------------------------
@router.get("/anomalies")
async def aircraft_anomalies():
    """Scan current ADS-B traffic for unusual patterns. No key."""
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get("https://opensky-network.org/api/states/all")
            r.raise_for_status()
            data = r.json()
    except Exception:
        return {"analyzed": 0, "anomalies": [], "error": "OpenSky unavailable"}

    states = data.get("states") or []
    anomalies = []
    MILITARY_PREFIXES = ("ae", "ad", "af", "a1", "a2", "a3", "a4", "a5")

    for s in states:
        if not s or len(s) < 17:
            continue
        icao = (s[0] or "").lower()
        callsign = (s[1] or "").strip()
        lon = s[5]
        lat = s[6]
        alt = s[7]       # barometric altitude (m)
        geo_alt = s[13]  # geometric altitude (m)
        vel = s[9]       # velocity (m/s)
        vert = s[11]     # vertical rate (m/s)
        squawk = s[14]   # squawk code

        if lon is None or lat is None:
            continue

        reasons = []

        # 1. Military hex prefix
        if any(icao.startswith(p) for p in MILITARY_PREFIXES):
            reasons.append("military_hex")

        # 2. No callsign (anon / dark)
        if not callsign:
            reasons.append("no_callsign")

        # 3. Emergency squawk
        if squawk in ("7500", "7600", "7700"):
            reasons.append(f"emergency_squawk_{squawk}")

        # 4. Very low altitude (possible surveillance / ground hover)
        if alt is not None and alt < 300 and alt > -50:
            reasons.append("very_low_altitude")

        # 5. Rapid descent (> 10 m/s)
        if vert is not None and vert < -10:
            reasons.append("rapid_descent")

        # 6. Unusually high speed for altitude (possible intercept)
        if vel is not None and vel > 150 and alt is not None and alt < 2000:
            reasons.append("high_speed_low_alt")

        if reasons:
            anomalies.append({
                "icao24": icao,
                "callsign": callsign or None,
                "lat": lat,
                "lon": lon,
                "alt_m": alt,
                "vel_ms": vel,
                "squawk": squawk,
                "reasons": reasons,
            })

    return {"analyzed": len(states), "anomalies": anomalies, "count": len(anomalies)}
