"""Tests for Session 16 — SAR, Push Delivery, Subgraph A/B, Benchmark, LLM A/B."""

from __future__ import annotations

import asyncio
import os
import unittest


# ---------------------------------------------------------------------------
# SAR Bridge
# ---------------------------------------------------------------------------


class TestSARBridge(unittest.TestCase):
    def setUp(self):
        os.environ["WORLDBASE_SAR"] = "1"

    def tearDown(self):
        os.environ.pop("WORLDBASE_SAR", None)

    def test_sar_disabled_by_default(self):
        os.environ.pop("WORLDBASE_SAR", None)
        import importlib

        import sar_bridge

        importlib.reload(sar_bridge)
        self.assertFalse(sar_bridge.sar_enabled())

    def test_sar_enabled(self):
        import sar_bridge

        self.assertTrue(sar_bridge.sar_enabled())

    def test_cfar_detects_bright_targets(self):
        import sar_bridge

        # 20x20 grid with one bright target at center
        grid = [[0.1] * 20 for _ in range(20)]
        grid[10][10] = 0.95
        dets = sar_bridge._ca_cfar_detect(grid, guard_cells=1, train_cells=2, pfa=1e-3)
        self.assertGreater(len(dets), 0)
        row, col, snr = dets[0]
        self.assertEqual(row, 10)
        self.assertEqual(col, 10)
        self.assertGreater(snr, 0)

    def test_cfar_empty_grid(self):
        import sar_bridge

        dets = sar_bridge._ca_cfar_detect([], guard_cells=2, train_cells=4)
        self.assertEqual(dets, [])

    def test_cfar_uniform_noise_no_detections(self):
        import sar_bridge

        grid = [[0.1] * 20 for _ in range(20)]
        dets = sar_bridge._ca_cfar_detect(grid, guard_cells=2, train_cells=4, pfa=1e-8)
        self.assertEqual(len(dets), 0)

    def test_pixel_to_geo(self):
        import sar_bridge

        bbox = [100.0, 7.0, 102.0, 9.0]
        lat, lon = sar_bridge._pixel_to_geo(0, 0, 64, 64, bbox)
        self.assertAlmostEqual(lat, 9.0, places=2)
        self.assertAlmostEqual(lon, 100.0, places=2)

        lat, lon = sar_bridge._pixel_to_geo(63, 63, 64, 64, bbox)
        self.assertAlmostEqual(lat, 7.0, places=2)
        self.assertAlmostEqual(lon, 102.0, places=2)

    def test_haversine(self):
        import sar_bridge

        # Bangkok to Phuket ~ 690 km
        dist = sar_bridge._haversine_km(13.75, 100.5, 7.88, 98.39)
        self.assertGreater(dist, 600)
        self.assertLess(dist, 750)

    def test_match_ais_within_threshold(self):
        import sar_bridge

        vessels = [
            {"mmsi": 123456, "name": "TEST_VESSEL", "lat": 13.75, "lon": 100.5},
        ]
        match = sar_bridge._match_ais(13.75, 100.5, vessels, threshold_km=2.0)
        self.assertIsNotNone(match)
        self.assertEqual(match["mmsi"], 123456)
        self.assertTrue(match["matched"])

    def test_match_ais_no_match(self):
        import sar_bridge

        vessels = [
            {"mmsi": 123456, "lat": 1.0, "lon": 1.0},
        ]
        match = sar_bridge._match_ais(13.75, 100.5, vessels, threshold_km=2.0)
        self.assertIsNone(match)

    def test_simulate_amplitude_grid(self):
        import sar_bridge

        scene = {"id": "test_scene_001"}
        grid = sar_bridge._simulate_amplitude_grid(scene, size=32)
        self.assertEqual(len(grid), 32)
        self.assertEqual(len(grid[0]), 32)
        # Should have some values > 0.5 (bright targets)
        max_val = max(max(row) for row in grid)
        self.assertGreater(max_val, 0.5)


