"""Tests for P6 — Spatial Reasoning Layer (NL → Spatial Operation)."""

from __future__ import annotations

import os
import unittest


class TestP6Config(unittest.TestCase):
    """P6 config integration."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_spatial_reasoning_disabled_by_default(self):
        os.environ.pop("WORLDBASE_SPATIAL_REASONING", None)
        from spatial_reasoning import spatial_reasoning_enabled

        self.assertFalse(spatial_reasoning_enabled())

    def test_spatial_reasoning_enabled(self):
        os.environ["WORLDBASE_SPATIAL_REASONING"] = "1"
        try:
            from spatial_reasoning import spatial_reasoning_enabled

            self.assertTrue(spatial_reasoning_enabled())
        finally:
            os.environ.pop("WORLDBASE_SPATIAL_REASONING", None)

    def test_config_spatial_reasoning_default_off(self):
        os.environ.pop("WORLDBASE_SPATIAL_REASONING", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.spatial_reasoning_enabled)


class TestP6NLParser(unittest.TestCase):
    """P6 NL parser pattern matching."""

    def test_parse_within(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("within 50km of Bangkok")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "within")
        self.assertEqual(plan.operations[0].params["radius_km"], 50.0)
        self.assertEqual(plan.operations[0].target, "bangkok")

    def test_parse_near(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("near Phuket")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "near")
        self.assertEqual(plan.operations[0].target, "phuket")

    def test_parse_downstream(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("downstream from Chao Phraya")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "river_direction")
        self.assertEqual(plan.operations[0].params["direction"], "downstream")

    def test_parse_border(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("near the Thailand border with Myanmar")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "border")

    def test_parse_composition_and(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("near Bangkok and within 50km of the border")
        self.assertEqual(plan.composition, "AND")
        self.assertEqual(len(plan.operations), 2)

    def test_parse_composition_or(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("near Bangkok or within 50km of Singapore")
        self.assertEqual(plan.composition, "OR")

    def test_parse_visible_from(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("visible from Bangkok")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "visible_from")

    def test_parse_contains(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("in the region of South China Sea")
        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].operation, "contains")

    def test_parse_empty_query(self):
        from spatial_reasoning import parse_spatial_query

        plan = parse_spatial_query("hello world")
        self.assertEqual(len(plan.operations), 0)


class TestP6EntityResolution(unittest.TestCase):
    """P6 entity resolution from static geography."""

    def test_resolve_city(self):
        from spatial_reasoning import resolve_entity

        result = resolve_entity("Bangkok")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "city")
        self.assertAlmostEqual(result["lat"], 13.7563, places=2)
        self.assertEqual(result["source"], "static")

    def test_resolve_river(self):
        from spatial_reasoning import resolve_entity

        result = resolve_entity("Chao Phraya")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "river")

    def test_resolve_border(self):
        from spatial_reasoning import resolve_entity

        result = resolve_entity("Thailand-Myanmar")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "border")

    def test_resolve_region(self):
        from spatial_reasoning import resolve_entity

        result = resolve_entity("South China Sea")
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "region")

    def test_resolve_not_found(self):
        from spatial_reasoning import resolve_entity

        result = resolve_entity("Nonexistent Place XYZ123")
        self.assertIsNone(result)

    def test_bbox_from_point(self):
        from spatial_reasoning import _bbox_from_point

        bbox = _bbox_from_point(13.75, 100.5, 50.0)
        self.assertEqual(len(bbox), 4)
        self.assertLess(bbox[0], bbox[2])  # west < east
        self.assertLess(bbox[1], bbox[3])  # south < north


class TestP6Executor(unittest.TestCase):
    """P6 spatial executor."""

    def test_execute_within_no_results(self):
        from spatial_reasoning import SpatialOperation, execute_spatial_operation

        op = SpatialOperation("within", "Bangkok", {"radius_km": 50.0})
        results = execute_spatial_operation(op)
        # May return empty if no FtM entities, but should not crash
        self.assertIsInstance(results, list)

    def test_execute_spatial_plan_empty(self):
        from spatial_reasoning import SpatialQueryPlan, execute_spatial_plan

        plan = SpatialQueryPlan(operations=[], composition="AND")
        result = execute_spatial_plan(plan)
        self.assertEqual(result["result_count"], 0)

    def test_spatial_query_full_pipeline(self):
        from spatial_reasoning import spatial_query

        result = spatial_query("within 50km of Bangkok")
        self.assertIn("query", result)
        self.assertIn("operations", result)
        self.assertIn("results", result)
        self.assertIn("resolved_entities", result)

    def test_spatial_reasoning_stats(self):
        from spatial_reasoning import spatial_reasoning_stats

        stats = spatial_reasoning_stats()
        self.assertIn("enabled", stats)
        self.assertIn("static_cities", stats)
        self.assertIn("operations", stats)
        self.assertGreater(stats["static_cities"], 0)


class TestP6CompositionMatrix(unittest.TestCase):
    """P6 SpaRAGraph composition matrix."""

    def test_compose_and(self):
        from spatial_relations import compose

        self.assertEqual(compose("within", "AND", "near"), "intersect_bbox")

    def test_compose_or(self):
        from spatial_relations import compose

        self.assertEqual(compose("within", "OR", "within"), "union_bbox")

    def test_compose_then_sequential(self):
        from spatial_relations import compose

        self.assertEqual(compose("river_direction", "THEN", "within"), "sequential")

    def test_compose_default_and(self):
        from spatial_relations import compose

        self.assertEqual(compose("visible_from", "AND", "contains"), "intersect_bbox")

    def test_detect_composition_and(self):
        from spatial_relations import detect_composition

        self.assertEqual(detect_composition("near Bangkok and within 50km"), "AND")

    def test_detect_composition_or(self):
        from spatial_relations import detect_composition

        self.assertEqual(detect_composition("near Bangkok or near Phuket"), "OR")

    def test_detect_composition_then(self):
        from spatial_relations import detect_composition

        self.assertEqual(detect_composition("downstream then within 50km"), "THEN")

    def test_composition_matrix(self):
        from spatial_relations import composition_matrix

        matrix = composition_matrix()
        self.assertIn("rules", matrix)
        self.assertIn("defaults", matrix)
        self.assertGreater(len(matrix["rules"]), 0)


class TestP6APIRoutes(unittest.TestCase):
    """P6 API route presence."""

    def test_spatial_router_has_query_route(self):
        from intel_proximity import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/spatial/query", paths)
        self.assertIn("/api/intel/spatial/reasoning/stats", paths)
        self.assertIn("/api/intel/spatial/composition", paths)


class TestP6PointInPolygon(unittest.TestCase):
    """P6 pure Python point-in-polygon (no Shapely)."""

    def test_point_inside_square(self):
        from spatial_reasoning import _point_in_polygon

        square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        self.assertTrue(_point_in_polygon(5, 5, square))

    def test_point_outside_square(self):
        from spatial_reasoning import _point_in_polygon

        square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        self.assertFalse(_point_in_polygon(15, 15, square))


if __name__ == "__main__":
    unittest.main()
