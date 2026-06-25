"""Tests for I6 — Tiered Storage: Feed Cache TTL + VACUUM + FtM Parquet Archival."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


class TestFeedCacheTTL(unittest.TestCase):
    """Feed cache TTL config + prune."""

    def test_config_defaults(self):
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertEqual(cfg.feed_cache_ttl, 604800)
        self.assertEqual(cfg.ftm_archive_days, 0)

    def test_config_env_override(self):
        os.environ["WORLDBASE_FEED_CACHE_TTL"] = "86400"
        os.environ["WORLDBASE_FTM_ARCHIVE_DAYS"] = "90"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertEqual(cfg.feed_cache_ttl, 86400)
            self.assertEqual(cfg.ftm_archive_days, 90)
        finally:
            os.environ.pop("WORLDBASE_FEED_CACHE_TTL", None)
            os.environ.pop("WORLDBASE_FTM_ARCHIVE_DAYS", None)

    def test_prune_removes_old_entries(self):
        from sqlite_bootstrap import prune_feed_cache

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE feed_cache (key TEXT PRIMARY KEY, value TEXT, cached_at TEXT, ttl_seconds INTEGER DEFAULT 300)"
            )
            now = datetime.now(timezone.utc)
            old = (now - timedelta(days=10)).isoformat()
            fresh = now.isoformat()
            conn.execute(
                "INSERT INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
                ("old_feed", "{}", old),
            )
            conn.execute(
                "INSERT INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
                ("fresh_feed", "{}", fresh),
            )
            conn.commit()
            conn.close()

            with patch("sqlite_bootstrap.DB_PATH", db_path):
                removed = prune_feed_cache(max_age_sec=7 * 24 * 3600)
            self.assertEqual(removed, 1)

            conn = sqlite3.connect(db_path)
            remaining = [r[0] for r in conn.execute("SELECT key FROM feed_cache").fetchall()]
            conn.close()
            self.assertIn("fresh_feed", remaining)
            self.assertNotIn("old_feed", remaining)
        finally:
            os.unlink(db_path)


class TestFtmArchive(unittest.TestCase):
    """FtM archival module."""

    def test_archive_disabled_by_default(self):
        import ftm_archive

        result = ftm_archive.archive_stale_entities()
        self.assertFalse(result["enabled"])
        self.assertIn("reason", result)

    def test_archive_stats_empty(self):
        import ftm_archive

        stats = ftm_archive.archive_stats()
        self.assertIn("file_count", stats)
        self.assertIn("size_mb", stats)
        self.assertIsInstance(stats["size_mb"], float)

    def test_duckdb_size_mb_returns_float(self):
        import ftm_archive

        size = ftm_archive.duckdb_size_mb()
        self.assertIsInstance(size, float)
        self.assertGreaterEqual(size, 0.0)

    def test_reload_nonexistent_month(self):
        import ftm_archive

        result = ftm_archive.reload_archive("1999-01")
        self.assertIn("error", result)

    def test_archive_dir_is_pathlike(self):
        import ftm_archive

        d = ftm_archive.archive_dir()
        self.assertTrue(hasattr(d, "exists"))

    def test_manifest_load_empty(self):
        import ftm_archive

        manifest = ftm_archive._load_manifest()
        self.assertIsInstance(manifest, dict)
        self.assertIn("archives", manifest)


class TestArchiveEndpoints(unittest.TestCase):
    """API endpoint smoke tests (no server required — function imports)."""

    def test_ftm_api_has_archive_routes(self):
        from routes import ftm_api

        routes = [r.path for r in ftm_api.router.routes]
        self.assertIn("/api/intel/archive/run", routes)
        self.assertIn("/api/intel/archive/reload", routes)
        self.assertIn("/api/intel/archive/stats", routes)


if __name__ == "__main__":
    unittest.main()
