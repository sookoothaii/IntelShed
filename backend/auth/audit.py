"""Auth audit log — SQLite-backed audit trail for auth events and MCP tool calls.

Records every authentication attempt and MCP write-tool invocation to a
dedicated ``auth_audit`` table.  Fail-soft: audit failures never block the
request path.

Table schema:
    id          INTEGER PRIMARY KEY AUTOINCREMENT
    timestamp   TEXT    NOT NULL (ISO-8601 UTC)
    client      TEXT    (IP address or "loopback")
    endpoint    TEXT    (request path or tool name)
    tool        TEXT    (MCP tool name, nullable)
    action      TEXT    (e.g. "auth_verify_api_key", "mcp_write", "rbac_check")
    success     INTEGER (0 or 1)
    error       TEXT    (error detail, nullable)

Retention: rows older than ``WORLDBASE_AUTH_AUDIT_RETENTION_DAYS`` (default 90)
are pruned on each insert (amortised — every 100th insert triggers a prune).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from structured_log import get_logger

log = get_logger(__name__)

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worldbase.db"
)

_RETENTION_DAYS = int(os.getenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "90"))
_ENABLED = os.getenv("WORLDBASE_AUTH_AUDIT", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

_INSERT_COUNTER = 0
_PRUNE_EVERY = 100


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=3000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def ensure_audit_table() -> None:
    """Create the auth_audit table if it does not exist. Fail-soft."""
    try:
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    client TEXT,
                    endpoint TEXT,
                    tool TEXT,
                    action TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_audit_ts ON auth_audit(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_audit_action ON auth_audit(action)"
            )
            conn.commit()
    except Exception as exc:
        log.warning("audit_table_create_failed", error=str(exc))


def audit_enabled() -> bool:
    """Return True when audit logging is enabled."""
    return _ENABLED


def record_audit_event(
    *,
    action: str,
    client: str = "",
    endpoint: str = "",
    tool: str = "",
    success: bool = True,
    error: str = "",
) -> None:
    """Write a single audit row. Fail-soft — never raises."""
    if not _ENABLED:
        return
    try:
        global _INSERT_COUNTER
        ts = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                "INSERT INTO auth_audit "
                "(timestamp, client, endpoint, tool, action, success, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, client, endpoint, tool, action, int(success), error),
            )
            conn.commit()
        _INSERT_COUNTER += 1
        if _INSERT_COUNTER % _PRUNE_EVERY == 0:
            prune_audit_log()
    except Exception as exc:
        log.warning("audit_record_failed", error=str(exc))


def prune_audit_log(retention_days: int = _RETENTION_DAYS) -> int:
    """Delete rows older than *retention_days*. Returns count deleted. Fail-soft."""
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        with _connect() as conn:
            cur = conn.execute("DELETE FROM auth_audit WHERE timestamp < ?", (cutoff,))
            conn.commit()
            deleted = cur.rowcount
        if deleted:
            log.info("audit_pruned", deleted=deleted, retention_days=retention_days)
        return deleted
    except Exception as exc:
        log.warning("audit_prune_failed", error=str(exc))
        return 0


def query_audit_log(
    *,
    limit: int = 100,
    action: str | None = None,
    success: bool | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Query audit log with optional filters. Returns list of dicts. Fail-soft."""
    try:
        sql = (
            "SELECT id, timestamp, client, endpoint, tool, action, success, error "
            "FROM auth_audit"
        )
        conditions: list[str] = []
        params: list[Any] = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if success is not None:
            conditions.append("success = ?")
            params.append(int(success))
        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with _connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        log.warning("audit_query_failed", error=str(exc))
        return []


def audit_stats() -> dict[str, Any]:
    """Return summary stats for the audit log. Fail-soft."""
    try:
        with _connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM auth_audit").fetchone()[0]
            failures = conn.execute(
                "SELECT COUNT(*) FROM auth_audit WHERE success = 0"
            ).fetchone()[0]
            by_action = conn.execute(
                "SELECT action, COUNT(*) as cnt FROM auth_audit GROUP BY action "
                "ORDER BY cnt DESC LIMIT 20"
            ).fetchall()
        return {
            "enabled": _ENABLED,
            "total": total,
            "failures": failures,
            "retention_days": _RETENTION_DAYS,
            "by_action": {r[0]: r[1] for r in by_action},
        }
    except Exception as exc:
        log.warning("audit_stats_failed", error=str(exc))
        return {"enabled": _ENABLED, "error": str(exc)}


__all__ = [
    "audit_enabled",
    "ensure_audit_table",
    "record_audit_event",
    "prune_audit_log",
    "query_audit_log",
    "audit_stats",
]
