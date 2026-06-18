"""Unit tests for FtM → briefing bridge (no network)."""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_store
import intel_briefing
from operator_briefing import format_digest_sections


class IntelBriefingTests(unittest.TestCase):
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

    def _seed_thailand_event(self):
        ev = ftm_store.make_entity(
            "Event",
            ["th", "flood"],
            {"name": ["Bangkok flood warning"]},
        )
        ftm_store.upsert(ev, dataset="gdacs", lat=13.75, lon=100.5)

    def _seed_global_vessel(self):
        v = ftm_store.make_entity(
            "Vessel",
            ["imo", "999"],
            {"name": ["MV Test Ship"], "imoNumber": ["9990001"]},
        )
        ftm_store.upsert(v, dataset="ais", lat=1.0, lon=103.0)

    def _seed_airplane_noise(self):
        ftm_store.upsert_legacy(
            "aircraft:noise1",
            "aircraft",
            label="FL999",
            source_feed="anomalies",
            lat=13.0,
            lon=100.0,
        )

    def test_entities_for_briefing_excludes_airplane(self):
        self._seed_thailand_event()
        self._seed_airplane_noise()
        rows = ftm_store.entities_for_briefing(
            window_hours=48,
            exclude_schemas={"Airplane"},
        )
        schemas = {r["schema"] for r in rows}
        self.assertIn("Event", schemas)
        self.assertNotIn("Airplane", schemas)

    def test_rank_prefers_gdacs_event_over_ais_vessel(self):
        self._seed_thailand_event()
        self._seed_global_vessel()
        candidates = ftm_store.entities_for_briefing(window_hours=48, exclude_schemas={"Airplane"})
        ranked = intel_briefing.rank_entities_for_briefing(candidates)
        self.assertEqual(ranked[0]["schema"], "Event")
        self.assertEqual(ranked[0]["datasets"], ["gdacs"])

    def test_same_as_neighbours_attached(self):
        p1 = ftm_store.make_entity("Person", ["a"], {"name": ["Alice Example"]})
        p2 = ftm_store.make_entity("Person", ["b"], {"name": ["Alice Example"]})
        e1 = ftm_store.upsert(p1, dataset="feedA", lat=13.7, lon=100.5)
        ftm_store.upsert(p2, dataset="feedB", lat=13.71, lon=100.51)
        ftm_store.add_edge(e1, p2.id, "sameAs", dataset="entity-resolution", confidence=0.95)
        rows = ftm_store.entities_for_briefing(window_hours=48, exclude_schemas={"Airplane"})
        target = next(r for r in rows if r["id"] == e1)
        self.assertTrue(target.get("same_as"))
        self.assertEqual(target["same_as"][0]["schema"], "Person")

    def test_digest_merges_intel_into_local_bucket(self):
        self._seed_thailand_event()
        intel_meta = intel_briefing.gather_for_briefing()
        digest = format_digest_sections({}, [], "none", [], intel_meta=intel_meta)
        local_text = " ".join(digest["local"])
        self.assertIn("Bangkok flood", local_text)
        self.assertGreaterEqual(digest["intel"]["count"], 1)
        self.assertIn("FtM Event/gdacs", local_text)

    def test_dedup_skips_intel_when_feed_already_has_caption(self):
        self._seed_thailand_event()
        intel_meta = intel_briefing.gather_for_briefing()
        snap = {
            "gdacs": {
                "alerts": [{
                    "title": "Bangkok flood warning",
                    "lat": 13.75,
                    "lon": 100.5,
                }],
            },
        }
        digest = format_digest_sections(snap, [], "none", [], intel_meta=intel_meta)
        ftm_lines = [i for i in (digest["intel"].get("items") or []) if "FtM" in i.get("text", "")]
        self.assertEqual(len(ftm_lines), 0)

    def test_format_entity_line_includes_same_as(self):
        line = intel_briefing.format_entity_line({
            "schema": "Person",
            "caption": "Alice",
            "datasets": ["intel-ingest"],
            "same_as": [{"caption": "Alice Example", "schema": "Person"}],
        })
        self.assertIn("linked:", line)
        self.assertIn("Alice Example", line)


if __name__ == "__main__":
    unittest.main()
