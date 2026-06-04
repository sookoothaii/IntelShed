"""GTFS-Realtime vehicle-position ingestor.

Supports configurable city endpoints.  Protobuf parsing via google.transit.gtfs_realtime_pb2.
Add GTFS_<CITY>_URL env vars to override defaults.
"""

import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

try:
    from google.transit import gtfs_realtime_pb2
    HAS_PB = True
except Exception:
    HAS_PB = False

router = APIRouter(prefix="/api/transit", tags=["transit"])

# ---------------------------------------------------------------------------
# Configurable endpoints (override via env var)
# ---------------------------------------------------------------------------
# Aggregated DE feed (gtfs.de) — filter by bbox per city when not using dedicated agency URL
_GTFS_DE_AGG = os.getenv(
    "GTFS_DE_AGGREGATE_URL",
    "https://realtime.gtfs.de/realtime-free.pb",
)

# (min_lat, max_lat, min_lon, max_lon)
CITY_BBOX: dict[str, tuple[float, float, float, float]] = {
    "berlin": (52.34, 52.62, 13.09, 13.76),
    "hamburg": (53.46, 53.70, 9.75, 10.35),
    "munich": (48.06, 48.22, 11.35, 11.72),
}

CITY_CONFIG: dict[str, dict] = {
    "berlin": {
        "url": os.getenv("GTFS_BERLIN_URL", "https://production.gtfsrt.vbb.de/data"),
        "ttl": 30,
        "bbox": CITY_BBOX["berlin"],
    },
    "hamburg": {
        "url": os.getenv("GTFS_HAMBURG_URL", _GTFS_DE_AGG),
        "ttl": 30,
        "bbox": CITY_BBOX["hamburg"],
    },
    "munich": {
        "url": os.getenv("GTFS_MUNICH_URL", _GTFS_DE_AGG),
        "ttl": 30,
        "bbox": CITY_BBOX["munich"],
    },
    "helsinki": {
        "url": os.getenv("GTFS_HELSINKI_URL", "https://cdn.hsl.fi/gtfs-realtime/vehicle-positions"),
        "ttl": 30,
        "bbox": None,
    },
    "boston": {
        "url": os.getenv("GTFS_BOSTON_URL", "https://cdn.mbta.com/realtime/VehiclePositions.pb"),
        "ttl": 30,
        "bbox": None,
    },
}


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float] | None) -> bool:
    if not bbox:
        return True
    min_lat, max_lat, min_lon, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

_CACHE: dict[str, tuple[float, dict]] = {}


@router.get("")
def list_cities():
    """Return configured cities and their URL status."""
    return {
        "cities": [
            {
                "id": k,
                "configured": bool(v["url"]),
                "url_preview": v["url"][:60] + "..." if v["url"] and len(v["url"]) > 60 else v["url"],
            }
            for k, v in CITY_CONFIG.items()
        ]
    }


@router.get("/{city}")
async def get_vehicles(city: str):
    """Fetch live vehicle positions for a configured city."""
    city = city.lower().strip()
    if city not in CITY_CONFIG:
        return {
            "error": f"Unknown city '{city}'",
            "available": sorted(CITY_CONFIG.keys()),
        }

    cfg = CITY_CONFIG[city]
    url = cfg["url"]
    if not url:
        return {
            "error": f"No GTFS-Realtime URL configured for {city}.",
            "hint": f"Set env var GTFS_{city.upper()}_URL and restart.",
            "configured": False,
        }

    if not HAS_PB:
        return {
            "error": "GTFS-Realtime protobuf bindings not installed.",
            "hint": "pip install gtfs-realtime-bindings",
        }

    # Cache
    cache_key = f"transit:{city}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < cfg["ttl"]:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            payload = r.content
    except Exception as exc:
        stale = _CACHE.get(cache_key)
        if stale:
            stale[1]["stale"] = True
            return stale[1]
        return {"error": f"Upstream fetch failed: {exc}", "city": city, "url": url}

    # Parse protobuf
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(payload)
    except Exception as exc:
        return {"error": f"Protobuf parse failed: {exc}", "city": city}

    vehicles = []
    trip_updates = 0
    for entity in feed.entity:
        if entity.HasField("trip_update"):
            trip_updates += 1
            continue
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        lat = lon = None
        bearing = speed = None
        if v.HasField("position"):
            pos = v.position
            if pos.latitude != 0.0 and pos.longitude != 0.0:
                lat, lon = pos.latitude, pos.longitude
                bearing = pos.bearing if pos.bearing else None
                speed = pos.speed if pos.speed else None
        label = None
        if v.HasField("vehicle"):
            desc = v.vehicle
            label = desc.label or desc.license_plate or None
        if lat is None or lon is None:
            continue
        if not _in_bbox(lat, lon, cfg.get("bbox")):
            continue
        vehicles.append({
            "id": entity.id,
            "route_id": v.trip.route_id if v.trip else None,
            "trip_id": v.trip.trip_id if v.trip else None,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "bearing": round(bearing, 1) if bearing else None,
            "speed": round(speed, 1) if speed else None,
            "timestamp": v.timestamp if v.timestamp else None,
            "label": label,
        })

    result = {
        "city": city,
        "count": len(vehicles),
        "vehicles": vehicles,
        "trip_updates": trip_updates,
        "feed_mode": "vehicle_positions" if vehicles else ("trip_updates_only" if trip_updates else "empty"),
        "feed_timestamp": feed.header.timestamp if feed.header else None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    if not vehicles and trip_updates:
        result["hint"] = (
            f"Feed has {trip_updates} trip updates, 0 vehicle positions right now. "
            "VBB/gtfs.de often publish delays only (not GPS buses). "
            "Use Helsinki/Boston to verify transit layer; Berlin icons need a VehiclePosition feed."
        )

    _CACHE[cache_key] = (time.time(), result)
    return result
