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
            age = (
                datetime.now(timezone.utc) - cached_at.replace(tzinfo=timezone.utc)
            ).total_seconds()
            if age < ttl:
                return json.loads(row[0])
    except Exception:
        pass
    return None


def _db_set(key: str, value):
    try:
        from connector_registry import feed_ttl_sec

        ttl = int(feed_ttl_sec(key))
        conn = _db_connect()
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO feed_cache (key, value, cached_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (key, json.dumps(value), datetime.now(timezone.utc).isoformat(), ttl),
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
    """Planetary K-index + solar wind + Dst + protons + alerts + forecast (cached 5 min). No key."""
    key = "spaceweather"
    cached = await _get(key, ttl=300.0)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            kp_task = client.get(
                "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
            )
            sw_task = client.get(
                "https://services.swpc.noaa.gov/json/ace/swepam/ace_swepam_1h.json"
            )
            dst_task = client.get("https://services.swpc.noaa.gov/json/dst.json")
            protons_task = client.get(
                "https://services.swpc.noaa.gov/json/ace/epam/ace_epam_1h.json"
            )
            alerts_task = client.get(
                "https://services.swpc.noaa.gov/products/alerts.json"
            )
            forecast_task = client.get(
                "https://services.swpc.noaa.gov/products/noaa-planetary-k-index-forecast.json"
            )
            kp_r, sw_r, dst_r, protons_r, alerts_r, forecast_r = await asyncio.gather(
                kp_task,
                sw_task,
                dst_task,
                protons_task,
                alerts_task,
                forecast_task,
                return_exceptions=True,
            )

        def _kp_row(r):
            if isinstance(r, dict):
                return r.get("time_tag"), r.get("Kp")
            if isinstance(r, list) and len(r) >= 2:
                return r[0], r[1]
            return None, None

        # Kp
        kp_val = None
        kp_time = None
        kp_rows = []
        try:
            kp_rows_raw = (
                kp_r.json()
                if isinstance(kp_r, httpx.Response) and kp_r.status_code == 200
                else []
            )
            kp_rows = [
                r
                for r in kp_rows_raw
                if not (isinstance(r, list) and r and r[1] == "Kp")
            ]
            latest = kp_rows[-1] if kp_rows else None
            kp_time, kp_raw = _kp_row(latest) if latest else (None, None)
            kp_val = float(kp_raw) if kp_raw not in (None, "null") else None
        except Exception:
            pass

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
        for r in kp_rows[-24:]:
            t, k = _kp_row(r)
            try:
                history.append({"time": t, "kp": float(k)})
            except (TypeError, ValueError):
                continue

        # Solar wind (latest 1h entry)
        solar_wind: dict = {}
        try:
            sw_data = (
                sw_r.json()
                if isinstance(sw_r, httpx.Response) and sw_r.status_code == 200
                else []
            )
            if sw_data and isinstance(sw_data, list):
                entry = sw_data[-1]
                if isinstance(entry, dict):
                    solar_wind = {
                        "time": entry.get("time_tag"),
                        "speed_km_s": _float_or_none(entry.get("speed")),
                        "density_p_cc": _float_or_none(entry.get("density")),
                        "temperature_k": _float_or_none(entry.get("temperature")),
                    }
        except Exception:
            pass

        # Dst
        dst_val = None
        dst_time = None
        try:
            dst_data = (
                dst_r.json()
                if isinstance(dst_r, httpx.Response) and dst_r.status_code == 200
                else []
            )
            if dst_data and isinstance(dst_data, list):
                # list of dicts: time_tag, dst
                entry = dst_data[-1]
                if isinstance(entry, dict):
                    dst_val = _float_or_none(entry.get("dst") or entry.get("Dst"))
                    dst_time = entry.get("time_tag")
        except Exception:
            pass

        # Proton flux
        protons: dict = {}
        try:
            p_data = (
                protons_r.json()
                if isinstance(protons_r, httpx.Response)
                and protons_r.status_code == 200
                else []
            )
            if p_data and isinstance(p_data, list):
                entry = p_data[-1]
                if isinstance(entry, dict):
                    protons = {
                        "time": entry.get("time_tag"),
                        "gt_10_mev": _float_or_none(
                            entry.get("flux") or entry.get("p1")
                        ),
                        "gt_50_mev": _float_or_none(entry.get("p5")),
                        "gt_100_mev": _float_or_none(entry.get("p10")),
                    }
        except Exception:
            pass

        # Alerts
        alerts: list[dict] = []
        try:
            alerts_data = (
                alerts_r.json()
                if isinstance(alerts_r, httpx.Response) and alerts_r.status_code == 200
                else []
            )
            if isinstance(alerts_data, list):
                for a in alerts_data[:10]:
                    if isinstance(a, dict):
                        alerts.append(
                            {
                                "time": a.get("issue_time") or a.get("time_tag"),
                                "product": a.get("product_id")
                                or a.get("product")
                                or "SWPC",
                                "message": (a.get("message") or "")[:220],
                                "severity": a.get("severity") or "",
                            }
                        )
        except Exception:
            pass

        # 3-day Kp forecast
        forecast: list[dict] = []
        try:
            fc_data = (
                forecast_r.json()
                if isinstance(forecast_r, httpx.Response)
                and forecast_r.status_code == 200
                else []
            )
            if isinstance(fc_data, list) and fc_data:
                # may contain header row
                rows = [
                    r
                    for r in fc_data
                    if not (isinstance(r, list) and r and "Kp" in str(r))
                ]
                for r in rows[:12]:
                    if isinstance(r, dict):
                        forecast.append(
                            {
                                "time": r.get("time_tag") or r.get("time"),
                                "kp": _float_or_none(r.get("Kp") or r.get("kp")),
                            }
                        )
                    elif isinstance(r, list) and len(r) >= 2:
                        forecast.append({"time": r[0], "kp": _float_or_none(r[1])})
        except Exception:
            pass

        out = {
            "kp_index": kp_val,
            "scale": scale,
            "time": kp_time,
            "dst": dst_val,
            "dst_time": dst_time,
            "solar_wind": solar_wind,
            "protons": protons,
            "alerts": alerts,
            "forecast": forecast,
            "aurora_visible_midlat": (kp_val or 0) >= 6,
            "hf_radio_impact": (kp_val or 0) >= 5,
            "gps_degrade": (kp_val or 0) >= 5
            or (dst_val is not None and dst_val <= -80),
            "history": history,
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        return {"kp_index": None, "scale": "unknown", "error": str(e)}


def _float_or_none(v):
    if v is None or v == "null":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
    """Current weather + 24h outlook. Windy Point Forecast if keyed, else Open-Meteo."""
    from windy_bridge import fetch_point_weather

    out = await fetch_point_weather(lat, lon)
    if out.get("current"):
        import feed_registry

        feed_registry.write_auto(f"weather:{round(lat, 2)}:{round(lon, 2)}", out)
    return out


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
            items.append(
                {
                    "id": sid,
                    "name": title[:120],
                    "status": "gdacs",
                    "url": a.get("link"),
                    "lat": lat,
                    "lon": lon,
                    "source": "gdacs",
                }
            )
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
                        items.append(
                            {
                                "id": did,
                                "name": name,
                                "status": fields.get("status") or "reliefweb",
                                "url": fields.get("url"),
                                "lat": lat,
                                "lon": lon,
                                "source": "reliefweb",
                            }
                        )
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
        alt = s[7]  # barometric altitude (m)
        vel = s[9]  # velocity (m/s)
        vert = s[11]  # vertical rate (m/s)
        squawk = s[14]  # squawk code

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
            anomalies.append(
                {
                    "icao24": icao,
                    "callsign": callsign or None,
                    "lat": lat,
                    "lon": lon,
                    "alt_m": alt,
                    "vel_ms": vel,
                    "squawk": squawk,
                    "reasons": reasons,
                }
            )

    return {"analyzed": len(states), "anomalies": anomalies, "count": len(anomalies)}


# ---------------------------------------------------------------------------
# Cross-feed correlation — detects developing situations from multiple sources
# ---------------------------------------------------------------------------
import math  # noqa: E402

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
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
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

    # 1+2. Fetch earthquakes (USGS) and disasters (ReliefWeb) in parallel
    async def _fetch_usgs() -> list:
        try:
            async with httpx.AsyncClient(timeout=8.0, headers=_UA) as client:
                r = await client.get(
                    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
                )
                return r.json().get("features", [])
        except Exception:
            return []

    async def _fetch_reliefweb() -> list:
        try:
            async with httpx.AsyncClient(timeout=8.0, headers=_UA) as client:
                r = await client.get(
                    "https://api.reliefweb.int/v1/disasters?appname=worldbase&profile=list&preset=latest&limit=20"
                )
                return r.json().get("data", [])
        except Exception:
            return []

    quakes, disasters = await asyncio.gather(_fetch_usgs(), _fetch_reliefweb())

    for q in quakes:
        props = q.get("properties", {})
        geo = q.get("geometry", {})
        coords = geo.get("coordinates", [0, 0])
        lon, lat = coords[0], coords[1]
        mag = props.get("mag", 0)
        for site_name, site_lon, site_lat, radius in NUCLEAR_SITES:
            dist = _haversine(lon, lat, site_lon, site_lat)
            if dist < radius and mag >= 3.0:
                situations.append(
                    {
                        "severity": "high" if mag >= 5 else "medium",
                        "type": "quake_near_nuclear",
                        "title": f"M{mag:.1f} earthquake {dist:.0f} km from {site_name}",
                        "location": {
                            "lon": lon,
                            "lat": lat,
                            "place": props.get("place", ""),
                        },
                        "details": {
                            "distance_km": round(dist, 1),
                            "site": site_name,
                            "magnitude": mag,
                        },
                    }
                )

    # 2. Military aircraft surge near disaster zone (ReliefWeb data fetched above)
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
            situations.append(
                {
                    "severity": "medium",
                    "type": "military_presence_disaster_zone",
                    "title": f"{mil_count} military aircraft near {dis_name}",
                    "location": {"lon": dlon, "lat": dlat, "place": dis_name},
                    "details": {"military_count": mil_count, "disaster": dis_name},
                }
            )

    # 3. High seismic activity cluster (>3 quakes M4+ within 2h in same region)
    recent = [q for q in quakes if q.get("properties", {}).get("mag", 0) >= 4.0]
    if len(recent) >= 3:
        # Check if clustered within 500km
        for i, q1 in enumerate(recent[:5]):
            c1 = q1.get("geometry", {}).get("coordinates", [0, 0])
            cluster = [q1]
            for q2 in recent[i + 1 :]:
                c2 = q2.get("geometry", {}).get("coordinates", [0, 0])
                if _haversine(c1[0], c1[1], c2[0], c2[1]) < 500:
                    cluster.append(q2)
            if len(cluster) >= 3:
                avg_lon = sum(
                    c.get("geometry", {}).get("coordinates", [0, 0])[0] for c in cluster
                ) / len(cluster)
                avg_lat = sum(
                    c.get("geometry", {}).get("coordinates", [0, 0])[1] for c in cluster
                ) / len(cluster)
                situations.append(
                    {
                        "severity": "high",
                        "type": "seismic_cluster",
                        "title": f"{len(cluster)} M4+ earthquakes in cluster",
                        "location": {
                            "lon": avg_lon,
                            "lat": avg_lat,
                            "place": "cluster region",
                        },
                        "details": {
                            "quake_count": len(cluster),
                            "max_mag": max(
                                c.get("properties", {}).get("mag", 0) for c in cluster
                            ),
                        },
                    }
                )
                break

    # 4. Elevated river gauge + heavy precipitation (Open-Meteo, no key)
    try:
        import pegel_bridge

        peg = await pegel_bridge.get_pegel()
        async with httpx.AsyncClient(timeout=8.0, headers=_UA) as client:
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
                    rain_mm = (
                        cur.get("precipitation")
                        if cur.get("precipitation") is not None
                        else cur.get("rain")
                    )
                except Exception:
                    pass
                if rain_mm is not None and float(rain_mm) >= 2.0:
                    situations.append(
                        {
                            "severity": "high"
                            if g["severity"] == "critical"
                            else "medium",
                            "type": "pegel_rain_correlation",
                            "title": f"High water + rain at {g['name']} ({rain_mm} mm/h)",
                            "location": {
                                "lon": lon,
                                "lat": lat,
                                "place": g.get("water", ""),
                            },
                            "details": {
                                "gauge": g["name"],
                                "water": g.get("water"),
                                "level": g.get("value"),
                                "unit": g.get("unit"),
                                "precipitation_mm": rain_mm,
                            },
                        }
                    )
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
        # ASEAN + operator region first, then global reference cities (Open-Meteo, no key)
        cities = [
            ("Bangkok", 13.75, 100.5),
            ("Chiang Mai", 18.79, 98.98),
            ("Phuket", 7.88, 98.39),
            ("Singapore", 1.35, 103.82),
            ("Kuala Lumpur", 3.14, 101.69),
            ("Jakarta", -6.21, 106.85),
            ("Manila", 14.60, 120.98),
            ("Ho Chi Minh City", 10.82, 106.63),
            ("Hanoi", 21.03, 105.85),
            ("Delhi", 28.6, 77.2),
            ("Beijing", 39.9, 116.4),
            ("London", 51.5, -0.1),
        ]
        results = []
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            for name, lat, lon in cities:
                try:
                    r = await client.get(
                        f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}"
                        "&current=pm10,pm2_5,dust,aerosol_optical_depth"
                    )
                    d = r.json()
                    cur = d.get("current", {})
                    results.append(
                        {
                            "city": name,
                            "lat": lat,
                            "lon": lon,
                            "pm25": cur.get("pm2_5"),
                            "pm10": cur.get("pm10"),
                            "dust": cur.get("dust"),
                            "aerosol_optical_depth": cur.get("aerosol_optical_depth"),
                            "time": cur.get("time"),
                        }
                    )
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
            cached["count_mapped"] = sum(
                1 for i in cached["alerts"] if i.get("lat") is not None
            )
        return cached
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get(
                "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
            )
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
            items.append(
                {
                    "title": props.get("name")
                    or props.get("eventname")
                    or "GDACS alert",
                    "link": url_obj.get("report") or "",
                    "description": props.get("htmldescription")
                    or props.get("description")
                    or "",
                    "published": props.get("datemodified") or "",
                    "lat": lat,
                    "lon": lon,
                    "alertlevel": props.get("alertlevel"),
                    "eventtype": props.get("eventtype"),
                }
            )
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


# ---------------------------------------------------------------------------
# Weather radar — RainViewer (free, no key). Tile URLs for globe overlay.
# ---------------------------------------------------------------------------
@router.get("/radar")
async def weather_radar():
    """Global precipitation radar tile URLs from RainViewer (cached 10m). No key."""
    key = "radar"
    cached = await _get(key, ttl=600.0)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get("https://api.rainviewer.com/public/weather-maps.json")
            if r.status_code != 200:
                return {"enabled": False, "error": f"status {r.status_code}"}
            data = r.json()

        past = data.get("radar", {}).get("past", [])
        nowcast = data.get("radar", {}).get("nowcast", [])
        satellite = data.get("satellite", {}).get("infrared", [])

        host = data.get("host", "https://tilecache.rainviewer.net")

        latest_past = past[-1] if past else None
        latest_nowcast = nowcast[0] if nowcast else None
        latest_sat = satellite[-1] if satellite else None

        def _tile_path(item, kind: str = "radar") -> str:
            path = item.get("path", "")
            return f"{host}{path}/256/{kind}/{{z}}/{{x}}/{{y}}/2/1_1.png"

        out: dict = {
            "enabled": True,
            "host": host,
            "updated": datetime.now(timezone.utc).isoformat(),
            "radar": {
                "past_count": len(past),
                "nowcast_count": len(nowcast),
                "latest_time": latest_past.get("time") if latest_past else None,
                "latest_tile": _tile_path(latest_past) if latest_past else None,
                "nowcast_time": latest_nowcast.get("time") if latest_nowcast else None,
                "nowcast_tile": _tile_path(latest_nowcast) if latest_nowcast else None,
                "past_tiles": [_tile_path(item) for item in past[-6:]],
            },
            "satellite": {
                "count": len(satellite),
                "latest_time": latest_sat.get("time") if latest_sat else None,
                "latest_tile": _tile_path(latest_sat, kind="satellite")
                if latest_sat
                else None,
            },
        }
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        return {"enabled": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Commodities — gold, silver, oil, natgas via Frankfurter + fallback. No key.
# ---------------------------------------------------------------------------
@router.get("/commodities")
async def commodities():
    """Key commodity prices (cached 5m). No key. Uses Frankfurter for gold-backed proxies."""
    key = "commodities"
    cached = await _get(key, ttl=300.0)
    if cached is not None:
        return cached
    out: dict = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "commodities": {},
        "source": "frankfurter.app",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            # XAU (gold) and XAG (silver) via Frankfurter (ECB reference rates)
            try:
                fx = await client.get(
                    "https://api.frankfurter.app/latest",
                    params={"from": "USD", "to": "XAU,XAG"},
                )
                if fx.status_code == 200:
                    rates = fx.json().get("rates", {})
                    if "XAU" in rates:
                        out["commodities"]["gold_usd_oz"] = round(1.0 / rates["XAU"], 2)
                    if "XAG" in rates:
                        out["commodities"]["silver_usd_oz"] = round(
                            1.0 / rates["XAG"], 2
                        )
            except Exception:
                pass

            # Oil (Brent/WTI) via Commodities-API free tier or fallback to static
            try:
                oil = await client.get(
                    "https://commodities-api.com/api/latest",
                    params={"base": "USD", "symbols": "BRENT,WTI"},
                )
                if oil.status_code == 200:
                    rates = oil.json().get("data", {}).get("rates", {})
                    if "BRENT" in rates:
                        out["commodities"]["brent_usd_bbl"] = round(
                            1.0 / rates["BRENT"], 2
                        )
                    if "WTI" in rates:
                        out["commodities"]["wti_usd_bbl"] = round(1.0 / rates["WTI"], 2)
            except Exception:
                pass

        if not out["commodities"]:
            out["error"] = "no commodity data available"
        await _set(key, out)
        return out
    except Exception as e:
        stale = await _stale(key)
        if stale:
            return stale
        out["error"] = str(e)
        return out
