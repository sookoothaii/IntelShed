"""Unit tests for the DuckDB Write-Through Queue (I1).

Tests cover:
- Direct mode (queue disabled) — backward compat passthrough
- Queue mode — serialization, WAL persistence, retry, DLQ
- Crash recovery — WAL replay
- Backpressure — QueueBacklogError on full queue
- Status endpoint data
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

# Ensure backend is importable
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import duckdb_queue
import ftm_query
import ftm_store


class TestQueueDisabled(unittest.TestCase):
    """When queue is disabled, operations pass through directly."""

    def setUp(self):
        if not ftm_store.init_store():
            self.skipTest("DuckDB unavailable")
        duckdb_queue._queue = None

    def test_upsert_direct(self):
        p = ftm_store.make_entity("Person", ["qtest1"], {"name": "Queue Test 1"})
        eid = ftm_store.upsert(p, dataset="test_queue")
        self.assertIsNotNone(eid)

    def test_add_edge_direct(self):
        ftm_store.add_edge("qtest_a", "qtest_b", "sameAs", dataset="test_queue")
        self.assertTrue(True)

    def test_status_disabled(self):
        q = duckdb_queue.get_queue()
        self.assertFalse(q.enabled)
        s = q.status()
        self.assertFalse(s["enabled"])


class TestQueueEnabled(unittest.TestCase):
    """Queue mode with WAL + retry + DLQ."""

    @classmethod
    def setUpClass(cls):
        if not ftm_store.init_store():
            raise unittest.SkipTest("DuckDB unavailable")
        duckdb_queue._queue = None

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="duckdb_queue_test_")
        self._wal_path = os.path.join(self._tmpdir, "test_wal.db")
        duckdb_queue._queue = None
        self.q = duckdb_queue.DuckDBWriterQueue(
            max_backlog=5, max_retries=2, wal_path=self._wal_path
        )
        duckdb_queue._queue = self.q
        self.q.enable()
        # Register ops from ftm_query
        duckdb_queue.register_op("upsert", ftm_query._op_upsert)
        duckdb_queue.register_op("add_edge", ftm_query._op_add_edge)
        duckdb_queue.register_op("delete_edges_for_dataset", ftm_query._op_delete_edges)
        duckdb_queue.register_op("import_entities", ftm_query._op_import_entities)

    def tearDown(self):
        self.q.disable()
        duckdb_queue._queue = None
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_queue_enabled_status(self):
        s = self.q.status()
        self.assertTrue(s["enabled"])
        self.assertEqual(s["backlog"], 0)
        self.assertEqual(s["dead_letters"], 0)

    def test_upsert_through_queue(self):
        p = ftm_store.make_entity("Person", ["qtest2"], {"name": "Queue Test 2"})
        eid = self.q.enqueue_sync("upsert", {
            "entity_dict": p.to_dict(),
            "dataset": "test_queue",
        })
        self.assertIsNotNone(eid)
        # Verify it landed in DuckDB
        ent = ftm_store.get_entity(eid)
        self.assertIsNotNone(ent)
        self.assertEqual(ent["schema"], "Person")

    def test_add_edge_through_queue(self):
        self.q.enqueue_sync("add_edge", {
            "source_id": "qtest_c",
            "target_id": "qtest_d",
            "kind": "sameAs",
            "dataset": "test_queue",
            "confidence": 0.9,
        })
        count = ftm_store.count_edges_for_dataset("test_queue")
        self.assertGreaterEqual(count, 1)

    def test_wal_persistence(self):
        """WAL row is created on enqueue and deleted on success."""
        p = ftm_store.make_entity("Person", ["qtest3"], {"name": "Queue Test 3"})
        self.q.enqueue_sync("upsert", {
            "entity_dict": p.to_dict(),
            "dataset": "test_queue",
        })
        # WAL should be empty after successful completion
        row = self.q._wal_conn.execute(
            "SELECT count(*) FROM duckdb_write_queue WHERE status = 'pending'"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_backpressure(self):
        """QueueFull raises QueueBacklogError when backlog exceeds max."""
        import threading

        block = threading.Event()
        processed = []

        def blocking_op(params):
            processed.append(True)
            block.wait(timeout=5)
            return "ok"

        duckdb_queue.register_op("blocking", blocking_op)

        # Put one task that will block the worker
        first = duckdb_queue.WriteTask(id="blk_0", op_name="blocking", params={})
        self.q._queue.put_nowait(first)

        # Wait for worker to pick it up
        time.sleep(0.3)

        # Now fill the rest of the queue (max_backlog=5, worker holds 1 → 5 slots free)
        for i in range(1, 6):
            self.q._queue.put_nowait(
                duckdb_queue.WriteTask(id=f"blk_{i}", op_name="blocking", params={})
            )

        # Next enqueue_sync should raise QueueBacklogError
        with self.assertRaises(duckdb_queue.QueueBacklogError):
            self.q.enqueue_sync("blocking", {})

        # Release the block so worker can drain
        block.set()

    def test_dlq_on_permanent_failure(self):
        """Task that fails all retries goes to DLQ."""
        def failing_op(params):
            raise RuntimeError("intentional failure")

        duckdb_queue.register_op("failing", failing_op)

        with self.assertRaises(RuntimeError):
            self.q.enqueue_sync("failing", {})

        # Should be in DLQ
        dlq = self.q.dlq_list()
        self.assertEqual(len(dlq), 1)
        self.assertEqual(dlq[0]["op_name"], "failing")
        self.assertIn("intentional", dlq[0]["error"])

    def test_dlq_clear(self):
        def failing_op(params):
            raise RuntimeError("fail")

        duckdb_queue.register_op("failing2", failing_op)

        with self.assertRaises(RuntimeError):
            self.q.enqueue_sync("failing2", {})

        cleared = self.q.dlq_clear()
        self.assertEqual(cleared, 1)
        self.assertEqual(len(self.q.dlq_list()), 0)


class TestWalReplay(unittest.TestCase):
    """Crash recovery: pending WAL rows are replayed on startup."""

    def setUp(self):
        if not ftm_store.init_store():
            self.skipTest("DuckDB unavailable")
        self._tmpdir = tempfile.mkdtemp(prefix="duckdb_queue_replay_")
        self._wal_path = os.path.join(self._tmpdir, "replay_wal.db")

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_replay_pending_tasks(self):
        """A WAL row with status='pending' is replayed when queue enables."""
        # Create a queue, enqueue a task, but kill worker before it processes
        duckdb_queue._queue = None
        q1 = duckdb_queue.DuckDBWriterQueue(
            max_backlog=10, max_retries=1, wal_path=self._wal_path
        )
        duckdb_queue._queue = q1
        q1.enable()
        duckdb_queue.register_op("upsert", ftm_query._op_upsert)

        # Manually insert a pending WAL row (simulating crash before processing)
        q1._wal_conn.execute(
            "INSERT INTO duckdb_write_queue "
            "(id, op_name, params, retry_count, status, created_at, error, result) "
            "VALUES (?, ?, ?, 0, 'pending', ?, NULL, NULL)",
            (
                "replay-test-1",
                "add_edge",
                '{"source_id": "replay_a", "target_id": "replay_b", "kind": "sameAs", "dataset": "test_replay", "confidence": 1.0}',
                time.time(),
            ),
        )
        q1.disable()

        # Re-enable — should replay the pending task
        duckdb_queue.register_op("add_edge", ftm_query._op_add_edge)
        q2 = duckdb_queue.DuckDBWriterQueue(
            max_backlog=10, max_retries=1, wal_path=self._wal_path
        )
        duckdb_queue._queue = q2
        q2.enable()

        # Give worker time to process
        time.sleep(0.5)

        # WAL should be drained
        row = q2._wal_conn.execute(
            "SELECT count(*) FROM duckdb_write_queue WHERE status = 'pending'"
        ).fetchone()
        self.assertEqual(row[0], 0)

        # Edge should exist in DuckDB
        count = ftm_store.count_edges_for_dataset("test_replay")
        self.assertGreaterEqual(count, 1)

        q2.disable()
        duckdb_queue._queue = None


class TestAsyncEnqueue(unittest.TestCase):
    """Async enqueue returns task_id for polling."""

    def setUp(self):
        if not ftm_store.init_store():
            self.skipTest("DuckDB unavailable")
        self._tmpdir = tempfile.mkdtemp(prefix="duckdb_queue_async_")
        self._wal_path = os.path.join(self._tmpdir, "async_wal.db")
        duckdb_queue._queue = None
        self.q = duckdb_queue.DuckDBWriterQueue(
            max_backlog=10, max_retries=2, wal_path=self._wal_path
        )
        duckdb_queue._queue = self.q
        self.q.enable()
        duckdb_queue.register_op("upsert", ftm_query._op_upsert)

    def tearDown(self):
        self.q.disable()
        duckdb_queue._queue = None
        import shutil

        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_async_enqueue_and_poll(self):
        import asyncio

        async def _run():
            p = ftm_store.make_entity("Person", ["qtest_async"], {"name": "Async Test"})
            task_id = await self.q.enqueue_async("upsert", {
                "entity_dict": p.to_dict(),
                "dataset": "test_queue",
            })
            self.assertFalse(task_id.startswith("direct:"))
            # Poll until done
            for _ in range(20):
                status = self.q.get_task_status(task_id)
                if status is None:
                    break
                if status["status"] not in ("pending", "processing"):
                    break
                await asyncio.sleep(0.1)
            # Task should be completed (WAL row deleted → status is None)
            return task_id

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
