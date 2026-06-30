"""DuckDB connection management for the FtM entity store.

Single in-process connection guarded by an RLock. Includes FATAL/invalidated
recovery logic (B-02 light) and the ``_run_with_recovery`` wrapper used by
all CRUD operations in ``ftm_store`` / ``ftm_schema`` / ``ftm_query``.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import duckdb

from structured_log import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Globals (single in-process connection, lock-guarded)
# ---------------------------------------------------------------------------

_DB_PATH: str | None = None
_CONN: duckdb.DuckDBPyConnection | None = None
_LOCK = threading.RLock()
_INIT_ERROR: str | None = None

# Thread-local secondary connections for lock-free reads. DuckDB supports
# multiple in-process connections; a single connection is not thread-safe.
_RO_CONN_LOCAL = threading.local()

# Whether the DuckDB spatial extension is loaded (enables R-Tree index + ST_Within)
_SPATIAL_LOADED: bool = False
# Whether LOAD spatial poisoned the connection — if so, never try again
_SPATIAL_POISONED: bool = False
# Recovery attempt counter — capped to prevent infinite recovery loops
_RECOVERY_ATTEMPTS: int = 0
_MAX_RECOVERY_ATTEMPTS: int = 3


# ---------------------------------------------------------------------------
# Path configuration
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "entities.duckdb")


def set_db_path(path: str | None = None) -> None:
    """Configure the DuckDB file path (call before init_store)."""
    global _DB_PATH
    _DB_PATH = path or os.getenv("WORLDBASE_FTM_DB_PATH") or _default_db_path()
    # Invalidate any thread-local read connections pointing at the old path
    _clear_ro_connections()


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


def _clear_ro_connections() -> None:
    """Close and clear all thread-local read connections (called on path change/reset)."""
    con = getattr(_RO_CONN_LOCAL, "con", None)
    if con is not None:
        try:
            con.close()
        except Exception:
            pass
        _RO_CONN_LOCAL.con = None


def _configure_connection(con: duckdb.DuckDBPyConnection) -> None:
    """Tune the embedded store. Single-writer: one in-process connection + _LOCK.

    DuckDB does not support SQLite ``PRAGMA journal_mode`` / ``locking_mode``.
    Do not open ``entities.duckdb`` from a second process while the API runs.
    """
    global _SPATIAL_LOADED, _SPATIAL_POISONED
    try:
        con.execute("SET checkpoint_threshold='16MB'")
    except Exception:
        pass
    # Load the spatial extension for R-Tree index + ST_Within/ST_Intersects.
    # Fail-soft: if the extension is unavailable (e.g. air-gapped Docker),
    # queries fall back to lat/lon BETWEEN filtering.
    if _SPATIAL_POISONED:
        _SPATIAL_LOADED = False
        return
    if os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        _SPATIAL_LOADED = False
        return
    try:
        con.execute("INSTALL spatial")
        con.execute("LOAD spatial")
        _SPATIAL_LOADED = True
    except Exception as exc:
        log.warning("duckdb_spatial_extension_unavailable", error=str(exc)[:200])
        _SPATIAL_LOADED = False
        if _is_invalidated_error(exc):
            _SPATIAL_POISONED = True
            log.warning("duckdb_spatial_poisoned", error=str(exc)[:200])


def spatial_available() -> bool:
    """True when the DuckDB spatial extension is loaded and ready."""
    return _SPATIAL_LOADED


def _conn() -> duckdb.DuckDBPyConnection:
    global _CONN, _INIT_ERROR
    if _CONN is not None:
        return _CONN
    if not _DB_PATH:
        set_db_path()
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)  # type: ignore[arg-type]
    try:
        _CONN = duckdb.connect(_DB_PATH)  # type: ignore[arg-type]
        _configure_connection(_CONN)
        # Defer schema creation to ftm_schema to avoid circular import
        from ftm_schema import _create_schema

        _create_schema(_CONN)
        _INIT_ERROR = None
    except Exception as exc:
        _INIT_ERROR = str(exc)
        raise
    return _CONN


def store_ready() -> bool:
    """True when DuckDB is open in this process."""
    return _CONN is not None


def store_status(*, _recover: bool = True) -> dict[str, Any]:
    """Compact readiness for /api/health and operator monitors.

    On DuckDB FATAL/invalidated, closes and reopens the file once (B-02 light).
    If soft reset fails, tries a hard reset (zero-downtime swap → delete fallback).
    """
    if _CONN is not None:
        try:
            with _LOCK:
                n = _CONN.execute("SELECT count(*) FROM entities").fetchone()[0]
            return {"ready": True, "entities": int(n), "error": None}
        except Exception as exc:
            if _recover and _is_invalidated_error(exc):
                log.warning("ftm_store_invalidated", error=str(exc))
                reset_store()
                status = store_status(_recover=False)
                if not status["ready"] and _is_invalidated_error(
                    Exception(status.get("error") or "")
                ):
                    log.warning("ftm_store_hard_reset", error=str(exc))
                    reset_store(hard=True)
                    return store_status(_recover=False)
                return status
            return {"ready": False, "entities": 0, "error": str(exc)}
    if _recover:
        if init_store():
            return store_status(_recover=False)
    return {"ready": False, "entities": 0, "error": _INIT_ERROR or "not initialized"}


def init_store() -> bool:
    """Idempotent: open the connection and ensure the schema exists (fail-soft)."""
    global _CONN, _INIT_ERROR, _RECOVERY_ATTEMPTS
    if _RECOVERY_ATTEMPTS >= _MAX_RECOVERY_ATTEMPTS:
        _INIT_ERROR = (
            _INIT_ERROR or f"recovery exhausted after {_RECOVERY_ATTEMPTS} attempts"
        )
        return False
    try:
        with _LOCK:
            con = _conn()
            con.execute("SELECT 1").fetchone()
        _INIT_ERROR = None
        _RECOVERY_ATTEMPTS = 0
        return True
    except Exception as exc:
        if _is_invalidated_error(exc):
            _RECOVERY_ATTEMPTS += 1
            log.warning(
                "ftm_init_probe_failed", error=str(exc), attempt=_RECOVERY_ATTEMPTS
            )
            with _LOCK:
                if _CONN is not None:
                    try:
                        _CONN.close()
                    except Exception:
                        pass
                    _CONN = None
                _INIT_ERROR = None
            # Soft retry: reopen same file
            retry_exc: Exception | None = None
            try:
                with _LOCK:
                    _conn().execute("SELECT 1").fetchone()
                _INIT_ERROR = None
                return True
            except Exception as exc_retry:
                retry_exc = exc_retry
                log.warning("ftm_init_soft_retry_failed", error=str(retry_exc))
            # Hard retry: zero-downtime swap (salvage data) → fallback to delete
            if _DB_PATH and os.path.exists(_DB_PATH):
                if _zero_downtime_enabled():
                    if _rebuild_and_swap():
                        return True
                    log.warning("ftm_init_zero_downtime_failed_fallback_to_hard_reset")
                # Fallback: delete corrupted file and recreate
                try:
                    os.remove(_DB_PATH)
                    log.info("ftm_init_hard_reset", path=_DB_PATH, action="deleted")
                except OSError as rm_exc:
                    log.warning("ftm_init_hard_reset_failed", error=str(rm_exc))
                _CONN = None
                _INIT_ERROR = None
                _clear_ro_connections()
                try:
                    with _LOCK:
                        _conn().execute("SELECT 1").fetchone()
                    _INIT_ERROR = None
                    return True
                except Exception as hard_exc:
                    exc = hard_exc
            elif retry_exc is not None:
                exc = retry_exc
        _INIT_ERROR = str(exc)
        log.error("ftm_store_unavailable", error=str(exc))
        return False


def _rebuild_and_swap() -> bool:
    """Build a fresh DuckDB file with salvaged data and atomically swap it in.

    Instead of deleting the corrupted file (total data loss), this:
    1. Creates a recovery file with fresh schema
    2. ATTACHes the old (possibly corrupted) DB and copies whatever data is readable
    3. Atomically replaces the old file via ``os.replace``
    4. Preserves the old file as ``.bak`` for forensic inspection

    Returns True on success. On failure, falls back to the caller's existing
    hard-reset path (delete + recreate).
    """
    global _CONN, _INIT_ERROR
    if not _DB_PATH:
        set_db_path()
    db_path = _DB_PATH  # type: ignore[assignment]
    recovery_path = db_path + ".recovery"
    bak_path = db_path + ".bak"

    # Close current connection under lock
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        _INIT_ERROR = None
    _clear_ro_connections()

    # Remove stale recovery file
    if os.path.exists(recovery_path):
        try:
            os.remove(recovery_path)
        except OSError:
            pass

    recovery_con: duckdb.DuckDBPyConnection | None = None
    try:
        # 1. Create fresh recovery DB with schema
        recovery_con = duckdb.connect(recovery_path)
        _configure_connection(recovery_con)
        from ftm_schema import _create_schema

        _create_schema(recovery_con)

        # 2. Salvage data from old file via ATTACH
        if os.path.exists(db_path):
            try:
                recovery_con.execute(f"ATTACH '{db_path}' AS old_db")
                for table in ("entities", "statements", "edges", "resolution_labels"):
                    try:
                        recovery_con.execute(
                            f"INSERT INTO {table} SELECT * FROM old_db.{table}"
                        )
                    except Exception as table_exc:
                        log.warning(
                            "ftm_recovery_salvage_table_failed",
                            table=table,
                            error=str(table_exc)[:200],
                        )
                recovery_con.execute("DETACH old_db")
                log.info("ftm_recovery_salvage_ok", path=db_path)
            except Exception as attach_exc:
                log.warning(
                    "ftm_recovery_salvage_failed",
                    path=db_path,
                    error=str(attach_exc)[:200],
                )
                # Old file completely unreadable — proceed with empty schema

        recovery_con.close()
        recovery_con = None

        # 3. Backup old file and atomically swap
        if os.path.exists(bak_path):
            try:
                os.remove(bak_path)
            except OSError:
                pass
        # Move old WAL alongside .bak (orphaned WAL causes geometry replay crash)
        _old_wal = db_path + ".wal"
        if os.path.exists(_old_wal):
            try:
                os.replace(_old_wal, bak_path + ".wal")
            except OSError:
                pass
        if os.path.exists(db_path):
            os.replace(db_path, bak_path)
        os.replace(recovery_path, db_path)
        log.info("ftm_recovery_swap_ok", path=db_path, backup=bak_path)

        # 4. Reopen
        return init_store()

    except Exception as exc:
        log.error("ftm_recovery_swap_failed", error=str(exc)[:200])
        # Clean up recovery file
        if recovery_con is not None:
            try:
                recovery_con.close()
            except Exception:
                pass
        if os.path.exists(recovery_path):
            try:
                os.remove(recovery_path)
            except OSError:
                pass
        # Try to restore from .bak if we already moved it
        if not os.path.exists(db_path) and os.path.exists(bak_path):
            try:
                os.replace(bak_path, db_path)
            except OSError:
                pass
        return False


def _zero_downtime_enabled() -> bool:
    """True when zero-downtime recovery is enabled (default on)."""
    return os.getenv("WORLDBASE_DUCKDB_ZERO_DOWNTIME", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def reset_store(*, hard: bool = False) -> bool:
    """Close and reopen DuckDB after a fatal/invalidated connection.

    When ``hard=True``, attempt zero-downtime recovery first (build fresh DB
    with salvaged data, atomically swap). Falls back to delete+recreate if
    the zero-downtime path fails or is disabled.
    """
    global _CONN, _INIT_ERROR
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        _INIT_ERROR = None
    _clear_ro_connections()
    if hard and _DB_PATH:
        if _zero_downtime_enabled():
            if _rebuild_and_swap():
                return True
            log.warning("ftm_zero_downtime_failed_fallback_to_hard_reset")
        # Fallback: old delete + recreate path
        if os.path.exists(_DB_PATH):
            try:
                os.remove(_DB_PATH)
                log.info("ftm_hard_reset", path=_DB_PATH, action="deleted")
            except OSError as exc:
                log.warning("ftm_hard_reset_failed", path=_DB_PATH, error=str(exc))
        # Also remove the WAL file — an orphaned WAL with geometry types
        # causes "Unsupported geometry type in legacy geometry" on replay.
        _wal = _DB_PATH + ".wal"
        if os.path.exists(_wal):
            try:
                os.remove(_wal)
                log.info("ftm_hard_reset_wal_deleted", path=_wal)
            except OSError as exc:
                log.warning("ftm_hard_reset_wal_failed", path=_wal, error=str(exc))
    return init_store()


# ---------------------------------------------------------------------------
# Error classification + recovery wrapper
# ---------------------------------------------------------------------------


def _is_invalidated_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return (
        "invalidated" in msg
        or "fatal error" in msg
        or "delete all rows from index" in msg
    )


def _run_with_recovery(fn):
    """Run ``fn(con)`` under the process lock; retry after reset on DuckDB FATAL.

    First attempt: normal execution.
    Second attempt (soft reset): close and reopen the same file.
    Third attempt (hard reset): zero-downtime swap (salvage data) → delete fallback.
    """
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            if _CONN is None and not init_store():
                raise RuntimeError(
                    store_status(_recover=False).get("error") or "ftm store unavailable"
                )
            with _LOCK:
                return fn(_conn())
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_invalidated_error(exc):
                log.warning("ftm_operation_failed", error=str(exc))
                reset_store()
                continue
            if attempt == 1 and _is_invalidated_error(exc):
                log.warning("ftm_operation_failed_after_soft_reset", error=str(exc))
                reset_store(hard=True)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("ftm store unavailable")


def _ro_conn() -> duckdb.DuckDBPyConnection:
    """Return a thread-local secondary connection for lock-free reads.

    A single DuckDB connection is not thread-safe; each thread that needs to
    read concurrently with the writer gets its own connection to the same
    on-disk database. DuckDB MVCC keeps this consistent.
    """
    con = getattr(_RO_CONN_LOCAL, "con", None)
    if con is None:
        if not _DB_PATH:
            set_db_path()
        # Ensure the main connection (and therefore schema) exists first.
        _conn()
        con = duckdb.connect(_DB_PATH)
        _configure_connection(con)
        _RO_CONN_LOCAL.con = con
    return con


def run_query(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list:
    """Run a read query on the process store connection (same thread as init_store)."""
    return _run_with_recovery(
        lambda con: con.execute(sql, list(params or ())).fetchall()
    )


def run_query_ro(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list:
    """Run a read query on a thread-local secondary connection without the global lock."""
    return _ro_conn().execute(sql, list(params or ())).fetchall()
