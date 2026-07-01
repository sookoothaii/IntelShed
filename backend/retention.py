"""V4-07 — Data retention policies and TTL pruning.

Provides:
  - Retention policy CRUD (per-table TTL rules stored in SQLite)
  - Pruning of expired rows across SQLite + DuckDB stores
  - Scheduled enforcement via lifespan autopilot
  - FastAPI router with /api/retention/* endpoints (operator-only)

Policies are per-table with a TTL in days. The pruner walks each policy
and deletes rows older than the TTL based on the table's timestamp column.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND

from middleware.rbac import require_operator, require_viewer
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/retention", tags=["retention"])


def _get_db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


# Default policies applied on first init
_DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "table_name": "feed_cache",
        "database": "sqlite",
        "ttl_days": 7,
        "timestamp_column": "cached_at",
        "enabled": True,
    },
    {
        "table_name": "auth_audit",
        "database": "sqlite",
        "ttl_days": 90,
        "timestamp_column": "timestamp",
        "enabled": True,
    },
    {
        "table_name": "gdpr_requests",
        "database": "sqlite",
        "ttl_days": 365,
        "timestamp_column": "created_at",
        "enabled": True,
    },
    {
        "table_name": "statements",
        "database": "duckdb",
        "ttl_days": 0,  # 0 = no pruning (keep forever)
        "timestamp_column": "seen_at",
        "enabled": False,
    },
    {
        "table_name": "edges",
        "database": "duckdb",
        "ttl_days": 0,
        "timestamp_column": "seen_at",
        "enabled": False,
    },
]


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_retention_tables() -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retention_policies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    table_name TEXT NOT NULL,
                    database TEXT NOT NULL DEFAULT 'sqlite',
                    ttl_days INTEGER NOT NULL DEFAULT 0,
                    timestamp_column TEXT NOT NULL DEFAULT 'created_at',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_pruned_at TEXT,
                    last_pruned_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(table_name, database)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS retention_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    policy_id INTEGER,
                    table_name TEXT NOT NULL,
                    rows_deleted INTEGER NOT NULL DEFAULT 0,
                    pruned_at TEXT NOT NULL,
                    error TEXT
                )
                """
            )
            conn.commit()

            # Seed defaults if empty
            count = conn.execute("SELECT COUNT(*) FROM retention_policies").fetchone()[
                0
            ]
            if count == 0:
                now = datetime.now(timezone.utc).isoformat()
                for p in _DEFAULT_POLICIES:
                    conn.execute(
                        "INSERT OR IGNORE INTO retention_policies "
                        "(table_name, database, ttl_days, timestamp_column, enabled, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            p["table_name"],
                            p["database"],
                            p["ttl_days"],
                            p["timestamp_column"],
                            int(p["enabled"]),
                            now,
                            now,
                        ),
                    )
                conn.commit()
    except Exception as exc:
        log.warning("retention_table_create_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Policy CRUD
# ---------------------------------------------------------------------------


def list_policies() -> list[dict[str, Any]]:
    _ensure_retention_tables()
    try:
        with _sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM retention_policies ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def get_policy(policy_id: int) -> dict[str, Any] | None:
    _ensure_retention_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT * FROM retention_policies WHERE id = ?", (policy_id,)
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def create_policy(
    table_name: str,
    database: str,
    ttl_days: int,
    timestamp_column: str,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    _ensure_retention_tables()
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO retention_policies "
                "(table_name, database, ttl_days, timestamp_column, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    table_name,
                    database,
                    ttl_days,
                    timestamp_column,
                    int(enabled),
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM retention_policies WHERE table_name = ? AND database = ?",
                (table_name, database),
            ).fetchone()
            return dict(row) if row else {}
    except Exception as exc:
        log.warning("retention_policy_create_failed", error=str(exc))
        return {"error": str(exc)}


def update_policy(
    policy_id: int,
    *,
    ttl_days: int | None = None,
    enabled: bool | None = None,
    timestamp_column: str | None = None,
) -> dict[str, Any] | None:
    _ensure_retention_tables()
    now = datetime.now(timezone.utc).isoformat()
    sets: list[str] = ["updated_at = ?"]
    params: list[Any] = [now]
    if ttl_days is not None:
        sets.append("ttl_days = ?")
        params.append(ttl_days)
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(int(enabled))
    if timestamp_column is not None:
        sets.append("timestamp_column = ?")
        params.append(timestamp_column)
    params.append(policy_id)
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                f"UPDATE retention_policies SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM retention_policies WHERE id = ?", (policy_id,)
            ).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


