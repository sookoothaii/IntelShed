"""WorldBase — additional no-key data feeds.

Every feed is fail-soft: on any upstream error it serves the last good value
(stale cache) or an empty payload, so the globe never breaks. No API keys
required for any source here.
"""

import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["feeds-extra"])

# Module-local TTL cache (independent of main.py)
_CACHE: dict = {}
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _get(key: str, ttl: float):
    # 1. Check in-memory cache first
    item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    # 2. Fall back to SQLite cache
    try:
        import sqlite3
        conn = sqlite3.connect(_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value, cached_at FROM feed_cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            cached_at = datetime.fromisoformat(row[1])
            age = (datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age < ttl:
                import json
                val = json.loads(row[0])
                _CACHE[key] = (time.time(), val)  # warm memory cache
                return val
    except Exception:
        pass
    return None


def _set(key: str, value):
    _CACHE[key] = (time.time(), value)
    # Persist to SQLite
    try:
        import sqlite3, json
        conn = sqlite3.connect(_DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _stale(key: str):
    item = _CACHE.get(key)
    if item:
        return item[1]
    # Fall back to SQLite
    try:
        import sqlite3, json
        conn = sqlite3.connect(_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT value FROM feed_cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


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


# ---------------------------------------------------------------------------
# Cross-feed correlation — detects developing situations from multiple sources
# ---------------------------------------------------------------------------
import math

NUCLEAR_SITES = [
    # Format: (name, lon, lat, radius_km)
    ("Fukushima", 140.9, 37.3, 50),
    ("Chernobyl", 30.1, 51.4, 80),
    ("Zaporizhzhia", 34.6, 47.5, 60),
    ("Hanford", -119.6, 46.5, 40),
    ("Sellafield", -3.5, 54.4, 30),
]


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.get("/correlations")
async def cross_feed_correlations():
    """Scan feeds for spatial-temporal correlations. No key."""
    situations = []

    # 1. Earthquake near nuclear site
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson")
            quakes = r.json().get("features", [])
    except Exception:
        quakes = []

    for q in quakes:
        props = q.get("properties", {})
        geo = q.get("geometry", {})
        coords = geo.get("coordinates", [0, 0])
        lon, lat = coords[0], coords[1]
        mag = props.get("mag", 0)
        for site_name, site_lon, site_lat, radius in NUCLEAR_SITES:
            dist = _haversine(lon, lat, site_lon, site_lat)
            if dist < radius and mag >= 3.0:
                situations.append({
                    "severity": "high" if mag >= 5 else "medium",
                    "type": "quake_near_nuclear",
                    "title": f"M{mag:.1f} earthquake {dist:.0f} km from {site_name}",
                    "location": {"lon": lon, "lat": lat, "place": props.get("place", "")},
                    "details": {"distance_km": round(dist, 1), "site": site_name, "magnitude": mag},
                })

    # 2. Military aircraft surge near disaster zone ( ReliefWeb )
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get("https://api.reliefweb.int/v1/disasters?appname=worldbase&profile=list&preset=latest&limit=20")
            disasters = r.json().get("data", [])
    except Exception:
        disasters = []

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get("https://opensky-network.org/api/states/all")
            states = r.json().get("states", [])
    except Exception:
        states = []

    MIL_HEX = tuple("ae ad af a1 a2 a3 a4 a5".split())
    for d in disasters:
        fields = d.get("fields", {})
        dis_name = fields.get("name", "")
        # Rough: place at 0,0 if no coords; in production geocode country name
        dlon, dlat = 0, 0
        mil_count = 0
        for s in states:
            if not s or len(s) < 17:
                continue
            icao = (s[0] or "").lower()
            if not any(icao.startswith(p) for p in MIL_HEX):
                continue
            alon, alat = s[5], s[6]
            if alon is None or alat is None:
                continue
            dist = _haversine(alon, alat, dlon, dlat)
            if dist < 500:
                mil_count += 1
        if mil_count >= 3:
            situations.append({
                "severity": "medium",
                "type": "military_presence_disaster_zone",
                "title": f"{mil_count} military aircraft near {dis_name}",
                "location": {"lon": dlon, "lat": dlat, "place": dis_name},
                "details": {"military_count": mil_count, "disaster": dis_name},
            })

    # 3. High seismic activity cluster (>3 quakes M4+ within 2h in same region)
    recent = [q for q in quakes if q.get("properties", {}).get("mag", 0) >= 4.0]
    if len(recent) >= 3:
        # Check if clustered within 500km
        for i, q1 in enumerate(recent[:5]):
            c1 = q1.get("geometry", {}).get("coordinates", [0, 0])
            cluster = [q1]
            for q2 in recent[i + 1:]:
                c2 = q2.get("geometry", {}).get("coordinates", [0, 0])
                if _haversine(c1[0], c1[1], c2[0], c2[1]) < 500:
                    cluster.append(q2)
            if len(cluster) >= 3:
                avg_lon = sum(c.get("geometry", {}).get("coordinates", [0, 0])[0] for c in cluster) / len(cluster)
                avg_lat = sum(c.get("geometry", {}).get("coordinates", [0, 0])[1] for c in cluster) / len(cluster)
                situations.append({
                    "severity": "high",
                    "type": "seismic_cluster",
                    "title": f"{len(cluster)} M4+ earthquakes in cluster",
                    "location": {"lon": avg_lon, "lat": avg_lat, "place": "cluster region"},
                    "details": {"quake_count": len(cluster), "max_mag": max(c.get("properties", {}).get("mag", 0) for c in cluster)},
                })
                break

    situations.sort(key=lambda s: 0 if s["severity"] == "high" else 1)
    return {"situations": situations, "count": len(situations)}
