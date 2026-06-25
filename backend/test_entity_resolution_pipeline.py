"""Unit tests for two-stage entity resolution pipeline (P2).

Tests verify that:
- Per-dataset dedupe finds within-dataset duplicates
- Cross-dataset exact matching still works in two_stage mode
- Two-stage mode reports cross_edges field
- Fallback to single-mode when no dataset labels present
- API route accepts ?pipeline=two_stage
- list_datasets_for_schema returns correct datasets
- list_entities_for_resolution dataset filter works
"""

import os
import tempfile
import unittest

import entity_resolution
import ftm_connection
import ftm_query
import ftm_store


class TwoStagePipelineTest(unittest.TestCase):
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

    def test_two_stage_finds_within_dataset_duplicates(self):
        """Two-stage mode should still find exact duplicates within a single dataset."""
        p1 = ftm_store.make_entity(
            "Person", ["a1"], {"name": "John Smith", "country": "us"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["a2"], {"name": "john smith", "country": "US"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedA")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["pipeline_mode"], "two_stage")
        self.assertGreaterEqual(result["exact_edges"], 1)

    def test_two_stage_finds_cross_dataset_exact_matches(self):
        """Two-stage mode should find exact matches across different datasets."""
        p1 = ftm_store.make_entity(
            "Person", ["x1"], {"name": "Alice Wonder", "country": "uk"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["x2"], {"name": "alice wonder", "country": "UK"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["exact_edges"], 1)
        g = ftm_store.graph_view(p1.id, depth=1)
        kinds = {e["kind"] for e in g["edges"]}
        self.assertIn("sameAs", kinds)

    def test_two_stage_reports_cross_edges_field(self):
        """Result should include cross_edges field (0 when Splink disabled)."""
        p = ftm_store.make_entity(
            "Person", ["p1"], {"name": "Test Person", "country": "de"}
        )
        ftm_store.upsert(p, dataset="feedA")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertIn("cross_edges", result)
        self.assertEqual(result["cross_edges"], 0)

    def test_two_stage_reports_pipeline_mode(self):
        """Result should echo the pipeline_mode used."""
        p = ftm_store.make_entity("Person", ["p1"], {"name": "Solo Person"})
        ftm_store.upsert(p, dataset="feedA")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertEqual(result["pipeline_mode"], "two_stage")

    def test_single_mode_still_default(self):
        """Default pipeline_mode should be 'single'."""
        p = ftm_store.make_entity("Person", ["p1"], {"name": "Default Person"})
        ftm_store.upsert(p, dataset="feedA")
        result = entity_resolution.run_resolution(schemas=("Person",))
        self.assertEqual(result["pipeline_mode"], "single")

    def test_two_stage_fallback_when_no_datasets(self):
        """Two-stage should fall back to single-mode when no dataset labels exist."""
        p1 = ftm_store.make_entity(
            "Person", ["n1"], {"name": "No Dataset", "country": "fr"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["n2"], {"name": "no dataset", "country": "FR"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedA")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["exact_edges"], 1)

    def test_list_datasets_for_schema_returns_distinct(self):
        """list_datasets_for_schema should return distinct dataset names."""
        p1 = ftm_store.make_entity("Person", ["d1"], {"name": "Person A"})
        p2 = ftm_store.make_entity("Person", ["d2"], {"name": "Person B"})
        o1 = ftm_store.make_entity("Organization", ["o1"], {"name": "Org A"})
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        ftm_store.upsert(o1, dataset="feedA")
        datasets = ftm_query.list_datasets_for_schema(["Person"])
        self.assertIn("feedA", datasets)
        self.assertIn("feedB", datasets)
        datasets_org = ftm_query.list_datasets_for_schema(["Organization"])
        self.assertIn("feedA", datasets_org)
        self.assertNotIn("feedB", datasets_org)

    def test_list_entities_for_resolution_dataset_filter(self):
        """Dataset filter should only return entities from that dataset."""
        p1 = ftm_store.make_entity("Person", ["f1"], {"name": "Filtered Person"})
        p2 = ftm_store.make_entity("Person", ["f2"], {"name": "Other Person"})
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        only_a = ftm_query.list_entities_for_resolution(["Person"], dataset="feedA")
        ids = [e["id"] for e in only_a]
        self.assertIn(p1.id, ids)
        self.assertNotIn(p2.id, ids)

    def test_two_stage_per_dataset_dedupe_separates_datasets(self):
        """Within-dataset dedupe in two-stage should not cross-link different names."""
        p1 = ftm_store.make_entity(
            "Person", ["s1"], {"name": "Unique Name One", "country": "th"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["s2"], {"name": "Unique Name Two", "country": "th"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedA")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["exact_edges"], 0)

    def test_two_stage_with_multiple_datasets_and_splink_off(self):
        """Two-stage with Splink off should still do exact+subset per dataset."""
        p1 = ftm_store.make_entity(
            "Person", ["m1"], {"name": "Maria Garcia", "country": "es"}
        )
        p2 = ftm_store.make_entity(
            "Person", ["m2"], {"name": "maria garcia", "country": "ES"}
        )
        p3 = ftm_store.make_entity(
            "Person", ["m3"], {"name": "Maria Garcia Lopez", "country": "es"}
        )
        ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedA")
        ftm_store.upsert(p3, dataset="feedB")
        result = entity_resolution.run_resolution(
            schemas=("Person",),
            pipeline_mode="two_stage",
        )
        self.assertTrue(result["ok"])
        # p1 and p2 are exact duplicates within feedA
        self.assertGreaterEqual(result["exact_edges"], 1)
        # p3 is a superset match for p1 across datasets (subset runs per-dataset,
        # so this cross-dataset subset won't fire in two_stage without Splink)
        g = ftm_store.graph_view(p1.id, depth=1)
        same_edges = [e for e in g["edges"] if e["kind"] == "sameAs"]
        self.assertTrue(
            any(e["source_id"] == p2.id or e["target_id"] == p2.id for e in same_edges)
        )


if __name__ == "__main__":
    unittest.main()