# ---------------------------------------------------------------------------
# Push Delivery
# ---------------------------------------------------------------------------


class TestPushDelivery(unittest.TestCase):
    def setUp(self):
        os.environ["WORLDBASE_PUSH"] = "1"
        import importlib

        import push_delivery

        importlib.reload(push_delivery)
        self.push = push_delivery

    def tearDown(self):
        os.environ.pop("WORLDBASE_PUSH", None)
        self.push._client_queues.clear()
        self.push._watch_items.clear()
        self.push._event_history.clear()

    def test_push_disabled_by_default(self):
        os.environ.pop("WORLDBASE_PUSH", None)
        import importlib

        import push_delivery

        importlib.reload(push_delivery)
        self.assertFalse(push_delivery.push_enabled())

    def test_register_watch_item(self):
        item = self.push.register_watch_item(
            "test_watch",
            item_type="geo_fence",
            criteria={"bbox": [100, 7, 102, 9]},
            label="Test Watch",
        )
        self.assertEqual(item["id"], "test_watch")
        self.assertEqual(item["type"], "geo_fence")
        self.assertTrue(item["active"])
        self.assertEqual(item["triggered_count"], 0)

    def test_remove_watch_item(self):
        self.push.register_watch_item("test", item_type="generic", criteria={})
        removed = self.push.remove_watch_item("test")
        self.assertTrue(removed)
        removed = self.push.remove_watch_item("nonexistent")
        self.assertFalse(removed)

    def test_trigger_event_no_clients(self):
        event = self.push.trigger_event("test_event", {"message": "hello"})
        self.assertEqual(event["type"], "test_event")
        self.assertEqual(event["data"]["message"], "hello")
        self.assertGreater(event["id"], 0)

    def test_trigger_event_with_queue(self):
        queue = asyncio.Queue(maxsize=10)
        self.push._client_queues["test_client"] = queue

        self.push.trigger_event("alert", {"level": "high"})
        self.push.trigger_event("info", {"msg": "update"})

        self.assertEqual(queue.qsize(), 2)
        event = queue.get_nowait()
        self.assertEqual(event["type"], "alert")

    def test_trigger_updates_watch_item_stats(self):
        self.push.register_watch_item("watch_1", item_type="generic", criteria={})
        self.push.trigger_event("test", {"data": 1}, watch_item_id="watch_1")
        item = self.push._watch_items["watch_1"]
        self.assertEqual(item["triggered_count"], 1)
        self.assertIsNotNone(item["last_triggered"])

    def test_format_sse(self):
        sse = self.push._format_sse("alert", {"msg": "test"}, event_id=42)
        self.assertIn("id: 42", sse)
        self.assertIn("event: alert", sse)
        self.assertIn("data:", sse)
        self.assertIn('"msg": "test"', sse)


# ---------------------------------------------------------------------------
# Subgraph A/B
# ---------------------------------------------------------------------------


