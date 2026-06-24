"""Unit tests for semantic intel edges (Track 3+ Sprint 1, no network)."""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_connection
import ftm_store
import intel_semantic_links as isl


class IntelSemanticLinksTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

    def tearDown(self):
        try:
            if ftm_connection._CONN is not None:
                ftm_connection._CONN.close()
        finally:
            ftm_connection._CONN = None
        for ext in ("", ".wal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _seed(self, key: str, schema: str, lat: float, lon: float, dataset: str) -> str:
        proxy = ftm_store.make_entity(schema, [key], {"name": [f"{schema} {key}"]})
        return ftm_store.upsert(proxy, dataset=dataset, lat=lat, lon=lon)

    def test_colocated_same_place(self):
        self._seed("gdacs-a", "Event", 13.75, 100.5, "gdacs")
        self._seed("ais-a", "Vessel", 13.75, 100.5, "ais")
        entities = isl._fetch_bbox_entities(
            [100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_colocated_entities(entities, refresh=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)

    def test_vessel_near_event(self):
        self._seed("storm", "Event", 13.75, 100.5, "gdacs")
        self._seed("ship", "Vessel", 13.76, 100.51, "ais")
        entities = isl._fetch_bbox_entities(
            [100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_vessels_near_events(entities, max_km=50, refresh=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)

    def test_link_semantic_edges_combined(self):
        self._seed("e1", "Event", 13.75, 100.5, "gdacs")
        self._seed("v1", "Vessel", 13.751, 100.501, "ais")
        out = isl.link_semantic_edges(bbox=[100.0, 13.0, 101.0, 14.5], window_hours=48)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)


if __name__ == "__main__":
    unittest.main()
