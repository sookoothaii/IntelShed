"""AIS vessel-position bridge.

Sources (graceful degradation):
1. AISstream.io WebSocket background collector (AISSTREAM_API_KEY)
2. MyShipTracking JSON (bounding-box, no key)
3. AISHub (AISHUB_API_KEY)

When all sources are empty, returns count=0 and errors — no synthetic vessels.

Endpoints:
  GET /api/maritime          — live vessel positions
  GET /api/maritime/ports    — tracked port regions
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter

import feed_registry

router = APIRouter(prefix="/api/maritime", tags=["maritime"])

# Thailand / ASEAN corridor — default when operator region is thailand
_THAI_REGIONS = ("malacca", "laem_chabang", "bangkok_port", "phuket", "singapore")

PORT_REGIONS: dict[str, dict] = {
    "hamburg": {"min_lat": 53.4, "max_lat": 53.6, "min_lon": 9.7, "max_lon": 10.2, "label": "Hamburg"},
    "rotterdam": {"min_lat": 51.8, "max_lat": 52.1, "min_lon": 3.8, "max_lon": 4.4, "label": "Rotterdam"},
    "singapore": {"min_lat": 1.1, "max_lat": 1.4, "min_lon": 103.7, "max_lon": 104.1, "label": "Singapore"},
    "malacca": {"min_lat": 1.0, "max_lat": 6.5, "min_lon": 99.0, "max_lon": 104.5, "label": "Malacca Strait"},
    "laem_chabang": {"min_lat": 12.8, "max_lat": 13.2, "min_lon": 100.7, "max_lon": 101.1, "label": "Laem Chabang"},
    "bangkok_port": {"min_lat": 13.3, "max_lat": 13.8, "min_lon": 100.4, "max_lon": 100.9, "label": "Bangkok Port"},
    "phuket": {"min_lat": 7.5, "max_lat": 8.2, "min_lon": 98.2, "max_lon": 98.6, "label": "Phuket"},
    "suez": {"min_lat": 29.8, "max_lat": 30.2, "min_lon": 32.2, "max_lon": 32.6, "label": "Suez Canal"},
    "panama": {"min_lat": 8.8, "max_lat": 9.2, "min_lon": -79.7, "max_lon": -79.4, "label": "Panama Canal"},
    "malmoe": {"min_lat": 55.5, "max_lat": 55.7, "min_lon": 12.8, "max_lon": 13.1, "label": "Malmö / Øresund"},
}

_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 45  # seconds
_FETCH_TIMEOUT = 10.0
_REFRESH_LOCK = asyncio.Lock()

_STREAM: dict[str, Any] = {
    "vessels": {},
    "connected": False,
    "last_msg_at": 0.0,
    "errors": [],
}
_STREAM_TASK: asyncio.Task | None = None

# aisstream.io/docs — position-bearing AIS message types
_AISSTREAM_POSITION_TYPES = (
    "PositionReport",
    "StandardClassBPositionReport",
    "ExtendedClassBPositionReport",
)


def _aisstream_subscription(api_key: str, regions: dict[str, dict]) -> dict[str, Any]:
    """Build subscription JSON per https://aisstream.io/documentation (no empty optional fields)."""
    boxes = [
        [[box["min_lat"], box["min_lon"]], [box["max_lat"], box["max_lon"]]]
        for box in regions.values()
    ]
    return {
        "APIKey": api_key,
        "BoundingBoxes": boxes,
        "FilterMessageTypes": list(_AISSTREAM_POSITION_TYPES),
    }


def _aisstream_service_error(msg: dict) -> str | None:
    err = msg.get("error") or msg.get("Error")
    if err is None:
        return None
    return str(err).strip() or None