class TestSubgraphAB(unittest.TestCase):
    def setUp(self):
        os.environ["WORLDBASE_SUBGRAPH_AB"] = "1"

    def tearDown(self):
        os.environ.pop("WORLDBASE_SUBGRAPH_AB", None)

    def test_disabled_by_default(self):
        os.environ.pop("WORLDBASE_SUBGRAPH_AB", None)
        import importlib

        import subgraph_ab

        importlib.reload(subgraph_ab)
        self.assertFalse(subgraph_ab.subgraph_ab_enabled())

    def test_jaccard_identical(self):
        import subgraph_ab

        result = subgraph_ab._jaccard({1, 2, 3}, {1, 2, 3})
        self.assertEqual(result, 1.0)

    def test_jaccard_disjoint(self):
        import subgraph_ab

        result = subgraph_ab._jaccard({1, 2}, {3, 4})
        self.assertEqual(result, 0.0)

    def test_jaccard_partial(self):
        import subgraph_ab

        result = subgraph_ab._jaccard({1, 2, 3}, {2, 3, 4})
        self.assertAlmostEqual(result, 0.5, places=2)

    def test_jaccard_both_empty(self):
        import subgraph_ab

        result = subgraph_ab._jaccard(set(), set())
        self.assertEqual(result, 1.0)

    def test_schema_distribution(self):
        import subgraph_ab

        nodes = [
            {"id": "1", "schema": "Person"},
            {"id": "2", "schema": "Person"},
            {"id": "3", "schema": "Company"},
        ]
        dist = subgraph_ab._schema_distribution(nodes)
        self.assertEqual(dist["Person"], 2)
        self.assertEqual(dist["Company"], 1)

    def test_edge_type_distribution(self):
        import subgraph_ab

        edges = [
            {"source": "1", "target": "2", "type": "owns"},
            {"source": "2", "target": "3", "type": "owns"},
            {"source": "1", "target": "3", "type": "knows"},
        ]
        dist = subgraph_ab._edge_type_distribution(edges)
        self.assertEqual(dist["owns"], 2)
        self.assertEqual(dist["knows"], 1)

    def test_degree_centrality(self):
        import subgraph_ab

        nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "C"},
        ]
        degree = subgraph_ab._degree_centrality(nodes, edges)
        self.assertEqual(degree["A"], 2)
        self.assertEqual(degree["B"], 2)
        self.assertEqual(degree["C"], 2)

    def test_top_k_by_degree(self):
        import subgraph_ab

        degree = {"A": 5, "B": 3, "C": 1, "D": 4}
        top = subgraph_ab._top_k_by_degree(degree, k=2)
        self.assertEqual(top[0]["id"], "A")
        self.assertEqual(top[0]["degree"], 5)
        self.assertEqual(top[1]["id"], "D")
        self.assertEqual(top[1]["degree"], 4)


# ---------------------------------------------------------------------------
# Benchmark vec1
# ---------------------------------------------------------------------------


class TestBenchmarkVec1(unittest.TestCase):
    def setUp(self):
        os.environ["WORLDBASE_BENCHMARK"] = "1"

    def tearDown(self):
        os.environ.pop("WORLDBASE_BENCHMARK", None)

    def test_disabled_by_default(self):
        os.environ.pop("WORLDBASE_BENCHMARK", None)
        import importlib

        import benchmark_vec1

        importlib.reload(benchmark_vec1)
        self.assertFalse(benchmark_vec1.benchmark_enabled())

    def test_benchmark_queries_exist(self):
        import benchmark_vec1

        self.assertGreaterEqual(len(benchmark_vec1._BENCHMARK_QUERIES), 15)
        # Check categories
        categories = {q["category"] for q in benchmark_vec1._BENCHMARK_QUERIES}
        self.assertIn("spatial", categories)
        self.assertIn("keyword", categories)

    def test_benchmark_queries_have_query_and_category(self):
        import benchmark_vec1

        for q in benchmark_vec1._BENCHMARK_QUERIES:
            self.assertIn("query", q)
            self.assertIn("category", q)
            self.assertIsInstance(q["query"], str)
            self.assertGreater(len(q["query"]), 5)


# ---------------------------------------------------------------------------
# LLM A/B
# ---------------------------------------------------------------------------


