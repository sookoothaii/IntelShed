"""AIS vessel-position bridge.

Tries multiple free/open AIS sources with graceful degradation:
1. MyShipTracking JSON (no key, bounding-box query)
2. AISHub NMEA TCP (if AIS_MMSI_LIST env var set)
3. Static demo fleet (fallback for offline dev)

Endpoints:
  GET /api/maritime          — live vessel positions
  GET /api/maritime/ports    — tracked port regions
"""

import asyncio
import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/maritime", tags=["maritime"])

# Bounding boxes for high-traffic port regions (lat/lon)
PORT_REGIONS: dict[str, dict] = {
    "hamburg": {"min_lat": 53.4, "max_lat": 53.6, "min_lon": 9.7, "max_lon": 10.2, "label": "Hamburg"},
    "rotterdam": {"min_lat": 51.8, "max_lat": 52.1, "min_lon": 3.8, "max_lon": 4.4, "label": "Rotterdam"},
    "singapore": {"min_lat": 1.1, "max_lat": 1.4, "min_lon": 103.7, "max_lon": 104.1, "label": "Singapore"},
    "suez": {"min_lat": 29.8, "max_lat": 30.2, "min_lon": 32.2, "max_lon": 32.6, "label": "Suez Canal"},
    "panama": {"min_lat": 8.8, "max_lat": 9.2, "min_lon": -79.7, "max_lon": -79.4, "label": "Panama Canal"},
    "malmoe": {"min_lat": 55.5, "max_lat": 55.7, "min_lon": 12.8, "max_lon": 13.1, "label": "Malmö / Øresund"},
}

_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 45  # seconds
_FETCH_TIMEOUT = 6.0
_REFRESH_LOCK = asyncio.Lock()


def _vessel_type_label(type_code: int | None) -> str:
    # AIS vessel type codes (first digit group)
    if type_code is None:
        return "Unknown"
    tc = type_code
    if 10 <= tc < 20:
        return "Reserved"
    if 20 <= tc < 30:
        return "WIG"
    if 30 <= tc < 33:
        return "Fishing"
    if 33 <= tc < 36:
        return "Tug"
    if 36 <= tc < 38:
        return "Yacht"
    if 40 <= tc < 50:
        return "High Speed"
    if 50 <= tc < 53:
        return "Pilot"
    if 53 <= tc < 56:
        return "Military"
    if 60 <= tc < 70:
        return "Passenger"
    if 70 <= tc < 80:
        return "Cargo"
    if 80 <= tc < 90:
        return "Tanker"
    if tc >= 90:
        return "Other"
    return "Unknown"


async def _fetch_myshiptracking(region: str, box: dict) -> list[dict]:
    """Fetch from MyShipTracking JSON endpoint."""
    url = (
        "https://www.myshiptracking.com/requests/vesselsonmap/"
        f"?type=json&minLat={box['min_lat']}&maxLat={box['max_lat']}"
        f"&minLon={box['min_lon']}&maxLon={box['max_lon']}"
    )
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "WorldBase/1.0"})
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    vessels: list[dict] = []
    items = data if isinstance(data, list) else data.get("data", data.get("vessels", []))
    for v in items:
        if not isinstance(v, dict):
            continue
        lat = v.get("LAT") or v.get("lat") or v.get("latitude")
        lon = v.get("LON") or v.get("lon") or v.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat = float(lat)
            lon = float(lon)
        except (ValueError, TypeError):
            continue
        vessels.append({
            "mmsi": str(v.get("MMSI", v.get("mmsi", ""))),
            "name": v.get("NAME", v.get("name", "Unknown")),
            "type": _vessel_type_label(v.get("TYPE", v.get("type", None))),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "course": v.get("COURSE", v.get("course", None)),
            "speed": v.get("SPEED", v.get("speed", None)),
            "destination": v.get("DESTINATION", v.get("destination", None)),
            "flag": v.get("FLAG", v.get("flag", None)),
            "length": v.get("LENGTH", v.get("length", None)),
            "region": region,
        })
    return vessels