def _parse_aisstream_message(msg: dict) -> tuple[str | None, dict | None, dict]:
    """Return (message_type, position_body, metadata) from an AISstream websocket frame."""
    if _aisstream_service_error(msg):
        return None, None, {}
    mtype = str(msg.get("MessageType") or "").strip()
    meta = msg.get("MetaData") or msg.get("Metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    body: dict | None = None
    message_obj = msg.get("Message") or {}
    if isinstance(message_obj, dict):
        if mtype and isinstance(message_obj.get(mtype), dict):
            body = message_obj[mtype]
        elif isinstance(message_obj.get("PositionReport"), dict):
            body = message_obj["PositionReport"]
            mtype = mtype or "PositionReport"
    return mtype or None, body, meta

    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _collect_sec() -> float:
    return _env_float("WORLDBASE_MARITIME_COLLECT_SEC", 30.0)


def _stream_stale_sec() -> float:
    return _env_float("WORLDBASE_MARITIME_STREAM_STALE_SEC", 1800.0)


def _max_vessels() -> int:
    return _env_int("WORLDBASE_MARITIME_MAX_VESSELS", 800)


def _aisstream_background_on() -> bool:
    if not os.getenv("AISSTREAM_API_KEY", "").strip():
        return False
    raw = os.getenv("WORLDBASE_MARITIME_AISSTREAM", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _active_regions() -> dict[str, dict]:
    """Operator-focused region set — avoids hammering every global port on each poll."""
    raw = os.getenv("WORLDBASE_MARITIME_REGIONS", "").strip()
    if raw:
        if raw.lower() == "all":
            return PORT_REGIONS
        ids = {p.strip() for p in raw.split(",") if p.strip()}
        return {k: v for k, v in PORT_REGIONS.items() if k in ids}
    if os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower() == "thailand":
        return {k: PORT_REGIONS[k] for k in _THAI_REGIONS if k in PORT_REGIONS}
    return PORT_REGIONS


def maritime_operator_bbox() -> list[float] | None:
    """STAC bbox union for the active maritime port regions (lon/lat STAC order)."""
    boxes: list[list[float]] = []
    for box in _active_regions().values():
        boxes.append([box["min_lon"], box["min_lat"], box["max_lon"], box["max_lat"]])
    if not boxes:
        return None
    if len(boxes) == 1:
        return boxes[0]
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _region_for_point(lat: float, lon: float, regions: dict[str, dict]) -> str:
    for name, box in regions.items():
        if (
            box["min_lat"] <= lat <= box["max_lat"]
            and box["min_lon"] <= lon <= box["max_lon"]
        ):
            return name
    return "global"


def _point_in_regions(lat: float, lon: float, regions: dict[str, dict]) -> bool:
    for box in regions.values():
        if (
            box["min_lat"] <= lat <= box["max_lat"]
            and box["min_lon"] <= lon <= box["max_lon"]
        ):
            return True
    return False


def _vessel_type_label(type_code: int | None) -> str:
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


def _vessel_from_aisstream(msg: dict, regions: dict[str, dict]) -> dict | None:
    mtype, body, meta = _parse_aisstream_message(msg)
    if mtype not in _AISSTREAM_POSITION_TYPES:
        return None

    mmsi = meta.get("MMSI") or (body or {}).get("UserID")
    if mmsi is None:
        return None
    mmsi = str(mmsi).strip()
    if not mmsi:
        return None

    lat = meta.get("latitude", meta.get("Latitude"))
    lon = meta.get("longitude", meta.get("Longitude"))
    if body:
        if lat is None:
            lat = body.get("Latitude")
        if lon is None:
            lon = body.get("Longitude")
    if lat is None or lon is None:
        return None
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None

    pr = body or {}
    ship_type = meta.get("ShipType")
    if ship_type is None and isinstance(pr.get("Type"), int):
        ship_type = pr.get("Type")

    return {
        "mmsi": mmsi,
        "name": meta.get("ShipName") or meta.get("shipName") or "Unknown",
        "type": _vessel_type_label(ship_type if isinstance(ship_type, int) else None),
        "lat": round(lat_f, 5),
        "lon": round(lon_f, 5),
        "course": pr.get("Cog"),
        "speed": pr.get("Sog"),
        "destination": meta.get("destination"),
        "flag": meta.get("Flag") or meta.get("CountryCode"),
        "length": meta.get("Dimension", {}).get("A") if isinstance(meta.get("Dimension"), dict) else None,
        "region": _region_for_point(lat_f, lon_f, regions),
        "source": "aisstream",
    }


def _ingest_stream_message(msg: dict, regions: dict[str, dict]) -> bool:
    """Ingest one websocket frame. Returns False when the service reports an error."""
    err = _aisstream_service_error(msg)
    if err:
        _STREAM["errors"] = [err[:200]]
        return False
    vessel = _vessel_from_aisstream(msg, regions)
    if not vessel:
        return True
    if not _point_in_regions(vessel["lat"], vessel["lon"], regions):
        return True
    vessel["_seen_at"] = time.time()
    _STREAM["vessels"][vessel["mmsi"]] = vessel
    _STREAM["last_msg_at"] = time.time()
    max_n = _max_vessels()
    if len(_STREAM["vessels"]) > max_n:
        _prune_stream_vessels()
        if len(_STREAM["vessels"]) > max_n:
            oldest = sorted(
                _STREAM["vessels"].items(),
                key=lambda kv: float(kv[1].get("_seen_at") or 0),
            )
            for mmsi, _ in oldest[: len(_STREAM["vessels"]) - max_n]:
                _STREAM["vessels"].pop(mmsi, None)
    return True


def _prune_stream_vessels() -> None:
    stale_after = _stream_stale_sec()
    now = time.time()
    vessels: dict[str, dict] = _STREAM["vessels"]
    drop = [mmsi for mmsi, row in vessels.items() if now - float(row.get("_seen_at") or 0) > stale_after]
    for mmsi in drop:
        vessels.pop(mmsi, None)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _snapshot_from_stream(regions: dict[str, dict] | None = None) -> list[dict]:
    active = regions or _active_regions()
    out: list[dict] = []
    for row in _STREAM["vessels"].values():
        lat = row.get("lat")
        lon = row.get("lon")
        if lat is None or lon is None:
            continue
        if not _point_in_regions(float(lat), float(lon), active):
            continue
        clean = {k: v for k, v in row.items() if not str(k).startswith("_")}
        out.append(clean)
    return out


async def _fetch_myshiptracking(region: str, box: dict) -> list[dict]:
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
            "source": "myshiptracking",
        })
    return vessels


