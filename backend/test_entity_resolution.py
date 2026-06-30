"""Unit tests for entity resolution (deterministic path; Splink optional)."""

import os
import tempfile
import unittest

import entity_resolution
import ftm_connection
import ftm_store


class EntityResolutionTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()
        entity_resolution._LAST_RUN = None
        entity_resolution._LAST_ERROR = None

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

    def test_exact_name_country_creates_same_as_edge(self):
        p1 = ftm_store.make_entity(
            "Person", ["a"], {"name": "Alice Example", "country": "th"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["b"], {"name": "alice example", "country": "TH"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        result = entity_resolution.run_resolution(schemas=("Person",))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["exact_edges"], 1)
        self.assertGreaterEqual(result["resolution_edges_total"], 1)
        g = ftm_store.graph_view(p1.id, depth=1)
        kinds = {e["kind"] for e in g["edges"]}
        self.assertIn("sameAs", kinds)

    def test_different_names_do_not_exact_match(self):
        p1 = ftm_store.make_entity("Person", ["x"], {"name": "Alice", "country": "de"})
        p2 = ftm_store.make_entity("Person", ["y"], {"name": "Bob", "country": "de"})
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        result = entity_resolution.run_resolution(schemas=("Person",))
        self.assertEqual(result["exact_edges"], 0)

    def test_token_subset_links_partial_name(self):
        p1 = ftm_store.make_entity("Person", ["e1"], {"name": "Erdogan"})
        p2 = ftm_store.make_entity("Person", ["e2"], {"name": "Recep Tayyip Erdogan"})
        ftm_store.upsert(p1, dataset="newsA")
        ftm_store.upsert(p2, dataset="newsB")
        result = entity_resolution.run_resolution(schemas=("Person",))
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["subset_edges"], 1)
        g = ftm_store.graph_view(p1.id, depth=1)
        self.assertIn("sameAs", {e["kind"] for e in g["edges"]})

    def test_multi_token_subset_links_org_variants(self):
        o1 = ftm_store.make_entity(
            "Organization", ["u1"], {"name": "University of Alaska"}
        )
        o2 = ftm_store.make_entity(
            "Organization", ["u2"], {"name": "University of Alaska Fairbanks"}
        )
        ftm_store.upsert(o1, dataset="docA")
        ftm_store.upsert(o2, dataset="docB")
        result = entity_resolution.run_resolution(schemas=("Organization",))
        self.assertGreaterEqual(result["subset_edges"], 1)

    def test_generic_single_token_not_subset_matched(self):
        o1 = ftm_store.make_entity("Organization", ["g1"], {"name": "Authorities"})
        o2 = ftm_store.make_entity(
            "Organization", ["g2"], {"name": "Local Authorities"}
        )
        ftm_store.upsert(o1, dataset="docA")
        ftm_store.upsert(o2, dataset="docB")
        result = entity_resolution.run_resolution(schemas=("Organization",))
        self.assertEqual(result["subset_edges"], 0)

    def test_short_single_token_not_subset_matched(self):
        o1 = ftm_store.make_entity("Organization", ["s1"], {"name": "EU"})
        o2 = ftm_store.make_entity("Organization", ["s2"], {"name": "EU States"})
        ftm_store.upsert(o1, dataset="docA")
        ftm_store.upsert(o2, dataset="docB")
        result = entity_resolution.run_resolution(schemas=("Organization",))
        self.assertEqual(result["subset_edges"], 0)

    def test_scattered_common_name_subset_not_matched(self):
        # "Jose Hernandez" shares only the 1st + last token of "Ricardo Jose
        # Moron Hernandez" (scattered, not contiguous) -> different people.
        p1 = ftm_store.make_entity("Person", ["h1"], {"name": "Jose Hernandez"})
        p2 = ftm_store.make_entity(
            "Person", ["h2"], {"name": "Ricardo Jose Moron Hernandez"}
        )
        ftm_store.upsert(p1, dataset="sanA")
        ftm_store.upsert(p2, dataset="sanB")
        result = entity_resolution.run_resolution(schemas=("Person",))
        self.assertEqual(result["subset_edges"], 0)

    def test_name_only_schema_above_em_threshold_does_not_crash(self):
        # Regression: with the Splink stage enabled, EM training on a name-derived
        # blocking rule with only a name comparison produced invalid SQL.
        # >= _EM_MIN_ROWS distinct persons with no country must run clean.
        try:
            import splink  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("splink not installed")
        n = entity_resolution._EM_MIN_ROWS + 5
        for i in range(n):
            p = ftm_store.make_entity(
                "Person", [f"u{i}"], {"name": f"Unique{i} Distinct{i}"}
            )
            ftm_store.upsert(p, dataset="bulk")
        prev = entity_resolution._SPLINK_ENABLED
        entity_resolution._SPLINK_ENABLED = True
        try:
            result = entity_resolution.run_resolution(schemas=("Person",))
        finally:
            entity_resolution._SPLINK_ENABLED = prev
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])

    def test_status_reports_resolution_dataset_count(self):
        ftm_store.add_edge(
            "a",
            "b",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.9,
        )
        st = entity_resolution.status()
        self.assertGreaterEqual(st["resolution_edges"], 1)


