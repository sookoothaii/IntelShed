"""Tests for V4-09 Daily Snapshot Archiver — collection, persistence, manifest, fail-soft."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

# Ensure clean env
os.environ.pop("WORLDBASE_SNAPSHOT_ARCHIVER", None)

import snapshot_archiver as sa


class TestSnapshotEnabled(unittest.TestCase):
    def test_default_disabled(self):
        os.environ.pop("WORLDBASE_SNAPSHOT_ARCHIVER", None)
        self.assertFalse(sa._enabled())

    def test_enabled_flag(self):
        os.environ["WORLDBASE_SNAPSHOT_ARCHIVER"] = "1"
        try:
            self.assertTrue(sa._enabled())
        finally:
            os.environ.pop("WORLDBASE_SNAPSHOT_ARCHIVER", None)


class TestSnapshotCollection(unittest.TestCase):
    """Test _collect_snapshot with mocked data sources."""

    def test_collect_returns_timestamp_and_date(self):
        with patch("ftm_query.stats", side_effect=Exception("no duckdb")), patch(
            "entity_store.init_entity_db"
        ), patch("sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"), patch(
            "metrics.collect_all", side_effect=Exception("no metrics")
        ), patch(
            "prediction_ledger.list_predictions", side_effect=Exception("no preds")
        ):
            snapshot = sa._collect_snapshot()
        self.assertIn("timestamp", snapshot)
        self.assertIn("date", snapshot)
        # All sections should have error keys, not crash
        self.assertIn("error", snapshot.get("ftm", {}))
        self.assertIn("error", snapshot.get("feeds", {}))

    def test_collect_ftm_stats(self):
        mock_stats = {
            "entities": 100,
            "statements": 500,
            "edges": 50,
            "by_schema": {"Person": 60, "Company": 40},
            "by_dataset": {},
        }
        with patch("ftm_query.stats", return_value=mock_stats), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", side_effect=Exception("skip")), patch(
            "prediction_ledger.list_predictions", side_effect=Exception("skip")
        ):
            snapshot = sa._collect_snapshot()
        self.assertEqual(snapshot["ftm"]["entities"], 100)
        self.assertEqual(snapshot["ftm"]["statements"], 500)
        self.assertEqual(snapshot["ftm"]["edges"], 50)

    def test_collect_feeds(self):
        mock_metrics = {
            "feed_fresh_count": 15,
            "feed_stale_count": 3,
            "feed_error_count": 1,
            "feed_total_count": 19,
        }
        with patch("ftm_query.stats", side_effect=Exception("skip")), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", return_value=mock_metrics), patch(
            "prediction_ledger.list_predictions", side_effect=Exception("skip")
        ):
            snapshot = sa._collect_snapshot()
        self.assertEqual(snapshot["feeds"]["fresh_count"], 15)
        self.assertEqual(snapshot["feeds"]["stale_count"], 3)

    def test_collect_predictions(self):
        mock_preds = {
            "pending": [],
            "resolved": [
                {"outcome": "correct"},
                {"outcome": "correct"},
                {"outcome": "incorrect"},
            ],
        }
        with patch("ftm_query.stats", side_effect=Exception("skip")), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", side_effect=Exception("skip")), patch(
            "prediction_ledger.list_predictions", return_value=mock_preds
        ):
            snapshot = sa._collect_snapshot()
        self.assertEqual(snapshot["predictions"]["resolved_count"], 3)
        self.assertEqual(snapshot["predictions"]["correct_count"], 2)
        self.assertAlmostEqual(snapshot["predictions"]["accuracy"], 2 / 3, places=4)

    def test_collect_predictions_no_resolved(self):
        mock_preds = {"pending": [], "resolved": []}
        with patch("ftm_query.stats", side_effect=Exception("skip")), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", side_effect=Exception("skip")), patch(
            "prediction_ledger.list_predictions", return_value=mock_preds
        ):
            snapshot = sa._collect_snapshot()
        self.assertIsNone(snapshot["predictions"]["accuracy"])

    def test_fusion_defaults_to_zero(self):
        with patch("ftm_query.stats", side_effect=Exception("skip")), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", side_effect=Exception("skip")), patch(
            "prediction_ledger.list_predictions", side_effect=Exception("skip")
        ):
            snapshot = sa._collect_snapshot()
        self.assertEqual(snapshot["fusion"]["hotspot_count"], 0)


class TestSnapshotPersistence(unittest.TestCase):
    """Test snapshot save/load/manifest."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="snapshots_")
        self._orig_dir = sa._SNAPSHOT_DIR
        sa._SNAPSHOT_DIR = self._tmpdir

    def tearDown(self):
        sa._SNAPSHOT_DIR = self._orig_dir

    def test_save_and_load_snapshot(self):
        snapshot = {
            "timestamp": "2026-06-30T00:00:00+00:00",
            "date": "2026-06-30",
            "ftm": {"entities": 42, "statements": 100, "edges": 5},
            "feeds": {"fresh_count": 10, "stale_count": 2},
            "briefing": {"latest_at": "2026-06-29T22:00:00Z"},
            "fusion": {"hotspot_count": 3},
            "predictions": {"accuracy": 0.75},
            "rag": {"chunk_count": 500},
        }
        filepath = sa._save_snapshot(snapshot)
        self.assertTrue(os.path.exists(filepath))

        # Load it back
        loaded = sa.get_snapshot_by_date("2026-06-30")
        self.assertEqual(loaded["ftm"]["entities"], 42)
        self.assertEqual(loaded["rag"]["chunk_count"], 500)

    def test_manifest_updated_on_save(self):
        snapshot = {
            "timestamp": "2026-06-30T00:00:00+00:00",
            "date": "2026-06-30",
            "ftm": {"entities": 42, "statements": 100, "edges": 5},
            "feeds": {"fresh_count": 10, "stale_count": 2},
            "briefing": {"latest_at": None},
            "fusion": {"hotspot_count": 0},
            "predictions": {"accuracy": None},
            "rag": {"chunk_count": 0},
        }
        sa._save_snapshot(snapshot)
        manifest = sa._load_manifest()
        self.assertEqual(len(manifest["snapshots"]), 1)
        entry = manifest["snapshots"][0]
        self.assertEqual(entry["date"], "2026-06-30")
        self.assertEqual(entry["ftm_entities"], 42)

    def test_manifest_replaces_same_date(self):
        """Saving a snapshot for the same date should replace, not duplicate."""
        base = {
            "timestamp": "2026-06-30T00:00:00+00:00",
            "date": "2026-06-30",
            "ftm": {"entities": 42, "statements": 100, "edges": 5},
            "feeds": {"fresh_count": 10, "stale_count": 2},
            "briefing": {"latest_at": None},
            "fusion": {"hotspot_count": 0},
            "predictions": {"accuracy": None},
            "rag": {"chunk_count": 0},
        }
        sa._save_snapshot(base)
        base["ftm"]["entities"] = 99
        sa._save_snapshot(base)
        manifest = sa._load_manifest()
        self.assertEqual(len(manifest["snapshots"]), 1)
        self.assertEqual(manifest["snapshots"][0]["ftm_entities"], 99)

    def test_list_snapshots(self):
        for day in ["2026-06-28", "2026-06-29", "2026-06-30"]:
            sa._save_snapshot(
                {
                    "timestamp": f"{day}T00:00:00+00:00",
                    "date": day,
                    "ftm": {"entities": 1, "statements": 1, "edges": 1},
                    "feeds": {"fresh_count": 1, "stale_count": 0},
                    "briefing": {"latest_at": None},
                    "fusion": {"hotspot_count": 0},
                    "predictions": {"accuracy": None},
                    "rag": {"chunk_count": 0},
                }
            )
        result = sa.list_snapshots(limit=10)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["returned"], 3)
        # Should be sorted descending by date
        self.assertEqual(result["snapshots"][0]["date"], "2026-06-30")
        self.assertEqual(result["snapshots"][2]["date"], "2026-06-28")

    def test_get_latest_snapshot(self):
        sa._save_snapshot(
            {
                "timestamp": "2026-06-29T00:00:00+00:00",
                "date": "2026-06-29",
                "ftm": {"entities": 10, "statements": 20, "edges": 2},
                "feeds": {"fresh_count": 5, "stale_count": 1},
                "briefing": {"latest_at": None},
                "fusion": {"hotspot_count": 0},
                "predictions": {"accuracy": None},
                "rag": {"chunk_count": 0},
            }
        )
        sa._save_snapshot(
            {
                "timestamp": "2026-06-30T00:00:00+00:00",
                "date": "2026-06-30",
                "ftm": {"entities": 20, "statements": 40, "edges": 4},
                "feeds": {"fresh_count": 8, "stale_count": 0},
                "briefing": {"latest_at": None},
                "fusion": {"hotspot_count": 0},
                "predictions": {"accuracy": None},
                "rag": {"chunk_count": 0},
            }
        )
        latest = sa.get_latest_snapshot()
        self.assertEqual(latest["date"], "2026-06-30")
        self.assertEqual(latest["ftm"]["entities"], 20)

    def test_get_latest_no_snapshots(self):
        result = sa.get_latest_snapshot()
        self.assertIn("error", result)

    def test_get_snapshot_missing_date(self):
        result = sa.get_snapshot_by_date("1999-01-01")
        self.assertIn("error", result)


class TestTakeSnapshot(unittest.TestCase):
    """Test the full take_snapshot flow."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="snapshots_")
        self._orig_dir = sa._SNAPSHOT_DIR
        sa._SNAPSHOT_DIR = self._tmpdir

    def tearDown(self):
        sa._SNAPSHOT_DIR = self._orig_dir

    def test_take_snapshot_creates_file(self):
        with patch("ftm_query.stats", side_effect=Exception("skip")), patch(
            "sqlite_bootstrap.DB_PATH", "/nonexistent/path.db"
        ), patch("metrics.collect_all", side_effect=Exception("skip")), patch(
            "prediction_ledger.list_predictions", side_effect=Exception("skip")
        ):
            result = sa.take_snapshot()
        self.assertIn("date", result)
        self.assertIn("_filepath", result)
        self.assertTrue(os.path.exists(result["_filepath"]))
        self.assertIn("_elapsed_s", result)


if __name__ == "__main__":
    unittest.main()
