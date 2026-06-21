"""Unit tests for spatial proximity edges (Track 3+, no network)."""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_store
import intel_proximity as ip


class IntelProximityTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_store._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

    def tearDown(self):
        try:
            if ftm_store._CONN is not None:
                ftm_store._CONN.close()
        finally:
            ftm_store._CONN = None
        for ext in ("", ".wal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _seed(self, key: str, lat: float, lon: float) -> str:
        proxy = ftm_store.make_entity("Event", [key], {"name": [f"Event {key}"]})
        return ftm_store.upsert(proxy, dataset="gdacs", lat=lat, lon=lon)

    def test_haversine_short_distance(self):
        km = ip.haversine_km(13.75, 100.5, 13.76, 100.51)
        self.assertLess(km, 2.0)

    def test_link_proximity_edges_within_range(self):
        self._seed("a", 13.75, 100.5)
        self._seed("b", 13.76, 100.51)
        out = ip.link_proximity_edges(
            bbox=[100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            max_km=50,
            entity_cap=10,
        )
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)
        self.assertGreaterEqual(out["edges_total"], 1)

    def test_link_proximity_skips_far_pairs(self):
        self._seed("near-a", 13.75, 100.5)
        self._seed("far-b", 20.0, 110.0)
        out = ip.link_proximity_edges(
            bbox=[95.0, 5.0, 115.0, 22.0],
            window_hours=48,
            max_km=50,
            entity_cap=10,
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["edges_added"], 0)

    def test_link_proximity_refresh_does_not_accumulate(self):
        for key, lat, lon in (("a", 13.75, 100.5), ("b", 13.76, 100.51), ("c", 13.77, 100.52)):
            self._seed(key, lat, lon)
        bbox = [100.0, 13.0, 101.0, 14.5]
        first = ip.link_proximity_edges(bbox=bbox, window_hours=48, max_km=120, entity_cap=10)
        second = ip.link_proximity_edges(bbox=bbox, window_hours=48, max_km=120, entity_cap=10)
        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertGreaterEqual(first["edges_total"], 1)
        self.assertEqual(second["edges_total"], first["edges_total"])


if __name__ == "__main__":
    unittest.main()
