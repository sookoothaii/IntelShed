"""WorldBase — additional no-key data feeds.

Every feed is fail-soft: on any upstream error it serves the last good value
(stale cache) or an empty payload, so the globe never breaks. No API keys
required for any source here.
"""

import asyncio
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

import opensky_client
import aircraft_provider
import adsb_client
import geo_centroids

router = APIRouter(prefix="/api", tags=["feeds-extra"])

# Module-local TTL cache (independent of main.py)
_CACHE: dict = {}
_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _db_get(key: str, ttl: float):
    try:
        conn = _db_connect()
        c = conn.cursor()
        c.execute("SELECT value, cached_at FROM feed_cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            cached_at = datetime.fromisoformat(row[1])
            age = (datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)).total_seconds()
            if age < ttl:
                return json.loads(row[0])
    except Exception:
        pass
    return None


def _db_set(key: str, value):
    try:
        conn = _db_connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _db_stale(key: str):
    try:
        conn = _db_connect()
        c = conn.cursor()
        c.execute("SELECT value FROM feed_cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


async def _get(key: str, ttl: float):
    item = _CACHE.get(key)
    if item and (time.time() - item[0]) < ttl:
        return item[1]
    val = await asyncio.to_thread(_db_get, key, ttl)
    if val is not None:
        _CACHE[key] = (time.time(), val)
    return val


async def _set(key: str, value):
    _CACHE[key] = (time.time(), value)
    await asyncio.to_thread(_db_set, key, value)


async def _stale(key: str):
    item = _CACHE.get(key)
    if item:
        return item[1]
    return await asyncio.to_thread(_db_stale, key)


_UA = {"User-Agent": "WorldBase/1.0 (spatial intelligence dashboard)"}


# ---------------------------------------------------------------------------
# Space weather — NOAA SWPC (radio propagation, GPS, aurora; off-grid relevant)
# ---------------------------------------------------------------------------
@router.get("/spaceweather")
async def space_weather():
    """Planetary K-index + solar wind summary (cached 5 min). No key."""
    key = "spaceweather"
    cached = await _get(key, ttl=300.0)
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
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
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
    cached = await _get(key, ttl=60.0)
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
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
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
    cached = await _get(key, ttl=20.0)
    if cached is not None:
        return cached
    ac: list[dict] = []
    source = "adsb.fi"
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get("https://opendata.adsb.fi/api/v2/mil")
            r.raise_for_status()
            ac = r.json().get("ac", []) or []
    except Exception:
        try:
            ac = await adsb_client.fetch_mil_states()
            source = "adsb.lol"
        except Exception as e:
            stale = await _stale(key)
            if stale:
                return stale
            return {"count": 0, "aircraft": [], "error": str(e)}

    out = {
        "count": len(ac),
        "source": source,
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
    await _set(key, out)
    return out


# ---------------------------------------------------------------------------
# Point weather — Open-Meteo (no key). Great for click-to-locate + node site.
# ---------------------------------------------------------------------------
@router.get("/weather")
async def point_weather(lat: float, lon: float):
    """Current weather + 24h outlook for any coordinate (cached 10 min). No key."""
    key = f"weather:{round(lat, 2)}:{round(lon, 2)}"
    cached = await _get(key, ttl=600.0)
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
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        return {"lat": lat, "lon": lon, "current": {}, "error": str(e)}


# ---------------------------------------------------------------------------
# Geopolitics — ReliefWeb (UN OCHA) active disasters worldwide. No key.
# ---------------------------------------------------------------------------
@router.get("/geopolitics")
async def geopolitics(limit: int = 40):
    """Humanitarian crises on the globe — GDACS (coords) + ReliefWeb v2 when appname approved."""
    key = "geopolitics"
    cached = await _get(key, ttl=1800.0)
    if cached is not None:
        return cached

    items: list[dict] = []
    seen: set[str] = set()

    # GDACS — always free, often has Lat/Lon in description
    try:
        gd = await gdacs_alerts()
        for i, a in enumerate((gd.get("alerts") or [])[:25]):
            title = a.get("title") or "GDACS alert"
            lat, lon = a.get("lat"), a.get("lon")
            if lat is None or lon is None:
                lat, lon = geo_centroids.resolve_lat_lon(name=title)
            if lat is None:
                continue
            sid = f"gdacs:{i}"
            if sid in seen:
                continue
            seen.add(sid)
            items.append({
                "id": sid,
                "name": title[:120],
                "status": "gdacs",
                "url": a.get("link"),
                "lat": lat,
                "lon": lon,
                "source": "gdacs",
            })
    except Exception:
        pass

    # ReliefWeb v2 — needs approved RELIEFWEB_APPNAME in .env
    rw_app = os.environ.get("RELIEFWEB_APPNAME", "").strip()
    if rw_app:
        try:
            async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
                r = await client.get(
                    "https://api.reliefweb.int/v2/disasters",
                    params={
                        "appname": rw_app,
                        "limit": min(limit, 50),
                        "profile": "list",
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    for d in data.get("data", []):
                        fields = d.get("fields", {})
                        name = fields.get("name") or "Disaster"
                        did = str(d.get("id", name))
                        if did in seen:
                            continue
                        countries = fields.get("country") or []
                        iso3 = None
                        if countries and isinstance(countries[0], dict):
                            iso3 = countries[0].get("iso3")
                        lat, lon = geo_centroids.resolve_lat_lon(
                            name=name, iso3=iso3, countries=countries
                        )
                        if lat is None:
                            continue
                        seen.add(did)
                        items.append({
                            "id": did,
                            "name": name,
                            "status": fields.get("status") or "reliefweb",
                            "url": fields.get("url"),
                            "lat": lat,
                            "lon": lon,
                            "source": "reliefweb",
                        })
        except Exception:
            pass

    out = {
        "count": len(items),
        "disasters": items[:limit],
        "sources": list({x["source"] for x in items}),
        "hint": (
            "GDACS is always on. For ReliefWeb, set RELIEFWEB_APPNAME in backend/.env "
            "(request at https://apidoc.reliefweb.int/parameters#appname)."
            if not rw_app
            else None
        ),
    }
    await _set(key, out)
    return out


# ---------------------------------------------------------------------------
# Aircraft anomaly detection — flags unusual patterns in real-time ADS-B data
# ---------------------------------------------------------------------------
@router.get("/anomalies")
async def aircraft_anomalies():
    """Scan ADS-B for unusual patterns (OpenSky or adsb.lol)."""
    data = aircraft_provider.last_known_states()
    if not data or not data.get("states"):
        try:
            data, _src = await aircraft_provider.fetch_live_states(timeout=10.0)
        except Exception as e:
            return {
                "analyzed": 0,
                "anomalies": [],
                "error": f"Aircraft feed unavailable ({e.__class__.__name__}).",
            }

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


_CORR_CACHE: dict = {"ts": 0.0, "data": None}
_CORR_TTL = 120.0


@router.get("/correlations")
async def cross_feed_correlations():
    """Scan feeds for spatial-temporal correlations. No key."""
    now = time.time()
    if _CORR_CACHE["data"] and (now - _CORR_CACHE["ts"]) < _CORR_TTL:
        return _CORR_CACHE["data"]

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

    os_data = aircraft_provider.last_known_states()
    if not os_data or not os_data.get("states"):
        try:
            os_data, _ = await aircraft_provider.fetch_live_states(timeout=10.0)
        except Exception:
            os_data = None
    states = (os_data or {}).get("states", [])

    MIL_HEX = tuple("ae ad af a1 a2 a3 a4 a5".split())
    for d in disasters:
        fields = d.get("fields", {})
        dis_name = fields.get("name", "")
        countries = fields.get("country") or []
        country_name = ""
        if countries:
            c0 = countries[0]
            country_name = c0.get("name", "") if isinstance(c0, dict) else str(c0)
        dlat, dlon = geo_centroids.resolve_lat_lon(name=country_name or dis_name)
        if dlat is None:
            continue
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

    # 4. Elevated river gauge + heavy precipitation (Open-Meteo, no key)
    try:
        import pegel_bridge
        peg = await pegel_bridge.get_pegel()
        async with httpx.AsyncClient(timeout=12.0, headers=_UA) as client:
            for g in peg.get("gauges") or []:
                if g.get("severity") not in ("high", "critical"):
                    continue
                lat, lon = g.get("lat"), g.get("lon")
                if lat is None or lon is None:
                    continue
                rain_mm = None
                try:
                    wr = await client.get(
                        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                        "&current=precipitation,rain&timezone=UTC"
                    )
                    cur = wr.json().get("current") or {}
                    rain_mm = cur.get("precipitation") if cur.get("precipitation") is not None else cur.get("rain")
                except Exception:
                    pass
                if rain_mm is not None and float(rain_mm) >= 2.0:
                    situations.append({
                        "severity": "high" if g["severity"] == "critical" else "medium",
                        "type": "pegel_rain_correlation",
                        "title": f"High water + rain at {g['name']} ({rain_mm} mm/h)",
                        "location": {"lon": lon, "lat": lat, "place": g.get("water", "")},
                        "details": {
                            "gauge": g["name"],
                            "water": g.get("water"),
                            "level": g.get("value"),
                            "unit": g.get("unit"),
                            "precipitation_mm": rain_mm,
                        },
                    })
    except Exception:
        pass

    situations.sort(key=lambda s: 0 if s["severity"] == "high" else 1)
    out = {"situations": situations, "count": len(situations)}
    _CORR_CACHE["data"] = out
    _CORR_CACHE["ts"] = now
    return out


# ---------------------------------------------------------------------------
# Air quality — Open-Meteo (no key)
# ---------------------------------------------------------------------------
@router.get("/airquality")
async def air_quality():
    """Global air quality PM2.5 + PM10 from Open-Meteo. Cached 1h. No key."""
    key = "airquality"
    cached = await _get(key, ttl=3600.0)
    if cached is not None:
        return cached
    try:
        # Use a few representative cities for global snapshot
        cities = [
            ("Bangkok", 13.75, 100.5), ("Delhi", 28.6, 77.2), ("Beijing", 39.9, 116.4),
            ("London", 51.5, -0.1), ("New York", 40.7, -74.0), ("Sao Paulo", -23.5, -46.6),
        ]
        results = []
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            for name, lat, lon in cities:
                try:
                    r = await client.get(
                        f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=pm10,pm2_5"
                    )
                    d = r.json()
                    cur = d.get("current", {})
                    results.append({
                        "city": name,
                        "lat": lat,
                        "lon": lon,
                        "pm25": cur.get("pm2_5"),
                        "pm10": cur.get("pm10"),
                        "time": cur.get("time"),
                    })
                except Exception:
                    continue
        out = {"cities": results, "updated": datetime.now(timezone.utc).isoformat()}
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        return {"cities": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Tsunami / Cyclone / Flood — GDACS JSON API (no key)
# ---------------------------------------------------------------------------
def _gdacs_active(props: dict) -> bool:
    if str(props.get("iscurrent", "")).lower() == "true":
        level = (props.get("alertlevel") or "").lower()
        return level in ("red", "orange")
    return (props.get("alertlevel") or "").lower() in ("red", "orange")


@router.get("/gdacs")
async def gdacs_alerts():
    """GDACS humanitarian alerts via JSON API (coords included). Cached 15m. No key."""
    key = "gdacs_v3"
    cached = await _get(key, ttl=900.0)
    if cached is not None:
        cached.setdefault("source", "gdacs.org")
        if "count_mapped" not in cached and cached.get("alerts"):
            cached["count_mapped"] = sum(1 for i in cached["alerts"] if i.get("lat") is not None)
        return cached
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get("https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH")
            r.raise_for_status()
            data = r.json()
        items = []
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            if not _gdacs_active(props):
                continue
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or []
            lat = lon = None
            if len(coords) >= 2:
                lon, lat = float(coords[0]), float(coords[1])
            url_obj = props.get("url") or {}
            items.append({
                "title": props.get("name") or props.get("eventname") or "GDACS alert",
                "link": url_obj.get("report") or "",
                "description": props.get("htmldescription") or props.get("description") or "",
                "published": props.get("datemodified") or "",
                "lat": lat,
                "lon": lon,
                "alertlevel": props.get("alertlevel"),
                "eventtype": props.get("eventtype"),
            })
            if len(items) >= 25:
                break
        out = {
            "count": len(items),
            "count_mapped": sum(1 for i in items if i.get("lat") is not None),
            "alerts": items,
            "source": "gdacs.org",
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        return {"count": 0, "alerts": [], "error": str(e)}
