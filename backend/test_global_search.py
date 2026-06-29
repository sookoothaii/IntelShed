"""Tests for V4-08 FTS5 Global Search — indexing, search, rebuild, fail-soft."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

# Ensure clean env
os.environ.pop("WORLDBASE_GLOBAL_SEARCH", None)

import global_search as gs


class TestGlobalSearchEnabled(unittest.TestCase):
    def test_default_disabled(self):
        os.environ.pop("WORLDBASE_GLOBAL_SEARCH", None)
        self.assertFalse(gs._enabled())

    def test_enabled_flag(self):
        os.environ["WORLDBASE_GLOBAL_SEARCH"] = "1"
        try:
            self.assertTrue(gs._enabled())
        finally:
            os.environ.pop("WORLDBASE_GLOBAL_SEARCH", None)


class TestInitAndSearch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db = gs._DB_PATH
        gs._DB_PATH = self._tmp.name
        # Create source tables + populate
        conn = sqlite3.connect(self._tmp.name)
        conn.executescript("""
            CREATE TABLE entities (
                id TEXT PRIMARY KEY, type TEXT, label TEXT,
                lat REAL, lon REAL, source_feed TEXT, external_id TEXT,
                meta_json TEXT, updated_at TEXT
            );
            CREATE TABLE rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT, source_id TEXT, text TEXT,
                embedding_json TEXT, meta_json TEXT, created_at TEXT
            );
            CREATE TABLE briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT, text TEXT
            );
        """)
        conn.execute(
            "INSERT INTO entities (id, type, label) VALUES (?, ?, ?)",
            ("ent-1", "Person", "Alice Cooper"),
        )
        conn.execute(
            "INSERT INTO rag_chunks (source, source_id, text, embedding_json, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "gdelt_pulse",
                "g1",
                "Bangkok flood warning issued today",
                "[]",
                "{}",
                "2026-01-01",
            ),
        )
        conn.execute(
            "INSERT INTO briefings (created_at, text) VALUES (?, ?)",
            (
                "2026-01-01T00:00:00Z",
                "Daily security briefing: Thailand situation stable",
            ),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        gs._DB_PATH = self._orig_db
        os.unlink(self._tmp.name)

    def test_init_creates_fts_table(self):
        gs.init_global_search_db()
        conn = sqlite3.connect(self._tmp.name)
        # Verify FTS5 table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='global_search_fts'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(tables), 1)

    def test_rebuild_indexes_all_sources(self):
        # Mock FtM indexing to avoid DuckDB dependency
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            result = gs.rebuild_index()
        self.assertTrue(result["ok"])
        self.assertEqual(result["total_indexed"], 3)  # 1 entity + 1 rag + 1 briefing
        self.assertEqual(result["by_source"]["entity_store"], 1)
        self.assertEqual(result["by_source"]["rag_chunk"], 1)
        self.assertEqual(result["by_source"]["briefing"], 1)

    def test_search_finds_entity(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("Alice")
        self.assertTrue(any(r["ref_id"] == "ent-1" for r in results))
        self.assertTrue(any(r["source_type"] == "entity_store" for r in results))

    def test_search_finds_rag_chunk(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("Bangkok flood")
        self.assertTrue(any(r["source_type"] == "rag_chunk" for r in results))

    def test_search_finds_briefing(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("security briefing Thailand")
        self.assertTrue(any(r["source_type"] == "briefing" for r in results))

    def test_search_empty_query_returns_empty(self):
        results = gs.global_search("")
        self.assertEqual(results, [])
        results = gs.global_search("   ")
        self.assertEqual(results, [])

    def test_search_filter_by_source_type(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("Alice", source_type="entity_store")
        self.assertTrue(all(r["source_type"] == "entity_store" for r in results))

    def test_search_no_results_for_garbage(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("zzzznonexistentxyzzy")
        self.assertEqual(results, [])

    def test_rebuild_clears_old_data(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
            # Rebuild again — should not duplicate
            result = gs.rebuild_index()
        self.assertEqual(result["total_indexed"], 3)  # Still 3, not 6

    def test_search_results_have_required_fields(self):
        with patch.object(gs, "_index_ftm_entities", return_value=0), patch.object(
            gs, "_index_ftm_statements", return_value=0
        ):
            gs.rebuild_index()
        results = gs.global_search("Alice")
        self.assertTrue(len(results) > 0)
        r = results[0]
        self.assertIn("ref_id", r)
        self.assertIn("source_type", r)
        self.assertIn("title", r)
        self.assertIn("snippet", r)
        self.assertIn("score", r)
        self.assertIn("meta", r)


class TestSourceWeights(unittest.TestCase):
    def test_entity_weight_higher_than_rag(self):
        self.assertGreater(
            gs._SOURCE_WEIGHTS["entity"],
            gs._SOURCE_WEIGHTS["rag_chunk"],
        )

    def test_briefing_weight_higher_than_rag(self):
        self.assertGreater(
            gs._SOURCE_WEIGHTS["briefing"],
            gs._SOURCE_WEIGHTS["rag_chunk"],
        )


class TestFtmIndexingFailSoft(unittest.TestCase):
    def test_ftm_entities_fail_soft(self):
        """If DuckDB/FtM is unavailable, indexing returns 0 without raising."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE VIRTUAL TABLE global_search_fts USING fts5(ref_id, source_type, title, body, meta_json)"
        )
        with patch("ftm_query.list_entities", side_effect=Exception("DuckDB locked")):
            n = gs._index_ftm_entities(conn)
        self.assertEqual(n, 0)
        conn.close()

    def test_ftm_statements_fail_soft(self):
        """If DuckDB is unavailable, statement indexing returns 0 without raising."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE VIRTUAL TABLE global_search_fts USING fts5(ref_id, source_type, title, body, meta_json)"
        )
        with patch("duckdb.connect", side_effect=Exception("DuckDB locked")):
            n = gs._index_ftm_statements(conn)
        self.assertEqual(n, 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
