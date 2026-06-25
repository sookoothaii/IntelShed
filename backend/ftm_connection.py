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


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


def _configure_connection(con: duckdb.DuckDBPyConnection) -> None:
    """Tune the embedded store. Single-writer: one in-process connection + _LOCK.

    DuckDB does not support SQLite ``PRAGMA journal_mode`` / ``locking_mode``.
    Do not open ``entities.duckdb`` from a second process while the API runs.
    """
    try:
        con.execute("SET checkpoint_threshold='16MB'")
    except Exception:
        pass


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
                return store_status(_recover=False)
            return {"ready": False, "entities": 0, "error": str(exc)}
    if _recover:
        if init_store():
            return store_status(_recover=False)
    return {"ready": False, "entities": 0, "error": _INIT_ERROR or "not initialized"}


def init_store() -> bool:
    """Idempotent: open the connection and ensure the schema exists (fail-soft)."""
    global _CONN, _INIT_ERROR
    try:
        with _LOCK:
            con = _conn()
            con.execute("SELECT 1").fetchone()
        _INIT_ERROR = None
        return True
    except Exception as exc:
        if _is_invalidated_error(exc):
            log.warning("ftm_init_probe_failed", error=str(exc))
            with _LOCK:
                if _CONN is not None:
                    try:
                        _CONN.close()
                    except Exception:
                        pass
                    _CONN = None
                _INIT_ERROR = None
            try:
                with _LOCK:
                    _conn().execute("SELECT 1").fetchone()
                _INIT_ERROR = None
                return True
            except Exception as retry_exc:
                exc = retry_exc
        _INIT_ERROR = str(exc)
        log.error("ftm_store_unavailable", error=str(exc))
        return False


def reset_store() -> bool:
    """Close and reopen DuckDB after a fatal/invalidated connection."""
    global _CONN, _INIT_ERROR
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        _INIT_ERROR = None
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
    """Run ``fn(con)`` under the process lock; retry once after reset on DuckDB FATAL."""
    last_exc: Exception | None = None
    for attempt in range(2):
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
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("ftm store unavailable")


def run_query(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list:
    """Run a read query on the process store connection (same thread as init_store)."""
    return _run_with_recovery(
        lambda con: con.execute(sql, list(params or ())).fetchall()
    )
