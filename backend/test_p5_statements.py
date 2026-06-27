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

    def test_get_entity_provenance_function_exists(self):
        from ftm_query import get_entity_provenance

        self.assertTrue(callable(get_entity_provenance))

    def test_detect_value_conflicts_function_exists(self):
        from ftm_query import detect_value_conflicts

        self.assertTrue(callable(detect_value_conflicts))

    def test_make_stmt_id_deterministic(self):
        from ftm_query import _make_stmt_id

        sid1 = _make_stmt_id("gdacs", "ent1", "name", "Test Event")
        sid2 = _make_stmt_id("gdacs", "ent1", "name", "Test Event")
        self.assertEqual(sid1, sid2)
        self.assertEqual(len(sid1), 40)  # SHA1 hex

    def test_make_stmt_id_different_inputs(self):
        from ftm_query import _make_stmt_id

        sid1 = _make_stmt_id("gdacs", "ent1", "name", "A")
        sid2 = _make_stmt_id("gdelt", "ent1", "name", "A")
        self.assertNotEqual(sid1, sid2)

    def test_make_stmt_id_matches_ftm_statement_key(self):
        from ftm_query import _make_stmt_id
        from followthemoney.statement import Statement

        ours = _make_stmt_id("gdacs", "ent1", "name", "Test")
        theirs = Statement.make_key("gdacs", "ent1", "name", "Test", external=False)
        self.assertEqual(ours, theirs)


class TestP5StatementFields(unittest.TestCase):
    """P5 — StatementEntity field coverage in get_statements."""

    def test_get_statements_returns_full_fields(self):
        """get_statements should return all P5 StatementEntity fields."""
        from ftm_query import get_statements

        # Call with a non-existent entity — should return empty list, not error
        result = get_statements("nonexistent-entity-id-12345")
        self.assertIsInstance(result, list)

    def test_get_statements_field_names(self):
        """Verify the expected field names are in the query."""
        import inspect

        from ftm_query import get_statements

        source = inspect.getsource(get_statements)
        # Check that the SQL query selects the new P5 columns
        self.assertIn("stmt_id", source)
        self.assertIn("canonical_id", source)
        self.assertIn("schema", source)
        self.assertIn("first_seen", source)
        self.assertIn("last_seen", source)
        self.assertIn("origin", source)


class TestP5ProvenanceScoring(unittest.TestCase):
    """P5 — Statement-level provenance scoring."""

    def test_score_statement_function_exists(self):
        from provenance import score_statement

        self.assertTrue(callable(score_statement))

    def test_score_statement_basic(self):
        from provenance import score_statement

        score = score_statement(
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "entity_id": "ent1",
                "prop": "name",
            }
        )
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_score_statement_unknown_dataset(self):
        from provenance import score_statement

        score = score_statement(
            {
                "dataset": "unknown",
                "seen_at": None,
            }
        )
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_statement_provenance_summary_empty(self):
        from provenance import statement_provenance_summary

        result = statement_provenance_summary([])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["scored"], 0)
        self.assertEqual(result["avg_score"], 0.0)
        self.assertEqual(result["conflicts"], 0)

    def test_statement_provenance_summary_with_data(self):
        from provenance import statement_provenance_summary

        statements = [
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "prop": "name",
                "value": "Event A",
            },
            {
                "dataset": "gdelt",
                "seen_at": "2026-06-25T09:00:00Z",
                "prop": "name",
                "value": "Event A",
            },
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "prop": "country",
                "value": "TH",
            },
        ]
        result = statement_provenance_summary(statements)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["scored"], 3)
        self.assertGreater(result["avg_score"], 0.0)
        self.assertIn("gdacs", result["by_dataset"])
        self.assertIn("gdelt", result["by_dataset"])
        # name has 1 distinct value, country has 1 → 0 conflicts
        self.assertEqual(result["conflicts"], 0)

    def test_statement_provenance_summary_detects_conflicts(self):
        from provenance import statement_provenance_summary

        statements = [
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "prop": "name",
                "value": "Alpha",
            },
            {
                "dataset": "gdelt",
                "seen_at": "2026-06-25T09:00:00Z",
                "prop": "name",
                "value": "Beta",
            },
        ]
        result = statement_provenance_summary(statements)
        self.assertEqual(result["conflicts"], 1)

    def test_statement_provenance_summary_by_dataset_avg(self):
        from provenance import statement_provenance_summary

        statements = [
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "prop": "name",
                "value": "A",
            },
            {
                "dataset": "gdacs",
                "seen_at": "2026-06-25T08:00:00Z",
                "prop": "country",
                "value": "TH",
            },
        ]
        result = statement_provenance_summary(statements)
        gdacs = result["by_dataset"]["gdacs"]
        self.assertEqual(gdacs["count"], 2)
        self.assertGreater(gdacs["avg_score"], 0.0)


