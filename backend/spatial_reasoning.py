"""Spatial Reasoning Layer — NL → Spatial Operation (P6).

Rule-based NL parser for geospatial queries. Zero VRAM, zero dependencies.
Parses natural language into spatial operations (within, near, intersects,
contains, adjacent, downstream, border, visible_from) and executes them
against FtM entities.

Inspired by SpaRAGraph (ACM 2026) — spatial relation composition matrix.

WORLDBASE_SPATIAL_REASONING=0 (default off, opt-in)
WORLDBASE_SPATIAL_NEAR_DEFAULT_KM=25
"""

from __future__ import annotations

import json
import math
import os
import re
from typing import Any

from config import get_config


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")
_GEO_FILE = os.path.join(_DATA_DIR, "geography.json")

_NEAR_DEFAULT_KM = get_config().spatial_near_default_km


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def spatial_reasoning_enabled() -> bool:
    return get_config().spatial_reasoning_enabled


# ---------------------------------------------------------------------------
# Static geography data
# ---------------------------------------------------------------------------

_GEO_CACHE: dict[str, Any] | None = None


def _load_geography() -> dict[str, Any]:
    global _GEO_CACHE
    if _GEO_CACHE is not None:
        return _GEO_CACHE
    try:
        with open(_GEO_FILE, "r", encoding="utf-8") as f:
            _GEO_CACHE = json.load(f)
    except Exception:
        _GEO_CACHE = {"cities": [], "rivers": [], "borders": [], "regions": []}
    return _GEO_CACHE


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class SpatialOperation:
    __slots__ = ("operation", "target", "params", "confidence")

    def __init__(
        self, operation: str, target: str, params: dict, confidence: float = 0.8
    ):
        self.operation = operation
        self.target = target
        self.params = params
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"SpatialOperation({self.operation}, {self.target}, {self.params})"


class SpatialQueryPlan:
    __slots__ = ("operations", "composition", "resolved_entities")

    def __init__(self, operations: list[SpatialOperation], composition: str = "AND"):
        self.operations = operations
        self.composition = composition
        self.resolved_entities: list[dict] = []

    def __repr__(self) -> str:
        return f"SpatialQueryPlan(ops={self.operations}, comp={self.composition})"


# ---------------------------------------------------------------------------
# NL Parser (rule-based, 0 VRAM)
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str, Any]] = [
    # downstream / upstream (specific — before near/within)
    (
        r"(downstream|upstream)(?:\s+from|\s+of)?\s+(.+?)(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "river_direction",
        lambda m: {"direction": m.group(1), "river": m.group(2).strip()},
    ),
    # border / boundary (specific — before near)
    (
        r"(?:along|at|near)\s+(?:the\s+)?((?:(?!\s+and\s+|\s+or\s+|\s+within\s+).)+?)\s+(?:border|boundary)(?:\s+with\s+(.+?))?(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "border",
        lambda m: {
            "region_a": m.group(1).strip(),
            "region_b": m.group(2).strip() if m.group(2) else None,
            "radius_km": 50.0,
        },
    ),
    # within / inside / in + radius (specific — before generic 'in')
    (
        r"(?:within|inside|in)\s+(?:about\s+)?(\d+(?:\.\d+)?)\s*(?:km|kilometers?)\s+(?:of|from)\s+(.+?)(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "within",
        lambda m: {"radius_km": float(m.group(1)), "target": m.group(2).strip()},
    ),
    # contains / inside region (specific keyword pattern)
    (
        r"(?:in|inside|within)\s+(?:the\s+)?(?:country|region|area|province|state)\s+(?:of\s+)?(.+?)(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "contains",
        lambda m: {"container": m.group(1).strip()},
    ),
    # visible from (specific — before near)
    (
        r"(?:visible from|can be seen from|line of sight from|overlooking)\s+(.+?)(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "visible_from",
        lambda m: {"observer": m.group(1).strip()},
    ),
    # near / around / close to (generic — last, catches remaining)
    (
        r"(?:near|around|close to|adjacent to|by)\s+(.+?)(?=\s+(?:and|or|that|which|with|\.|,|$)|$)",
        "near",
        lambda m: {"radius_km": _NEAR_DEFAULT_KM, "target": m.group(1).strip()},
    ),
]


