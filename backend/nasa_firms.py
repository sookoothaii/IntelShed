"""NASA FIRMS — Fire Information for Resource Management System.
Near real-time wildfire / thermal anomaly detection.
Requires free MAP_KEY from https://firms.modaps.eosdis.nasa.gov/api/map_key
Falls back to NASA EONET open wildfire events when MAP_KEY is missing.
"""
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

import feed_registry

router = APIRouter(prefix="/api", tags=["firms"])

FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()

_FIRMS_SOURCES = {
    "modis": "MODIS_NRT",
    "viirs_noaa20": "VIIRS_NOAA20_NRT",
    "viirs_snpp": "VIIRS_SNPP_NRT",
}

_firms_cache: dict = {}
_FIRMS_TTL = 600  # 10 minutes


def _firms_url(source: str) -> str | None:
    api_source = _FIRMS_SOURCES.get(source)
    if not FIRMS_MAP_KEY or not api_source:
        return None
    return f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{FIRMS_MAP_KEY}/{api_source}/world/1"


async def _fetch_firms(source: str):
    """Fetch FIRMS CSV and parse to list of fire records."""
    url = _firms_url(source)
    if not url:
        return [{"error": "FIRMS_MAP_KEY not set — get a free key at firms.modaps.eosdis.nasa.gov/api/map_key"}]
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            text = r.text
    except Exception as e:
        return [{"error": str(e)}]

    lines = text.strip().split("\n")
    if len(lines) < 2:
        return []

    headers = lines[0].split(",")
    records = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) < len(headers):
            continue
        row = dict(zip(headers, parts))
        try:
            lat = float(row.get("latitude", 0))
            lon = float(row.get("longitude", 0))
            conf = int(row.get("confidence", 0))
            bright = float(row.get("brightness", 0))
            records.append({
                "lat": lat,
                "lon": lon,
                "brightness": bright,
                "confidence": conf,
                "confidence_label": "high" if conf >= 80 else "medium" if conf >= 50 else "low",
                "scan": float(row.get("scan", 0)),
                "track": float(row.get("track", 0)),
                "acq_date": row.get("acq_date"),
                "acq_time": row.get("acq_time"),
                "satellite": row.get("satellite"),
                "instrument": row.get("instrument"),
                "frp": float(row.get("frp", 0)) if row.get("frp") else 0,
            })
        except (ValueError, TypeError):
            continue

    records.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return records[:500]


async def _eonet_wildfire_fallback() -> list[dict]:
    """Open NASA EONET wildfire events when FIRMS is unavailable."""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200"
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return []

    fires = []
    for ev in data.get("events", []):
        cat_ids = [str(c.get("id", "")).lower() for c in ev.get("categories", [])]
        title = (ev.get("title") or "").lower()
        if not any("wildfire" in c or "fire" in c for c in cat_ids) and "fire" not in title:
            continue
        geo = ev.get("geometry", [])
        if not geo:
            continue
        last = geo[-1]
        coords = last.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        fires.append({
            "lat": float(coords[1]),
            "lon": float(coords[0]),
            "brightness": 0,
            "confidence": 65,
            "confidence_label": "inferred",
            "scan": 0,
            "track": 0,
            "acq_date": (last.get("date") or "")[:10],
            "acq_time": "",
            "satellite": "EONET",
            "instrument": "EONET",
            "frp": 0,
            "source": "eonet",
        })
    return fires[:300]


@router.get("/wildfires")
async def get_wildfires():
    """Global thermal anomalies / wildfires from NASA FIRMS (+ EONET fallback). Cached 10 min."""
    now = datetime.now(timezone.utc).timestamp()
    cache_key = "firms_v2"
    cached = _firms_cache.get(cache_key)
    if cached and (now - cached["ts"]) < _FIRMS_TTL:
        return cached["data"]

    all_fires = []
    errors = []
    # One VIIRS world query is enough for the globe (~30k rows max); three sources block the API for minutes.
    sources = ["viirs_snpp"] if FIRMS_MAP_KEY else []
    if FIRMS_MAP_KEY:
        for src in sources:
            try:
                fires = await _fetch_firms(src)
                if fires and "error" in fires[0]:
                    errors.append({src: fires[0]["error"]})
                else:
                    for f in fires:
                        f["source"] = src
                    all_fires.extend(fires)
            except Exception as e:
                errors.append({src: str(e)})
    else:
        errors.append({"firms": "FIRMS_MAP_KEY not set — using EONET wildfire events"})

    source_note = None
    if not all_fires:
        all_fires = await _eonet_wildfire_fallback()
        if all_fires:
            source_note = "eonet_fallback"

    seen = set()
    unique = []
    for f in all_fires:
        key = (round(f["lat"], 2), round(f["lon"], 2), f.get("acq_date"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    unique.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    result = {
        "count": len(unique),
        "updated": datetime.now(timezone.utc).isoformat(),
        "fires": unique[:300],
        "errors": errors if errors else None,
        "source": source_note or ("firms" if FIRMS_MAP_KEY and unique else None),
        "spatial_resolution": "1 day VIIRS world" if FIRMS_MAP_KEY else "EONET event centroids",
        "data_quality": "eonet_inferred" if source_note == "eonet_fallback" else "firms_thermal",
    }

    _firms_cache[cache_key] = {"ts": now, "data": result}
    feed_registry.write("wildfires", result)
    return result
