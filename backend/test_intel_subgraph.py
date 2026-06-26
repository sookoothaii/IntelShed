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
        import config

        config.get_config.cache_clear()
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

    def test_aggregate_edges_collapses_duplicates(self):
        edges = [
            {
                "source_id": "a",
                "target_id": "b",
                "kind": "relatedEvent",
                "confidence": 0.8,
                "decayed_confidence": 0.6,
                "decay_weight": 0.75,
                "dataset": "gdelt",
                "seen_at": "2026-01-01T00:00:00Z",
            },
            {
                "source_id": "a",
                "target_id": "b",
                "kind": "relatedEvent",
                "confidence": 0.9,
                "decayed_confidence": 0.7,
                "decay_weight": 0.78,
                "dataset": "gdacs",
                "seen_at": "2026-01-02T00:00:00Z",
            },
            {
                "source_id": "a",
                "target_id": "c",
                "kind": "linked",
                "confidence": 1.0,
                "decayed_confidence": 1.0,
                "decay_weight": 1.0,
                "dataset": "osint",
                "seen_at": None,
            },
        ]
        agg = sg._aggregate_edges(edges)
        self.assertEqual(len(agg), 2)
        ab = next(e for e in agg if e["source_id"] == "a" and e["target_id"] == "b")
        self.assertEqual(ab["count"], 2)
        self.assertAlmostEqual(ab["avg_confidence"], 0.85, places=2)
        self.assertAlmostEqual(ab["combined_weight"], 0.65, places=2)
        self.assertIn("relatedEvent", ab["source_types"])
        self.assertIn("gdelt", ab["datasets"])
        self.assertIn("gdacs", ab["datasets"])

    def test_graph_density_hub_detection(self):
        nodes = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
        edges = [
            {"source_id": "a", "target_id": "b"},
            {"source_id": "a", "target_id": "c"},
            {"source_id": "a", "target_id": "d"},
        ]
        density = sg._graph_density(nodes, edges)
        self.assertAlmostEqual(density["a"], 1.0, places=2)
        self.assertLess(density["b"], 0.5)
        self.assertGreater(density["a"], density["b"])

    def test_graph_density_single_node(self):
        nodes = [{"id": "a"}]
        edges = []
        density = sg._graph_density(nodes, edges)
        self.assertEqual(density["a"], 0.0)

    def test_prune_stale_edges(self):
        edges = [
            {"source_id": "a", "target_id": "b", "decay_weight": 0.8},
            {"source_id": "c", "target_id": "d", "decay_weight": 0.1},
            {"source_id": "e", "target_id": "f", "decay_weight": 0.3},
        ]
        pruned = sg._prune_stale_edges(edges, floor=0.3)
        ids = {(e["source_id"], e["target_id"]) for e in pruned}
        self.assertIn(("a", "b"), ids)
        self.assertIn(("e", "f"), ids)
        self.assertNotIn(("c", "d"), ids)

    def test_prune_stale_edges_floor_zero_keeps_all(self):
        edges = [
            {"source_id": "a", "target_id": "b", "decay_weight": 0.01},
        ]
        pruned = sg._prune_stale_edges(edges, floor=0.0)
        self.assertEqual(len(pruned), 1)

    def test_prioritize_edges_caps_at_20(self):
        edges = []
        for i in range(30):
            edges.append(
                {
                    "source_id": f"s{i}",
                    "target_id": f"t{i}",
                    "decayed_confidence": 0.5 + i * 0.01,
                    "count": 1,
                }
            )
        density = {}
        prioritized = sg._prioritize_edges(edges, density, cap=20)
        self.assertEqual(len(prioritized), 20)
        self.assertGreaterEqual(
            prioritized[0].get("decayed_confidence", 0),
            prioritized[-1].get("decayed_confidence", 0),
        )

    def test_prioritize_edges_hub_bonus(self):
        edges = [
            {
                "source_id": "hub",
                "target_id": "x",
                "decayed_confidence": 0.5,
                "count": 1,
            },
            {"source_id": "a", "target_id": "b", "decayed_confidence": 0.5, "count": 1},
        ]
        density = {"hub": 0.8, "x": 0.1, "a": 0.1, "b": 0.1}
        prioritized = sg._prioritize_edges(edges, density, cap=2)
        self.assertEqual(prioritized[0]["source_id"], "hub")

    def test_build_subgraph_aggregates_edges(self):
        seed = self._seed_event("agg1", 13.75, 100.5)
        org = ftm_store.make_entity("Organization", ["org1"], {"name": ["Org 1"]})
        org_id = ftm_store.upsert(org, dataset="osint")
        ftm_store.add_edge(
            seed, org_id, "relatedEvent", dataset="gdelt", confidence=0.8
        )
        ftm_store.add_edge(
            seed, org_id, "relatedEvent", dataset="gdacs", confidence=0.9
        )

        bbox = [100.0, 13.0, 101.0, 14.5]
        out = sg.build_subgraph(
            bbox=bbox, hops=2, window_hours=48, seed_limit=10, node_limit=20
        )
        self.assertTrue(out["available"])
        self.assertGreaterEqual(out["raw_edge_count"], 2)
        self.assertLessEqual(out["edge_count"], out["raw_edge_count"])
        if out["edges"]:
            edge = out["edges"][0]
            self.assertIn("count", edge)
            self.assertIn("avg_confidence", edge)
            self.assertIn("combined_weight", edge)
            self.assertIn("source_types", edge)

    def test_build_subgraph_density_and_hub(self):
        seed = self._seed_event("hub1", 13.75, 100.5)
        org1 = ftm_store.make_entity("Organization", ["h1"], {"name": ["H1"]})
        org2 = ftm_store.make_entity("Organization", ["h2"], {"name": ["H2"]})
        o1 = ftm_store.upsert(org1, dataset="osint")
        o2 = ftm_store.upsert(org2, dataset="osint")
        ftm_store.add_edge(seed, o1, "linked", dataset="osint", confidence=0.9)
        ftm_store.add_edge(seed, o2, "linked", dataset="osint", confidence=0.9)

        bbox = [100.0, 13.0, 101.0, 14.5]
        out = sg.build_subgraph(
            bbox=bbox, hops=2, window_hours=48, seed_limit=10, node_limit=20
        )
        self.assertTrue(out["available"])
        for node in out["nodes"]:
            self.assertIn("density_score", node)
            self.assertIn("hub", node)

    def test_format_prompt_prunes_stale_edges(self):
        block = sg.format_subgraph_prompt_block(
            {
                "available": True,
                "hops": 2,
                "node_count": 3,
                "nodes": [
                    {
                        "id": "a",
                        "schema": "Event",
                        "caption": "A",
                        "hop": 0,
                        "in_bbox": True,
                        "datasets": ["gdacs"],
                    },
                    {
                        "id": "b",
                        "schema": "Organization",
                        "caption": "B",
                        "hop": 1,
                        "datasets": ["osint"],
                    },
                    {
                        "id": "c",
                        "schema": "Event",
                        "caption": "C",
                        "hop": 1,
                        "datasets": ["gdelt"],
                    },
                ],
                "edges": [
                    {
                        "source_id": "a",
                        "target_id": "b",
                        "kind": "linked",
                        "dataset": "osint",
                        "decay_weight": 0.8,
                    },
                    {
                        "source_id": "a",
                        "target_id": "c",
                        "kind": "linked",
                        "dataset": "gdelt",
                        "decay_weight": 0.05,
                    },
                ],
            },
            lang="en",
        )
        self.assertIn("A", block)
        self.assertIn("B", block)
        # C's edge is pruned (decay_weight 0.05 < floor 0.3) — should not appear in Links
        lines = block.split("\n")
        link_section = False
        for line in lines:
            if line.startswith("Links:"):
                link_section = True
                continue
            if link_section and "C" in line:
                self.fail("Stale edge to C should have been pruned from Links section")

    def test_format_prompt_hub_tag(self):
        block = sg.format_subgraph_prompt_block(
            {
                "available": True,
                "hops": 2,
                "node_count": 2,
                "nodes": [
                    {
                        "id": "a",
                        "schema": "Event",
                        "caption": "HubNode",
                        "hop": 0,
                        "in_bbox": True,
                        "datasets": ["gdacs"],
                        "hub": True,
                    },
                    {
                        "id": "b",
                        "schema": "Organization",
                        "caption": "Other",
                        "hop": 1,
                        "datasets": ["osint"],
                        "hub": False,
                    },
                ],
                "edges": [
                    {
                        "source_id": "a",
                        "target_id": "b",
                        "kind": "linked",
                        "dataset": "osint",
                        "decay_weight": 0.9,
                    },
                ],
            },
            lang="en",
        )
        self.assertIn("hub", block)

    def test_format_prompt_aggregation_count(self):
        block = sg.format_subgraph_prompt_block(
            {
                "available": True,
                "hops": 2,
                "node_count": 2,
                "nodes": [
                    {
                        "id": "a",
                        "schema": "Event",
                        "caption": "A",
                        "hop": 0,
                        "in_bbox": True,
                        "datasets": ["gdacs"],
                    },
                    {
                        "id": "b",
                        "schema": "Organization",
                        "caption": "B",
                        "hop": 1,
                        "datasets": ["osint"],
                    },
                ],
                "edges": [
                    {
                        "source_id": "a",
                        "target_id": "b",
                        "kind": "relatedEvent",
                        "dataset": "gdelt",
                        "decay_weight": 0.8,
                        "count": 5,
                    },
                ],
            },
            lang="en",
        )
        self.assertIn("x5", block)


if __name__ == "__main__":
    unittest.main()