class TestP5EntityProvenance(unittest.TestCase):
    """P5 — get_entity_provenance structure."""

    def test_get_entity_provenance_returns_dict(self):
        from ftm_query import get_entity_provenance

        result = get_entity_provenance("nonexistent-entity-id-12345")
        self.assertIsInstance(result, dict)
        self.assertIn("entity_id", result)
        self.assertIn("datasets", result)
        self.assertIn("total_statements", result)
        self.assertIn("by_prop", result)
        self.assertIn("by_dataset", result)

    def test_get_entity_provenance_empty(self):
        from ftm_query import get_entity_provenance

        result = get_entity_provenance("nonexistent-entity-id-12345")
        self.assertEqual(result["total_statements"], 0)
        self.assertEqual(result["datasets"], [])


class TestP5ValueConflicts(unittest.TestCase):
    """P5 — detect_value_conflicts structure."""

    def test_detect_value_conflicts_returns_list(self):
        from ftm_query import detect_value_conflicts

        result = detect_value_conflicts("nonexistent-entity-id-12345")
        self.assertIsInstance(result, list)

    def test_detect_value_conflicts_empty(self):
        from ftm_query import detect_value_conflicts

        result = detect_value_conflicts("nonexistent-entity-id-12345")
        self.assertEqual(result, [])


class TestP5SchemaMigration(unittest.TestCase):
    """P5 — Schema migration adds StatementEntity columns."""

    def test_migrate_statements_schema_exists(self):
        from ftm_schema import _migrate_statements_schema

        self.assertTrue(callable(_migrate_statements_schema))

    def test_stmt_new_columns_defined(self):
        from ftm_schema import _STMT_NEW_COLUMNS

        col_names = [c[0] for c in _STMT_NEW_COLUMNS]
        self.assertIn("stmt_id", col_names)
        self.assertIn("canonical_id", col_names)
        self.assertIn("schema", col_names)
        self.assertIn("original_value", col_names)
        self.assertIn("external", col_names)
        self.assertIn("first_seen", col_names)
        self.assertIn("last_seen", col_names)
        self.assertIn("origin", col_names)

    def test_migrate_statements_schema_idempotent(self):
        """Running migration twice should not raise."""
        import duckdb

        from ftm_schema import _migrate_statements_schema, _create_schema

        con = duckdb.connect(":memory:")
        _create_schema(con)
        # Second call should be a no-op (columns already exist)
        _migrate_statements_schema(con)
        # Verify columns exist
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'statements'"
            ).fetchall()
        }
        for expected in [
            "stmt_id",
            "canonical_id",
            "schema",
            "first_seen",
            "last_seen",
            "origin",
        ]:
            self.assertIn(expected, cols)


class TestP5UpsertFields(unittest.TestCase):
    """P5 — Verify upsert writes full StatementEntity columns."""

    def test_upsert_impl_writes_stmt_id(self):
        """Check that _upsert_impl source code references stmt_id and canonical_id."""
        import inspect

        from ftm_query import _upsert_impl

        source = inspect.getsource(_upsert_impl)
        self.assertIn("stmt_id", source)
        self.assertIn("canonical_id", source)
        self.assertIn("schema_name", source)
        self.assertIn("first_seen", source)


class TestP5PlusExternalEdges(unittest.TestCase):
    """P5+ — Dynamic Knowledge Graph external edges."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

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

    def test_ftm_api_has_statement_conflicts_route(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/statements/conflicts", paths)

    def test_ftm_api_has_statement_provenance_summary_route(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/statements/provenance/summary", paths)

    def test_ftm_api_has_entity_provenance_route(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/entity/{entity_id}/provenance", paths)

    def test_ftm_api_has_external_edge_routes(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/edges/external", paths)
        self.assertIn("/api/intel/edges/approve", paths)
        self.assertIn("/api/intel/edges/reject", paths)
        self.assertIn("/api/intel/edges/review/stats", paths)


class TestP5StoreReExports(unittest.TestCase):
    """P5 — ftm_store re-exports new functions."""

    def test_ftm_store_exports_get_statements(self):
        import ftm_store

        self.assertTrue(callable(ftm_store.get_statements))

    def test_ftm_store_exports_get_entity_provenance(self):
        import ftm_store

        self.assertTrue(callable(ftm_store.get_entity_provenance))

    def test_ftm_store_exports_detect_value_conflicts(self):
        import ftm_store

        self.assertTrue(callable(ftm_store.detect_value_conflicts))

    def test_ftm_store_exports_make_stmt_id(self):
        import ftm_store

        self.assertTrue(callable(ftm_store._make_stmt_id))

    def test_ftm_store_exports_query_by_provenance(self):
        import ftm_store

        self.assertTrue(callable(ftm_store.query_by_provenance))

    def test_ftm_store_exports_statement_stats(self):
        import ftm_store

        self.assertTrue(callable(ftm_store.statement_stats))


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
