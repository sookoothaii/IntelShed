"""DuckDB Write-Through Queue with SQLite WAL + Retry + Dead-Letter Queue.

Serializes all DuckDB write operations through a dedicated worker thread.
Every write is persisted to SQLite (WAL mode) *before* attempting DuckDB,
so a process crash mid-batch loses nothing — pending ops are replayed on
startup.

When ``WORLDBASE_DUCKDB_QUEUE=0`` (default), all operations pass through
directly with zero overhead — backward compatible.

Architecture
------------
    caller ──> enqueue_sync(op_name, params)
                      │
                      ├── persist to SQLite WAL (duckdb_write_queue)
                      ├── put WriteTask on queue.Queue
                      └── block on threading.Event until worker finishes

    Worker Thread (daemon):
        dequeue ──> _OPS[op_name](params) ──> retry 3x (100/200/400ms)
                   ├── success: delete from WAL, set event
                   └── failure:  mark 'dead' in WAL (DLQ), set event with error

    Startup: replay all 'pending'/'processing' WAL rows (crash recovery)
    Shutdown: signal + join(10s timeout)
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from structured_log import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Operation registry
# ---------------------------------------------------------------------------

_OPS: dict[str, Callable[[dict], Any]] = {}


def register_op(name: str, fn: Callable[[dict], Any]) -> None:
    """Register a handler for a named write operation."""
    _OPS[name] = fn


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class WriteTask:
    id: str
    op_name: str
    params: dict
    retry_count: int = 0
    # For sync callers: worker sets event + result
    done_event: threading.Event | None = None
    result: dict = field(default_factory=dict)


class QueueBacklogError(Exception):
    """Raised when queue backlog exceeds max_backlog."""


class QueueDisabledError(Exception):
    """Raised when queue is not enabled but async operations are attempted."""


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class DuckDBWriterQueue:
    """Single-worker queue for DuckDB write serialization."""

    def __init__(
        self,
        max_backlog: int = 50,
        max_retries: int = 3,
        wal_path: str | None = None,
    ) -> None:
        self._queue: queue.Queue[WriteTask] = queue.Queue(maxsize=max_backlog)
        self._max_backlog = max_backlog
        self._max_retries = max_retries
        self._worker_thread: threading.Thread | None = None
        self._shutting_down = False
        self._enabled = False

        self._wal_path = wal_path or os.getenv(
            "WORLDBASE_DB_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db"),
        )
        self._wal_conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """Initialize WAL table, replay pending tasks, start worker thread."""
        if self._enabled:
            return
        self._wal_conn = sqlite3.connect(
            self._wal_path, check_same_thread=False, isolation_level=None
        )
        self._wal_conn.execute("PRAGMA journal_mode=WAL")
        self._wal_conn.execute("PRAGMA busy_timeout=5000")
        self._wal_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS duckdb_write_queue (
                id           TEXT PRIMARY KEY,
                op_name      TEXT NOT NULL,
                params       TEXT NOT NULL,
                retry_count  INTEGER DEFAULT 0,
                status       TEXT DEFAULT 'pending',
                created_at   REAL,
                error        TEXT,
                result       TEXT
            )
            """
        )
        self._enabled = True
        replayed = self._replay_wal()
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="duckdb-writer", daemon=True
        )
        self._worker_thread.start()
        log.info("duckdb_queue_enabled", replayed=replayed, backlog=self._queue.qsize())

    def disable(self) -> None:
        """Drain queue and shut down worker (10s timeout)."""
        if not self._enabled:
            return
        self._shutting_down = True
        if self._worker_thread:
            self._worker_thread.join(timeout=10.0)
        if self._wal_conn:
            self._wal_conn.close()
            self._wal_conn = None
        self._enabled = False
        self._shutting_down = False
        log.info("duckdb_queue_disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def backlog(self) -> int:
        return self._queue.qsize()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue_sync(self, op_name: str, params: dict) -> Any:
        """Enqueue and block until result. Raises on failure.

        When queue is disabled, calls the operation directly — zero overhead.
        """
        if not self._enabled:
            fn = _OPS.get(op_name)
            if not fn:
                raise ValueError(f"unknown op: {op_name}")
            return fn(params)

        task_id = str(uuid.uuid4())
        event = threading.Event()
        task = WriteTask(id=task_id, op_name=op_name, params=params, done_event=event)

        # WAL before queue — crash safety
        self._persist_wal(task)
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            self._delete_wal(task_id)
            raise QueueBacklogError(
                f"backlog {self._queue.qsize()} >= max {self._max_backlog}"
            )

        # Block until worker processes
        event.wait()
        if task.result.get("error"):
            raise task.result["error"]
        return task.result.get("result")

    async def enqueue_async(self, op_name: str, params: dict) -> str:
        """Non-blocking enqueue, returns task_id for polling.

        When queue is disabled, executes directly via to_thread and returns
        a pseudo task_id starting with ``direct:``.
        """
        import asyncio

        if not self._enabled:
            fn = _OPS.get(op_name)
            if not fn:
                raise ValueError(f"unknown op: {op_name}")
            result = await asyncio.to_thread(fn, params)
            return f"direct:{json.dumps(result, default=str)}"

        task_id = str(uuid.uuid4())
        task = WriteTask(id=task_id, op_name=op_name, params=params)
        self._persist_wal(task)
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            self._delete_wal(task_id)
            raise QueueBacklogError(
                f"backlog {self._queue.qsize()} >= max {self._max_backlog}"
            )
        return task_id

    def get_task_status(self, task_id: str) -> dict | None:
        """Poll task status from WAL."""
        if not self._wal_conn:
            return None
        row = self._wal_conn.execute(
            "SELECT status, error, result FROM duckdb_write_queue WHERE id = ?",
            (task_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "status": row[0],
            "error": row[1],
            "result": json.loads(row[2]) if row[2] else None,
        }

    # ------------------------------------------------------------------
    # Dead-Letter Queue
    # ------------------------------------------------------------------

    def dlq_list(self) -> list[dict]:
        """List dead-letter tasks for manual replay."""
        if not self._wal_conn:
            return []
        rows = self._wal_conn.execute(
            "SELECT id, op_name, params, retry_count, error, created_at "
            "FROM duckdb_write_queue WHERE status = 'dead' ORDER BY created_at DESC"
        ).fetchall()
        return [
            {
                "id": r[0],
                "op_name": r[1],
                "params": json.loads(r[2]),
                "retry_count": r[3],
                "error": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    def dlq_replay(self, task_id: str) -> str:
        """Re-enqueue a dead-letter task. Returns new task_id."""
        if not self._wal_conn:
            raise QueueDisabledError("queue not enabled")
        row = self._wal_conn.execute(
            "SELECT op_name, params FROM duckdb_write_queue WHERE id = ? AND status = 'dead'",
            (task_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"no dead task {task_id}")
        new_id = str(uuid.uuid4())
        task = WriteTask(id=new_id, op_name=row[0], params=json.loads(row[1]))
        self._persist_wal(task)
        self._wal_conn.execute(
            "UPDATE duckdb_write_queue SET status = 'replayed' WHERE id = ?",
            (task_id,),
        )
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            self._delete_wal(new_id)
            raise QueueBacklogError(
                f"backlog {self._queue.qsize()} >= max {self._max_backlog}"
            )
        return new_id

    def dlq_clear(self) -> int:
        """Remove all dead-letter entries. Returns count cleared."""
        if not self._wal_conn:
            return 0
        cur = self._wal_conn.execute(
            "DELETE FROM duckdb_write_queue WHERE status = 'dead'"
        )
        return cur.rowcount or 0

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Queue status for /api/health."""
        if not self._enabled:
            return {"enabled": False, "backlog": 0}
        dead = 0
        if self._wal_conn:
            row = self._wal_conn.execute(
                "SELECT count(*) FROM duckdb_write_queue WHERE status = 'dead'"
            ).fetchone()
            dead = int(row[0] if row else 0)
        return {
            "enabled": True,
            "backlog": self._queue.qsize(),
            "dead_letters": dead,
            "max_backlog": self._max_backlog,
            "max_retries": self._max_retries,
        }

    # ------------------------------------------------------------------
    # Internal — WAL
    # ------------------------------------------------------------------

    def _persist_wal(self, task: WriteTask) -> None:
        if not self._wal_conn:
            return
        self._wal_conn.execute(
            "INSERT OR REPLACE INTO duckdb_write_queue "
            "(id, op_name, params, retry_count, status, created_at, error, result) "
            "VALUES (?, ?, ?, ?, 'pending', ?, NULL, NULL)",
            (
                task.id,
                task.op_name,
                json.dumps(task.params, default=str),
                task.retry_count,
                time.time(),
            ),
        )

    def _delete_wal(self, task_id: str) -> None:
        if not self._wal_conn:
            return
        self._wal_conn.execute(
            "DELETE FROM duckdb_write_queue WHERE id = ?", (task_id,)
        )

    def _mark_done_wal(self, task_id: str) -> None:
        if not self._wal_conn:
            return
        self._wal_conn.execute(
            "DELETE FROM duckdb_write_queue WHERE id = ?", (task_id,)
        )

    def _mark_dead_wal(self, task_id: str, error: str) -> None:
        if not self._wal_conn:
            return
        self._wal_conn.execute(
            "UPDATE duckdb_write_queue SET status = 'dead', error = ? WHERE id = ?",
            (error, task_id),
        )

    def _update_retry_wal(self, task_id: str, retry_count: int) -> None:
        if not self._wal_conn:
            return
        self._wal_conn.execute(
            "UPDATE duckdb_write_queue SET retry_count = ? WHERE id = ?",
            (retry_count, task_id),
        )

    def _replay_wal(self) -> int:
        """Re-enqueue pending/processing tasks from a previous crash."""
        if not self._wal_conn:
            return 0
        rows = self._wal_conn.execute(
            "SELECT id, op_name, params, retry_count FROM duckdb_write_queue "
            "WHERE status IN ('pending', 'processing')"
        ).fetchall()
        replayed = 0
        for r in rows:
            task = WriteTask(
                id=r[0],
                op_name=r[1],
                params=json.loads(r[2]),
                retry_count=r[3],
            )
            try:
                self._queue.put_nowait(task)
                replayed += 1
            except queue.Full:
                log.warning("duckdb_queue_replay_full", task_id=r[0])
                break
        if replayed:
            log.info("duckdb_queue_replayed", tasks=replayed)
        return replayed

    # ------------------------------------------------------------------
    # Internal — Worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._shutting_down:
            try:
                task = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            success = False
            error: Exception | None = None
            result: Any = None

            for attempt in range(self._max_retries + 1):
                try:
                    fn = _OPS.get(task.op_name)
                    if not fn:
                        raise ValueError(f"unknown op: {task.op_name}")
                    result = fn(task.params)
                    success = True
                    break
                except Exception as exc:
                    error = exc
                    if attempt < self._max_retries:
                        time.sleep(0.1 * (2**attempt))
                        task.retry_count = attempt + 1
                        self._update_retry_wal(task.id, task.retry_count)
                        continue
                    break

            if success:
                self._mark_done_wal(task.id)
            else:
                self._mark_dead_wal(task.id, str(error) if error else "unknown")
                log.error(
                    "duckdb_write_dead",
                    task_id=task.id,
                    op=task.op_name,
                    error=str(error) if error else "unknown",
                )

            # Notify sync caller
            if task.done_event:
                if success:
                    task.result = {"result": result}
                else:
                    task.result = {"error": error or RuntimeError("unknown")}
                task.done_event.set()

            self._queue.task_done()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_queue: DuckDBWriterQueue | None = None


def get_queue() -> DuckDBWriterQueue:
    global _queue
    if _queue is None:
        _queue = DuckDBWriterQueue()
    return _queue


def is_enabled() -> bool:
    return _queue is not None and _queue.enabled
