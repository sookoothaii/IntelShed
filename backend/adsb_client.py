"""ADS-B.lol — free global aircraft positions (ODbL). No API key required.

Used when OpenSky is rate-limited or unconfigured. Fetches several regional
bubbles in parallel and merges by ICAO hex.
"""

from __future__ import annotations

import asyncio
import time

import httpx

_BASE = "https://api.adsb.lol"
_UA = {"User-Agent": "WorldBase/1.0 (civic situational awareness; ODbL)"}

# (lat, lon, radius_nm) — up to 250 nm per API docs
_COVERAGE_NODES: list[tuple[float, float, int]] = [
    (51.5, 10.5, 250),   # Europe
    (40.0, -95.0, 250),  # North America
    (34.0, -118.0, 250), # US West
    (35.0, 139.0, 250),  # East Asia
    (22.0, 78.0, 250),   # South Asia
    (-25.0, 135.0, 250), # Australia
    (-15.0, -60.0, 250), # South America
    (30.0, 30.0, 250),   # Middle East / N Africa
    (55.0, 37.0, 250),   # Russia
    (-1.0, 36.8, 250),   # East Africa
]


def _alt_meters(ac: dict) -> float | None:
    raw = ac.get("alt_geom")
    if raw is None or raw == "ground":
        raw = ac.get("alt_baro")
    if raw is None or raw == "ground":
        return None
    try:
        # readsb / OpenSky convention: feet
        return float(raw) * 0.3048
    except (TypeError, ValueError):
        return None


def ac_to_opensky_state(ac: dict) -> list | None:
    """Map adsb.lol aircraft object to OpenSky state vector (17 elements)."""
    icao = (ac.get("hex") or "").strip().lower()
    lat = ac.get("lat")
    lon = ac.get("lon")
    if not icao or lat is None or lon is None:
        return None
    alt_m = _alt_meters(ac)
    on_ground = ac.get("alt_baro") == "ground" or (alt_m is not None and alt_m < 30)
    gs = ac.get("gs")
    vel_ms = float(gs) * 0.514444 if gs is not None else None
    br = ac.get("baro_rate")
    vert_ms = float(br) * 0.00508 if br is not None else None  # ft/min → m/s
    track = ac.get("track")
    callsign = (ac.get("flight") or "").strip() or None
    squawk = ac.get("squawk")
    if squawk is not None:
        squawk = str(squawk).strip()
    return [
        icao,
        callsign,
        None,
        None,
        None,
        float(lon),
        float(lat),
        alt_m,
        on_ground,
        vel_ms,
        float(track) if track is not None else None,
        vert_ms,
        None,
        alt_m,
        squawk,
        False,
        None,
    ]


async def _fetch_node(
    client: httpx.AsyncClient, lat: float, lon: float, radius_nm: int
) -> list[dict]:
    url = f"{_BASE}/v2/point/{lat}/{lon}/{radius_nm}"
    r = await client.get(url, headers=_UA)
    r.raise_for_status()
    data = r.json()
    return data.get("ac") or []


async def fetch_global_states(max_aircraft: int = 4000) -> dict:
    """Return OpenSky-shaped payload from merged adsb.lol regional queries."""
    merged: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=25.0) as client:
        tasks = [_fetch_node(client, la, lo, r) for la, lo, r in _COVERAGE_NODES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                continue
            for ac in res:
                hx = (ac.get("hex") or "").lower()
                if hx:
                    merged[hx] = ac
    states = []
    for ac in merged.values():
        st = ac_to_opensky_state(ac)
        if st:
            states.append(st)
    now = int(time.time())
    return {
        "time": now,
        "states": states[:max_aircraft],
        "source": "adsb.lol",
        "nodes_queried": len(_COVERAGE_NODES),
        "raw_count": len(merged),
    }


async def fetch_mil_states() -> list[dict]:
    """Military aircraft list from adsb.lol /v2/mil."""
    async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
        r = await client.get(f"{_BASE}/v2/mil", headers=_UA)
        r.raise_for_status()
        return r.json().get("ac") or []
