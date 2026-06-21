"""Derive nearby edges between geolocated FtM entities (Track 3+).

Rebuilds ephemeral ``spatial-proximity`` links after feed ingest so subgraph BFS
has edges even when YAML mappings only write entities.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import ftm_store

DATASET = "spatial-proximity"
EDGE_KIND = "nearby"


def enabled() -> bool:
    return os.getenv("WORLDBASE_INTEL_SPATIAL_EDGES", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def max_distance_km() -> float:
    try:
        return max(5.0, float(os.getenv("WORLDBASE_INTEL_SPATIAL_MAX_KM", "120")))
    except ValueError:
        return 120.0


def max_entities() -> int:
    try:
        return max(10, min(200, int(os.getenv("WORLDBASE_INTEL_SPATIAL_MAX_ENTITIES", "80"))))
    except ValueError:
        return 80


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def confidence_for_distance(km: float, max_km: float) -> float:
    ratio = min(1.0, km / max(1.0, max_km))
    return round(0.95 - 0.4 * ratio, 3)


def _fetch_geolocated_entities(
    bbox: list[float],
    *,
    window_hours: int,
    entity_cap: int,
    exclude_schemas: set[str],
) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))).isoformat()
    clauses = [
        "e.lat IS NOT NULL",
        "e.lon IS NOT NULL",
        "e.last_seen IS NOT NULL",
        "e.last_seen >= ?",
        "e.lat BETWEEN ? AND ?",
        "e.lon BETWEEN ? AND ?",
    ]
    params: list[Any] = [cutoff, south, north, west, east]
    if exclude_schemas:
        placeholders = ", ".join("?" * len(exclude_schemas))
        clauses.append(f"e.schema NOT IN ({placeholders})")
        params.extend(sorted(exclude_schemas))
    params.append(entity_cap)
    rows = ftm_store.run_query(
        f"""
        SELECT e.id, e.lat, e.lon
        FROM entities e
        WHERE {" AND ".join(clauses)}
        ORDER BY e.last_seen DESC
        LIMIT ?
        """,
        params,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat, lon = float(row[1]), float(row[2])
        except (TypeError, ValueError):
            continue
        out.append({"id": row[0], "lat": lat, "lon": lon})
    return out


def link_proximity_edges(
    *,
    bbox: list[float] | None = None,
    region: str | None = None,
    window_hours: int = 24,
    max_km: float | None = None,
    entity_cap: int | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Link geolocated entities within ``max_km`` in operator bbox."""
    from intel_subgraph import _exclude_schemas, operator_bbox

    if not ftm_store.init_store():
        return {"ok": False, "edges_added": 0, "error": ftm_store.store_status().get("error")}

    target_bbox = list(bbox) if bbox else operator_bbox(region)
    limit_km = max_km if max_km is not None else max_distance_km()
    cap = entity_cap if entity_cap is not None else max_entities()
    exclude = _exclude_schemas()
    entities = _fetch_geolocated_entities(
        target_bbox,
        window_hours=window_hours,
        entity_cap=cap,
        exclude_schemas=exclude,
    )

    if refresh:
        ftm_store.delete_edges_for_dataset(DATASET)

    seen_at = datetime.now(timezone.utc).isoformat()
    edges_added = 0
    pairs_within = 0
    for i, left in enumerate(entities):
        for right in entities[i + 1 :]:
            km = haversine_km(left["lat"], left["lon"], right["lat"], right["lon"])
            if km > limit_km:
                continue
            pairs_within += 1
            before = ftm_store.count_edges_for_dataset(DATASET)
            ftm_store.add_edge(
                left["id"],
                right["id"],
                EDGE_KIND,
                dataset=DATASET,
                confidence=confidence_for_distance(km, limit_km),
                properties={"distance_km": round(km, 2), "method": "haversine"},
                seen_at=seen_at,
            )
            after = ftm_store.count_edges_for_dataset(DATASET)
            if after > before:
                edges_added += 1

    return {
        "ok": True,
        "dataset": DATASET,
        "bbox": target_bbox,
        "window_hours": window_hours,
        "max_km": limit_km,
        "entities_scanned": len(entities),
        "pairs_within": pairs_within,
        "edges_added": edges_added,
        "edges_total": ftm_store.count_edges_for_dataset(DATASET),
    }


from fastapi import APIRouter, HTTPException, Query  # noqa: E402

router = APIRouter(prefix="/api/intel/spatial", tags=["intel"])


@router.get("/status")
async def spatial_status():
    return {
        "enabled": enabled(),
        "dataset": DATASET,
        "max_km": max_distance_km(),
        "max_entities": max_entities(),
        "edges": ftm_store.count_edges_for_dataset(DATASET) if ftm_store.init_store() else 0,
    }


@router.post("/run")
async def spatial_run(
    window_hours: int = Query(24, ge=1, le=168),
    max_km: float | None = Query(None, ge=5, le=500),
):
    if not enabled():
        raise HTTPException(status_code=503, detail="spatial proximity edges disabled")
    try:
        return link_proximity_edges(window_hours=window_hours, max_km=max_km)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"spatial link failed: {exc}") from exc
