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

    def _seed_with_caption(
        self, key: str, schema: str, lat: float, lon: float, dataset: str, caption: str
    ) -> str:
        proxy = ftm_store.make_entity(schema, [key], {"name": [caption]})
        return ftm_store.upsert(proxy, dataset=dataset, lat=lat, lon=lon)

    def test_related_events_cross_feed(self):
        """GDACS flood and GDELT flood news near each other should link."""
        self._seed_with_caption(
            "gdacs-flood",
            "Event",
            13.75,
            100.5,
            "gdacs",
            "Flood warning Thailand Bangkok",
        )
        self._seed_with_caption(
            "gdelt-flood",
            "Event",
            13.76,
            100.51,
            "gdelt-pulse",
            "Thailand Bangkok flooding situation",
        )
        entities = isl._fetch_bbox_entities(
            [100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_related_events(entities, max_km=50, refresh=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)

    def test_related_events_same_feed_skipped(self):
        """Two events from the same dataset should NOT get relatedEvent edges."""
        self._seed_with_caption(
            "g1", "Event", 13.75, 100.5, "gdacs", "Flood warning Thailand Bangkok"
        )
        self._seed_with_caption(
            "g2", "Event", 13.76, 100.51, "gdacs", "Flood Thailand Bangkok area"
        )
        entities = isl._fetch_bbox_entities(
            [100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_related_events(entities, max_km=50, refresh=True)
        self.assertEqual(out["edges_added"], 0)

    def test_related_events_no_text_overlap_skipped(self):
        """Events with no shared words should not link even if close."""
        self._seed_with_caption(
            "a1", "Event", 13.75, 100.5, "gdacs", "Earthquake Japan Tokyo"
        )
        self._seed_with_caption(
            "a2",
            "Event",
            13.76,
            100.51,
            "gdelt-pulse",
            "Maritime piracy Malacca Strait",
        )
        entities = isl._fetch_bbox_entities(
            [100.0, 13.0, 101.0, 14.5],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_related_events(entities, max_km=50, refresh=True)
        self.assertEqual(out["edges_added"], 0)

    def test_related_events_too_far_skipped(self):
        """Events with shared words but too far apart should not link."""
        self._seed_with_caption(
            "far1", "Event", 13.75, 100.5, "gdacs", "Flood warning Thailand Bangkok"
        )
        self._seed_with_caption(
            "far2", "Event", 5.0, 97.0, "gdelt-pulse", "Flood Thailand Bangkok region"
        )
        entities = isl._fetch_bbox_entities(
            [90.0, 0.0, 110.0, 20.0],
            window_hours=48,
            cap=20,
            exclude_schemas={"Airplane"},
        )
        out = isl.link_related_events(entities, max_km=50, refresh=True)
        self.assertEqual(out["edges_added"], 0)

    def test_related_events_in_semantic_edges(self):
        """link_semantic_edges should include related_events in output."""
        self._seed_with_caption(
            "r1", "Event", 13.75, 100.5, "gdacs", "Flood warning Thailand Bangkok"
        )
        self._seed_with_caption(
            "r2",
            "Event",
            13.76,
            100.51,
            "gdelt-pulse",
            "Thailand Bangkok flooding situation",
        )
        out = isl.link_semantic_edges(bbox=[100.0, 13.0, 101.0, 14.5], window_hours=48)
        self.assertTrue(out["ok"])
        self.assertIn("related_events", out)
        self.assertGreaterEqual(out["related_events"].get("edges_added", 0), 1)

    def test_tokenize_caption_stops_words(self):
        """Stop words and short tokens should be filtered out."""
        tokens = isl._tokenize_caption("The flood in a big city of Thailand")
        self.assertIn("flood", tokens)
        self.assertIn("thailand", tokens)
        self.assertNotIn("the", tokens)
        self.assertNotIn("in", tokens)
        self.assertNotIn("a", tokens)
        self.assertNotIn("of", tokens)

    def test_related_events_text_only_no_geo(self):
        """Cross-feed events with shared words but no coordinates should link via text-only matching."""
        self._seed_with_caption(
            "gdacs-flood",
            "Event",
            13.75,
            100.5,
            "gdacs",
            "Flood warning Thailand Bangkok",
        )
        # GDELT event with no coordinates (lat/lon not set)
        proxy = ftm_store.make_entity(
            "Event", ["gdelt-flood"], {"name": ["Thailand Bangkok flooding situation"]}
        )
        ftm_store.upsert(proxy, dataset="gdelt-pulse", lat=None, lon=None)
        events = isl._fetch_events_for_correlation(None, window_hours=48, cap=20)
        out = isl.link_related_events(events, max_km=50, refresh=True)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["edges_added"], 1)
        self.assertGreaterEqual(out.get("text_only_edges", 0), 1)

    def test_datasets_for_entity_json_list(self):
        """Should parse JSON list format datasets."""
        ent = {"datasets": '["gdacs", "eonet"]'}
        ds = isl._datasets_for_entity(ent)
        self.assertEqual(ds, {"gdacs", "eonet"})

    def test_datasets_for_entity_comma_string(self):
        """Should parse comma-separated datasets."""
        ent = {"datasets": "gdacs, eonet"}
        ds = isl._datasets_for_entity(ent)
        self.assertEqual(ds, {"gdacs", "eonet"})


if __name__ == "__main__":
    unittest.main()
