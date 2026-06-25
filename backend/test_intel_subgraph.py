"""Unit tests for intel_subgraph (Track 3, no network)."""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_connection
import ftm_store
import intel_subgraph as sg


class IntelSubgraphTests(unittest.TestCase):
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

    def _seed_event(self, key: str, lat: float, lon: float) -> str:
        proxy = ftm_store.make_entity("Event", [key], {"name": [f"Event {key}"]})
        eid = ftm_store.upsert(proxy, dataset="gdacs", lat=lat, lon=lon)
        return eid

    def test_parse_bbox(self):
        self.assertEqual(sg.parse_bbox("92,5,102,15"), [92.0, 5.0, 102.0, 15.0])
        self.assertIsNone(sg.parse_bbox("bad"))
        self.assertIsNone(sg.parse_bbox("1,2,3"))

    def test_decay_weight_fresh(self):
        self.assertEqual(sg.decay_weight(0), 1.0)
        self.assertEqual(sg.decay_weight(0.1), 1.0)

    def test_decay_weight_half_life(self):
        self.assertAlmostEqual(sg.decay_weight(30, 30), 0.5, places=2)
        self.assertAlmostEqual(sg.decay_weight(60, 30), 0.25, places=2)

    def test_decay_weight_custom_half_life(self):
        self.assertAlmostEqual(sg.decay_weight(7, 7), 0.5, places=2)

    def test_decay_weight_very_old(self):
        w = sg.decay_weight(150, 30)  # 5 half-lives
        self.assertLess(w, 0.04)

    def test_subgraph_edge_has_decay_fields(self):
        seed = self._seed_event("local", 13.75, 100.5)
        org = ftm_store.make_entity(
            "Organization", ["relief"], {"name": ["Relief Org"]}
        )
        org_id = ftm_store.upsert(org, dataset="osint")
        ftm_store.add_edge(seed, org_id, "linked", dataset="osint", confidence=0.9)

        bbox = [100.0, 13.0, 101.0, 14.5]
        out = sg.build_subgraph(
            bbox=bbox, hops=2, window_hours=48, seed_limit=10, node_limit=20
        )
        self.assertTrue(out["available"])
        self.assertGreaterEqual(len(out["edges"]), 1)
        edge = out["edges"][0]
        self.assertIn("decayed_confidence", edge)
        self.assertIn("decay_weight", edge)
        self.assertIn("age_days", edge)
        self.assertLessEqual(edge["decayed_confidence"], edge["confidence"])

    def test_subgraph_stale_edge_in_prompt(self):
        block = sg.format_subgraph_prompt_block(
            {
                "available": True,
                "hops": 2,
                "node_count": 2,
                "nodes": [
                    {
                        "id": "a",
                        "schema": "Event",
                        "caption": "E1",
                        "hop": 0,
                        "in_bbox": True,
                        "datasets": ["gdacs"],
                    },
                    {
                        "id": "b",
                        "schema": "Organization",
                        "caption": "Org",
                        "hop": 1,
                        "datasets": ["osint"],
                    },
                ],
                "edges": [
                    {
                        "source_id": "a",
                        "target_id": "b",
                        "kind": "linked",
                        "dataset": "osint",
                        "decay_weight": 0.3,
                    },
                ],
            },
            lang="en",
        )
        self.assertIn("stale", block)

    def test_build_subgraph_two_hop(self):
        seed = self._seed_event("local", 13.75, 100.5)
        org = ftm_store.make_entity(
            "Organization", ["relief"], {"name": ["Relief Org"]}
        )
        org_id = ftm_store.upsert(org, dataset="osint")
        ftm_store.add_edge(seed, org_id, "linked", dataset="osint", confidence=0.9)

        bbox = [100.0, 13.0, 101.0, 14.5]
        out = sg.build_subgraph(
            bbox=bbox, hops=2, window_hours=48, seed_limit=10, node_limit=20
        )
        self.assertTrue(out["available"])
        node_ids = {n["id"] for n in out["nodes"]}
        self.assertIn(seed, node_ids)
        self.assertIn(org_id, node_ids)
        self.assertGreaterEqual(out["edge_count"], 1)

    def test_build_subgraph_no_seeds(self):
        out = sg.build_subgraph(bbox=[0, 0, 1, 1], hops=2, window_hours=48)
        self.assertFalse(out["available"])
        self.assertEqual(out["nodes"], [])

    def test_format_subgraph_prompt_en(self):
        block = sg.format_subgraph_prompt_block(
            {
                "available": True,
                "hops": 2,
                "node_count": 1,
                "nodes": [
                    {
                        "id": "a",
                        "schema": "Event",
                        "caption": "Test",
                        "hop": 0,
                        "in_bbox": True,
                        "datasets": ["gdacs"],
                    }
                ],
                "edges": [],
            },
            lang="en",
        )
        self.assertIn("INTEL SUBGRAPH", block)
        self.assertIn("[Event] Test", block)

    def test_intel_prompt_uses_subgraph_when_available(self):
        from intel_briefing import format_intel_prompt_block

        self._seed_event("bkk", 13.75, 100.5)
        block = format_intel_prompt_block(
            {"enabled": True, "window_hours": 48, "items": []}, lang="en"
        )
        self.assertIn("INTEL SUBGRAPH", block)

    def test_subgraph_disabled_falls_back_to_flat(self):
        from intel_briefing import format_intel_prompt_block

        old = os.environ.get("WORLDBASE_BRIEFING_INTEL_SUBGRAPH")
        os.environ["WORLDBASE_BRIEFING_INTEL_SUBGRAPH"] = "0"
        try:
            block = format_intel_prompt_block(
                {
                    "enabled": True,
                    "items": [{"bucket": "local", "text": "Person: Alice (osint)"}],
                },
                lang="en",
            )
            self.assertIn("INTEL ENTITIES", block)
            self.assertIn("Alice", block)
        finally:
            if old is None:
                os.environ.pop("WORLDBASE_BRIEFING_INTEL_SUBGRAPH", None)
            else:
                os.environ["WORLDBASE_BRIEFING_INTEL_SUBGRAPH"] = old


if __name__ == "__main__":
    unittest.main()
