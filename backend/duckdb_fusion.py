"""DuckDB spatial fusion — GeoParquet staging + sample queries."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.security import verify_lan_auth

import fusion_spatial_stage as fss

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fusion", tags=["fusion"])

_GEOPARQUET = os.getenv("FUSION_GEOPARQUET", "")
_DUCKDB_PATH = os.getenv("FUSION_DUCKDB_PATH", "")


def _duck():
    try:
        import duckdb
    except ImportError as e:
        raise HTTPException(503, "duckdb not installed — pip install duckdb") from e
    conn = duckdb.connect(_DUCKDB_PATH or ":memory:")
    conn.execute("INSTALL spatial; LOAD spatial;")
    return conn


@router.get("/status")
def fusion_status():
    """Whether DuckDB spatial is available and which data paths are configured."""
    try:
        import duckdb

        ver = duckdb.__version__
        ok = True
    except ImportError:
        ver = None
        ok = False
    gp = _GEOPARQUET
    return {
        "duckdb": ok,
        "version": ver,
        "geoparquet_env": "FUSION_GEOPARQUET",
        "geoparquet_set": bool(gp),
        "geoparquet_path": gp if gp and Path(gp).exists() else None,
        "persist_db": _DUCKDB_PATH or None,
        "hint": "Set FUSION_GEOPARQUET to a local .parquet path or S3 URL for Overture/STAC joins",
    }


@router.get("/sample")
def fusion_sample(limit: int = 20):
    """
    Demo spatial query — counts entities in SQLite export or empty stub.
    """
    conn = _duck()
    try:
        if _GEOPARQUET and Path(_GEOPARQUET).exists():
            rows = conn.execute(
                "SELECT * FROM read_parquet(?) LIMIT ?", [_GEOPARQUET, min(limit, 100)]
            ).fetchdf()
            return {"mode": "geoparquet", "count": len(rows), "columns": list(rows.columns), "preview": rows.head(5).to_dict(orient="records")}
        # Built-in demo: H3-style grid from entity_store lat/lon
        db = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
        )
        if Path(db).exists():
            n = conn.execute(
                "SELECT COUNT(*) FROM sqlite_scan(?, 'entities') WHERE lat IS NOT NULL", [db]
            ).fetchone()[0]
            sample = conn.execute(
                """
                SELECT id, type, label, lat, lon, source_feed
                FROM sqlite_scan(?, 'entities')
                WHERE lat IS NOT NULL
                LIMIT ?
                """,
                [db, min(limit, 50)],
            ).fetchdf()
            return {"mode": "entities", "count": int(n), "preview": sample.to_dict(orient="records")}
        return {"mode": "empty", "count": 0, "hint": "Set FUSION_GEOPARQUET or populate entities"}
    finally:
        conn.close()


@router.get("/stage/status")
def fusion_stage_status():
    """GeoParquet staging file metadata (H3-indexed feed points)."""
    try:
        return fss.stage_status()
    except Exception as exc:
        logger.exception("fusion stage status failed")
        raise HTTPException(503, "stage status unavailable") from exc


@router.post("/stage")
def fusion_stage_run(_auth: str | None = Depends(verify_lan_auth)):
    """Extract geolocated rows from feed_cache → GeoParquet on disk."""
    try:
        return fss.stage_to_parquet()
    except RuntimeError as exc:
        logger.exception("fusion stage run failed")
        raise HTTPException(503, "staging failed — check FUSION_GEOPARQUET and feed data") from exc
    except Exception as exc:
        logger.exception("fusion stage run failed")
        raise HTTPException(500, "internal error during staging") from exc


@router.get("/stage/query")
def fusion_stage_query(
    min_lat: float = Query(..., ge=-90, le=90),
    min_lon: float = Query(..., ge=-180, le=180),
    max_lat: float = Query(..., ge=-90, le=90),
    max_lon: float = Query(..., ge=-180, le=180),
    limit: int = Query(50, ge=1, le=500),
):
    """BBox filter on staged GeoParquet (Thailand operator region, etc.)."""
    if min_lat > max_lat or min_lon > max_lon:
        raise HTTPException(400, "invalid bbox")
    try:
        return fss.query_bbox(min_lat, min_lon, max_lat, max_lon, limit=limit)
    except Exception as exc:
        logger.exception("fusion bbox query failed")
        raise HTTPException(503, "query failed — staged data may be unavailable") from exc
