"""Unit tests for YAML mapping runner and feed normalizers (no network)."""

import os
import tempfile
import unittest

import feed_ingest
import ftm_connection
import ftm_store
from ingest.mapping_runner import apply_mapping


class MappingRunnerTest(unittest.TestCase):
    def setUp(self):
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

    def test_gdelt_events_mapping_writes_event(self):
        record = feed_ingest.normalize_gdelt_geo(
            {
                "name": "Flood near Bangkok",
                "url": "http://example.com/a",
                "lat": 13.7,
                "lon": 100.5,
            },
            0,
        )
        result = apply_mapping([record], "gdelt_events", dataset="gdelt-geo")
        self.assertEqual(result["entities_written"], 1)
        self.assertGreaterEqual(ftm_store.stats()["entities"], 1)

    def test_gdacs_mapping_writes_event_without_coords(self):
        record = feed_ingest.normalize_gdacs_alert(
            {"title": "EQ Alert", "published": "2026-06-17", "eventtype": "EQ"},
            0,
        )
        result = apply_mapping([record], "gdacs_alerts", dataset="gdacs")
        self.assertEqual(result["entities_written"], 1)
        self.assertEqual(result["edges_written"], 0)

    def test_gdacs_with_coords_writes_place_link(self):
        record = feed_ingest.normalize_gdacs_alert(
            {
                "title": "EQ Alert",
                "published": "2026-06-17",
                "lat": 1.0,
                "lon": 2.0,
                "eventtype": "EQ",
            },
            0,
        )
        result = apply_mapping([record], "gdacs_alerts", dataset="gdacs")
        self.assertEqual(result["entities_written"], 3)
        self.assertEqual(result["edges_written"], 1)
        stats = ftm_store.stats()
        self.assertGreaterEqual(stats["entities"], 2)

    def test_mapping_aliases_get_distinct_entity_ids(self):
        """Event + place must not share one id (DuckDB INSERT OR REPLACE schema clash)."""
        record = feed_ingest.normalize_gdacs_alert(
            {
                "title": "Flood",
                "published": "2026-06-17",
                "lat": 10.0,
                "lon": 20.0,
                "eventtype": "FL",
            },
            0,
        )
        apply_mapping([record], "gdacs_alerts", dataset="gdacs")
        rows = (
            ftm_store._conn()
            .execute(
                "SELECT id, schema FROM entities WHERE id LIKE 'gdacs:%' ORDER BY id"
            )
            .fetchall()
        )
        schemas = {r[1] for r in rows}
        self.assertIn("Event", schemas)
        self.assertIn("Address", schemas)
        self.assertGreaterEqual(len(rows), 2)

    def test_gdacs_rag_profile_present(self):
        from ingest.mapping_runner import load_rag_profile

        profile = load_rag_profile("gdacs_alerts")
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.strategy, "paragraph")

    def test_iter_rag_chunk_entries_from_gdelt_record(self):
        from ingest.mapping_runner import iter_rag_chunk_entries

        record = feed_ingest.normalize_gdelt_geo(
            {
                "name": "Flood near Bangkok",
                "url": "http://example.com/a",
                "lat": 13.7,
                "lon": 100.5,
            },
            0,
        )
        entries = iter_rag_chunk_entries(
            [record], "gdelt_events", rag_source="gdelt_geo"
        )
        self.assertEqual(len(entries), 1)
        self.assertIn("Bangkok", entries[0][2])

    def test_ais_vessel_mapping(self):
        record = feed_ingest.normalize_ais_vessel(
            {
                "mmsi": "123456789",
                "name": "Test Ship",
                "flag": "DE",
                "type": "Cargo",
                "lat": 53.5,
                "lon": 9.9,
            }
        )
        result = apply_mapping([record], "ais_vessels", dataset="ais")
        self.assertEqual(result["entities_written"], 3)
        self.assertEqual(result["edges_written"], 1)


if __name__ == "__main__":
    unittest.main()
