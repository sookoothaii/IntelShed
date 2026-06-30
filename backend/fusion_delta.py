"""V4-52 Fusion Delta Grid — 24h comparison with delta_score.

Wraps the existing ``fusion_heatmap.apply_compare`` infrastructure into a
dedicated delta endpoint that returns only cells with meaningful change
vs a historical baseline snapshot.

Also provides watch-item generation from delta_score for the briefing
pipeline and a Cesium-friendly GeoJSON output mode.

Endpoints:
    GET /api/fusion/delta?compare=24h&cell_deg=2.0&top=20
        Returns cells with delta_score, sorted by absolute delta.
        Includes ``watch_items`` for high-delta cells.

Briefing integration:
    ``gather_delta_watch_items()`` — called by briefing_digest to produce
    forward-looking watch items from rising fusion cells.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query

from auth.security import verify_api_key
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/fusion", tags=["fusion-delta"])

_MIN_DELTA = float(os.getenv("WORLDBASE_FUSION_DELTA_MIN", "0.12"))
_MAX_WATCH_ITEMS = int(os.getenv("WORLDBASE_FUSION_DELTA_MAX_WATCH", "5"))


def _lat_lon_label(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.1f}°{ns} {abs(lon):.1f}°{ew}"


def build_delta_watch_items(
    delta_cells: list[dict[str, Any]],
    *,
    max_items: int = _MAX_WATCH_ITEMS,
    min_delta: float = _MIN_DELTA,
) -> list[dict[str, Any]]:
    """Generate watch items from fusion delta cells.

    Only positive deltas above ``min_delta`` are considered "rising".
    Returns at most ``max_items`` watch item dicts.
    """
    from operator_briefing import (
        classify_item,
        _region_bbox,
        _ASEAN_BBOX,
        OPERATOR_REGION,
    )

    local_bbox = _region_bbox(OPERATOR_REGION)
    regional_bbox = _ASEAN_BBOX if OPERATOR_REGION == "thailand" else local_bbox

    items: list[dict[str, Any]] = []
    for cell in delta_cells:
        delta = float(cell.get("delta_score") or 0)
        if delta < min_delta:
            continue

        lat = cell.get("lat")
        lon = cell.get("lon")
        if lat is None or lon is None:
            continue

        cid = cell.get("cell_id") or f"{float(lat):.2f},{float(lon):.2f}"
        score = float(cell.get("score") or 0)
        sources = cell.get("sources") or ["fusion"]
        bucket = classify_item(float(lat), float(lon), "", local_bbox, regional_bbox)
        label = _lat_lon_label(float(lat), float(lon))

        items.append(
            {
                "id": f"fusion_delta:{cid}:{delta}",
                "prefix": "fusion_delta",
                "title": f"Rising fusion cell (Δ+{delta:.2f}): {label}",
                "horizon_h": 48,
                "confidence": min(0.92, 0.5 + delta + score * 0.25),
                "sources": sources,
                "bucket": bucket,
                "cell_id": cid,
                "delta_score": round(delta, 4),
                "lat": float(lat),
                "lon": float(lon),
            }
        )

        if len(items) >= max_items:
            break

    return items


async def compute_delta(
    cell_deg: float = 2.0,
    compare_hours: float = 24.0,
    top: int = 20,
    include_geojson: int = 0,
) -> dict[str, Any]:
    """Compute fusion delta grid vs historical baseline.

    Delegates to ``fusion_heatmap.fusion_heatmap`` with compare parameter,
    then filters and enriches for delta-focused output.
    """
    from fusion_heatmap import (
        fusion_heatmap as _fh,
    )

    compare_arg = f"{compare_hours:g}h"
    data = await _fh(
        cell_deg=cell_deg,
        top=max(top * 3, 60),
        include_geojson=include_geojson,
        compare=compare_arg,
    )

    cells = data.get("cells") or []
    compare_meta = data.get("compare") or {}

    # Filter to cells with delta_score
    delta_cells = [c for c in cells if c.get("delta_score") is not None]
    delta_cells.sort(key=lambda c: -abs(float(c.get("delta_score") or 0)))

    # Top delta cells
    top_deltas = delta_cells[:top]

    # Rising cells (positive delta) for watch items
    rising = [c for c in delta_cells if float(c.get("delta_score") or 0) > 0]
    watch_items = build_delta_watch_items(rising)

    # Build GeoJSON for delta cells if requested
    geojson = None
    if include_geojson and top_deltas:
        feats = []
        half = cell_deg / 2
        for c in top_deltas:
            lat, lon = c.get("lat"), c.get("lon")
            if lat is None or lon is None:
                continue
            ds = c.get("delta_score")
            ring = [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "cell_id": c.get("cell_id"),
                        "score": c.get("score"),
                        "baseline_score": c.get("baseline_score"),
                        "delta_score": ds,
                        "sources": c.get("sources"),
                        "intensity": c.get("intensity"),
                    },
                }
            )
        geojson = {"type": "FeatureCollection", "features": feats}

    return {
        "enabled": True,
        "cell_deg": cell_deg,
        "compare_hours": compare_hours,
        "available": compare_meta.get("available", False),
        "baseline_at": compare_meta.get("baseline_at"),
        "target_at": compare_meta.get("target_at"),
        "snapshots_stored": compare_meta.get("snapshots_stored", 0),
        "total_delta_cells": len(delta_cells),
        "returned": len(top_deltas),
        "cells": top_deltas,
        "watch_items": watch_items,
        "top_delta": compare_meta.get("top_delta"),
        "scanned_at": data.get("scanned_at"),
        "geojson": geojson,
    }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get("/delta")
async def delta_endpoint(
    compare: str = Query("24h", description="Compare window (e.g. 24h, 6h)"),
    cell_deg: float = Query(2.0, ge=0.5, le=10.0),
    top: int = Query(20, ge=5, le=200),
    include_geojson: int = Query(0, ge=0, le=1),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Fusion delta grid — cells with delta_score vs historical baseline."""
    from fusion_heatmap import parse_compare_hours

    compare_hours = parse_compare_hours(compare)
    if compare_hours is None:
        return {
            "enabled": True,
            "error": f"Invalid compare value: {compare}. Use format like '24h'.",
            "cells": [],
            "watch_items": [],
        }

    try:
        return await compute_delta(
            cell_deg=cell_deg,
            compare_hours=compare_hours,
            top=top,
            include_geojson=include_geojson,
        )
    except Exception as exc:
        log.warning("fusion_delta_failed", error=str(exc)[:200])
        return {
            "enabled": True,
            "error": str(exc)[:200],
            "cells": [],
            "watch_items": [],
        }