async def _fetch_aisstream_snapshot(regions: dict[str, dict]) -> list[dict]:
    """One-shot AISstream snapshot when background collector is disabled."""
    api_key = os.getenv("AISSTREAM_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        import websockets
    except ImportError:
        return []

    subscription = _aisstream_subscription(api_key, regions)
    collect_sec = _collect_sec()
    wait_timeout = collect_sec + 5.0
    vessels: list[dict] = []
    seen: set[str] = set()
    try:
        async with websockets.connect(
            "wss://stream.aisstream.io/v0/stream",
            open_timeout=8,
            close_timeout=2,
        ) as ws:
            await ws.send(json.dumps(subscription))
            deadline = time.monotonic() + collect_sec
            while time.monotonic() < deadline and len(vessels) < _max_vessels():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                except asyncio.TimeoutError:
                    continue
                msg = json.loads(raw)
                if not _ingest_stream_message(msg, regions):
                    break
                vessel = _vessel_from_aisstream(msg, regions)
                if not vessel or vessel["mmsi"] in seen:
                    continue
                seen.add(vessel["mmsi"])
                vessels.append(vessel)
    except Exception:
        return []
    return vessels


async def _fetch_aishub() -> list[dict]:
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
            "source": "aishub",
        })
    return vessels


async def _aisstream_collector_loop() -> None:
    """Persistent AISstream WebSocket — API reads snapshots without blocking."""
    while True:
        if not _aisstream_background_on():
            _STREAM["connected"] = False
            await asyncio.sleep(10.0)
            continue
        regions = _active_regions()
        api_key = os.getenv("AISSTREAM_API_KEY", "").strip()
        subscription = _aisstream_subscription(api_key, regions)
        try:
            import websockets
        except ImportError:
            _STREAM["errors"] = ["websockets package not installed"]
            await asyncio.sleep(30.0)
            continue
        try:
            async with websockets.connect(
                "wss://stream.aisstream.io/v0/stream",
                open_timeout=8,
                close_timeout=2,
            ) as ws:
                await ws.send(json.dumps(subscription))
                _STREAM["connected"] = False
                _STREAM["errors"] = []
                while _aisstream_background_on():
                    regions = _active_regions()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=45.0)
                    except asyncio.TimeoutError:
                        continue
                    msg = json.loads(raw)
                    if not _ingest_stream_message(msg, regions):
                        break
                    if _STREAM["vessels"]:
                        _STREAM["connected"] = True
        except asyncio.CancelledError:
            _STREAM["connected"] = False
            raise
        except Exception as exc:
            _STREAM["connected"] = False
            _STREAM["errors"] = [str(exc)[:200]]
            await asyncio.sleep(10.0)


def start_aisstream_collector() -> None:
    global _STREAM_TASK
    if not _aisstream_background_on():
        return
    if _STREAM_TASK and not _STREAM_TASK.done():
        return
    _STREAM_TASK = asyncio.create_task(_aisstream_collector_loop())


def stop_aisstream_collector() -> None:
    global _STREAM_TASK
    if _STREAM_TASK and not _STREAM_TASK.done():
        _STREAM_TASK.cancel()
    _STREAM_TASK = None
    _STREAM["connected"] = False


async def _empty_maritime_errors(errors: list[str]) -> list[str]:
    out = list(errors)
    out.extend(str(e) for e in (_STREAM.get("errors") or []) if e)
    if _aisstream_background_on():
        if _STREAM.get("connected"):
            if _STREAM.get("last_msg_at"):
                out.append("AISstream connected but no vessels in buffer yet")
            else:
                out.append("AISstream connected; waiting for first PositionReport")
        elif _STREAM.get("errors"):
            pass  # already copied above
        else:
            out.append("AISstream collector not connected")
    elif not os.getenv("AISSTREAM_API_KEY", "").strip():
        out.append("Set AISSTREAM_API_KEY for live AIS WebSocket")
    if not out:
        out.append("No live AIS vessels from configured sources")
    return out


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


