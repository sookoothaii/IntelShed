"""Schema consistency tests for feed_cache table.

Verifies that SQLite schema, ORM model, and Postgres migration script
all agree on columns, indexes, and column names.
"""

from __future__ import annotations

import unittest
import sqlite3
import os
import tempfile


class TestSqliteSchemaConsistency(unittest.TestCase):
    """sqlite_bootstrap.init_db() creates feed_cache with expected columns + indexes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_schema.db")

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.tmpdir)

    def test_feed_cache_has_ttl_seconds_column(self):
        import sqlite_bootstrap

        sqlite_bootstrap.DB_PATH = self.db_path
        sqlite_bootstrap.init_db()
        conn = sqlite3.connect(self.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(feed_cache)").fetchall()]
        conn.close()
        self.assertIn("key", cols)
        self.assertIn("value", cols)
        self.assertIn("cached_at", cols)
        self.assertIn("ttl_seconds", cols)

    def test_feed_cache_has_indexes(self):
        import sqlite_bootstrap

        sqlite_bootstrap.DB_PATH = self.db_path
        sqlite_bootstrap.init_db()
        conn = sqlite3.connect(self.db_path)
        indexes = [
            r[1] for r in conn.execute("PRAGMA index_list(feed_cache)").fetchall()
        ]
        conn.close()
        self.assertIn("idx_feed_cache_cached_at", indexes)
        self.assertIn("idx_feed_cache_ttl", indexes)

    def test_migration_adds_ttl_seconds_to_existing_db(self):
        """Simulate an old DB without ttl_seconds, then run init_db()."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE feed_cache (key TEXT PRIMARY KEY, value TEXT, cached_at TEXT)"
        )
        conn.execute(
            "INSERT INTO feed_cache (key, value, cached_at) VALUES ('test', '{}', '2024-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        import sqlite_bootstrap

        sqlite_bootstrap.DB_PATH = self.db_path
        sqlite_bootstrap.init_db()

        conn = sqlite3.connect(self.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(feed_cache)").fetchall()]
        self.assertIn("ttl_seconds", cols)
        # Existing data preserved
        row = conn.execute(
            "SELECT key, value FROM feed_cache WHERE key = 'test'"
        ).fetchone()
        self.assertIsNotNone(row)
        conn.close()


class TestPostgresMigrationScriptConsistency(unittest.TestCase):
    """migrate_to_postgres.py feed_cache schema matches ORM model."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "scripts",
            "migrate_to_postgres.py",
        )
        with open(path, encoding="utf-8") as f:
            cls.source = f.read()

    def test_uses_value_json_not_value(self):
        """ORM model uses value_json, so migration must too."""
        self.assertIn("value_json", self.source)
        self.assertNotIn("value JSONB", self.source)

    def test_has_ttl_seconds(self):
        self.assertIn("ttl_seconds", self.source)

    def test_has_indexes(self):
        self.assertIn("idx_feed_cache_cached_at", self.source)
        self.assertIn("idx_feed_cache_ttl", self.source)


class TestOrmModelConsistency(unittest.TestCase):
    """db/models.py FeedCache ORM model matches expectations."""

    def test_orm_model_columns(self):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "db",
            "models.py",
        )
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn("value_json", source)
        self.assertIn("ttl_seconds", source)
        self.assertIn("idx_feed_cache_cached_at", source)
        self.assertIn("idx_feed_cache_ttl", source)


if __name__ == "__main__":
    unittest.main()