def parse_spatial_query(query: str) -> SpatialQueryPlan:
    """Parse a natural language spatial query into a query plan.

    Handles multiple operations with AND/OR composition.
    Uses consumed-segment tracking to avoid overlapping matches.
    """
    query_lower = query.lower()
    operations: list[SpatialOperation] = []
    consumed: set[int] = set()

    for pattern, op_type, extractor in _PATTERNS:
        for match in re.finditer(pattern, query_lower, re.IGNORECASE):
            start, end = match.span()
            if any(i in consumed for i in range(start, end)):
                continue
            try:
                params = extractor(match)
                target = (
                    params.get("target")
                    or params.get("river")
                    or params.get("container")
                    or params.get("observer")
                    or ""
                )
                op = SpatialOperation(
                    operation=op_type,
                    target=target,
                    params=params,
                    confidence=0.8,
                )
                operations.append(op)
                for i in range(start, end):
                    consumed.add(i)
            except Exception:
                continue

    composition = (
        "AND" if " and " in query_lower else "OR" if " or " in query_lower else "AND"
    )
    return SpatialQueryPlan(operations=operations, composition=composition)


# ---------------------------------------------------------------------------
# Entity Resolution
# ---------------------------------------------------------------------------


def _bbox_from_point(lat: float, lon: float, radius_km: float) -> list[float]:
    """BBox [west, south, east, north] from center + radius."""
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(max(abs(lat), 0.01))))
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_entity(name: str) -> dict[str, Any] | None:
    """Resolve a place name to coordinates.

    Resolution order:
    1. Static geography (cities, rivers, borders, regions)
    2. FtM entity lookup (if available)
    3. None (not found)
    """
    name_lower = name.lower().strip()

    # 1. Static geography
    geo = _load_geography()

    for city in geo.get("cities", []):
        if name_lower == city["name"].lower():
            return {
                "name": city["name"],
                "lat": city["lat"],
                "lon": city["lon"],
                "type": "city",
                "bbox": _bbox_from_point(city["lat"], city["lon"], 10.0),
                "source": "static",
            }

    for river in geo.get("rivers", []):
        if name_lower == river["name"].lower():
            pts = river["points"]
            lat = sum(p[0] for p in pts) / len(pts)
            lon = sum(p[1] for p in pts) / len(pts)
            return {
                "name": river["name"],
                "lat": lat,
                "lon": lon,
                "type": "river",
                "points": pts,
                "bbox": _bbox_from_point(lat, lon, 50.0),
                "source": "static",
            }

    for border in geo.get("borders", []):
        if name_lower == border["name"].lower() or name_lower in border["name"].lower():
            poly = border["polygon"]
            lats = [p[1] for p in poly]
            lons = [p[0] for p in poly]
            return {
                "name": border["name"],
                "lat": sum(lats) / len(lats),
                "lon": sum(lons) / len(lons),
                "type": "border",
                "polygon": poly,
                "bbox": [min(lons), min(lats), max(lons), max(lats)],
                "source": "static",
            }

    for region in geo.get("regions", []):
        if name_lower == region["name"].lower():
            bbox = region["bbox"]
            return {
                "name": region["name"],
                "lat": (bbox[1] + bbox[3]) / 2,
                "lon": (bbox[0] + bbox[2]) / 2,
                "type": "region",
                "bbox": bbox,
                "source": "static",
            }

    # 2. FtM entity lookup (lazy import)
    try:
        import ftm_query

        entities = ftm_query.list_entities_recent(limit=500)
        for ent in entities:
            ent_name = (ent.get("caption") or "").lower()
            if name_lower in ent_name and ent.get("lat") and ent.get("lon"):
                return {
                    "name": ent.get("caption", name),
                    "lat": ent["lat"],
                    "lon": ent["lon"],
                    "type": ent.get("schema", "Place"),
                    "bbox": _bbox_from_point(ent["lat"], ent["lon"], 10.0),
                    "source": "ftm",
                }
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Spatial Executor
# ---------------------------------------------------------------------------


