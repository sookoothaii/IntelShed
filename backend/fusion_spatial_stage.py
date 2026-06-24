"""Stage geolocated feed_cache rows into GeoParquet via DuckDB spatial (H3 index).

Research track: spatially queryable intelligence without a second stack.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_DEFAULT_PARQUET = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "fusion_events.parquet"
)
_PARQUET = os.getenv("FUSION_STAGE_PARQUET", _DEFAULT_PARQUET)
_H3_RES = int(os.getenv("FUSION_H3_RES", "5"))

_LIST_FIELDS = (
    "earthquakes",
    "alerts",
    "events",
    "volcanoes",
    "articles",
    "items",
    "vulnerabilities",
    "cities",
)


def _parquet_path() -> Path:
    return Path(_PARQUET)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _safe_lat_lon(item: dict[str, Any]) -> tuple[float, float] | None:
    lat = item.get("lat")
    lon = item.get("lon")
    if lat is None or lon is None:
        loc = item.get("location") or {}
        lat = loc.get("lat")
        lon = loc.get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def _label(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = item.get(key)
        if val:
            return str(val)[:240]
    return ""


def _rows_from_payload(feed_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    out: list[dict[str, Any]] = []
    cached_at = payload.get("cached_at") or payload.get("updated_at")
    for field in _LIST_FIELDS:
        items = payload.get(field)
        if not isinstance(items, list):
            continue
        for item in items[:500]:
            if not isinstance(item, dict):
                continue
            ll = _safe_lat_lon(item)
            if not ll:
                continue
            out.append(
                {
                    "feed_key": feed_key,
                    "source": str(item.get("source") or feed_key.split(":")[0])[:64],
                    "lat": ll[0],
                    "lon": ll[1],
                    "label": _label(item, "title", "place", "name", "headline", "event", "caption"),
                    "cached_at": cached_at,
                }
            )
    return out


def collect_staging_rows() -> list[dict[str, Any]]:
    """Read all feed_cache payloads and extract geolocated rows."""
    rows: list[dict[str, Any]] = []
    with _conn() as conn:
        for row in conn.execute("SELECT key, value, cached_at FROM feed_cache ORDER BY key"):
            try:
                payload = json.loads(row["value"] or "{}")
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            payload = dict(payload)
            payload.setdefault("cached_at", row["cached_at"])
            rows.extend(_rows_from_payload(row["key"], payload))
    return rows


def _duck_conn():
    try:
        import duckdb
    except ImportError as e:
        raise RuntimeError("duckdb not installed") from e
    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial;")
    return conn


def stage_to_parquet(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Write staging rows to GeoParquet with H3 cell column."""
    rows = rows if rows is not None else collect_staging_rows()
    path = _parquet_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return {
            "ok": True,
            "count": 0,
            "path": str(path),
            "h3_res": _H3_RES,
            "staged_at": datetime.now(timezone.utc).isoformat(),
            "hint": "no geolocated feed_cache rows — warm feeds first",
        }

    conn = _duck_conn()
    try:
        conn.execute(
            """
            CREATE OR REPLACE TABLE staging_raw (
                feed_key VARCHAR,
                source VARCHAR,
                lat DOUBLE,
                lon DOUBLE,
                label VARCHAR,
                cached_at VARCHAR
            )
            """
        )
        conn.executemany(
            "INSERT INTO staging_raw VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    r.get("feed_key"),
                    r.get("source"),
                    r.get("lat"),
                    r.get("lon"),
                    r.get("label"),
                    r.get("cached_at"),
                )
                for r in rows
            ],
        )
        h3_ok = False
        try:
            conn.execute(
                f"""
                CREATE OR REPLACE TABLE staging_h3 AS
                SELECT
                    feed_key,
                    source,
                    lat,
                    lon,
                    label,
                    cached_at,
                    h3_latlng_to_cell(lat, lon, {_H3_RES}) AS h3_cell
                FROM staging_raw
                """
            )
            h3_ok = True
        except Exception:
            conn.execute(
                """
                CREATE OR REPLACE TABLE staging_h3 AS
                SELECT
                    feed_key,
                    source,
                    lat,
                    lon,
                    label,
                    cached_at,
                    NULL::VARCHAR AS h3_cell
                FROM staging_raw
                """
            )

        safe = str(path).replace("'", "''")
        conn.execute(f"COPY staging_h3 TO '{safe}' (FORMAT PARQUET)")
        count = int(conn.execute("SELECT COUNT(*) FROM staging_h3").fetchone()[0])
    finally:
        conn.close()

    return {
        "ok": True,
        "count": count,
        "path": str(path),
        "h3_res": _H3_RES if h3_ok else None,
        "h3_indexed": h3_ok,
        "staged_at": datetime.now(timezone.utc).isoformat(),
    }


def stage_status() -> dict[str, Any]:
    """Last staged parquet metadata."""
    path = _parquet_path()
    if not path.exists():
        return {
            "staged": False,
            "path": str(path),
            "count": 0,
            "h3_res": _H3_RES,
        }
    conn = _duck_conn()
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0])
        cols = [r[0] for r in conn.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()]
    finally:
        conn.close()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "staged": True,
        "path": str(path),
        "count": count,
        "columns": cols,
        "h3_indexed": "h3_cell" in cols,
        "h3_res": _H3_RES,
        "modified_at": mtime,
        "size_bytes": path.stat().st_size,
    }


def query_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Spatial filter on staged parquet (operator region pre-filter)."""
    path = _parquet_path()
    if not path.exists():
        return {"ok": False, "count": 0, "rows": [], "detail": "parquet not staged"}
    conn = _duck_conn()
    try:
        lim = min(max(limit, 1), 500)
        df = conn.execute(
            """
            SELECT feed_key, source, lat, lon, label, h3_cell, cached_at
            FROM read_parquet(?)
            WHERE lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            LIMIT ?
            """,
            [str(path), min_lat, max_lat, min_lon, max_lon, lim],
        ).fetchdf()
        rows = df.to_dict(orient="records")
    finally:
        conn.close()
    return {"ok": True, "count": len(rows), "rows": rows, "bbox": [min_lat, min_lon, max_lat, max_lon]}