class TestLLMAB(unittest.TestCase):
    def setUp(self):
        os.environ["WORLDBASE_LLM_AB"] = "1"

    def tearDown(self):
        os.environ.pop("WORLDBASE_LLM_AB", None)

    def test_disabled_by_default(self):
        os.environ.pop("WORLDBASE_LLM_AB", None)
        import importlib

        import llm_ab

        importlib.reload(llm_ab)
        self.assertFalse(llm_ab.llm_ab_enabled())

    def test_estimate_tokens(self):
        import llm_ab

        # "hello world" = 11 chars → ~2 tokens
        self.assertEqual(llm_ab._estimate_tokens("hello world"), 2)
        # Empty string → 1 (min)
        self.assertEqual(llm_ab._estimate_tokens(""), 1)

    def test_quality_heuristics_empty(self):
        import llm_ab

        q = llm_ab._quality_heuristics("")
        self.assertEqual(q["chars"], 0)
        self.assertEqual(q["words"], 0)
        self.assertEqual(q["quality_score"], 0.0)

    def test_quality_heuristics_with_evidence(self):
        import llm_ab

        content = """
## Analysis
The vessel was detected at [EVIDENCE-001] coordinates 13.75N, 100.5E.
Confidence: HIGH based on [EVIDENCE-002].
[source: AIS feed]
"""
        q = llm_ab._quality_heuristics(content)
        self.assertGreater(q["chars"], 0)
        self.assertGreater(q["words"], 5)
        self.assertEqual(q["evidence_refs"], 2)
        self.assertGreater(q["section_headers"], 0)
        self.assertGreater(q["source_tags"], 0)
        self.assertGreater(q["quality_score"], 0.25)

    def test_quality_heuristics_no_evidence(self):
        import llm_ab

        content = "This is a short response with no evidence tags or sources."
        q = llm_ab._quality_heuristics(content)
        self.assertEqual(q["evidence_refs"], 0)
        self.assertEqual(q["source_tags"], 0)
        self.assertLess(q["quality_score"], 0.2)

    def test_determine_winner_both_failed(self):
        import llm_ab

        result_a = {"error": "timeout", "latency_ms": 60000}
        result_b = {"error": "auth", "latency_ms": 100}
        qa = {"quality_score": 0.0}
        qb = {"quality_score": 0.0}
        winner = llm_ab._determine_winner(result_a, result_b, qa, qb)
        self.assertEqual(winner["winner"], "none")

    def test_determine_winner_a_failed(self):
        import llm_ab

        result_a = {"error": "timeout", "latency_ms": 60000}
        result_b = {"error": None, "latency_ms": 2000}
        qa = {"quality_score": 0.0}
        qb = {"quality_score": 0.5}
        winner = llm_ab._determine_winner(result_a, result_b, qa, qb)
        self.assertEqual(winner["winner"], "b")

    def test_determine_winner_quality_tie(self):
        import llm_ab

        result_a = {"error": None, "latency_ms": 1000}
        result_b = {"error": None, "latency_ms": 2000}
        qa = {"quality_score": 0.5}
        qb = {"quality_score": 0.52}
        winner = llm_ab._determine_winner(result_a, result_b, qa, qb)
        self.assertEqual(winner["winner"], "a")
        self.assertEqual(winner["reason"], "quality_tie_faster")

    def test_determine_winner_higher_quality(self):
        import llm_ab

        result_a = {"error": None, "latency_ms": 5000}
        result_b = {"error": None, "latency_ms": 1000}
        qa = {"quality_score": 0.8}
        qb = {"quality_score": 0.3}
        winner = llm_ab._determine_winner(result_a, result_b, qa, qb)
        self.assertEqual(winner["winner"], "a")
        self.assertEqual(winner["reason"], "higher_quality")


# ---------------------------------------------------------------------------
# useMapEngine (frontend hook) — smoke test via import
# ---------------------------------------------------------------------------


class TestUseMapEngineHook(unittest.TestCase):
    """The hook is TypeScript — verify the file exists and exports are correct."""

    def test_file_exists(self):
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "hooks",
            "useMapEngine.ts",
        )
        self.assertTrue(os.path.exists(path))

    def test_exports_documented(self):
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "frontend",
            "src",
            "hooks",
            "useMapEngine.ts",
        )
        with open(path) as f:
            content = f.read()
        self.assertIn("export type MapEngine", content)
        self.assertIn("export function useMapEngine", content)
        self.assertIn("export async function loadDeckGL", content)
        self.assertIn("deck.gl", content)


if __name__ == "__main__":
    unittest.main()
