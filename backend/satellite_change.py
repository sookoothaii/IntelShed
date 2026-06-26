"""WorldBase K4 — Satellite Imagery Change Detection.

Windowed read of Sentinel-2 Cloud-Optimized GeoTIFFs for AOI change detection.
Computes NDVI or NDWI differences between two cloud-free epochs and returns
GeoJSON anomaly polygons with pixel count and confidence.

Uses public EarthSearch STAC API (no API key) and GDAL/rasterio wheels.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/satellite", tags=["satellite"])

# Lazy import rasterio so the backend can still start if the wheel is missing.
try:
    import rasterio
    from rasterio import warp
    from rasterio.enums import Resampling
    from rasterio.features import shapes as rasterio_shapes
    from rasterio.mask import mask as rasterio_mask
    from rasterio.transform import Affine

    _RASTERIO_AVAILABLE = True
    _RASTERIO_IMPORT_ERROR: str | None = None
except Exception as _exc:  # pragma: no cover
    rasterio = None  # type: ignore[assignment]
    warp = None  # type: ignore[assignment]
    Resampling = None  # type: ignore[assignment]
    rasterio_shapes = None  # type: ignore[assignment]
    rasterio_mask = None  # type: ignore[assignment]
    Affine = None  # type: ignore[assignment]
    _RASTERIO_AVAILABLE = False
    _RASTERIO_IMPORT_ERROR = str(_exc)

_ENABLED = os.getenv("WORLDBASE_SATELLITE_CHANGE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_STAC_URL = os.getenv(
    "STAC_API_URL", "https://earth-search.aws.element84.com/v1"
).rstrip("/")
_UA = {"User-Agent": "WorldBase/1.0 (research dashboard; +https://github.com/local)"}

# AOI presets — kept in sync with stac_bridge.py REGION_PRESETS.
_REGION_PRESETS: dict[str, list[float]] = {
    "thailand": [97.3, 5.6, 105.65, 20.46],
    "bangkok": [100.30, 13.50, 100.95, 14.05],
    "phuket": [98.10, 7.55, 98.65, 8.20],
    "mekong-delta": [103.5, 9.5, 108.5, 13.5],
    "asean": [92.0, -11.0, 141.0, 28.0],
    "germany": [5.86, 47.27, 15.04, 55.07],
    "rhein": [6.0, 49.0, 9.0, 52.2],
}

# Result cache: heavy COG reads should not be repeated on every UI click.
_RESULT_CACHE: dict[str, tuple[float, dict]] = {}
_RESULT_CACHE_TTL = 3600.0

# GDAL / vsicurl tuning for public S3 COGs.
_RASTERIO_ENV = {
    "AWS_NO_SIGN_REQUEST": "YES",
    "AWS_REGION": "us-west-2",
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "50000000",
}

# Band asset mapping for Sentinel-2 L2A on EarthSearch.
_INDEX_BANDS: dict[str, dict[str, tuple[str, ...]]] = {
    "ndvi": {"a": ("red", "B04"), "b": ("nir", "B08")},
    "ndwi": {"a": ("green", "B03"), "b": ("nir", "B08")},
}


def _resolve_bbox(bbox: str | None, region: str | None) -> list[float]:
    if region:
        preset = _REGION_PRESETS.get(region.lower())
        if not preset:
            raise HTTPException(
                400,
                f"unknown region '{region}' — known: {sorted(_REGION_PRESETS)}",
            )
        return list(preset)
    if not bbox:
        raise HTTPException(
            400, "supply bbox=minLon,minLat,maxLon,maxLat or region=<preset>"
        )
    parts = [p.strip() for p in bbox.split(",") if p.strip()]
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be 4 comma-separated floats")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise HTTPException(400, f"bbox must be floats: {exc}") from exc
    if not (
        -180 <= nums[0] <= 180
        and -90 <= nums[1] <= 90
        and -180 <= nums[2] <= 180
        and -90 <= nums[3] <= 90
    ):
        raise HTTPException(400, "bbox out of range")
    return nums


def _parse_iso_date(value: str | None, default: datetime) -> datetime:
    if not value:
        return default
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"invalid ISO date '{value}': {exc}") from exc


def _utm_epsg(lon: float, lat: float) -> str:
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return f"EPSG:{epsg}"


def _cache_key(params: dict[str, Any]) -> str:
    payload = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _href_for_band(item: dict, band_keys: tuple[str, ...]) -> str | None:
    assets = (item.get("assets") or {}) if isinstance(item, dict) else {}
    for key in band_keys:
        asset = assets.get(key)
        if asset and asset.get("href"):
            return asset["href"]
    # Fall back to the slim item keys produced by stac_bridge._slim_item.
    for key in band_keys:
        href = item.get(f"cog_{key}")
        if href:
            return href
    return None


async def _stac_search(
    bbox: list[float],
    collection: str,
    start: datetime,
    end: datetime,
    cloud_cover_max: int,
    limit: int = 20,
) -> list[dict]:
    """Search EarthSearch for items covering bbox in a date range."""
    start_s = start.isoformat().replace("+00:00", "Z")
    end_s = end.isoformat().replace("+00:00", "Z")
    body = {
        "collections": [collection],
        "bbox": bbox,
        "datetime": f"{start_s}/{end_s}",
        "limit": limit,
        "query": {"eo:cloud_cover": {"lt": cloud_cover_max}},
        "sortby": [
            {"field": "properties.eo:cloud_cover", "direction": "asc"},
            {"field": "properties.datetime", "direction": "desc"},
        ],
    }
    url = f"{_STAC_URL}/search"
    async with httpx.AsyncClient(timeout=30.0, headers=_UA) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
    return data.get("features") or []


def _pick_best_scene(items: list[dict], target: datetime) -> dict | None:
    """Pick the cloud-free scene closest to the target date."""
    if not items:
        return None
    best = None
    best_score: float | None = None
    for it in items:
        dt_s = (it.get("properties") or {}).get("datetime")
        if not dt_s:
            continue
        try:
            dt = datetime.fromisoformat(dt_s.replace("Z", "+00:00"))
        except ValueError:
            continue
        cc = (it.get("properties") or {}).get("eo:cloud_cover") or 100
        age = abs((dt - target).total_seconds())
        # Cloud cover dominates (1 % ≈ 1 day of age).
        score = cc * 86400.0 + age
        if best_score is None or score < best_score:
            best_score = score
            best = it
    return best


def _read_band_aoi(
    href: str,
    dst_crs: str,
    dst_bounds: tuple[float, float, float, float],
    dst_res: float,
) -> tuple[np.ndarray, Affine]:
    """Read a single COG band, reprojected to the AOI in the target CRS."""
    if not href:
        raise ValueError("missing COG href")
    if rasterio is None:
        raise RuntimeError("rasterio not available")

    with rasterio.Env(**_RASTERIO_ENV):
        with rasterio.open(href) as src:
            # Transform AOI bounds into the source CRS for a tight window.
            src_bounds = warp.transform_bounds(dst_crs, src.crs, *dst_bounds)
            src_window = src.window(*src_bounds)
            src_array = src.read(1, window=src_window)
            src_transform = src.window_transform(src_window)

            dst_width = max(1, int((dst_bounds[2] - dst_bounds[0]) / dst_res))
            dst_height = max(1, int((dst_bounds[3] - dst_bounds[1]) / dst_res))
            dst_transform = Affine.translation(
                dst_bounds[0], dst_bounds[3]
            ) * Affine.scale(dst_res, -dst_res)
            dst_array = np.empty((dst_height, dst_width), dtype=np.float32)

            warp.reproject(
                src_array,
                dst_array,
                src_transform=src_transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
            )
            # Sentinel-2 L2A uses 0 as nodata/background in many COGs.
            dst_array[dst_array == 0] = np.nan
            return dst_array, dst_transform


def _compute_index(
    a: np.ndarray,
    b: np.ndarray,
) -> np.ndarray:
    """Compute (b - a) / (b + a) with safe masking."""
    with np.errstate(divide="ignore", invalid="ignore"):
        idx = (b - a) / (b + a)
    valid = np.isfinite(a) & np.isfinite(b) & ((a + b) > 0)
    idx[~valid] = np.nan
    return idx


def _confidence(mean_delta: float, pixel_count: int) -> float:
    """Simple heuristic: bigger magnitude and larger area → higher confidence."""
    magnitude = min(abs(mean_delta) / 0.5, 1.0)
    area = min(np.log1p(pixel_count) / np.log1p(100), 1.0)
    return float(magnitude * 0.6 + area * 0.4)


def _detect_changes(
    before_idx: np.ndarray,
    after_idx: np.ndarray,
    transform: Affine,
    dst_crs: str,
    threshold: float,
    min_area_px: int,
    before_id: str,
    after_id: str,
    index_name: str,
) -> dict:
    """Threshold the index difference and vectorize anomalies."""
    if rasterio is None or rasterio_shapes is None or rasterio_mask is None:
        raise RuntimeError("rasterio not available")

    diff = after_idx - before_idx
    valid = np.isfinite(diff)
    if not valid.any():
        return {
            "type": "FeatureCollection",
            "properties": {
                "before_id": before_id,
                "after_id": after_id,
                "index": index_name,
                "threshold": threshold,
                "feature_count": 0,
                "total_pixels": 0,
                "error": "no overlapping valid pixels",
            },
            "features": [],
        }

    features: list[dict] = []
    for cls, condition in (
        ("decrease", diff < -threshold),
        ("increase", diff > threshold),
    ):
        binary = condition.astype(np.uint8)
        if not binary.any():
            continue

        # Build one in-memory dataset for this class so rasterio_mask can sample.
        with rasterio.io.MemoryFile() as memfile:
            with memfile.open(
                driver="GTiff",
                height=diff.shape[0],
                width=diff.shape[1],
                count=1,
                dtype=diff.dtype,
                crs=dst_crs,
                transform=transform,
                nodata=np.nan,
            ) as ds:
                ds.write(diff, 1)
                for geom, val in rasterio_shapes(
                    binary,
                    mask=binary.astype(bool),
                    transform=transform,
                    connectivity=8,
                ):
                    if val == 0:
                        continue
                    geom_4326 = warp.transform_geom(
                        dst_crs, "EPSG:4326", geom, precision=6
                    )
                    try:
                        masked, _ = rasterio_mask(
                            ds,
                            [geom],
                            all_touched=True,
                            crop=True,
                            nodata=np.nan,
                        )
                    except Exception:
                        continue
                    values = masked[~np.isnan(masked)]
                    if values.size < min_area_px:
                        continue
                    mean_delta = float(np.mean(values))
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": geom_4326,
                            "properties": {
                                "class": cls,
                                "mean_delta": round(mean_delta, 4),
                                "max_delta": round(float(np.max(values)), 4),
                                "min_delta": round(float(np.min(values)), 4),
                                "pixel_count": int(values.size),
                                "confidence": round(
                                    _confidence(mean_delta, int(values.size)), 4
                                ),
                            },
                        }
                    )

    total_pixels = sum(f["properties"]["pixel_count"] for f in features)
    return {
        "type": "FeatureCollection",
        "properties": {
            "before_id": before_id,
            "after_id": after_id,
            "index": index_name,
            "threshold": threshold,
            "feature_count": len(features),
            "total_pixels": total_pixels,
        },
        "features": features,
    }


async def _search_best_scenes(
    bbox: list[float],
    before_target: datetime,
    after_target: datetime,
    collection: str,
    cloud_cover_max: int,
    window_days: int,
) -> tuple[dict, dict]:
    """Async STAC search: pick the best cloud-free scene for each epoch."""
    before_items = await _stac_search(
        bbox,
        collection,
        before_target - timedelta(days=window_days),
        before_target + timedelta(days=3),
        cloud_cover_max,
    )
    after_items = await _stac_search(
        bbox,
        collection,
        after_target - timedelta(days=3),
        after_target + timedelta(days=window_days),
        cloud_cover_max,
    )

    before_scene = _pick_best_scene(before_items, before_target)
    after_scene = _pick_best_scene(after_items, after_target)
    if not before_scene or not after_scene:
        missing = []
        if not before_scene:
            missing.append("before")
        if not after_scene:
            missing.append("after")
        raise HTTPException(
            503,
            f"could not find suitable cloud-free scenes for {', '.join(missing)} epoch",
        )
    return before_scene, after_scene


def _run_change_detection_sync(
    params: dict[str, Any], before_scene: dict, after_scene: dict
) -> dict:
    """Synchronous rasterio body of the change-detection pipeline (run in thread)."""
    bbox = params["bbox"]
    index_name = params["index"]
    threshold = params["threshold"]
    min_area_px = params["min_area_px"]
    resolution = params["resolution"]

    band_cfg = _INDEX_BANDS[index_name]
    before_a_href = _href_for_band(before_scene, band_cfg["a"])
    before_b_href = _href_for_band(before_scene, band_cfg["b"])
    after_a_href = _href_for_band(after_scene, band_cfg["a"])
    after_b_href = _href_for_band(after_scene, band_cfg["b"])
    if not all([before_a_href, before_b_href, after_a_href, after_b_href]):
        raise HTTPException(
            503,
            "scene assets missing required bands for " + index_name,
        )

    # Define a common target grid in UTM for the AOI.
    center_lon = (bbox[0] + bbox[2]) / 2.0
    center_lat = (bbox[1] + bbox[3]) / 2.0
    dst_crs = _utm_epsg(center_lon, center_lat)
    dst_bounds = warp.transform_bounds("EPSG:4326", dst_crs, *bbox)

    # Read all four bands into the common grid.
    before_a, _ = _read_band_aoi(before_a_href, dst_crs, dst_bounds, resolution)
    before_b, _ = _read_band_aoi(before_b_href, dst_crs, dst_bounds, resolution)
    after_a, _ = _read_band_aoi(after_a_href, dst_crs, dst_bounds, resolution)
    after_b, _ = _read_band_aoi(after_b_href, dst_crs, dst_bounds, resolution)

    before_idx = _compute_index(before_a, before_b)
    after_idx = _compute_index(after_a, after_b)

    before_id = before_scene.get("id", "unknown")
    after_id = after_scene.get("id", "unknown")
    transform = Affine.translation(dst_bounds[0], dst_bounds[3]) * Affine.scale(
        resolution, -resolution
    )

    result = _detect_changes(
        before_idx,
        after_idx,
        transform,
        dst_crs,
        threshold,
        min_area_px,
        before_id,
        after_id,
        index_name,
    )
    result["properties"]["before_scene"] = {
        "id": before_id,
        "datetime": (before_scene.get("properties") or {}).get("datetime"),
        "cloud_cover": (before_scene.get("properties") or {}).get("eo:cloud_cover"),
    }
    result["properties"]["after_scene"] = {
        "id": after_id,
        "datetime": (after_scene.get("properties") or {}).get("datetime"),
        "cloud_cover": (after_scene.get("properties") or {}).get("eo:cloud_cover"),
    }
    result["properties"]["bbox"] = bbox
    result["properties"]["crs"] = dst_crs
    result["properties"]["resolution"] = resolution
    return result


@router.get("/change")
async def satellite_change(
    bbox: str | None = None,
    region: str | None = None,
    before: str | None = Query(None, description="ISO date for the earlier epoch"),
    after: str | None = Query(None, description="ISO date for the later epoch"),
    index: str = Query("ndvi", description="Index to difference: ndvi or ndwi"),
    threshold: float = Query(
        0.2, ge=0.0, le=1.0, description="Minimum delta magnitude"
    ),
    cloud_cover_max: int = Query(25, ge=0, le=100, description="Max cloud cover %"),
    min_area_px: int = Query(10, ge=1, description="Minimum anomaly area in pixels"),
    resolution: int = Query(
        60, ge=10, le=500, description="Target pixel size in meters"
    ),
    collection: str = Query("sentinel-2-l2a", description="STAC collection id"),
    window_days: int = Query(
        30, ge=1, le=180, description="Search window around each epoch"
    ),
):
    """Detect spectral index changes between two Sentinel-2 epochs over an AOI.

    Returns a GeoJSON FeatureCollection of increase/decrease anomalies with
    pixel count, mean delta, and confidence. Public EarthSearch COGs are used;
    no API key required.
    """
    if not _ENABLED:
        raise HTTPException(
            503,
            "satellite change detection disabled (set WORLDBASE_SATELLITE_CHANGE=1)",
        )
    if not _RASTERIO_AVAILABLE:
        raise HTTPException(
            503,
            f"rasterio/GDAL not available: {_RASTERIO_IMPORT_ERROR}",
        )

    bbox_arr = _resolve_bbox(bbox, region)
    now = datetime.now(timezone.utc)
    before_target = _parse_iso_date(before, now - timedelta(days=30))
    after_target = _parse_iso_date(after, now)

    # Ensure before is earlier than after.
    if after_target <= before_target:
        before_target, after_target = after_target, before_target
        before_target = before_target - timedelta(days=30)

    if index not in _INDEX_BANDS:
        raise HTTPException(
            400,
            f"unknown index '{index}' — known: {list(_INDEX_BANDS)}",
        )

    params = {
        "bbox": bbox_arr,
        "before": before_target,
        "after": after_target,
        "index": index,
        "threshold": threshold,
        "cloud_cover_max": cloud_cover_max,
        "min_area_px": min_area_px,
        "resolution": resolution,
        "collection": collection,
        "window_days": window_days,
    }
    cache_key = _cache_key(params)
    cached = _RESULT_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _RESULT_CACHE_TTL:
        return cached[1]

    try:
        before_scene, after_scene = await _search_best_scenes(
            bbox_arr,
            before_target,
            after_target,
            collection,
            cloud_cover_max,
            window_days,
        )
        result = await asyncio.to_thread(
            _run_change_detection_sync, params, before_scene, after_scene
        )
    except HTTPException:
        raise
    except Exception as exc:
        # Fail-soft: never crash the backend because of a downstream COG/STAC issue.
        raise HTTPException(
            503,
            f"change detection failed: {exc}",
        ) from exc

    result["cached"] = False
    result["cached_at"] = datetime.now(timezone.utc).isoformat()
    _RESULT_CACHE[cache_key] = (time.time(), result)
    return result


@router.get("/health")
async def satellite_health():
    """Quick status check: is rasterio available and the feature enabled?"""
    return {
        "enabled": _ENABLED,
        "rasterio_available": _RASTERIO_AVAILABLE,
        "rasterio_error": _RASTERIO_IMPORT_ERROR,
        "collections": ["sentinel-2-l2a", "sentinel-2-c1-l2a"],
    }