async def _fetch_aishub() -> list[dict]:
    """Fetch from AISHub if API key is configured."""
    key = os.getenv("AISHUB_API_KEY")
    if not key:
        return []
    url = f"https://data.aishub.net/ws.php?username={key}&format=1&output=json&compress=0"
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    vessels: list[dict] = []
    for v in data if isinstance(data, list) else data.get("vessels", []):
        if not isinstance(v, dict):
            continue
        lat = v.get("LATITUDE")
        lon = v.get("LONGITUDE")
        if lat is None or lon is None:
            continue
        vessels.append({
            "mmsi": str(v.get("MMSI", "")),
            "name": v.get("SHIPNAME", "Unknown"),
            "type": _vessel_type_label(v.get("TYPE", None)),
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "course": v.get("COURSE"),
            "speed": v.get("SPEED"),
            "destination": v.get("DESTINATION"),
            "flag": v.get("FLAG"),
            "length": v.get("LENGTH"),
            "region": "global",
        })
    return vessels


def _demo_fleet() -> list[dict]:
    """Static demo vessels for offline development."""
    return [
        {"mmsi": "123456789", "name": "Demo Tug Alpha", "type": "Tug", "lat": 53.55, "lon": 9.95, "course": 45, "speed": 5.2, "destination": "Hamburg", "flag": "DE", "length": 32, "region": "hamburg"},
        {"mmsi": "987654321", "name": "Demo Cargo Beta", "type": "Cargo", "lat": 53.52, "lon": 9.92, "course": 120, "speed": 12.5, "destination": "Rotterdam", "flag": "NL", "length": 180, "region": "hamburg"},
        {"mmsi": "111222333", "name": "Demo Tanker Gamma", "type": "Tanker", "lat": 51.92, "lon": 4.05, "course": 270, "speed": 8.0, "destination": "Antwerp", "flag": "BE", "length": 220, "region": "rotterdam"},
        {"mmsi": "444555666", "name": "Demo Passenger Delta", "type": "Passenger", "lat": 1.25, "lon": 103.85, "course": 180, "speed": 15.0, "destination": "Singapore", "flag": "SG", "length": 340, "region": "singapore"},
    ]


def _dedupe_vessels(all_vessels: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for v in all_vessels:
        mmsi = v.get("mmsi", "")
        if mmsi and mmsi in seen:
            continue
        seen.add(mmsi)
        deduped.append(v)
    return deduped


def _build_result(all_vessels: list[dict], *, demo_mode: bool, errors: list[str] | None, stale: bool = False) -> dict:
    deduped = _dedupe_vessels(all_vessels)
    result = {
        "count": len(deduped),
        "vessels": deduped,
        "regions_tracked": list(PORT_REGIONS.keys()),
        "demo_mode": demo_mode,
        "errors": errors if errors else None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    if stale:
        result["stale"] = True
    return result


async def _fetch_live_vessels() -> tuple[list[dict], list[str]]:
    """Query all regions in parallel — bounded by _FETCH_TIMEOUT per request."""
    errors: list[str] = []
    region_tasks = [
        _fetch_myshiptracking(region, box) for region, box in PORT_REGIONS.items()
    ]
    region_results = await asyncio.gather(*region_tasks, return_exceptions=True)
    all_vessels: list[dict] = []
    for region, res in zip(PORT_REGIONS.keys(), region_results):
        if isinstance(res, Exception):
            errors.append(f"{region}: {res}")
            continue
        all_vessels.extend(res)

    try:
        all_vessels.extend(await _fetch_aishub())
    except Exception as exc:
        errors.append(f"aishub: {exc}")

    return all_vessels, errors


@router.get("")
async def get_maritime():
    """Return live vessel positions from all tracked regions."""
    cache_key = "maritime:all"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < TTL:
        return cached[1]

    stale_payload = cached[1] if cached else None

    async with _REFRESH_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < TTL:
            return cached[1]

        try:
            all_vessels, errors = await asyncio.wait_for(
                _fetch_live_vessels(),
                timeout=_FETCH_TIMEOUT + 2.0,
            )
        except asyncio.TimeoutError:
            if stale_payload:
                out = dict(stale_payload)
                out["stale"] = True
                out["errors"] = (stale_payload.get("errors") or []) + ["upstream timeout — serving stale cache"]
                return out
            all_vessels, errors = [], ["upstream timeout"]

        demo_mode = False
        if not all_vessels:
            all_vessels = _demo_fleet()
            demo_mode = True
            errors.append("All live sources failed — returning demo fleet")

        result = _build_result(all_vessels, demo_mode=demo_mode, errors=errors or None)
        _CACHE[cache_key] = (time.time(), result)
        return result


@router.get("/ports")
def list_ports():
    """Return tracked port regions with bounding boxes."""
    return {
        "ports": [
            {"id": k, **v} for k, v in PORT_REGIONS.items()
        ]
    }
