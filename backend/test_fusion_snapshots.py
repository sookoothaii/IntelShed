"""Unit tests for fusion grid snapshots and 24h compare (Track 5)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import fusion_heatmap as fh


class FusionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name
        self._old = fh._DB_PATH
        fh._DB_PATH = self.db_path
        fh.init_fusion_snapshots_db()

    def tearDown(self):
        fh._DB_PATH = self._old
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _insert_snapshot(self, cell_deg: float, recorded_at: str, cells: list[dict]) -> None:
        payload = json.dumps({"cells": cells})
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO fusion_grid_snapshots (cell_deg, recorded_at, payload) VALUES (?, ?, ?)",
                (cell_deg, recorded_at, payload),
            )
            conn.commit()

    def test_parse_compare_hours(self):
        self.assertEqual(fh.parse_compare_hours("24h"), 24.0)
        self.assertEqual(fh.parse_compare_hours("6hours"), 6.0)
        self.assertIsNone(fh.parse_compare_hours(""))
        self.assertIsNone(fh.parse_compare_hours("bad"))

    def test_record_snapshot_respects_interval(self):
        cells = [{"lat": 13.0, "lon": 100.5, "score": 0.8, "intensity": 10.0, "sources": ["quake"]}]
        now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(fh.record_snapshot_if_due(2.0, cells, now=now))
        self.assertFalse(fh.record_snapshot_if_due(2.0, cells, now=now + timedelta(hours=1)))

    def test_apply_compare_delta(self):
        now = datetime.now(timezone.utc)
        baseline_at = (now - timedelta(hours=24)).isoformat()
        cid = fh.fusion_cell_id(13.0, 100.5)
        self._insert_snapshot(
            2.0,
            baseline_at,
            [{"cell_id": cid, "lat": 13.0, "lon": 100.5, "score": 0.4, "intensity": 8.0, "sources": ["quake"]}],
        )
        current = [{
            "lat": 13.0,
            "lon": 100.5,
            "score": 0.85,
            "intensity": 17.0,
            "sources": ["quake", "hazard"],
            "samples": [{"label": "Flood watch"}],
        }]
        meta = fh.apply_compare(current, 2.0, 24.0)
        self.assertTrue(meta["available"])
        self.assertAlmostEqual(current[0]["delta_score"], 0.45, places=4)
        deltas = fh.extract_delta_watch_cells(current, min_delta=0.12, top=3)
        self.assertEqual(len(deltas), 1)
        self.assertGreaterEqual(deltas[0]["delta_score"], 0.12)

    def test_build_watch_items_fusion_delta(self):
        from operator_briefing import build_watch_items

        snap: dict = {}
        fusion = [{"lat": 13.0, "lon": 100.5, "score": 0.9, "sources": ["hazard"], "samples": [{"label": "Static"}]}]
        deltas = [{
            "cell_id": "13.00,100.50",
            "lat": 13.0,
            "lon": 100.5,
            "score": 0.9,
            "delta_score": 0.35,
            "sources": ["hazard"],
            "samples": [{"label": "Flood rising"}],
        }]
        items = build_watch_items(snap, [], fusion, fusion_deltas=deltas)
        self.assertGreaterEqual(len(items), 1)
        top = items[0]
        self.assertIn("Rising fusion cell", top["title"])
        self.assertAlmostEqual(top["delta_score"], 0.35, places=4)
        self.assertEqual(top["cell_id"], "13.00,100.50")


if __name__ == "__main__":
    unittest.main()
