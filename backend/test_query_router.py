"""Offline unit tests for P1 Query Router — classification + route dispatch."""

from __future__ import annotations

import os
import unittest

from query_router import (
    classify_query,
    fallback_route,
    route_label,
    router_enabled,
    VALID_ROUTES,
)


class TestClassification(unittest.TestCase):
    """classify_query() signal detection."""

    def test_empty_query_returns_fallback(self):
        self.assertEqual(classify_query(""), fallback_route())
        self.assertEqual(classify_query("   "), fallback_route())

    def test_graph_entity_connection(self):
        self.assertEqual(classify_query("who is Alice Johnson?"), "graph")

    def test_graph_relationship_keywords(self):
        self.assertEqual(
            classify_query("connection between vessel Alpha and org Beta"), "graph"
        )

    def test_graph_related_to(self):
        self.assertEqual(
            classify_query("entities related to the Bangkok event"), "graph"
        )

    def test_graph_same_as_duplicate(self):
        self.assertEqual(
            classify_query("are these two persons same as each other?"), "graph"
        )

    def test_spatial_near(self):
        self.assertEqual(classify_query("what events are near Bangkok?"), "spatial")

    def test_spatial_within_radius(self):
        self.assertEqual(
            classify_query("entities within 50km of the border"), "spatial"
        )

    def test_spatial_coordinates(self):
        self.assertEqual(
            classify_query("show me entities around coordinates 13.7, 100.5"), "spatial"
        )

    def test_live_temporal(self):
        self.assertEqual(classify_query("what is the current situation today?"), "live")

    def test_live_breaking(self):
        self.assertEqual(classify_query("any breaking news or latest updates?"), "live")

    def test_vector_factual(self):
        self.assertEqual(classify_query("what is the GDELT pulse?"), "vector")

    def test_vector_summarize(self):
        self.assertEqual(classify_query("summarize the last briefing"), "vector")

    def test_vector_explain(self):
        self.assertEqual(classify_query("explain the FtM schema"), "vector")

    def test_hybrid_mixed_signals(self):
        """Graph + spatial signals together → hybrid."""
        route = classify_query("who is near the border and connected to org Alpha?")
        self.assertEqual(route, "hybrid")

    def test_hybrid_graph_and_temporal(self):
        route = classify_query(
            "what are the latest connections between these entities?"
        )
        self.assertEqual(route, "hybrid")

    def test_no_signal_returns_fallback(self):
        self.assertEqual(classify_query("hello"), fallback_route())

    def test_route_is_always_valid(self):
        queries = [
            "who is X",
            "near Bangkok",
            "what is AI",
            "latest news today",
            "connection between A and B near border",
            "random text xyz",
        ]
        for q in queries:
            route = classify_query(q)
            self.assertIn(route, VALID_ROUTES, f"Invalid route '{route}' for '{q}'")


class TestEnvFlags(unittest.TestCase):
    """Env-based configuration."""

    def test_router_enabled_default(self):
        os.environ.pop("WORLDBASE_QUERY_ROUTER", None)
        self.assertTrue(router_enabled())

    def test_router_disabled(self):
        os.environ["WORLDBASE_QUERY_ROUTER"] = "0"
        self.assertFalse(router_enabled())
        os.environ.pop("WORLDBASE_QUERY_ROUTER", None)

    def test_fallback_default(self):
        os.environ.pop("WORLDBASE_QUERY_ROUTER_FALLBACK", None)
        self.assertEqual(fallback_route(), "vector")

    def test_fallback_custom(self):
        os.environ["WORLDBASE_QUERY_ROUTER_FALLBACK"] = "graph"
        self.assertEqual(fallback_route(), "graph")
        os.environ.pop("WORLDBASE_QUERY_ROUTER_FALLBACK", None)

    def test_fallback_invalid_defaults_vector(self):
        os.environ["WORLDBASE_QUERY_ROUTER_FALLBACK"] = "nonsense"
        self.assertEqual(fallback_route(), "vector")
        os.environ.pop("WORLDBASE_QUERY_ROUTER_FALLBACK", None)


class TestRouteLabel(unittest.TestCase):
    """route_label() returns human-readable strings."""

    def test_all_routes_have_labels(self):
        for route in VALID_ROUTES:
            label = route_label(route)
            self.assertTrue(label.isupper() or label[0].isupper())
            self.assertIn(route.upper(), label.upper())

    def test_unknown_route(self):
        label = route_label("unknown")
        self.assertEqual(label, "UNKNOWN")


class TestRouteRetrieval(unittest.TestCase):
    """route_retrieval() dispatch — offline, no network."""

    def test_live_route_returns_dict(self):
        import asyncio
        from query_router import route_retrieval

        result = asyncio.run(route_retrieval("latest news today", route="live"))
        self.assertEqual(result["route"], "live")
        self.assertIn("block", result)
        self.assertIn("meta", result)

    def test_graph_route_returns_dict(self):
        import asyncio
        from query_router import route_retrieval

        result = asyncio.run(route_retrieval("who is Alice?", route="graph"))
        self.assertEqual(result["route"], "graph")
        self.assertIn("block", result)
        self.assertIn("meta", result)

    def test_vector_route_returns_dict(self):
        import asyncio
        from query_router import route_retrieval

        result = asyncio.run(route_retrieval("what is GDELT?", route="vector"))
        self.assertEqual(result["route"], "vector")
        self.assertIn("block", result)

    def test_spatial_route_returns_dict(self):
        import asyncio
        from query_router import route_retrieval

        result = asyncio.run(route_retrieval("near Bangkok", route="spatial"))
        self.assertEqual(result["route"], "spatial")
        self.assertIn("block", result)

    def test_hybrid_route_returns_dict(self):
        import asyncio
        from query_router import route_retrieval

        result = asyncio.run(route_retrieval("who is near the border?", route="hybrid"))
        self.assertEqual(result["route"], "hybrid")
        self.assertIn("block", result)

    def test_router_disabled_uses_fallback(self):
        import asyncio
        from query_router import route_retrieval

        os.environ["WORLDBASE_QUERY_ROUTER"] = "0"
        try:
            result = asyncio.run(route_retrieval("who is Alice?", route="graph"))
            self.assertEqual(result["route"], fallback_route())
        finally:
            os.environ.pop("WORLDBASE_QUERY_ROUTER", None)


if __name__ == "__main__":
    unittest.main()