class LabelVersioningTests(unittest.TestCase):
    """Lücke 1: resolution_labels must persist model_version + confidence_timestamp."""

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.unlink(self.path)  # DuckDB needs to create the file itself
        ftm_connection._CONN = None
        ftm_connection._INIT_ERROR = None
        ftm_connection.set_db_path(self.path)
        ftm_store.upsert(
            ftm_store.make_entity("Person", ["s1"], {"name": "Alice"}),
            dataset="feedA",
        )
        ftm_store.upsert(
            ftm_store.make_entity("Person", ["t1"], {"name": "Alice"}),
            dataset="feedB",
        )

    def tearDown(self):
        ftm_connection._CONN = None
        ftm_connection._INIT_ERROR = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_label_pair_writes_model_version(self):
        result = entity_resolution.label_pair(
            "s1",
            "t1",
            confirmed=True,
            schema="Person",
            model_version="20260628_120000",
            confidence=0.78,
        )
        self.assertTrue(result["ok"])
        from ftm_connection import _conn

        row = (
            _conn()
            .execute(
                "SELECT model_version, confidence, confidence_timestamp "
                "FROM resolution_labels WHERE pair_id = ?",
                ["s1::t1"],
            )
            .fetchone()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "20260628_120000")
        self.assertEqual(row[1], 0.78)
        self.assertIsNotNone(row[2])

    def test_label_pair_defaults_model_version(self):
        result = entity_resolution.label_pair(
            "s1", "t1", confirmed=False, schema="Person"
        )
        self.assertTrue(result["ok"])
        from ftm_connection import _conn

        row = (
            _conn()
            .execute(
                "SELECT model_version FROM resolution_labels WHERE pair_id = ?",
                ["s1::t1"],
            )
            .fetchone()
        )
        self.assertIsNotNone(row)
        # Should be "unknown" or a timestamp string, not NULL
        self.assertIsNotNone(row[0])

    def test_get_model_version_returns_string(self):
        ver = entity_resolution._get_model_version()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)

    def test_schema_migration_adds_columns(self):
        """Verify that _migrate_resolution_labels_schema adds the new columns."""
        from ftm_schema import _migrate_resolution_labels_schema
        from ftm_connection import _conn

        # Drop and recreate without new columns to simulate old DB
        conn = _conn()
        conn.execute("DROP TABLE IF EXISTS resolution_labels")
        conn.execute(
            "CREATE TABLE resolution_labels ("
            "pair_id VARCHAR PRIMARY KEY, source_id VARCHAR NOT NULL, "
            "target_id VARCHAR NOT NULL, schema VARCHAR, confidence DOUBLE, "
            "confirmed BOOLEAN, labeled_at VARCHAR)"
        )
        # Run migration
        _migrate_resolution_labels_schema(conn)
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'resolution_labels'"
            ).fetchall()
        }
        self.assertIn("model_version", cols)
        self.assertIn("confidence_timestamp", cols)


if __name__ == "__main__":
    unittest.main()
