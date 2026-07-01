"""V4-39 — Bitemporal entity store (valid_time / system_time).

Implements bitemporal tracking for FtM entities:

  - **valid_time** — when the fact was true in the real world (e.g. a person
    held a position from 2020-01-01 to 2023-06-30).
  - **system_time** — when the fact was recorded in the database (the
    transaction timestamp).

Every upsert produces a versioned record in the ``entity_versions`` table.
Queries can ask "what did we know at time X?" (system-time travel) or
"what was true at time Y?" (valid-time travel).

This module wraps the existing FtM store — it does not replace it. The
canonical entities table remains the current-state snapshot; the versions
table provides the full historical audit trail.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND

from middleware.rbac import require_operator, require_viewer
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/bitemporal", tags=["bitemporal"])


def _get_db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_bitemporal_tables() -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    schema TEXT,
                    caption TEXT,
                    properties TEXT,
                    datasets TEXT,
                    lat REAL,
                    lon REAL,
                    valid_from TEXT,
                    valid_to TEXT,
                    system_from TEXT NOT NULL,
                    system_to TEXT,
                    change_type TEXT NOT NULL DEFAULT 'upsert',
                    source TEXT,
                    UNIQUE(entity_id, version)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ev_entity ON entity_versions(entity_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ev_valid ON entity_versions(valid_from, valid_to)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ev_system ON entity_versions(system_from, system_to)"
            )
            conn.commit()
    except Exception as exc:
        log.warning("bitemporal_table_create_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def record_version(
    entity_id: str,
    *,
    schema: str = "",
    caption: str = "",
    properties: dict | None = None,
    datasets: list[str] | None = None,
    lat: float | None = None,
    lon: float | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    change_type: str = "upsert",
    source: str = "",
) -> dict[str, Any]:
    """Record a new version of an entity in the bitemporal store.

    Automatically increments the version number and closes the previous
    version's system_time interval.
    """
    _ensure_bitemporal_tables()
    now = datetime.now(timezone.utc).isoformat()

    # Determine next version number
    version = 1
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT MAX(version) as max_v FROM entity_versions WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if row and row["max_v"] is not None:
                version = row["max_v"] + 1

            # Close previous version's system_to
            conn.execute(
                "UPDATE entity_versions SET system_to = ? "
                "WHERE entity_id = ? AND system_to IS NULL",
                (now, entity_id),
            )
            conn.commit()
    except Exception:
        pass

    props_json = json.dumps(properties or {})
    datasets_json = json.dumps(sorted(datasets or []))

    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """
                INSERT INTO entity_versions
                    (entity_id, version, schema, caption, properties, datasets,
                     lat, lon, valid_from, valid_to, system_from, system_to,
                     change_type, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    entity_id,
                    version,
                    schema,
                    caption,
                    props_json,
                    datasets_json,
                    lat,
                    lon,
                    valid_from,
                    valid_to,
                    now,
                    change_type,
                    source,
                ),
            )
            conn.commit()
    except Exception as exc:
        log.warning("bitemporal_record_failed", entity_id=entity_id, error=str(exc))

    return {
        "entity_id": entity_id,
        "version": version,
        "system_from": now,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "change_type": change_type,
    }


def get_entity_history(entity_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    """Return all versions of an entity, newest first."""
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entity_versions WHERE entity_id = ? ORDER BY version DESC LIMIT ?",
                (entity_id, limit),
            ).fetchall()
            return [_row_to_dict(r) for r in rows]
    except Exception:
        return []


def get_version(entity_id: str, version: int) -> dict[str, Any] | None:
    """Get a specific version of an entity."""
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entity_versions WHERE entity_id = ? AND version = ?",
                (entity_id, version),
            ).fetchone()
            return _row_to_dict(row) if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Time travel queries
# ---------------------------------------------------------------------------


