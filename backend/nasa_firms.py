"""NASA FIRMS — Fire Information for Resource Management System.
Near real-time wildfire / thermal anomaly detection.
No API key required for small area queries.
"""
import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["firms"])

# MODIS and VIIRS near-real-time feeds
_FIRMS_URLS = {
    "modis": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/MODIS_NRT/world/1",
    "viirs_noaa20": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/VIIRS_NOAA20_NRT/world/1",
    "viirs_snpp": "https://firms.modaps.eosdis.nasa.gov/api/area/csv/VIIRS_SNPP_NRT/world/1",
}

# Simple in-memory cache
_firms_cache: dict = {}
_FIRMS_TTL = 600  # 10 minutes


async def _fetch_firms(source: str):
    """Fetch FIRMS CSV and parse to list of fire records."""
    url = _FIRMS_URLS.get(source)
    if not url:
        return []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
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

    # Sort by confidence descending, limit to 500 hottest
    records.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return records[:500]


@router.get("/wildfires")
async def get_wildfires():
    """Global thermal anomalies / wildfires from NASA FIRMS.
    Combines MODIS + VIIRS. Cached 10 minutes. No key.
    """
    now = datetime.now(timezone.utc).timestamp()
    cache_key = "firms_all"
    cached = _firms_cache.get(cache_key)
    if cached and (now - cached["ts"]) < _FIRMS_TTL:
        return cached["data"]

    sources = ["modis", "viirs_noaa20", "viirs_snpp"]
    all_fires = []
    errors = []
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

    # Deduplicate by lat/lon rounded to 2 decimals + date
    seen = set()
    unique = []
    for f in all_fires:
        key = (round(f["lat"], 2), round(f["lon"], 2), f.get("acq_date"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # Sort by confidence
    unique.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    result = {
        "count": len(unique),
        "updated": datetime.now(timezone.utc).isoformat(),
        "fires": unique[:300],  # top 300
        "errors": errors if errors else None,
    }

    _firms_cache[cache_key] = {"ts": now, "data": result}
    return result
