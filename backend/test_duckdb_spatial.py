"""Unit tests for DuckDB spatial JOIN operator (R-Tree index + ST_Within).

Tests verify:
1. Spatial extension loads correctly
2. geom column is added to entities table
3. R-Tree index is created (when WORLDBASE_DUCKDB_RTREE=1)
4. ST_Within queries return correct results
5. Fallback to lat/lon BETWEEN when spatial is disabled
6. _seed_entities_in_bbox uses spatial path when available
7. _get_entities_in_bbox uses spatial path when available

Note: DuckDB 1.5.x has a FATAL bug (duckdb-spatial #769) where the R-Tree
index causes "flat vector" internal errors on writes. The R-Tree index is
not created by default. Set WORLDBASE_DUCKDB_RTREE=1 to force-enable it
for testing.
"""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_connection
import ftm_store


class DuckDBSpatialTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_connection._SPATIAL_LOADED = False
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

    def tearDown(self):
        try:
            if ftm_connection._CONN is not None:
                ftm_connection._CONN.close()
        finally:
            ftm_connection._CONN = None
            ftm_connection._SPATIAL_LOADED = False
        for ext in ("", ".wal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _seed_entity(self, key: str, lat: float, lon: float) -> str:
        proxy = ftm_store.make_entity("Event", [key], {"name": [f"Event {key}"]})
        eid = ftm_store.upsert(proxy, dataset="gdacs", lat=lat, lon=lon)
        return eid

    def test_spatial_extension_loaded(self):
        """The spatial extension should be loaded after init_store."""
        # This may be False if the extension can't be installed (air-gapped)
        # but in the venv it should be True
        self.assertTrue(
            ftm_connection.spatial_available(),
            "DuckDB spatial extension should be loaded in venv",
        )

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_geom_column_exists(self):
        """The geom GEOMETRY column should be added to entities table."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        con = ftm_connection._conn()
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'entities'"
            ).fetchall()
        }
        self.assertIn("geom", cols, "geom column should exist when spatial is loaded")

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_RTREE", "0") == "1",
        "R-Tree index disabled by default (DuckDB 1.5.x bug #769)",
    )
    def test_rtree_index_exists(self):
        """The R-Tree index should be created on the geom column when explicitly enabled."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        con = ftm_connection._conn()
        indexes = con.execute(
            "SELECT index_name FROM duckdb_indexes() WHERE table_name = 'entities'"
        ).fetchall()
        index_names = {r[0] for r in indexes}
        self.assertIn("idx_entities_geom", index_names)

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_st_within_query_returns_correct_results(self):
        """ST_Within should return entities inside the bbox and exclude others."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        inside_id = self._seed_entity("inside", 13.75, 100.5)
        outside_id = self._seed_entity("outside", 50.0, 50.0)

        con = ftm_connection._conn()
        # Thailand bbox
        rows = con.execute(
            "SELECT id FROM entities "
            "WHERE geom IS NOT NULL "
            "AND ST_Within(geom, ST_MakeEnvelope(97.0, 5.0, 106.0, 21.0))"
        ).fetchall()
        ids = {r[0] for r in rows}
        self.assertIn(inside_id, ids)
        self.assertNotIn(outside_id, ids)

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_geom_synced_on_upsert(self):
        """geom should be populated after entity upsert with lat/lon."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        eid = self._seed_entity("sync_test", 13.75, 100.5)

        con = ftm_connection._conn()
        row = con.execute(
            "SELECT lat, lon, geom IS NOT NULL FROM entities WHERE id = ?", [eid]
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 13.75)
        self.assertEqual(row[1], 100.5)
        self.assertTrue(row[2], "geom should be populated after upsert")

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_geom_updated_on_second_upsert(self):
        """geom should be updated when lat/lon change on a second upsert."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        eid = self._seed_entity("update_test", 13.75, 100.5)

        # Second upsert with different coordinates
        proxy = ftm_store.make_entity("Event", ["update_test"], {"name": ["Updated"]})
        ftm_store.upsert(proxy, dataset="gdacs", lat=50.0, lon=50.0)

        con = ftm_connection._conn()
        row = con.execute(
            "SELECT lat, lon FROM entities WHERE id = ?", [eid]
        ).fetchone()
        self.assertEqual(row[0], 50.0)
        self.assertEqual(row[1], 50.0)

        # Verify geom reflects new position via ST_Within
        rows = con.execute(
            "SELECT id FROM entities "
            "WHERE ST_Within(geom, ST_MakeEnvelope(40.0, 40.0, 60.0, 60.0))"
        ).fetchall()
        ids = {r[0] for r in rows}
        self.assertIn(eid, ids)

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_seed_entities_in_bbox_uses_spatial_path(self):
        """_seed_entities_in_bbox should return results via ST_Within when spatial is available."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        import intel_subgraph as sg

        inside_id = self._seed_entity("seed_in", 13.75, 100.5)
        outside_id = self._seed_entity("seed_out", 50.0, 50.0)

        # Use a wide window so the time filter doesn't exclude our entities
        seeds = sg._seed_entities_in_bbox(
            [97.0, 5.0, 106.0, 21.0],
            window_hours=9999,
            seed_limit=100,
            exclude_schemas=set(),
        )
        ids = {s["id"] for s in seeds}
        self.assertIn(inside_id, ids)
        self.assertNotIn(outside_id, ids)

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_get_entities_in_bbox_uses_spatial_path(self):
        """_get_entities_in_bbox should return results via ST_Within when spatial is available."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        from spatial_reasoning import _get_entities_in_bbox

        inside_id = self._seed_entity("reason_in", 13.75, 100.5)
        outside_id = self._seed_entity("reason_out", 50.0, 50.0)

        results = _get_entities_in_bbox([97.0, 5.0, 106.0, 21.0], limit=100)
        ids = {r["id"] for r in results}
        self.assertIn(inside_id, ids)
        self.assertNotIn(outside_id, ids)

    def test_fallback_when_spatial_disabled(self):
        """When spatial is disabled, queries should fall back to lat/lon BETWEEN."""
        # Drop RTREE index and close connection before disabling spatial,
        # since DuckDB requires the extension to modify tables with RTREE indexes.
        if ftm_connection._CONN is not None:
            try:
                ftm_connection._CONN.execute("DROP INDEX IF EXISTS idx_entities_geom")
            except Exception:
                pass
            ftm_connection._CONN.close()
        ftm_connection._CONN = None
        ftm_connection._SPATIAL_LOADED = False
        os.environ["WORLDBASE_DUCKDB_SPATIAL"] = "0"
        try:
            ftm_store.set_db_path(self.path)
            ftm_store.init_store()
            self.assertFalse(ftm_connection.spatial_available())

            inside_id = self._seed_entity("fallback_in", 13.75, 100.5)
            outside_id = self._seed_entity("fallback_out", 50.0, 50.0)

            import intel_subgraph as sg

            seeds = sg._seed_entities_in_bbox(
                [97.0, 5.0, 106.0, 21.0],
                window_hours=9999,
                seed_limit=100,
                exclude_schemas=set(),
            )
            ids = {s["id"] for s in seeds}
            self.assertIn(inside_id, ids)
            self.assertNotIn(outside_id, ids)
        finally:
            os.environ.pop("WORLDBASE_DUCKDB_SPATIAL", None)

    @unittest.skipUnless(
        os.getenv("WORLDBASE_DUCKDB_SPATIAL", "1") not in ("0", "false", "no"),
        "Spatial extension disabled",
    )
    def test_st_intersects_boundary_point(self):
        """ST_Intersects should return points on or near the envelope boundary."""
        if not ftm_connection.spatial_available():
            self.skipTest("spatial extension not available")
        # Point slightly inside the west edge of the envelope
        eid = self._seed_entity("boundary", 13.0, 97.001)

        con = ftm_connection._conn()
        rows = con.execute(
            "SELECT id FROM entities "
            "WHERE ST_Intersects(geom, ST_MakeEnvelope(97.0, 5.0, 106.0, 21.0))"
        ).fetchall()
        ids = {r[0] for r in rows}
        self.assertIn(
            eid,
            ids,
            "Point near boundary should be returned by ST_Intersects",
        )


if __name__ == "__main__":
    unittest.main()
