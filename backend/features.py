"""Dynamic feature flags — SQLite-backed with TTL cache and env precedence.

Design:
- ``feature_flags`` table in ``worldbase.db`` stores runtime overrides.
- ``feature_flag_log`` table records every toggle (audit trail).
- ``is_enabled(key)`` checks SQLite first (5s TTL cache), then falls back
  to the env-var default.
- ``WORLDBASE_FLAG_OVERRIDE=env`` forces env-only mode (ignores SQLite).
- Zero overhead when ``WORLDBASE_ADMIN_FLAGS=0`` — ``is_enabled`` reads
  env directly without touching SQLite.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from sqlite_bootstrap import DB_PATH

_CACHE_TTL = 5.0  # seconds
_cache: dict[str, tuple[bool, float]] = {}
_cache_lock = threading.Lock()

_flag_override_env = os.getenv("WORLDBASE_FLAG_OVERRIDE", "").strip().lower()


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def init_feature_flags_db() -> None:
    """Create tables if missing. Called once on startup."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                key TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                updated_by TEXT
            );
            CREATE TABLE IF NOT EXISTS feature_flag_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                old_value INTEGER,
                new_value INTEGER,
                updated_by TEXT,
                at TEXT NOT NULL
            );
        """)
        conn.commit()


def _env_default(key: str) -> bool:
    """Read the env-var default for a flag key.

    Convention: flag key ``chat_agentic`` → env ``WORLDBASE_CHAT_AGENTIC``.
    """
    env_name = f"WORLDBASE_{key.upper()}"
    return _truthy(os.getenv(env_name))


def _flag_override_env_only() -> bool:
    return _flag_override_env == "env"


def is_enabled(key: str) -> bool:
    """Check if a feature flag is enabled.

    Precedence (when ``WORLDBASE_ADMIN_FLAGS != 0``):
    1. SQLite override (if row exists) — cached for 5s
    2. Env-var default (``WORLDBASE_{KEY_UPPER}``)

    When ``WORLDBASE_ADMIN_FLAGS=0`` or ``WORLDBASE_FLAG_OVERRIDE=env``:
    always reads env directly, no SQLite access.
    """
    admin_enabled = _truthy(os.getenv("WORLDBASE_ADMIN_FLAGS", "1"))
    if not admin_enabled or _flag_override_env_only():
        return _env_default(key)

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and (now - cached[1]) < _CACHE_TTL:
            return cached[0]

    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT enabled FROM feature_flags WHERE key = ?", (key,)
            ).fetchone()
    except sqlite3.OperationalError:
        # Table doesn't exist yet — fall back to env
        result = _env_default(key)
        with _cache_lock:
            _cache[key] = (result, now)
        return result

    if row is not None:
        result = bool(row["enabled"])
    else:
        result = _env_default(key)

    with _cache_lock:
        _cache[key] = (result, now)
    return result


def get_all_flags() -> list[dict]:
    """Return all known flags with their current state and source.

    Merges SQLite overrides with known env-var defaults.
    """
    admin_enabled = _truthy(os.getenv("WORLDBASE_ADMIN_FLAGS", "1"))
    if not admin_enabled or _flag_override_env_only():
        return _all_env_flags()

    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT key, enabled, updated_at, updated_by FROM feature_flags"
            ).fetchall()
    except sqlite3.OperationalError:
        return _all_env_flags()

    sqlite_flags = {r["key"]: dict(r) for r in rows}

    # Start with env defaults, overlay SQLite overrides
    result = _all_env_flags()
    for flag in result:
        key = flag["key"]
        if key in sqlite_flags:
            flag["enabled"] = bool(sqlite_flags[key]["enabled"])
            flag["source"] = "sqlite"
            flag["updated_at"] = sqlite_flags[key]["updated_at"]
            flag["updated_by"] = sqlite_flags[key]["updated_by"]
        else:
            flag["source"] = "env"

    # Add SQLite-only flags not in env registry
    env_keys = {f["key"] for f in result}
    for key, info in sqlite_flags.items():
        if key not in env_keys:
            result.append(
                {
                    "key": key,
                    "enabled": bool(info["enabled"]),
                    "source": "sqlite",
                    "updated_at": info["updated_at"],
                    "updated_by": info["updated_by"],
                }
            )

    return result


# Known feature flags and their env-var names
_KNOWN_FLAGS: list[str] = [
    "duckdb_queue",
    "chat_agentic",
    "query_router",
    "provenance",
    "intel_semantic_edges",
    "briefing_intel",
    "briefing_autopilot",
    "briefing_intel_subgraph",
    "intel_spatial_edges",
    "intel_sanction_edges",
    "rag_feed_ingest",
    "rag_rerank",
    "rag_spatial",
    "rag_crag",
    "slim_guard",
    "mcp",
    "mcp_write",
    "agent_bus",
    "feed_ingest_autopilot",
    "entity_resolution_autopilot",
    "entity_resolution_splink",
    "entity_resolution_after_feeds",
    "intel_glirel",
    "prediction_ledger",
    "briefing_agentic_loop",
    "rag_autopilot",
    "spatial_reasoning",
    "maritime_trajectory",
    "dynamic_graph",
    "ftm_statements",
    "lineage",
    "prompt_registry",
    "websocket",
    "rbac",
    "darkweb",
    "briefing_darkweb",
]


def _all_env_flags() -> list[dict]:
    """Return all known flags with their env-var defaults."""
    return [
        {
            "key": key,
            "enabled": _env_default(key),
            "source": "env",
            "updated_at": None,
            "updated_by": None,
        }
        for key in _KNOWN_FLAGS
    ]


def set_flag(key: str, enabled: bool, updated_by: str = "operator") -> dict:
    """Set a feature flag in SQLite and log the change.

    Returns the old and new values.
    """
    key = key.strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    # Read old value
    old_value = None
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT enabled FROM feature_flags WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                old_value = bool(row["enabled"])
    except sqlite3.OperationalError:
        pass

    # Upsert
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO feature_flags (key, enabled, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, 1 if enabled else 0, now, updated_by),
        )
        conn.execute(
            """
            INSERT INTO feature_flag_log (key, old_value, new_value, updated_by, at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                key,
                None if old_value is None else int(old_value),
                int(enabled),
                updated_by,
                now,
            ),
        )
        conn.commit()

    # Invalidate cache
    with _cache_lock:
        _cache.pop(key, None)

    return {
        "key": key,
        "old_value": old_value,
        "new_value": enabled,
        "updated_at": now,
        "updated_by": updated_by,
    }


def get_flag_log(limit: int = 100) -> list[dict]:
    """Return the audit log of flag changes."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT key, old_value, new_value, updated_by, at "
                "FROM feature_flag_log ORDER BY at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def clear_cache() -> None:
    """Clear the in-memory cache. Useful for tests."""
    with _cache_lock:
        _cache.clear()


def register_known_flag(key: str) -> None:
    """Register an additional known flag key at runtime."""
    key = key.strip().lower()
    if key not in _KNOWN_FLAGS:
        _KNOWN_FLAGS.append(key)