def delete_policy(policy_id: int) -> bool:
    _ensure_retention_tables()
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "DELETE FROM retention_policies WHERE id = ?", (policy_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Pruning
# ---------------------------------------------------------------------------


def prune_table(policy: dict[str, Any]) -> dict[str, Any]:
    """Execute a single retention policy. Returns a summary dict."""
    ttl_days = policy["ttl_days"]
    if ttl_days <= 0 or not policy["enabled"]:
        return {"table": policy["table_name"], "deleted": 0, "skipped": True}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
    ts_col = policy["timestamp_column"]
    table = policy["table_name"]
    db_type = policy["database"]
    result: dict[str, Any] = {
        "table": table,
        "database": db_type,
        "cutoff": cutoff,
        "deleted": 0,
        "error": None,
    }

    try:
        if db_type == "sqlite":
            with _sqlite_conn() as conn:
                cur = conn.execute(f"DELETE FROM {table} WHERE {ts_col} < ?", (cutoff,))
                conn.commit()
                result["deleted"] = cur.rowcount
        elif db_type == "duckdb":
            try:
                from ftm_connection import _conn, _LOCK

                with _LOCK:
                    con = _conn()
                    if con is None:
                        result["error"] = "DuckDB connection not available"
                        return result
                    cur = con.execute(
                        f"DELETE FROM {table} WHERE CAST({ts_col} AS VARCHAR) < ?",
                        [cutoff],
                    )
                    result["deleted"] = cur.rowcount if cur.rowcount > 0 else 0
            except Exception as exc:
                result["error"] = str(exc)
    except Exception as exc:
        result["error"] = str(exc)
        log.warning("retention_prune_failed", table=table, error=str(exc))

    # Log the prune
    _log_prune(policy.get("id"), table, result["deleted"], result.get("error"))

    # Update policy metadata
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "UPDATE retention_policies SET last_pruned_at = ?, last_pruned_count = ? WHERE id = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    result["deleted"],
                    policy["id"],
                ),
            )
            conn.commit()
    except Exception:
        pass

    return result


def prune_all() -> list[dict[str, Any]]:
    """Run all enabled retention policies. Returns per-table summaries."""
    _ensure_retention_tables()
    policies = list_policies()
    results: list[dict[str, Any]] = []
    for p in policies:
        if p["enabled"] and p["ttl_days"] > 0:
            results.append(prune_table(p))
    if results:
        total = sum(r["deleted"] for r in results)
        log.info("retention_prune_all", total_deleted=total, policies_run=len(results))
    return results


def _log_prune(
    policy_id: int | None, table: str, deleted: int, error: str | None
) -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT INTO retention_log (policy_id, table_name, rows_deleted, pruned_at, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    policy_id,
                    table,
                    deleted,
                    datetime.now(timezone.utc).isoformat(),
                    error,
                ),
            )
            conn.commit()
    except Exception:
        pass


def prune_history(limit: int = 100) -> list[dict[str, Any]]:
    _ensure_retention_tables()
    try:
        with _sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM retention_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class PolicyCreate(BaseModel):
    table_name: str
    database: str = "sqlite"
    ttl_days: int
    timestamp_column: str = "created_at"
    enabled: bool = True


class PolicyUpdate(BaseModel):
    ttl_days: int | None = None
    enabled: bool | None = None
    timestamp_column: str | None = None


@router.get("/policies")
async def api_list_policies(
    _role: str | None = Depends(require_viewer),
):
    return {"policies": list_policies()}


@router.post("/policies")
async def api_create_policy(
    req: PolicyCreate,
    _role: str | None = Depends(require_operator),
):
    return create_policy(
        req.table_name,
        req.database,
        req.ttl_days,
        req.timestamp_column,
        enabled=req.enabled,
    )


@router.patch("/policies/{policy_id}")
async def api_update_policy(
    policy_id: int,
    req: PolicyUpdate,
    _role: str | None = Depends(require_operator),
):
    result = update_policy(
        policy_id,
        ttl_days=req.ttl_days,
        enabled=req.enabled,
        timestamp_column=req.timestamp_column,
    )
    if not result:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Policy not found")
    return result


@router.delete("/policies/{policy_id}")
async def api_delete_policy(
    policy_id: int,
    _role: str | None = Depends(require_operator),
):
    if not delete_policy(policy_id):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Policy not found")
    return {"deleted": True}


@router.post("/prune")
async def api_prune_all(
    _role: str | None = Depends(require_operator),
):
    return {"results": prune_all()}


@router.post("/prune/{policy_id}")
async def api_prune_one(
    policy_id: int,
    _role: str | None = Depends(require_operator),
):
    policy = get_policy(policy_id)
    if not policy:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Policy not found")
    return prune_table(policy)


@router.get("/log")
async def api_prune_log(
    limit: int = Query(100, ge=1, le=1000),
    _role: str | None = Depends(require_viewer),
):
    return {"entries": prune_history(limit=limit)}


__all__ = [
    "list_policies",
    "get_policy",
    "create_policy",
    "update_policy",
    "delete_policy",
    "prune_table",
    "prune_all",
    "prune_history",
    "router",
]
