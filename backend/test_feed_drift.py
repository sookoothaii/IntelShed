"""Unit tests for feed_drift (in-memory SQLite)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import feed_drift as fd


class FeedDriftTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db = os.path.join(self._tmpdir.name, "test.db")
        self._orig = fd._DB_PATH
        fd._DB_PATH = self._db
        with fd._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feed_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    cached_at TEXT
                )
                """
            )
            conn.commit()
        fd.init_drift_db()

    def tearDown(self):
        fd._DB_PATH = self._orig
        try:
            self._tmpdir.cleanup()
        except PermissionError:
            pass

    def _seed_cache(self, key: str, count: int, *, hours_ago: float = 0.0) -> None:
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        with fd._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
                (key, json.dumps({"count": count, "source": "test"}), ts.isoformat()),
            )
            conn.commit()

    def _seed_snapshot(self, key: str, count: int, *, hours_ago: float) -> None:
        ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        with fd._conn() as conn:
            conn.execute(
                "INSERT INTO feed_count_snapshots (cache_key, count, recorded_at) VALUES (?, ?, ?)",
                (key, count, ts.isoformat()),
            )
            conn.commit()

    def test_extract_count_from_list_field(self):
        self.assertEqual(fd.extract_count({"articles": [{"a": 1}, {"b": 2}]}), 2)

    def test_no_drift_without_baseline(self):
        self._seed_cache("gdacs_v3", 50)
        out = fd.check_feed_drift()
        self.assertTrue(out["ok"])
        self.assertEqual(out["drifting"], [])

    def test_detects_large_drop(self):
        self._seed_cache("gdacs_v3", 2)
        self._seed_snapshot("gdacs_v3", 100, hours_ago=12)
        with fd._conn() as conn:
            feeds = fd._read_feed_cache(conn)
            now = datetime.now(timezone.utc)
            drifting = fd.detect_drift(feeds, conn, now)
        self.assertEqual(len(drifting), 1)
        self.assertEqual(drifting[0]["previous_count"], 100)
        self.assertEqual(drifting[0]["current_count"], 2)

    def test_skips_structural_count_drop_when_feed_healthy(self):
        self._seed_cache("wildfires", 1575)
        self._seed_snapshot("wildfires", 27359, hours_ago=9)
        with fd._conn() as conn:
            feeds = fd._read_feed_cache(conn)
            now = datetime.now(timezone.utc)
            drifting = fd.detect_drift(feeds, conn, now)
        self.assertEqual(drifting, [])

    def test_freshness_status_fresh(self):
        self._seed_cache("cve", 10, hours_ago=0.1)
        with fd._conn() as conn:
            feeds = fd._read_feed_cache(conn)
        rows = fd.build_freshness(feeds, datetime.now(timezone.utc))
        cve = next(r for r in rows if r["cache_key"] == "cve")
        self.assertEqual(cve["status"], "fresh")

    def test_quakes_day_resolves_prefixed_cache_key(self):
        self._seed_cache("quakes:day:2.5", 42, hours_ago=0.05)
        with fd._conn() as conn:
            feeds = fd._read_feed_cache(conn)
        rows = fd.build_freshness(feeds, datetime.now(timezone.utc))
        quakes = next(r for r in rows if r["cache_key"] == "quakes:day")
        self.assertEqual(quakes["status"], "fresh")
        self.assertEqual(quakes["resolved_key"], "quakes:day:2.5")
        self.assertEqual(quakes["count"], 42)

    def test_hazards_missing_when_not_in_cache(self):
        with fd._conn() as conn:
            feeds = fd._read_feed_cache(conn)
        rows = fd.build_freshness(feeds, datetime.now(timezone.utc))
        haz = next(r for r in rows if r["cache_key"] == "hazards")
        self.assertEqual(haz["status"], "missing")


if __name__ == "__main__":
    unittest.main()