def _build_result(
    all_vessels: list[dict],
    *,
    errors: list[str] | None,
    stale: bool = False,
    regions: dict[str, dict] | None = None,
    stream_meta: dict[str, Any] | None = None,
) -> dict:
    deduped = _dedupe_vessels(all_vessels)
    active = regions or _active_regions()
    result: dict[str, Any] = {
        "count": len(deduped),
        "vessels": deduped,
        "regions_tracked": list(active.keys()),
        "regions_all": list(PORT_REGIONS.keys()),
        "errors": errors if errors else None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    if stale:
        result["stale"] = True
    if stream_meta:
        result.update(stream_meta)
    return result


async def _supplement_myshiptracking(
    all_vessels: list[dict],
    regions: dict[str, dict],
    errors: list[str],
    *,
    min_count: int = 5,
) -> list[dict]:
    if len(all_vessels) >= min_count:
        return all_vessels
    region_tasks = [
        _fetch_myshiptracking(region, box) for region, box in regions.items()
    ]
    region_results = await asyncio.gather(*region_tasks, return_exceptions=True)
    merged = list(all_vessels)
    for region, res in zip(regions.keys(), region_results):
        if isinstance(res, Exception):
            errors.append(f"{region}: {res}")
            continue
        if res:
            merged.extend(res)
    return merged


async def _build_maritime_result() -> dict:
    regions = _active_regions()
    errors: list[str] = list(_STREAM.get("errors") or [])
    all_vessels = _snapshot_from_stream(regions)

    stream_meta: dict[str, Any] | None = None
    if _aisstream_background_on():
        stream_meta = {
            "stream_connected": bool(_STREAM.get("connected")),
            "stream_buffer": len(_STREAM.get("vessels") or {}),
        }

    if len(all_vessels) < 5:
        all_vessels = await _supplement_myshiptracking(all_vessels, regions, errors)

    if len(all_vessels) < 5 and not _aisstream_background_on():
        collect_sec = _collect_sec()
        wait_timeout = collect_sec + 5.0
        try:
            stream = await asyncio.wait_for(_fetch_aisstream_snapshot(regions), timeout=wait_timeout)
            all_vessels.extend(stream)
        except asyncio.TimeoutError:
            errors.append(f"aisstream: timeout after {wait_timeout:.0f}s")
        except Exception as exc:
            errors.append(f"aisstream: {exc}")

    if len(all_vessels) < 5:
        all_vessels = await _supplement_myshiptracking(all_vessels, regions, errors, min_count=999)

    try:
        hub = await _fetch_aishub()
        if hub:
            all_vessels.extend(hub)
    except Exception as exc:
        errors.append(f"aishub: {exc}")

    if not all_vessels:
        errors = await _empty_maritime_errors(errors)

    return _build_result(
        all_vessels,
        errors=errors or None,
        regions=regions,
        stream_meta=stream_meta,
    )


async def warm_maritime() -> dict | None:
    """Force a live maritime refresh (startup warm-up)."""
    start_aisstream_collector()
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline:
        if len(_snapshot_from_stream(_active_regions())) >= 5:
            break
        await asyncio.sleep(1.0)
    result = await _build_maritime_result()
    if not result.get("count"):
        return None
    _CACHE["maritime:all"] = (time.time(), result)
    feed_registry.write_auto("maritime", result)
    return result


async def touch_maritime_cache() -> bool:
    """Bump feed_cache.cached_at from the AISstream buffer (no upstream HTTP)."""
    regions = _active_regions()
    vessels = _snapshot_from_stream(regions)
    if not vessels:
        return False
    stream_meta: dict[str, Any] | None = None
    if _aisstream_background_on():
        stream_meta = {
            "stream_connected": bool(_STREAM.get("connected")),
            "stream_buffer": len(_STREAM.get("vessels") or {}),
        }
    result = _build_result(
        vessels,
        errors=None,
        regions=regions,
        stream_meta=stream_meta,
    )
    _CACHE["maritime:all"] = (time.time(), result)
    feed_registry.write_auto("maritime", result)
    return True


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
            result = await asyncio.wait_for(_build_maritime_result(), timeout=20.0)
        except asyncio.TimeoutError:
            if stale_payload:
                out = dict(stale_payload)
                out["stale"] = True
                out["errors"] = (stale_payload.get("errors") or []) + ["build timeout — serving stale cache"]
                return out
            result = _build_result(
                [],
                errors=["build timeout"],
                regions=_active_regions(),
            )

        _CACHE[cache_key] = (time.time(), result)
        if result.get("count"):
            feed_registry.write_auto("maritime", result)
        return result


@router.get("/ports")
def list_ports():
    return {
        "ports": [{"id": k, **v} for k, v in PORT_REGIONS.items()],
        "active": list(_active_regions().keys()),
    }
