"""Traffic camera feeds — regional (ASEAN) + global crowdsourced layers.

Sources:
- data.gov.sg v1 Traffic Images (Singapore, no key, lat/lon + image URLs)
- OpenTrafficCamMap USA.json (global, no key, nested state/county schema)
- LTA DataMall Traffic-Imagesv2 (optional LTA_DATAMALL_ACCOUNT_KEY — future enrich)

Fail-soft: stale cache or partial merge on upstream errors.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

import feed_registry

router = APIRouter(prefix="/api/traffic", tags=["traffic"])

_UA = {"User-Agent": "WorldBase/1.0 (private research; traffic cams)"}

SGP_API = "https://api.data.gov.sg/v1/transport/traffic-images"
OTCM_USA = (
    "https://raw.githubusercontent.com/AidanWelch/OpenTrafficCamMap/master/cameras/USA.json"
)
LTA_API = "https://datamall2.mytransport.sg/ltaodataservice/Traffic-Imagesv2"

_CACHE: dict[str, tuple[float, dict]] = {}
REGIONAL_TTL = 120.0
GLOBAL_TTL = 3600.0
MERGED_TTL = 90.0

# Thailand center + ASEAN regional bias for default bbox
_OPERATOR_LAT = float(os.getenv("WORLDBASE_OPERATOR_LAT", "9.55"))
_OPERATOR_LON = float(os.getenv("WORLDBASE_OPERATOR_LON", "100.05"))

_ASEAN_BBOX = (92.0, -8.0, 141.0, 28.0)  # west, south, east, north


def _cache_get(key: str, ttl: float) -> dict | None:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key: str, val: dict) -> None:
    _CACHE[key] = (time.time(), val)


def _cache_stale(key: str) -> dict | None:
    hit = _CACHE.get(key)
    return hit[1] if hit else None


def _cam_id(source: str, *parts: str) -> str:
    raw = ":".join([source, *parts])
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


def _normalize_cam(
    *,
    source: str,
    cam_key: str,
    lat: float,
    lon: float,
    name: str,
    country: str,
    image_url: str | None = None,
    stream_url: str | None = None,
    fmt: str = "IMAGE_STREAM",
    direction: str | None = None,
    geo_coverage: str = "regional",
    refresh_ms: int | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    return {
        "id": _cam_id(source, cam_key),
        "source": source,
        "source_type": "traffic_cam",
        "name": name[:160],
        "lat": lat,
        "lon": lon,
        "country": country,
        "direction": direction,
        "image_url": image_url,
        "stream_url": stream_url or image_url,
        "format": fmt,
        "geo_coverage": geo_coverage,
        "refresh_ms": refresh_ms,
        "license": "Singapore Open Data Licence" if source == "data.gov.sg" else "crowdsourced",
        "usage_policy": "private_research",
        **(extra or {}),
    }


async def _fetch_singapore() -> tuple[list[dict], str | None]:
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get(SGP_API)
            r.raise_for_status()
            body = r.json()
    except Exception as e:
        return [], str(e)

    cams: list[dict] = []
    for batch in body.get("items") or []:
        for row in batch.get("cameras") or []:
            loc = row.get("location") or {}
            try:
                lat = float(loc.get("latitude"))
                lon = float(loc.get("longitude"))
            except (TypeError, ValueError):
                continue
            cid = str(row.get("camera_id") or "")
            img = row.get("image") or ""
            cams.append(
                _normalize_cam(
                    source="data.gov.sg",
                    cam_key=cid,
                    lat=lat,
                    lon=lon,
                    name=f"SG Expressway cam {cid}",
                    country="SGP",
                    image_url=img,
                    geo_coverage="regional",
                    refresh_ms=120_000,
                )
            )
    return cams, None


def _parse_otcm_usa(raw: dict, *, limit: int, bbox: tuple[float, float, float, float] | None) -> list[dict]:
    out: list[dict] = []
    for state, counties in (raw or {}).items():
        if not isinstance(counties, dict):
            continue
        for county, rows in counties.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if len(out) >= limit:
                    return out
                try:
                    lat = float(row.get("latitude"))
                    lon = float(row.get("longitude"))
                except (TypeError, ValueError):
                    continue
                if bbox and not _in_bbox(lat, lon, bbox):
                    continue
                desc = (row.get("description") or "Traffic camera")[:160]
                url = row.get("url") or ""
                fmt = row.get("format") or "IMAGE_STREAM"
                out.append(
                    _normalize_cam(
                        source="opentrafficcammap",
                        cam_key=f"{state}:{county}:{desc}:{lat}:{lon}",
                        lat=lat,
                        lon=lon,
                        name=desc,
                        country="USA",
                        stream_url=url,
                        fmt=fmt,
                        direction=row.get("direction"),
                        geo_coverage="global",
                        refresh_ms=int(row.get("updateRate") or 0) or None,
                        extra={"state": state, "county": county},
                    )
                )
    return out


async def _fetch_usa(*, limit: int = 800, bbox: tuple[float, float, float, float] | None = None) -> tuple[list[dict], str | None]:
    try:
        async with httpx.AsyncClient(timeout=60.0, headers=_UA) as client:
            r = await client.get(OTCM_USA)
            r.raise_for_status()
            raw = r.json()
    except Exception as e:
        return [], str(e)
    return _parse_otcm_usa(raw, limit=limit, bbox=bbox), None


async def _fetch_lta_optional() -> tuple[list[dict], str | None]:
    key = os.getenv("LTA_DATAMALL_ACCOUNT_KEY", "").strip()
    if not key:
        return [], None
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
            r = await client.get(
                LTA_API,
                headers={"AccountKey": key, "accept": "application/json"},
            )
            r.raise_for_status()
            body = r.json()
    except Exception as e:
        return [], str(e)

    # LTA v2 lacks lat/lon in response — skip globe placement unless coords known
    cams: list[dict] = []
    for row in (body.get("value") or body.get("TrafficImages") or [])[:80]:
        cid = str(row.get("CameraID") or row.get("CameraId") or "")
        link = row.get("ImageLink") or row.get("ImageURL") or ""
        if not cid or not link:
            continue
        # Approximate Singapore island centroid for map pin until Annex G coords bundled
        cams.append(
            _normalize_cam(
                source="lta_datamall",
                cam_key=cid,
                lat=1.3521,
                lon=103.8198,
                name=f"LTA cam {cid}",
                country="SGP",
                image_url=link,
                geo_coverage="regional",
                refresh_ms=300_000,
                extra={"approximate_geo": True},
            )
        )
    return cams, None


async def fetch_scope(
    scope: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 800,
    force: bool = False,
) -> dict[str, Any]:
    """Load cameras for regional | global | all."""
    scope = (scope or "regional").strip().lower()
    cache_key = f"traffic_cams:{scope}"
    ttl = MERGED_TTL if scope == "all" else (REGIONAL_TTL if scope == "regional" else GLOBAL_TTL)
    if not force:
        cached = _cache_get(cache_key, ttl)
        if cached is not None:
            return cached

    errors: list[str] = []
    sources_used: list[str] = []
    cams: list[dict] = []

    if scope in ("regional", "all"):
        sg, err = await _fetch_singapore()
        if sg:
            cams.extend(sg)
            sources_used.append("data.gov.sg")
        elif err:
            errors.append(f"data.gov.sg: {err}")
        lta, lta_err = await _fetch_lta_optional()
        if lta:
            cams.extend(lta)
            sources_used.append("lta_datamall")
        elif lta_err:
            errors.append(f"lta_datamall: {lta_err}")

    if scope in ("global", "all"):
        usa, err = await _fetch_usa(limit=limit, bbox=bbox)
        if usa:
            cams.extend(usa)
            sources_used.append("opentrafficcammap")
        elif err:
            errors.append(f"opentrafficcammap: {err}")

    # Deduplicate by id
    seen: set[str] = set()
    unique: list[dict] = []
    for c in cams:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        unique.append(c)

    stale = _cache_stale(cache_key)
    if not unique and stale:
        stale = {**stale, "stale": True, "error": "; ".join(errors) if errors else "upstream empty"}
        return stale

    out = {
        "count": len(unique),
        "scope": scope,
        "source": "+".join(sources_used) if sources_used else "none",
        "sources": sources_used,
        "cameras": unique,
        "updated": datetime.now(timezone.utc).isoformat(),
        "usage_policy": "private_research",
        "operator": {"lat": _OPERATOR_LAT, "lon": _OPERATOR_LON, "region": os.getenv("WORLDBASE_OPERATOR_REGION", "thailand")},
        "hint": (
            "Thailand traffic cams (iTIC) require archive access — set ITIC_API_TOKEN when available."
            if scope == "regional"
            else None
        ),
        "error": "; ".join(errors) if errors and not unique else None,
    }
    _cache_set(cache_key, out)
    try:
        feed_registry.write_auto(f"traffic_cams:{scope}", out)
    except Exception:
        pass
    return out


async def warm_traffic_cams(*, force: bool = True) -> None:
    """Refresh all traffic cam scopes (fixes stale feed_cache after long idle)."""
    await asyncio.gather(
        *[fetch_scope(scope, force=force) for scope in ("regional", "global", "all")],
        return_exceptions=True,
    )


@router.get("/cams")
async def traffic_cams(
    scope: str = Query("regional", description="regional (ASEAN/SG) | global (USA OTCM) | all"),
    limit: int = Query(800, ge=1, le=5000),
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
):
    """Traffic cameras with normalized geo + provenance metadata."""
    bbox = None
    if all(v is not None for v in (west, south, east, north)):
        bbox = (west, south, east, north)
    return await fetch_scope(scope, bbox=bbox, limit=limit)


@router.get("/cams/status")
async def traffic_cams_status():
    """Quick source availability without full camera payload."""
    from credentials.registry import is_configured

    return {
        "sources": {
            "data.gov.sg": {"configured": True, "tier": "free", "geo_coverage": "regional"},
            "opentrafficcammap": {"configured": True, "tier": "free", "geo_coverage": "global"},
            "lta_datamall": {"configured": is_configured("lta_datamall"), "tier": "optional"},
            "itic_thailand": {"configured": is_configured("itic_thailand"), "tier": "optional", "geo_coverage": "local"},
        },
        "scopes": ["regional", "global", "all"],
        "operator_region": os.getenv("WORLDBASE_OPERATOR_REGION", "thailand"),
    }


async def _find_camera(cam_id: str) -> dict[str, Any] | None:
    for scope in ("regional", "all", "global"):
        payload = await fetch_scope(scope)
        for cam in payload.get("cameras") or []:
            if cam.get("id") == cam_id:
                return cam
    return None


@router.get("/cams/{cam_id}/frame")
async def traffic_cam_frame(cam_id: str):
    """Proxy latest camera JPEG (avoids browser hotlink/CORS issues)."""
    await fetch_scope("regional", force=True)
    cam = await _find_camera(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    url = cam.get("image_url") or cam.get("stream_url")
    if not url:
        raise HTTPException(status_code=404, detail="No image URL")
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=_UA, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            ctype = r.headers.get("content-type") or "image/jpeg"
            from fastapi.responses import Response
            return Response(content=r.content, media_type=ctype)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:120]) from e


@router.get("/cams/{cam_id}")
async def traffic_cam_detail(cam_id: str, refresh: bool = Query(False)):
    """Single traffic camera with fresh image URL (refreshes regional feed when refresh=1)."""
    if refresh:
        await fetch_scope("regional", force=True)
        if cam_id.startswith("opentrafficcammap") or len(cam_id) == 12:
            await fetch_scope("global", force=True)
    cam = await _find_camera(cam_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {
        "camera": cam,
        "updated": datetime.now(timezone.utc).isoformat(),
        "entity_id": f"traffic_cam:{cam_id}",
    }
