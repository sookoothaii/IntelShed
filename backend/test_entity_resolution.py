"""Unit tests for entity resolution (deterministic path; Splink optional)."""

import os
import tempfile
import unittest

import entity_resolution
import ftm_store


class EntityResolutionTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_store._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()
        entity_resolution._LAST_RUN = None
        entity_resolution._LAST_ERROR = None

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

    def test_exact_name_country_creates_same_as_edge(self):
        p1 = ftm_store.make_entity("Person", ["a"], {"name": "Alice Example", "country": "th"})
        p2 = ftm_store.make_entity("Person", ["b"], {"name": "alice example", "country": "TH"})
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

    def test_status_reports_resolution_dataset_count(self):
        ftm_store.add_edge("a", "b", "sameAs", dataset=entity_resolution.RESOLUTION_DATASET, confidence=0.9)
        st = entity_resolution.status()
        self.assertGreaterEqual(st["resolution_edges"], 1)


if __name__ == "__main__":
    unittest.main()
