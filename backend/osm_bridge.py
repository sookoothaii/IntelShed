"""OSM Critical Infrastructure POIs via Overpass API (no API key).

Fetches hospitals, power plants, airports, bridges, water treatment,
fire stations, and police stations for a bbox or region preset.
Free, key-less, community-run Overpass servers.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import APIRouter, Query

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/osm", tags=["osm"])

_UA = {"User-Agent": "WorldBase/1.0 (OSM Overpass research)"}
_TTL = float(os.getenv("WORLDBASE_OSM_CACHE_SEC", "7200"))
_FETCH_TIMEOUT = 30.0
_REFRESH_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector(
    "osm_infrastructure", ttl_sec=_TTL, default_source="osm/overpass"
)

_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Thailand + ASEAN capital city bboxes: (south, west, north, east)
_REGION_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "thailand": (5.0, 97.0, 21.0, 106.0),
    "bangkok": (13.5, 100.0, 14.0, 100.7),
    "chiang_mai": (18.5, 98.8, 19.1, 99.3),
    "asean": (-10.0, 95.0, 28.0, 141.0),
}

# OSM tags for critical infrastructure
_INFRA_TAGS: dict[str, str] = {
    "hospital": "amenity=hospital",
    "power_plant": "power=plant",
    "airport": "aeroway=aerodrome",
    "bridge": "bridge=yes",
    "water_treatment": "man_made=water_works",
    "fire_station": "amenity=fire_station",
    "police": "amenity=police",
    "fuel": "amenity=fuel",
    "telecom": "man_made=communications_tower",
}


def _build_overpass_query(
    bbox: tuple[float, float, float, float], infra_types: list[str]
) -> str:
    s, w, n, e = bbox
    bbox_str = f"({s},{w},{n},{e})"
    parts: list[str] = []
    for infra_type in infra_types:
        tag = _INFRA_TAGS.get(infra_type)
        if not tag:
            continue
        key, val = tag.split("=", 1)
        parts.append(
            f"  node{bbox_str}[{key}={val}];\n"
            f"  way{bbox_str}[{key}={val}];\n"
            f"  relation{bbox_str}[{key}={val}];"
        )
    body = "\n".join(parts)
    return f"[out:json][timeout:25];\n(\n{body}\n);\nout center 500;"


def _parse_element(el: dict, infra_type: str) -> dict | None:
    tags = el.get("tags") or {}
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None:
        return None
    name = tags.get("name") or tags.get("operator") or infra_type.title()
    return {
        "type": infra_type,
        "name": name,
        "lat": float(lat),
        "lon": float(lon),
        "osm_id": el.get("id"),
        "osm_type": el.get("type"),
        "tags": tags,
    }


async def _fetch_overpass(
    client: httpx.AsyncClient, endpoint: str, query: str
) -> dict | None:
    try:
        r = await client.post(endpoint, data={"data": query})
        if r.status_code == 429 or r.status_code == 504:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


async def fetch_infrastructure(
    bbox: tuple[float, float, float, float] | None = None,
    region: str = "thailand",
    infra_types: list[str] | None = None,
) -> dict:
    """Fetch critical infrastructure POIs from Overpass."""
    if bbox is None:
        bbox = _REGION_BBOXES.get(
            region.lower().replace(" ", "_"), _REGION_BBOXES["thailand"]
        )
    if infra_types is None:
        infra_types = list(_INFRA_TAGS.keys())

    query = _build_overpass_query(bbox, infra_types)

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, headers=_UA) as client:
        # Try endpoints in order, fail-soft
        for endpoint in _OVERPASS_ENDPOINTS:
            data = await _fetch_overpass(client, endpoint, query)
            if data is not None:
                break
        else:
            return {
                "count": 0,
                "elements": [],
                "by_type": {},
                "source": "osm/overpass",
                "updated": utc_now_iso(),
                "error": "all Overpass endpoints unavailable",
            }

    elements = data.get("elements") or []
    pois: list[dict] = []
    for el in elements:
        for infra_type in infra_types:
            tag = _INFRA_TAGS.get(infra_type, "")
            key, val = tag.split("=", 1) if "=" in tag else ("", "")
            el_tags = el.get("tags") or {}
            if el_tags.get(key) == val:
                parsed = _parse_element(el, infra_type)
                if parsed:
                    pois.append(parsed)
                break

    by_type: dict[str, int] = {}
    for p in pois:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1

    return {
        "count": len(pois),
        "elements": pois,
        "by_type": by_type,
        "region": region,
        "bbox": list(bbox),
        "source": "osm/overpass",
        "updated": utc_now_iso(),
    }


def _wrap_infra_payload(
    raw: dict, *, stale: bool = False, error: str | None = None
) -> dict:
    return _CONNECTOR.build(
        FeedEnvelope(
            count=int(raw.get("count") or 0),
            stale=stale,
            error=error or raw.get("error"),
        ),
        persist=bool(raw.get("elements")) and not stale and not error,
        elements=raw.get("elements") or [],
        by_type=raw.get("by_type") or {},
        region=raw.get("region", "thailand"),
        bbox=raw.get("bbox") or [],
    )


async def get_infrastructure(
    *,
    refresh: bool = False,
    bbox: tuple[float, float, float, float] | None = None,
    region: str = "thailand",
    infra_types: list[str] | None = None,
) -> dict:
    subkey = f"{region}:{':'.join(sorted(infra_types or list(_INFRA_TAGS.keys())))}"
    if not refresh:
        hit = _CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    async with _REFRESH_LOCK:
        if not refresh:
            hit = _CONNECTOR.get_cached(subkey)
            if hit is not None:
                return hit

        stale_hit = _CONNECTOR.peek_memory(subkey)
        try:
            raw = await asyncio.wait_for(
                fetch_infrastructure(bbox, region, infra_types),
                timeout=_FETCH_TIMEOUT + 10,
            )
        except asyncio.TimeoutError:
            if stale_hit:
                return _wrap_infra_payload(
                    stale_hit,
                    stale=True,
                    error="upstream timeout — serving stale cache",
                )
            return _CONNECTOR.build(
                FeedEnvelope(count=0, error="upstream timeout"),
                persist=False,
                elements=[],
                by_type={},
                region=region,
            )

        if raw.get("elements"):
            return _wrap_infra_payload(raw)
        if stale_hit:
            return _wrap_infra_payload(stale_hit, stale=True)
        return _wrap_infra_payload(raw)


def gather_osm_digest() -> dict:
    """Synchronous digest for briefing integration (reads memory cache)."""
    cached = _CONNECTOR.peek_memory()
    if not cached:
        return {"enabled": False, "count": 0, "lines": []}
    by_type = cached.get("by_type") or {}
    if not by_type:
        return {"enabled": False, "count": 0, "lines": []}
    lines: list[str] = []
    for infra_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"{infra_type.replace('_', ' ').title()}: {count}")
    return {
        "enabled": True,
        "count": cached.get("count", 0),
        "lines": lines[:10],
        "by_type": by_type,
    }


@router.get("/infrastructure")
async def osm_infrastructure(
    refresh: bool = Query(False),
    region: str = Query("thailand", description="Region preset"),
    south: float | None = Query(None),
    west: float | None = Query(None),
    north: float | None = Query(None),
    east: float | None = Query(None),
    infra_types: str | None = Query(None, description="Comma-separated infra types"),
):
    """Critical infrastructure POIs from OSM Overpass API (free, no key)."""
    bbox = None
    if all(v is not None for v in (south, west, north, east)):
        bbox = (south, west, north, east)
    types_list = infra_types.split(",") if infra_types else None
    return await get_infrastructure(
        refresh=refresh, bbox=bbox, region=region, infra_types=types_list
    )