def as_of_system_time(entity_id: str, system_time: str) -> dict[str, Any] | None:
    """What did the database know about *entity_id* at *system_time*?

    Returns the version whose [system_from, system_to) interval contains
    *system_time*.
    """
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM entity_versions
                WHERE entity_id = ?
                  AND system_from <= ?
                  AND (system_to IS NULL OR system_to > ?)
                ORDER BY version DESC LIMIT 1
                """,
                (entity_id, system_time, system_time),
            ).fetchone()
            return _row_to_dict(row) if row else None
    except Exception:
        return None


def as_of_valid_time(entity_id: str, valid_time: str) -> dict[str, Any] | None:
    """What was true about *entity_id* at *valid_time* in the real world?

    Returns the version whose [valid_from, valid_to) interval contains
    *valid_time*. Falls back to versions with NULL valid_from/valid_to
    (always-valid facts).
    """
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            # First try precise interval match
            row = conn.execute(
                """
                SELECT * FROM entity_versions
                WHERE entity_id = ?
                  AND (
                    (valid_from IS NOT NULL AND valid_from <= ?
                     AND (valid_to IS NULL OR valid_to > ?))
                    OR (valid_from IS NULL AND valid_to IS NULL)
                  )
                ORDER BY version DESC LIMIT 1
                """,
                (entity_id, valid_time, valid_time),
            ).fetchone()
            return _row_to_dict(row) if row else None
    except Exception:
        return None


def as_of_both(
    entity_id: str, system_time: str, valid_time: str
) -> dict[str, Any] | None:
    """Combined bi-temporal query: what did we know at *system_time* about
    what was true at *valid_time*?"""
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM entity_versions
                WHERE entity_id = ?
                  AND system_from <= ?
                  AND (system_to IS NULL OR system_to > ?)
                  AND (
                    (valid_from IS NOT NULL AND valid_from <= ?
                     AND (valid_to IS NULL OR valid_to > ?))
                    OR (valid_from IS NULL AND valid_to IS NULL)
                  )
                ORDER BY version DESC LIMIT 1
                """,
                (entity_id, system_time, system_time, valid_time, valid_time),
            ).fetchone()
            return _row_to_dict(row) if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def correct_valid_time(
    entity_id: str,
    version: int,
    *,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> bool:
    """Correct the valid_time interval of a specific version.

    This is a metadata correction — it does not create a new version.
    """
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "UPDATE entity_versions SET valid_from = ?, valid_to = ? "
                "WHERE entity_id = ? AND version = ?",
                (valid_from, valid_to, entity_id, version),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def bitemporal_stats() -> dict[str, Any]:
    _ensure_bitemporal_tables()
    try:
        with _sqlite_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entity_versions").fetchone()[0]
            entities = conn.execute(
                "SELECT COUNT(DISTINCT entity_id) FROM entity_versions"
            ).fetchone()[0]
            by_type = conn.execute(
                "SELECT change_type, COUNT(*) as cnt "
                "FROM entity_versions GROUP BY change_type ORDER BY cnt DESC"
            ).fetchall()
            with_valid = conn.execute(
                "SELECT COUNT(*) FROM entity_versions WHERE valid_from IS NOT NULL"
            ).fetchone()[0]
            return {
                "total_versions": total,
                "unique_entities": entities,
                "with_valid_time": with_valid,
                "by_change_type": {r["change_type"]: r["cnt"] for r in by_type},
            }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Parse JSON fields
    for key in ("properties", "datasets"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class VersionRequest(BaseModel):
    entity_id: str
    entity_schema: str = ""
    caption: str = ""
    properties: dict | None = None
    datasets: list[str] | None = None
    lat: float | None = None
    lon: float | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    change_type: str = "upsert"
    source: str = ""


class CorrectValidTimeRequest(BaseModel):
    valid_from: str | None = None
    valid_to: str | None = None


@router.post("/version")
async def api_record_version(
    req: VersionRequest,
    _role: str | None = Depends(require_operator),
):
    return record_version(
        req.entity_id,
        schema=req.entity_schema,
        caption=req.caption,
        properties=req.properties,
        datasets=req.datasets,
        lat=req.lat,
        lon=req.lon,
        valid_from=req.valid_from,
        valid_to=req.valid_to,
        change_type=req.change_type,
        source=req.source,
    )


@router.get("/history/{entity_id}")
async def api_history(
    entity_id: str,
    limit: int = Query(100, ge=1, le=1000),
    _role: str | None = Depends(require_viewer),
):
    return {"versions": get_entity_history(entity_id, limit=limit)}


@router.get("/version/{entity_id}/{version}")
async def api_get_version(
    entity_id: str,
    version: int,
    _role: str | None = Depends(require_viewer),
):
    result = get_version(entity_id, version)
    if not result:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Version not found")
    return result


@router.get("/as-of/system/{entity_id}")
async def api_as_of_system(
    entity_id: str,
    time: str = Query(..., description="ISO-8601 timestamp"),
    _role: str | None = Depends(require_viewer),
):
    result = as_of_system_time(entity_id, time)
    if not result:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="No version found at that system time",
        )
    return result


@router.get("/as-of/valid/{entity_id}")
async def api_as_of_valid(
    entity_id: str,
    time: str = Query(..., description="ISO-8601 timestamp"),
    _role: str | None = Depends(require_viewer),
):
    result = as_of_valid_time(entity_id, time)
    if not result:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail="No version found at that valid time"
        )
    return result


@router.get("/as-of/both/{entity_id}")
async def api_as_of_both(
    entity_id: str,
    system_time: str = Query(..., description="ISO-8601 system timestamp"),
    valid_time: str = Query(..., description="ISO-8601 valid timestamp"),
    _role: str | None = Depends(require_viewer),
):
    result = as_of_both(entity_id, system_time, valid_time)
    if not result:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="No version found matching both times",
        )
    return result


@router.patch("/correct/{entity_id}/{version}")
async def api_correct_valid_time(
    entity_id: str,
    version: int,
    req: CorrectValidTimeRequest,
    _role: str | None = Depends(require_operator),
):
    if not correct_valid_time(
        entity_id, version, valid_from=req.valid_from, valid_to=req.valid_to
    ):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Version not found")
    return {"corrected": True}


@router.get("/stats")
async def api_stats(
    _role: str | None = Depends(require_viewer),
):
    return bitemporal_stats()


__all__ = [
    "record_version",
    "get_entity_history",
    "get_version",
    "as_of_system_time",
    "as_of_valid_time",
    "as_of_both",
    "correct_valid_time",
    "bitemporal_stats",
    "router",
]