def _get_entities_in_bbox(bbox: list[float], limit: int = 200) -> list[dict]:
    """Get FtM entities within a bounding box."""
    try:
        import ftm_query
        from ftm_connection import spatial_available

        if spatial_available():
            w, s, e, n = bbox
            sql_spatial = (
                f"SELECT id, schema, caption, lat, lon FROM entities "
                f"WHERE geom IS NOT NULL "
                f"AND ST_Within(geom, ST_MakeEnvelope({w!r}, {s!r}, {e!r}, {n!r})) "
                f"LIMIT ?"
            )
            try:
                with ftm_query._LOCK:
                    rows = ftm_query._conn().execute(sql_spatial, [limit]).fetchall()
            except Exception as exc:
                if "flat vector" in str(exc).lower() or "INTERNAL" in str(exc):
                    # DuckDB 1.5.x R-Tree bug (duckdb-spatial #769) — fall back
                    sql_bbox = (
                        "SELECT id, schema, caption, lat, lon FROM entities "
                        "WHERE lat IS NOT NULL AND lon IS NOT NULL "
                        "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT ?"
                    )
                    with ftm_query._LOCK:
                        rows = (
                            ftm_query._conn()
                            .execute(
                                sql_bbox, [bbox[1], bbox[3], bbox[0], bbox[2], limit]
                            )
                            .fetchall()
                        )
                else:
                    raise
        else:
            sql_bbox = (
                "SELECT id, schema, caption, lat, lon FROM entities "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL "
                "AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ? LIMIT ?"
            )
            with ftm_query._LOCK:
                rows = (
                    ftm_query._conn()
                    .execute(sql_bbox, [bbox[1], bbox[3], bbox[0], bbox[2], limit])
                    .fetchall()
                )
        return [
            {"id": r[0], "schema": r[1], "caption": r[2], "lat": r[3], "lon": r[4]}
            for r in rows
        ]
    except Exception:
        return []


