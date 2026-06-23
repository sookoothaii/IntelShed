"""Unit tests for GeoParquet feed staging (no network)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import fusion_spatial_stage as fss
import feed_drift as fd


class TestFeedDriftDegradation(unittest.TestCase):
    def test_summarize_degradation_warns_on_half_offline(self):
        freshness = [
            {"cache_key": "a", "status": "fresh"},
            {"cache_key": "b", "status": "stale"},
            {"cache_key": "c", "status": "error"},
            {"cache_key": "d", "status": "missing"},
        ]
        out = fd.summarize_degradation(freshness)
        self.assertEqual(out["offline_pct"], 75.0)
        self.assertTrue(out["warn"])
        self.assertIn("b", out["offline_keys"])


class TestFusionSpatialStage(unittest.TestCase):
    def test_extract_rows_from_payload(self):
        payload = {
            "earthquakes": [
                {"lat": 13.7, "lon": 100.5, "place": "Near Bangkok", "mag": 4.2},
                {"lat": "bad", "lon": None},
            ],
            "count": 1,
        }
        rows = fss._rows_from_payload("quakes:day", payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["feed_key"], "quakes:day")
        self.assertAlmostEqual(rows[0]["lat"], 13.7)

    def test_stage_empty_parquet_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.parquet")
            with patch.object(fss, "_PARQUET", path):
                out = fss.stage_to_parquet([])
                self.assertTrue(out["ok"])
                self.assertEqual(out["count"], 0)
                self.assertFalse(os.path.exists(path))

    def test_stage_writes_parquet_with_h3_or_fallback(self):
        rows = [
            {
                "feed_key": "gdacs_v3",
                "source": "gdacs",
                "lat": 13.75,
                "lon": 100.5,
                "label": "Flood alert",
                "cached_at": "2026-06-23T00:00:00+00:00",
            },
            {
                "feed_key": "quakes:day",
                "source": "quake",
                "lat": 14.0,
                "lon": 101.0,
                "label": "M4.5 test",
                "cached_at": "2026-06-23T00:00:00+00:00",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.parquet")
            with patch.object(fss, "_PARQUET", path):
                out = fss.stage_to_parquet(rows)
                self.assertTrue(out["ok"])
                self.assertEqual(out["count"], 2)
                self.assertTrue(os.path.exists(path))
                status = fss.stage_status()
                self.assertTrue(status["staged"])
                self.assertEqual(status["count"], 2)
                q = fss.query_bbox(10.0, 95.0, 20.0, 105.0, limit=10)
                self.assertTrue(q["ok"])
                self.assertEqual(q["count"], 2)


if __name__ == "__main__":
    unittest.main()
