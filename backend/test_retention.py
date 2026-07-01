"""Tests for V4-07 — Data retention policies and TTL pruning."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone


class TestRetention(unittest.TestCase):
    """Retention policy CRUD and pruning."""

    _test_counter = 0

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        os.environ["WORLDBASE_DB_PATH"] = os.path.join(
            cls._tmpdir.name, "test_retention.db"
        )

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("WORLDBASE_DB_PATH", None)
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        TestRetention._test_counter += 1
        self._db_path = os.path.join(
            self._tmpdir.name, f"test_retention_{TestRetention._test_counter}.db"
        )
        os.environ["WORLDBASE_DB_PATH"] = self._db_path

    def test_ensure_tables(self):
        import retention

        retention._ensure_retention_tables()
        conn = sqlite3.connect(self._db_path)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        self.assertIn("retention_policies", tables)
        self.assertIn("retention_log", tables)

    def test_default_policies_seeded(self):
        import retention

        retention._ensure_retention_tables()
        policies = retention.list_policies()
        self.assertGreaterEqual(len(policies), 3)
        names = [p["table_name"] for p in policies]
        self.assertIn("feed_cache", names)
        self.assertIn("auth_audit", names)

    def test_create_policy(self):
        import retention

        retention._ensure_retention_tables()
        policy = retention.create_policy(
            "test_table", "sqlite", ttl_days=30, timestamp_column="created_at"
        )
        self.assertEqual(policy["table_name"], "test_table")
        self.assertEqual(policy["ttl_days"], 30)
        self.assertTrue(policy["enabled"])

    def test_update_policy(self):
        import retention

        retention._ensure_retention_tables()
        policy = retention.create_policy(
            "update_test", "sqlite", ttl_days=10, timestamp_column="created_at"
        )
        policy_id = policy["id"]
        updated = retention.update_policy(policy_id, ttl_days=60, enabled=False)
        self.assertEqual(updated["ttl_days"], 60)
        self.assertFalse(updated["enabled"])

    def test_delete_policy(self):
        import retention

        retention._ensure_retention_tables()
        policy = retention.create_policy(
            "delete_me", "sqlite", ttl_days=5, timestamp_column="created_at"
        )
        policy_id = policy["id"]
        self.assertTrue(retention.delete_policy(policy_id))
        self.assertIsNone(retention.get_policy(policy_id))

    def test_prune_table_sqlite(self):
        import retention

        retention._ensure_retention_tables()

        # Create a test table with old and new rows
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE test_prune (id INTEGER PRIMARY KEY, data TEXT, created_at TEXT)"
            )
            now = datetime.now(timezone.utc)
            old = (now - timedelta(days=100)).isoformat()
            new = now.isoformat()
            conn.execute(
                "INSERT INTO test_prune (data, created_at) VALUES (?, ?), (?, ?)",
                ("old-row", old, "new-row", new),
            )
            conn.commit()

        # Create policy with 30-day TTL
        policy = retention.create_policy(
            "test_prune", "sqlite", ttl_days=30, timestamp_column="created_at"
        )
        result = retention.prune_table(policy)
        self.assertEqual(result["deleted"], 1)
        self.assertIsNone(result["error"])

        # Verify only new row remains
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT data FROM test_prune").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][0], "new-row")

    def test_prune_skips_disabled(self):
        import retention

        retention._ensure_retention_tables()
        policy = retention.create_policy(
            "skip_test",
            "sqlite",
            ttl_days=1,
            timestamp_column="created_at",
            enabled=False,
        )
        result = retention.prune_table(policy)
        self.assertTrue(result["skipped"])
        self.assertEqual(result["deleted"], 0)

    def test_prune_skips_zero_ttl(self):
        import retention

        retention._ensure_retention_tables()
        policy = retention.create_policy(
            "zero_ttl", "sqlite", ttl_days=0, timestamp_column="created_at"
        )
        result = retention.prune_table(policy)
        self.assertTrue(result["skipped"])

    def test_prune_all(self):
        import retention

        retention._ensure_retention_tables()

        # Create test table with old data
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE prune_all_test (id INTEGER PRIMARY KEY, data TEXT, created_at TEXT)"
            )
            old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
            conn.execute(
                "INSERT INTO prune_all_test (data, created_at) VALUES (?, ?)",
                ("old", old),
            )
            conn.commit()

        retention.create_policy(
            "prune_all_test", "sqlite", ttl_days=30, timestamp_column="created_at"
        )
        results = retention.prune_all()
        self.assertTrue(len(results) > 0)
        # At least one result should have deleted > 0
        total = sum(r["deleted"] for r in results)
        self.assertGreater(total, 0)

    def test_prune_log(self):
        import retention

        retention._ensure_retention_tables()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE log_test (id INTEGER PRIMARY KEY, data TEXT, created_at TEXT)"
            )
            old = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
            conn.execute(
                "INSERT INTO log_test (data, created_at) VALUES (?, ?)",
                ("old", old),
            )
            conn.commit()

        policy = retention.create_policy(
            "log_test", "sqlite", ttl_days=30, timestamp_column="created_at"
        )
        retention.prune_table(policy)

        log = retention.prune_history()
        self.assertGreater(len(log), 0)
        self.assertEqual(log[0]["table_name"], "log_test")
        self.assertEqual(log[0]["rows_deleted"], 1)

    def test_get_policy_not_found(self):
        import retention

        self.assertIsNone(retention.get_policy(99999))


if __name__ == "__main__":
    unittest.main()