def _point_in_polygon(lat: float, lon: float, polygon: list[list[float]]) -> bool:
    """Pure Python point-in-polygon (Ray Casting). No Shapely dependency."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def _op_within(op: SpatialOperation) -> list[dict]:
    """BBox + haversine radius filter."""
    resolved = resolve_entity(op.target)
    if not resolved:
        return []
    radius = op.params.get("radius_km", 25.0)
    bbox = _bbox_from_point(resolved["lat"], resolved["lon"], radius)
    candidates = _get_entities_in_bbox(bbox)
    # Fine-grained haversine filter
    return [
        e
        for e in candidates
        if _haversine_km(resolved["lat"], resolved["lon"], e["lat"], e["lon"]) <= radius
    ]


def _op_near(op: SpatialOperation) -> list[dict]:
    """Near = within default radius."""
    return _op_within(op)


def _op_contains(op: SpatialOperation) -> list[dict]:
    """Contains = entities within a region/country bbox."""
    container = op.params.get("container", op.target)
    resolved = resolve_entity(container)
    if not resolved:
        return []
    bbox = resolved.get("bbox")
    if not bbox:
        bbox = _bbox_from_point(resolved["lat"], resolved["lon"], 100.0)
    return _get_entities_in_bbox(bbox)


def _op_border(op: SpatialOperation) -> list[dict]:
    """Near border = BBox of border polygon + point-in-buffer check."""
    region_a = op.params.get("region_a", "")
    region_b = op.params.get("region_b")
    name = f"{region_a}-{region_b}" if region_b else region_a
    resolved = resolve_entity(name)
    if not resolved:
        # Try just region_a
        resolved = resolve_entity(region_a)
    if not resolved or resolved.get("type") != "border":
        # Fallback: BBox around the border area
        resolved = resolve_entity(region_a)
        if not resolved:
            return []
        radius = op.params.get("radius_km", 50.0)
        bbox = _bbox_from_point(resolved["lat"], resolved["lon"], radius)
        return _get_entities_in_bbox(bbox)

    # Use border polygon bbox + proximity filter
    bbox = resolved.get(
        "bbox", _bbox_from_point(resolved["lat"], resolved["lon"], 50.0)
    )
    candidates = _get_entities_in_bbox(bbox)
    radius_km = op.params.get("radius_km", 50.0)

    results = []
    for e in candidates:
        # Check if within radius of any polygon edge (simplified: distance to centroid)
        dist = _haversine_km(resolved["lat"], resolved["lon"], e["lat"], e["lon"])
        if dist <= radius_km:
            results.append(e)
    return results


def _op_river(op: SpatialOperation) -> list[dict]:
    """Downstream/upstream — Phase 1 fallback: BBox around river."""
    river_name = op.params.get("river", op.target)
    resolved = resolve_entity(river_name)
    if not resolved:
        return []
    # Fallback: BBox around river centroid
    bbox = _bbox_from_point(resolved["lat"], resolved["lon"], 50.0)
    return _get_entities_in_bbox(bbox)


def _op_visible(op: SpatialOperation) -> list[dict]:
    """Line-of-sight — Phase 2. Phase 1: BBox around observer."""
    observer = op.params.get("observer", op.target)
    resolved = resolve_entity(observer)
    if not resolved:
        return []
    bbox = _bbox_from_point(resolved["lat"], resolved["lon"], 10.0)
    return _get_entities_in_bbox(bbox)


_OPS = {
    "within": _op_within,
    "near": _op_near,
    "contains": _op_contains,
    "border": _op_border,
    "river_direction": _op_river,
    "visible_from": _op_visible,
}


def execute_spatial_operation(op: SpatialOperation) -> list[dict]:
    """Execute a single spatial operation."""
    handler = _OPS.get(op.operation)
    if not handler:
        return []
    return handler(op)


def execute_spatial_plan(plan: SpatialQueryPlan) -> dict[str, Any]:
    """Execute a full spatial query plan with composition.

    AND = intersection of result sets.
    OR = union of result sets.
    """
    if not plan.operations:
        return {
            "operations": [],
            "results": [],
            "result_count": 0,
            "composition": plan.composition,
            "resolved_entities": [],
        }

    result_sets: list[set[str]] = []
    all_results: dict[str, dict] = {}
    resolved: list[dict] = []

    for op in plan.operations:
        entities = execute_spatial_operation(op)
        ent_resolved = resolve_entity(op.target)
        if ent_resolved:
            resolved.append(
                {
                    "operation": op.operation,
                    "target": op.target,
                    "resolved": ent_resolved,
                }
            )

        ids = set()
        for e in entities:
            eid = e.get("id", f"{e.get('lat',0)},{e.get('lon',0)}")
            ids.add(eid)
            all_results[eid] = e
        result_sets.append(ids)

    if not result_sets:
        final_ids: set[str] = set()
    elif plan.composition == "AND":
        final_ids = result_sets[0]
        for s in result_sets[1:]:
            final_ids &= s
    else:  # OR
        final_ids = result_sets[0]
        for s in result_sets[1:]:
            final_ids |= s

    return {
        "operations": [
            {"operation": op.operation, "target": op.target, "params": op.params}
            for op in plan.operations
        ],
        "results": [all_results[eid] for eid in final_ids if eid in all_results],
        "result_count": len(final_ids),
        "composition": plan.composition,
        "resolved_entities": resolved,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def spatial_query(query: str) -> dict[str, Any]:
    """Full pipeline: parse NL → resolve entities → execute → return results."""
    plan = parse_spatial_query(query)
    result = execute_spatial_plan(plan)
    result["query"] = query
    result["enabled"] = spatial_reasoning_enabled()
    return result


def spatial_reasoning_stats() -> dict[str, Any]:
    """Get spatial reasoning statistics."""
    geo = _load_geography()
    return {
        "enabled": spatial_reasoning_enabled(),
        "near_default_km": _NEAR_DEFAULT_KM,
        "static_cities": len(geo.get("cities", [])),
        "static_rivers": len(geo.get("rivers", [])),
        "static_borders": len(geo.get("borders", [])),
        "static_regions": len(geo.get("regions", [])),
        "operations": list(_OPS.keys()),
    }
