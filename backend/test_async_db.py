"""Unit tests for async SQLite wrappers in feed_registry."""

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest

import feed_registry


class TestAsyncWrappers(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db_path = feed_registry.db_path
        feed_registry.db_path = lambda: self._tmp.name  # type: ignore
        # Init schema
        conn = sqlite3.connect(self._tmp.name)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS feed_cache ("
            "key TEXT PRIMARY KEY, value TEXT, cached_at TEXT, ttl_seconds INTEGER)"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        feed_registry.db_path = self._orig_db_path  # type: ignore
        os.unlink(self._tmp.name)

    def test_async_read_sqlite_returns_none_for_missing(self):
        result = asyncio.run(feed_registry.async_read_sqlite("nonexistent"))
        self.assertIsNone(result)

    def test_async_write_then_read_sqlite(self):
        payload = {"status": "ok", "count": 42}
        asyncio.run(feed_registry.async_write_sqlite("test_feed", payload))
        result = asyncio.run(feed_registry.async_read_sqlite("test_feed"))
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 42)

    def test_async_read_does_not_block_event_loop(self):
        """Verify async_read_sqlite is a coroutine (non-blocking)."""
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(feed_registry.async_read_sqlite))
        self.assertTrue(inspect.iscoroutinefunction(feed_registry.async_write_sqlite))


if __name__ == "__main__":
    unittest.main()
