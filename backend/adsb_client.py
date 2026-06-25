"""ADS-B aircraft positions — adsb.lol (ODbL) + adsb.fi open data fallback.

Used when OpenSky is rate-limited or unconfigured. Fetches several regional
bubbles in parallel and merges by ICAO hex.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

_BASE = "https://api.adsb.lol"
_ADSBFI_BASE = "https://opendata.adsb.fi/api"
_UA = {"User-Agent": "WorldBase/1.0 (civic situational awareness; ODbL)"}

# (lat, lon, radius_nm) — up to 250 nm per API docs; keep count modest for latency
_COVERAGE_NODES: list[tuple[float, float, int]] = [
    (51.5, 10.5, 250),  # Europe
    (40.0, -95.0, 250),  # North America
    (35.0, 139.0, 250),  # East Asia
    (30.0, 30.0, 250),  # Middle East / N Africa
    (-25.0, 135.0, 250),  # Australia
    (-15.0, -60.0, 250),  # South America
]

_DEFAULT_NODE_TIMEOUT = float(os.getenv("ADSB_NODE_TIMEOUT", "6"))
_DEFAULT_TOTAL_TIMEOUT = float(os.getenv("ADSB_TOTAL_TIMEOUT", "14"))


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


async def _fetch_node_fi(
    client: httpx.AsyncClient, lat: float, lon: float, radius_nm: int
) -> list[dict]:
    url = f"{_ADSBFI_BASE}/v3/lat/{lat}/lon/{lon}/dist/{radius_nm}"
    r = await client.get(url, headers=_UA)
    r.raise_for_status()
    data = r.json()
    return data.get("ac") or data.get("aircraft") or []


async def _merge_regional(
    fetch_fn,
    timeout: float,
    node_timeout: float,
    *,
    parallel: bool = True,
) -> tuple[dict[str, dict], int]:
    merged: dict[str, dict] = {}
    nodes_ok = 0

    async with httpx.AsyncClient(timeout=node_timeout) as client:

        async def _safe_node(lat: float, lon: float, radius_nm: int) -> list[dict]:
            try:
                return await fetch_fn(client, lat, lon, radius_nm)
            except Exception:
                return []

        def _ingest(ac_list: list[dict]) -> None:
            nonlocal nodes_ok
            if ac_list:
                nodes_ok += 1
            for ac in ac_list:
                hx = (ac.get("hex") or "").lower()
                if hx:
                    merged[hx] = ac

        if parallel:
            tasks = [
                asyncio.create_task(_safe_node(la, lo, r))
                for la, lo, r in _COVERAGE_NODES
            ]
            done, pending = await asyncio.wait(tasks, timeout=timeout)
            for task in pending:
                task.cancel()
            for task in done:
                try:
                    _ingest(task.result())
                except Exception:
                    continue
        else:
            deadline = time.monotonic() + timeout
            for la, lo, r in _COVERAGE_NODES:
                if time.monotonic() >= deadline:
                    break
                _ingest(await _safe_node(la, lo, r))

    return merged, nodes_ok


def _payload_from_merged(
    merged: dict[str, dict],
    *,
    source: str,
    nodes_ok: int,
    max_aircraft: int,
) -> dict:
    states = []
    for ac in merged.values():
        st = ac_to_opensky_state(ac)
        if st:
            states.append(st)
    return {
        "time": int(time.time()),
        "states": states[:max_aircraft],
        "source": source,
        "nodes_queried": len(_COVERAGE_NODES),
        "nodes_ok": nodes_ok,
        "raw_count": len(merged),
    }


async def fetch_global_states(
    max_aircraft: int = 4000, timeout: float = _DEFAULT_TOTAL_TIMEOUT
) -> dict:
    """Return OpenSky-shaped payload from merged regional queries (lol + fi fallback)."""
    node_timeout = min(_DEFAULT_NODE_TIMEOUT, max(3.0, timeout * 0.75))
    primary = os.getenv("ADSB_PRIMARY", "auto").strip().lower()

    if primary in ("adsb.fi", "fi"):
        merged, nodes_ok = await _merge_regional(
            _fetch_node_fi, timeout, node_timeout, parallel=False
        )
        return _payload_from_merged(
            merged, source="adsb.fi", nodes_ok=nodes_ok, max_aircraft=max_aircraft
        )

    if primary in ("adsb.lol", "lol"):
        merged, nodes_ok = await _merge_regional(_fetch_node, timeout, node_timeout)
        return _payload_from_merged(
            merged, source="adsb.lol", nodes_ok=nodes_ok, max_aircraft=max_aircraft
        )

    # auto: query both; lol gets a short budget so a dead node does not block fi
    lol_budget = min(4.0, timeout * 0.35)
    fi_budget = timeout
    lol_result, fi_result = await asyncio.gather(
        _merge_regional(_fetch_node, lol_budget, min(node_timeout, lol_budget)),
        _merge_regional(_fetch_node_fi, fi_budget, node_timeout, parallel=False),
        return_exceptions=True,
    )

    merged: dict[str, dict] = {}
    nodes_ok = 0
    sources: list[str] = []
    for label, result in (("adsb.lol", lol_result), ("adsb.fi", fi_result)):
        if isinstance(result, Exception):
            continue
        reg_merged, ok = result
        if reg_merged:
            sources.append(label)
            nodes_ok += ok
            merged.update(reg_merged)

    source = "+".join(sources) if sources else "none"
    return _payload_from_merged(
        merged, source=source, nodes_ok=nodes_ok, max_aircraft=max_aircraft
    )


async def fetch_mil_states() -> list[dict]:
    """Military aircraft list from adsb.lol /v2/mil."""
    async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
        r = await client.get(f"{_BASE}/v2/mil", headers=_UA)
        r.raise_for_status()
        return r.json().get("ac") or []
