"""Tests for P5/P5+ — FtM StatementEntity + Edge Review."""

from __future__ import annotations

import os
import unittest


class TestP5Statements(unittest.TestCase):
    """P5 — Per-value provenance query helpers."""

    def test_ftm_statements_disabled_by_default(self):
        os.environ.pop("WORLDBASE_FTM_STATEMENTS", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.ftm_statements_enabled)

    def test_ftm_statements_enabled(self):
        os.environ["WORLDBASE_FTM_STATEMENTS"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.ftm_statements_enabled)
        finally:
            os.environ.pop("WORLDBASE_FTM_STATEMENTS", None)

    def test_get_statements_function_exists(self):
        from ftm_query import get_statements

        self.assertTrue(callable(get_statements))

    def test_query_by_provenance_function_exists(self):
        from ftm_query import query_by_provenance

        self.assertTrue(callable(query_by_provenance))

    def test_statement_stats_function_exists(self):
        from ftm_query import statement_stats

        self.assertTrue(callable(statement_stats))


class TestP5PlusExternalEdges(unittest.TestCase):
    """P5+ — Dynamic Knowledge Graph external edges."""

    def test_dynamic_graph_disabled_by_default(self):
        os.environ.pop("WORLDBASE_DYNAMIC_GRAPH", None)
        from edge_review import dynamic_graph_enabled

        self.assertFalse(dynamic_graph_enabled())

    def test_dynamic_graph_enabled(self):
        os.environ["WORLDBASE_DYNAMIC_GRAPH"] = "1"
        try:
            from edge_review import dynamic_graph_enabled

            self.assertTrue(dynamic_graph_enabled())
        finally:
            os.environ.pop("WORLDBASE_DYNAMIC_GRAPH", None)

    def test_add_external_edge_function_exists(self):
        from ftm_query import add_external_edge

        self.assertTrue(callable(add_external_edge))

    def test_list_external_edges_function_exists(self):
        from ftm_query import list_external_edges

        self.assertTrue(callable(list_external_edges))

    def test_approve_external_edge_function_exists(self):
        from ftm_query import approve_external_edge

        self.assertTrue(callable(approve_external_edge))

    def test_reject_external_edge_function_exists(self):
        from ftm_query import reject_external_edge

        self.assertTrue(callable(reject_external_edge))

    def test_edge_review_module_functions(self):
        from edge_review import (
            list_external_edges,
            approve_edge,
            reject_edge,
            add_external_edge,
            edge_review_stats,
        )

        self.assertTrue(callable(list_external_edges))
        self.assertTrue(callable(approve_edge))
        self.assertTrue(callable(reject_edge))
        self.assertTrue(callable(add_external_edge))
        self.assertTrue(callable(edge_review_stats))

    def test_max_confidence_env(self):
        os.environ["WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE"] = "0.5"
        # Need to reimport to get new value
        import importlib
        import ftm_query

        importlib.reload(ftm_query)
        self.assertEqual(ftm_query._MAX_EXT_CONF, 0.5)
        os.environ.pop("WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE", None)


class TestP5PlusAPIRoutes(unittest.TestCase):
    """P5+ API route presence."""

    def test_ftm_api_has_statement_routes(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/statements", paths)
        self.assertIn("/api/intel/statements/provenance", paths)
        self.assertIn("/api/intel/statements/stats", paths)

    def test_ftm_api_has_external_edge_routes(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/edges/external", paths)
        self.assertIn("/api/intel/edges/approve", paths)
        self.assertIn("/api/intel/edges/reject", paths)
        self.assertIn("/api/intel/edges/review/stats", paths)


class TestConfigP5(unittest.TestCase):
    """Config integration for P5/P5+."""

    def test_config_dynamic_graph_default_off(self):
        os.environ.pop("WORLDBASE_DYNAMIC_GRAPH", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.dynamic_graph_enabled)

    def test_config_dynamic_graph_enabled(self):
        os.environ["WORLDBASE_DYNAMIC_GRAPH"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.dynamic_graph_enabled)
        finally:
            os.environ.pop("WORLDBASE_DYNAMIC_GRAPH", None)


if __name__ == "__main__":
    unittest.main()
