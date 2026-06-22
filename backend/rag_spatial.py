"""Spatial helpers for RAG — geohash meta + bbox pre-filter (Track R1.1)."""

from __future__ import annotations

import os
from typing import Any

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def spatial_enabled() -> bool:
    return os.getenv("RAG_SPATIAL", "0").strip().lower() in ("1", "true", "yes")


def operator_search_bbox() -> list[float] | None:
    """Operator region bbox [west, south, east, north] or None."""
    try:
        from intel_subgraph import operator_bbox

        return operator_bbox()
    except Exception:
        return None


def encode_geohash(lat: float, lon: float, precision: int = 6) -> str:
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash: list[str] = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True
    while len(geohash) < precision:
        if even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if lon > mid:
                ch |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if lat > mid:
                ch |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(_BASE32[ch])
            bit = 0
            ch = 0
    return "".join(geohash)


def point_in_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    west, south, east, north = bbox
    return south <= float(lat) <= north and west <= float(lon) <= east


def extract_coords(meta: dict[str, Any] | None) -> tuple[float, float] | None:
    if not meta:
        return None
    lat = meta.get("lat")
    lon = meta.get("lon")
    if lat is None:
        lat = meta.get("latitude")
    if lon is None:
        lon = meta.get("longitude")
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            pass
    bbox = meta.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        try:
            west, south, east, north = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            return (south + north) / 2.0, (west + east) / 2.0
        except (TypeError, ValueError):
            pass
    cell_id = meta.get("cell_id")
    if cell_id and "," in str(cell_id):
        try:
            lat_s, lon_s = str(cell_id).split(",", 1)
            return float(lat_s), float(lon_s)
        except (TypeError, ValueError):
            pass
    return None


def enrich_meta_spatial(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Add lat, lon, geohash to chunk meta when coordinates are known."""
    out = dict(meta or {})
    coords = extract_coords(out)
    if coords is None:
        return out
    lat, lon = coords
    out["lat"] = round(lat, 5)
    out["lon"] = round(lon, 5)
    precision = int(os.getenv("RAG_GEOHASH_PRECISION", "6"))
    out["geohash"] = encode_geohash(lat, lon, max(4, min(precision, 8)))
    return out


def meta_passes_bbox(meta: dict[str, Any] | None, bbox: list[float] | None) -> bool:
    """Chunks without coords pass through (briefings, global text)."""
    if not bbox:
        return True
    coords = extract_coords(meta or {})
    if coords is None:
        return True
    return point_in_bbox(coords[0], coords[1], bbox)


def spatial_sql_clause(bbox: list[float] | None) -> tuple[str, list[Any]]:
    """SQL fragment: geolocated rows must fall in bbox; others always included."""
    if not bbox:
        return "", []
    west, south, east, north = bbox
    clause = """
        AND (
            json_extract(c.meta_json, '$.lat') IS NULL
            OR (
                CAST(json_extract(c.meta_json, '$.lat') AS REAL) BETWEEN ? AND ?
                AND CAST(json_extract(c.meta_json, '$.lon') AS REAL) BETWEEN ? AND ?
            )
        )
    """
    return clause, [south, north, west, east]


def apply_spatial_postfilter(
    hits: list[dict],
    bbox: list[float] | None,
    *,
    min_keep: int = 3,
) -> list[dict]:
    """Post-filter ranked hits; fail-open if too few remain."""
    if not bbox or not hits:
        return hits
    filtered = [h for h in hits if meta_passes_bbox(h.get("meta"), bbox)]
    if len(filtered) >= min_keep:
        return filtered
    return hits
