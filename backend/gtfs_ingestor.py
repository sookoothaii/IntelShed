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
CITY_CONFIG: dict[str, dict] = {
    "berlin": {
        "url": os.getenv("GTFS_BERLIN_URL", ""),
        "ttl": 30,
    },
    "hamburg": {
        "url": os.getenv("GTFS_HAMBURG_URL", ""),
        "ttl": 30,
    },
    "munich": {
        "url": os.getenv("GTFS_MUNICH_URL", ""),
        "ttl": 30,
    },
    "helsinki": {
        "url": os.getenv("GTFS_HELSINKI_URL", "https://cdn.hsl.fi/gtfs-realtime/vehicle-positions"),
        "ttl": 30,
    },
    "boston": {
        "url": os.getenv("GTFS_BOSTON_URL", "https://cdn.mbta.com/realtime/VehiclePositions.pb"),
        "ttl": 30,
    },
}

_CACHE: dict[str, tuple[float, dict]] = {}


@router.get("/")
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
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        vp = v.vehicle
        if vp is None:
            continue
        lat = vp.latitude if vp.latitude != 0.0 else None
        lon = vp.longitude if vp.longitude != 0.0 else None
        if lat is None or lon is None:
            continue
        vehicles.append({
            "id": entity.id,
            "route_id": v.trip.route_id if v.trip else None,
            "trip_id": v.trip.trip_id if v.trip else None,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "bearing": round(vp.bearing, 1) if vp.bearing else None,
            "speed": round(vp.speed, 1) if vp.speed else None,
            "timestamp": v.timestamp if v.timestamp else None,
            "label": v.vehicle.label if v.vehicle else None,
            "license_plate": v.vehicle.license_plate if v.vehicle else None,
        })

    result = {
        "city": city,
        "count": len(vehicles),
        "vehicles": vehicles,
        "feed_timestamp": feed.header.timestamp if feed.header else None,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    _CACHE[cache_key] = (time.time(), result)
    return result
