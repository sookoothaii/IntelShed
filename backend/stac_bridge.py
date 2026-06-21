"""STAC / Sentinel-2 satellite imagery bridge — Element84 EarthSearch (no key).

Element84 hosts the Sentinel-2 L2A and Landsat-C2-L2 collections on AWS open
data, served via a public STAC API at ``https://earth-search.aws.element84.com``.
No API key, no quota — perfect for the WorldBase "no purchase" philosophy.

This bridge gives the dashboard:

* ``GET /api/stac/collections`` — known collections + curated region presets
* ``GET /api/stac/search`` — bbox + datetime window + cloud filter
* ``GET /api/stac/preview/{item_id}`` — sanitized COG asset metadata + WMS-ish URLs
* ``GET /api/stac/thumbnail`` — server-side proxy so the browser can load JPGs
  cross-origin without leaking referrers; ETag + 5 min cache headers

A TiTiler-compatible WMTS URL is emitted when ``TITILER_URL`` is configured so
users with a local TiTiler can switch to live NDVI/true-color tiles without
changing the frontend. Otherwise the static ``thumbnail`` (visual.tif overview
JPG) is good enough to confirm scenes exist over Thailand or Germany.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/stac", tags=["stac"])

_STAC_URL = os.getenv("STAC_API_URL", "https://earth-search.aws.element84.com/v1").rstrip("/")
_TITILER = os.getenv("TITILER_URL", "").rstrip("/")  # optional; e.g. http://127.0.0.1:8001
_UA = {"User-Agent": "WorldBase/1.0 (research dashboard; +https://github.com/local)"}

# Curated bounding boxes for the operator's main areas of interest.
# Lon-min, lat-min, lon-max, lat-max (GeoJSON bbox order).
REGION_PRESETS: dict[str, dict[str, Any]] = {
    "thailand": {
        "label": "Thailand (full country)",
        "bbox": [97.3, 5.6, 105.65, 20.46],
    },
    "bangkok": {
        "label": "Bangkok metro",
        "bbox": [100.30, 13.50, 100.95, 14.05],
    },
    "phuket": {
        "label": "Phuket / Andaman coast",
        "bbox": [98.10, 7.55, 98.65, 8.20],
    },
    "mekong-delta": {
        "label": "Mekong Delta (TH/LA/VN/KH)",
        "bbox": [103.5, 9.5, 108.5, 13.5],
    },
    "asean": {
        "label": "Southeast Asia (ASEAN)",
        "bbox": [92.0, -11.0, 141.0, 28.0],
    },
    "germany": {
        "label": "Germany (DACH region)",
        "bbox": [5.86, 47.27, 15.04, 55.07],
    },
    "rhein": {
        "label": "Rhein corridor (DE)",
        "bbox": [6.0, 49.0, 9.0, 52.2],
    },
}

# Cache STAC search results to keep upstream load low — Sentinel-2 revisits are
# 5 days anyway so a 5 min cache is generous for users panning around.
_SEARCH_CACHE: dict[str, tuple[float, dict]] = {}
_THUMB_CACHE: dict[str, tuple[float, bytes, str]] = {}
_SEARCH_TTL = 300.0
_THUMB_TTL = 600.0


def _bbox_param(bbox: str | None, region: str | None) -> list[float]:
    if region:
        preset = REGION_PRESETS.get(region.lower())
        if not preset:
            raise HTTPException(400, f"unknown region '{region}' — known: {sorted(REGION_PRESETS)}")
        return list(preset["bbox"])
    if not bbox:
        raise HTTPException(400, "supply bbox=minLon,minLat,maxLon,maxLat or region=<preset>")
    parts = [p.strip() for p in bbox.split(",") if p.strip()]
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be 4 comma-separated floats")
    try:
        nums = [float(p) for p in parts]
    except ValueError as e:
        raise HTTPException(400, f"bbox must be floats: {e}") from e
    if not (-180 <= nums[0] <= 180 and -90 <= nums[1] <= 90 and -180 <= nums[2] <= 180 and -90 <= nums[3] <= 90):
        raise HTTPException(400, "bbox out of range")
    return nums


def _slim_item(it: dict) -> dict:
    """Reduce a STAC item to the fields the frontend actually renders."""
    props = it.get("properties") or {}
    assets = it.get("assets") or {}
    thumb_keys = ("thumbnail", "preview", "rendered_preview", "visual")
    thumb = None
    for k in thumb_keys:
        a = assets.get(k)
        if a and a.get("href"):
            thumb = a["href"]
            break
    visual = assets.get("visual") or {}
    nir = assets.get("nir") or assets.get("B08") or {}
    red = assets.get("red") or assets.get("B04") or {}
    return {
        "id": it.get("id"),
        "collection": it.get("collection"),
        "datetime": props.get("datetime"),
        "cloud_cover": props.get("eo:cloud_cover"),
        "platform": props.get("platform"),
        "instrument": props.get("instruments"),
        "bbox": it.get("bbox"),
        "thumbnail": thumb,
        # Convenient hrefs for COG/TiTiler users
        "cog_visual": visual.get("href"),
        "cog_nir": nir.get("href"),
        "cog_red": red.get("href"),
        # Proxied preview (CORS-safe through our backend)
        "proxy_thumbnail": f"/api/stac/thumbnail?id={it.get('id')}" if thumb else None,
    }


def _attach_titiler(item: dict) -> dict:
    """If TiTiler is configured, attach signed tile URLs for true-color + NDVI."""
    if not _TITILER:
        return item
    visual = item.get("cog_visual")
    nir = item.get("cog_nir")
    red = item.get("cog_red")
    tiles: dict[str, str] = {}
    if visual:
        tiles["truecolor"] = (
            f"{_TITILER}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={visual}"
        )
    if nir and red:
        # NDVI expression — TiTiler 0.18+ syntax
        tiles["ndvi"] = (
            f"{_TITILER}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png"
            f"?url={nir}&url={red}&expression=(b1-b2)/(b1%2Bb2)"
            "&rescale=-1,1&colormap_name=rdylgn"
        )
    if tiles:
        item["titiler_tiles"] = tiles
    return item


@router.get("/collections")
def stac_collections():
    """Static catalog: known free collections + region presets."""
    return {
        "endpoint": _STAC_URL,
        "titiler_configured": bool(_TITILER),
        "collections": [
            {
                "id": "sentinel-2-l2a",
                "label": "Sentinel-2 L2A (10 m, 5-day revisit, surface reflectance)",
                "default_cloud_cover": 30,
            },
            {
                "id": "sentinel-2-c1-l2a",
                "label": "Sentinel-2 Collection-1 L2A (Element84 reprocessing)",
                "default_cloud_cover": 30,
            },
            {
                "id": "landsat-c2-l2",
                "label": "Landsat Collection 2 Level-2 (30 m)",
                "default_cloud_cover": 40,
            },
        ],
        "regions": [{"id": k, **v} for k, v in REGION_PRESETS.items()],
        "feed_snapshots": {
            "id": "worldbase-feeds",
            "collection_href": "/api/stac/feeds/collection",
            "items_href": "/api/stac/feeds/items",
        },
    }


@router.get("/search")
async def stac_search(
    bbox: str | None = None,
    region: str | None = None,
    collection: str = Query("sentinel-2-l2a"),
    days: int = Query(14, ge=1, le=180),
    cloud_cover_max: int = Query(30, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
):
    """Search STAC items in a bbox + recent datetime window."""
    bbox_arr = _bbox_param(bbox, region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    dt = f"{start.isoformat().replace('+00:00', 'Z')}/{end.isoformat().replace('+00:00', 'Z')}"

    cache_key = f"{collection}|{bbox_arr}|{days}|{cloud_cover_max}|{limit}"
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _SEARCH_TTL:
        return cached[1]

    body = {
        "collections": [collection],
        "bbox": bbox_arr,
        "datetime": dt,
        "limit": limit,
        "query": {"eo:cloud_cover": {"lt": cloud_cover_max}},
        "sortby": [{"field": "properties.datetime", "direction": "desc"}],
    }
    url = f"{_STAC_URL}/search"
    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_UA) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        # Fallback GET for STAC APIs that don't accept POST search
        return {
            "error": f"STAC search failed: {e}",
            "collection": collection,
            "bbox": bbox_arr,
            "datetime": dt,
            "endpoint": url,
            "items": [],
        }

    feats = data.get("features") or []
    items = [_attach_titiler(_slim_item(f)) for f in feats]

    payload = {
        "collection": collection,
        "bbox": bbox_arr,
        "region": region,
        "datetime": dt,
        "cloud_cover_max": cloud_cover_max,
        "count": len(items),
        "items": items,
        "titiler_configured": bool(_TITILER),
        "endpoint": _STAC_URL,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _SEARCH_CACHE[cache_key] = (time.time(), payload)
    return payload


@router.get("/item/{item_id}")
async def stac_item(item_id: str, collection: str = Query("sentinel-2-l2a")):
    """Resolve a single STAC item by id (within a collection)."""
    url = f"{_STAC_URL}/collections/{collection}/items/{item_id}"
    async with httpx.AsyncClient(timeout=30.0, headers=_UA) as client:
        r = await client.get(url)
        if r.status_code == 404:
            raise HTTPException(404, f"STAC item not found: {item_id}")
        r.raise_for_status()
        data = r.json()
    return _attach_titiler(_slim_item(data))


async def _fetch_thumbnail_bytes(url: str) -> tuple[bytes, str]:
    cached = _THUMB_CACHE.get(url)
    if cached and (time.time() - cached[0]) < _THUMB_TTL:
        return cached[1], cached[2]
    async with httpx.AsyncClient(timeout=20.0, headers=_UA, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
        blob = r.content
        if len(blob) > 8_000_000:
            raise HTTPException(413, "thumbnail too large")
    _THUMB_CACHE[url] = (time.time(), blob, ctype)
    # Prune cache aggressively (small set, no LRU library)
    if len(_THUMB_CACHE) > 200:
        for k in list(_THUMB_CACHE)[:50]:
            _THUMB_CACHE.pop(k, None)
    return blob, ctype


@router.get("/thumbnail")
async def stac_thumbnail(
    id: str = Query(..., description="STAC item id"),
    collection: str = Query("sentinel-2-l2a"),
):
    """CORS-safe proxy for STAC item thumbnail / preview image."""
    item = await stac_item(item_id=id, collection=collection)
    href = item.get("thumbnail")
    if not href:
        raise HTTPException(404, "no thumbnail asset on this item")
    blob, ctype = await _fetch_thumbnail_bytes(href)
    return Response(
        content=blob,
        media_type=ctype,
        headers={
            "Cache-Control": "public, max-age=600",
            "X-Source": "stac-proxy",
        },
    )


async def fetch_recent_thailand_items(limit: int = 6) -> list[dict]:
    """Used by RAG ingest + briefing to log latest cloud-free Sentinel-2 scenes."""
    try:
        out = await stac_search(
            bbox=None,
            region="thailand",
            collection="sentinel-2-l2a",
            days=14,
            cloud_cover_max=25,
            limit=limit,
        )
        return out.get("items") or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# STAC Items for live feed snapshots (connector registry + feed_cache)
# ---------------------------------------------------------------------------
_FEEDS_COLLECTION_ID = "worldbase-feeds"
_SELF = os.getenv("WORLDBASE_SELF", "http://127.0.0.1:8002").rstrip("/")
_OPERATOR_REGION = os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()
_GLOBAL_BBOX = [-180.0, -90.0, 180.0, 90.0]

# Briefing bucket tags → STAC region preset ids (operator-specific).
_REGION_TAG_PRESETS: dict[str, dict[str, str]] = {
    "thailand": {"local": "bangkok", "regional": "asean", "global": "global"},
    "germany": {"local": "rhein", "regional": "germany", "global": "global"},
}

# Keys inside feed_cache JSON payloads that may hold geolocated rows.
_GEO_LIST_KEYS = (
    "vessels", "events", "quakes", "volcanoes", "aircraft", "nodes",
    "cities", "items", "alerts", "features", "hotspots", "datasets",
)


def _union_bbox(bboxes: list[list[float]]) -> list[float]:
    return [
        min(b[0] for b in bboxes),
        min(b[1] for b in bboxes),
        max(b[2] for b in bboxes),
        max(b[3] for b in bboxes),
    ]


def _bbox_to_polygon(bbox: list[float]) -> dict[str, Any]:
    minx, miny, maxx, maxy = bbox
    return {
        "type": "Polygon",
        "coordinates": [[
            [minx, miny],
            [maxx, miny],
            [maxx, maxy],
            [minx, maxy],
            [minx, miny],
        ]],
    }


def _connector_bbox(spec) -> list[float] | None:
    """Map connector region tags to a STAC bbox (operator-aware)."""
    if spec.id == "maritime":
        try:
            from ais_bridge import maritime_operator_bbox

            mb = maritime_operator_bbox()
            if mb:
                return mb
        except Exception:
            pass

    tags = list(spec.region or ("global",))
    tags_lower = [t.lower() for t in tags]
    if tags_lower == ["global"]:
        return list(_GLOBAL_BBOX)

    presets = _REGION_TAG_PRESETS.get(_OPERATOR_REGION, _REGION_TAG_PRESETS["thailand"])
    bboxes: list[list[float]] = []
    for tag in tags:
        tag_l = tag.lower()
        if tag_l == "global":
            continue
        preset_id = presets.get(tag_l) or tag_l
        if preset_id == "global":
            continue
        preset = REGION_PRESETS.get(preset_id)
        if preset:
            bboxes.append(list(preset["bbox"]))
    if not bboxes:
        if "global" in tags_lower:
            return list(_GLOBAL_BBOX)
        return None
    if len(bboxes) == 1:
        return bboxes[0]
    return _union_bbox(bboxes)


def _extract_payload_centroid(payload: dict[str, Any] | None) -> tuple[float, float] | None:
    """Best-effort centroid from a cached feed JSON payload."""
    if not payload or not isinstance(payload, dict):
        return None
    lat = payload.get("lat")
    lon = payload.get("lon")
    if lat is not None and lon is not None:
        try:
            return float(lon), float(lat)
        except (TypeError, ValueError):
            pass
    lats: list[float] = []
    lons: list[float] = []
    for key in _GEO_LIST_KEYS:
        arr = payload.get(key)
        if not isinstance(arr, list):
            continue
        for item in arr[:80]:
            if not isinstance(item, dict):
                continue
            ilat = item.get("lat", item.get("latitude"))
            ilon = item.get("lon", item.get("longitude"))
            if ilat is None or ilon is None:
                continue
            try:
                lats.append(float(ilat))
                lons.append(float(ilon))
            except (TypeError, ValueError):
                continue
        if lats:
            break
    if not lats:
        return None
    return sum(lons) / len(lons), sum(lats) / len(lats)


def _feed_geometry_and_bbox(
    spec,
    cache_meta: dict[str, Any] | None,
    cache_payload: dict[str, Any] | None,
) -> tuple[list[float] | None, dict[str, Any] | None]:
    bbox = _connector_bbox(spec)
    centroid = _extract_payload_centroid(cache_payload)
    if centroid:
        lon, lat = centroid
        point = {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]}
        if bbox:
            return bbox, point
        return [lon, lat, lon, lat], point
    if bbox:
        return bbox, _bbox_to_polygon(bbox)
    return None, None


def _connector_registry_links(spec) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = [
        {
            "rel": "describedby",
            "href": f"{_SELF}/api/connectors?include_unlisted=0",
            "type": "application/json",
            "title": "Connector registry",
        },
    ]
    if spec.credential_ids:
        try:
            from credentials.registry import PROVIDERS

            for cid in spec.credential_ids:
                provider = PROVIDERS.get(cid)
                if provider and provider.docs_url:
                    links.append({
                        "rel": "license",
                        "href": provider.docs_url,
                        "type": "text/html",
                        "title": provider.name,
                    })
        except Exception:
            pass
    return links


def _feed_item_status(meta: dict[str, Any], ttl_sec: float, now: datetime) -> str:
    cached_at_raw = meta.get("cached_at")
    if not cached_at_raw:
        return "unknown"
    try:
        ts = datetime.fromisoformat(str(cached_at_raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_sec = (now - ts).total_seconds()
    except Exception:
        return "unknown"
    if meta.get("error"):
        return "error"
    if meta.get("stale"):
        return "stale"
    if age_sec < ttl_sec:
        return "fresh"
    if age_sec < ttl_sec * 2:
        return "aging"
    return "stale"


def _feed_stac_item(
    spec,
    cache_meta: dict[str, Any] | None,
    *,
    cache_payload: dict[str, Any] | None = None,
    now: datetime,
) -> dict[str, Any]:
    from connector_registry import feed_ttl_sec

    cache_key = spec.cache_key or spec.id
    endpoint = spec.endpoints[0] if spec.endpoints else f"/api/{spec.id}"
    meta = cache_meta or {}
    ttl = feed_ttl_sec(cache_key)
    status = _feed_item_status(meta, ttl, now) if cache_meta else "missing"
    cached_at = meta.get("cached_at") or now.isoformat()
    item_id = f"worldbase-{spec.id}"
    bbox, geometry = _feed_geometry_and_bbox(spec, cache_meta, cache_payload)
    item: dict[str, Any] = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": _FEEDS_COLLECTION_ID,
        "geometry": geometry,
        "properties": {
            "datetime": cached_at,
            "title": spec.name,
            "license": spec.license,
            "worldbase:connector_id": spec.id,
            "worldbase:cache_key": cache_key,
            "worldbase:category": spec.category,
            "worldbase:count": meta.get("count"),
            "worldbase:status": status,
            "worldbase:bridge": spec.bridge,
            "worldbase:source": meta.get("source"),
            "worldbase:region": list(spec.region),
            "worldbase:globe_layer": spec.globe_layer,
            "worldbase:endpoints": list(spec.endpoints),
            "worldbase:operator_region": _OPERATOR_REGION,
        },
        "links": [
            {"rel": "self", "href": f"{_SELF}/api/stac/feeds/items/{spec.id}", "type": "application/geo+json"},
            {"rel": "collection", "href": f"{_SELF}/api/stac/feeds/collection", "type": "application/json"},
            {"rel": "via", "href": f"{_SELF}{endpoint}", "type": "application/json", "title": "Live feed JSON"},
            *_connector_registry_links(spec),
        ],
        "assets": {
            "json": {
                "href": f"{_SELF}{endpoint}",
                "type": "application/json",
                "roles": ["data"],
                "title": spec.name,
            }
        },
    }
    if bbox:
        item["bbox"] = bbox
    return item


def build_feed_stac_items(*, connector_id: str | None = None) -> dict[str, Any]:
    """Build a STAC ItemCollection from connector catalog + feed_cache rows."""
    from connector_registry import CONNECTOR_CATALOG, _read_feed_cache_keys
    import feed_registry

    now = datetime.now(timezone.utc)
    cache = _read_feed_cache_keys()

    items: list[dict[str, Any]] = []
    for spec in sorted(CONNECTOR_CATALOG.values(), key=lambda s: s.id):
        if not spec.cache_key:
            continue
        if connector_id and spec.id != connector_id:
            continue
        cache_meta = cache.get(spec.cache_key)
        cache_payload = feed_registry.read_auto(spec.cache_key) if cache_meta else None
        items.append(
            _feed_stac_item(
                spec,
                cache_meta,
                cache_payload=cache_payload,
                now=now,
            )
        )

    return {
        "type": "FeatureCollection",
        "stac_version": "1.0.0",
        "collection": _FEEDS_COLLECTION_ID,
        "time": now.isoformat(),
        "numberMatched": len(items),
        "numberReturned": len(items),
        "features": items,
        "links": [
            {"rel": "self", "href": f"{_SELF}/api/stac/feeds/items", "type": "application/geo+json"},
            {"rel": "collection", "href": f"{_SELF}/api/stac/feeds/collection", "type": "application/json"},
        ],
    }


@router.get("/feeds/collection")
def stac_feeds_collection():
    """STAC Collection describing cached WorldBase connector feed snapshots."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": "Collection",
        "stac_version": "1.0.0",
        "id": _FEEDS_COLLECTION_ID,
        "title": "WorldBase live feed snapshots",
        "description": "Synthetic STAC items pointing at WorldBase connector JSON endpoints (feed_cache overlay). Phase 2: bbox/geometry from operator region + cache centroids; connector registry links.",
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[None, now]]},
        },
        "links": [
            {"rel": "self", "href": f"{_SELF}/api/stac/feeds/collection", "type": "application/json"},
            {"rel": "items", "href": f"{_SELF}/api/stac/feeds/items", "type": "application/geo+json"},
            {"rel": "root", "href": f"{_SELF}/api/stac/collections", "type": "application/json"},
        ],
    }


@router.get("/feeds/items")
def stac_feeds_items(connector_id: str | None = Query(None, description="Filter to one connector id")):
    """STAC ItemCollection for connector feeds that use feed_cache."""
    return build_feed_stac_items(connector_id=connector_id)


@router.get("/feeds/items/{connector_id}")
def stac_feeds_item(connector_id: str):
    """Single STAC Item for a connector feed snapshot."""
    from connector_registry import CONNECTOR_CATALOG

    spec = CONNECTOR_CATALOG.get(connector_id)
    if not spec or not spec.cache_key:
        raise HTTPException(404, f"connector '{connector_id}' has no feed cache key")
    payload = build_feed_stac_items(connector_id=connector_id)
    feats = payload.get("features") or []
    if not feats:
        raise HTTPException(404, f"no STAC item for connector '{connector_id}'")
    return feats[0]
