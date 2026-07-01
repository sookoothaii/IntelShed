"""Tests for V4-39 — Bitemporal entity store."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class TestBitemporal(unittest.TestCase):
    """Bitemporal versioning, time travel, and corrections."""

    _test_counter = 0

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        os.environ["WORLDBASE_DB_PATH"] = os.path.join(
            cls._tmpdir.name, "test_bitemporal.db"
        )

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("WORLDBASE_DB_PATH", None)
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        TestBitemporal._test_counter += 1
        self._db_path = os.path.join(
            self._tmpdir.name, f"test_bitemporal_{TestBitemporal._test_counter}.db"
        )
        os.environ["WORLDBASE_DB_PATH"] = self._db_path

    def test_ensure_tables(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        conn = sqlite3.connect(self._db_path)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        self.assertIn("entity_versions", tables)

    def test_record_version(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        result = bitemporal.record_version(
            "ent-001",
            schema="Person",
            caption="John Doe",
            properties={"name": ["John Doe"]},
            datasets=["test"],
            valid_from="2020-01-01T00:00:00+00:00",
            valid_to="2023-06-30T00:00:00+00:00",
            source="test",
        )
        self.assertEqual(result["entity_id"], "ent-001")
        self.assertEqual(result["version"], 1)
        self.assertIsNotNone(result["system_from"])
        self.assertEqual(result["valid_from"], "2020-01-01T00:00:00+00:00")

    def test_version_increment(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        v1 = bitemporal.record_version("ent-002", caption="V1")
        v2 = bitemporal.record_version("ent-002", caption="V2")
        v3 = bitemporal.record_version("ent-002", caption="V3")
        self.assertEqual(v1["version"], 1)
        self.assertEqual(v2["version"], 2)
        self.assertEqual(v3["version"], 3)

    def test_get_entity_history(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version("ent-003", caption="First", change_type="create")
        bitemporal.record_version("ent-003", caption="Second", change_type="upsert")
        bitemporal.record_version("ent-003", caption="Third", change_type="upsert")

        history = bitemporal.get_entity_history("ent-003")
        self.assertEqual(len(history), 3)
        # Newest first
        self.assertEqual(history[0]["caption"], "Third")
        self.assertEqual(history[2]["caption"], "First")

    def test_get_version(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version("ent-004", caption="V1", properties={"x": [1]})
        bitemporal.record_version("ent-004", caption="V2", properties={"x": [2]})

        v1 = bitemporal.get_version("ent-004", 1)
        self.assertIsNotNone(v1)
        self.assertEqual(v1["caption"], "V1")
        self.assertEqual(v1["properties"], {"x": [1]})

        v2 = bitemporal.get_version("ent-004", 2)
        self.assertEqual(v2["caption"], "V2")

    def test_get_version_not_found(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        self.assertIsNone(bitemporal.get_version("nonexistent", 1))

    def test_as_of_system_time(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()

        # Record v1 at time T1
        v1 = bitemporal.record_version("ent-005", caption="Old")
        t1 = v1["system_from"]

        # Record v2 at time T2 (closes v1's system_to)
        v2 = bitemporal.record_version("ent-005", caption="New")
        t2 = v2["system_from"]

        # Query at T1 should return v1
        result = bitemporal.as_of_system_time("ent-005", t1)
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "Old")

        # Query at T2 should return v2
        result = bitemporal.as_of_system_time("ent-005", t2)
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "New")

    def test_as_of_valid_time(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version(
            "ent-006",
            caption="2020-2023",
            valid_from="2020-01-01T00:00:00+00:00",
            valid_to="2023-06-30T00:00:00+00:00",
        )
        bitemporal.record_version(
            "ent-006",
            caption="2023-present",
            valid_from="2023-07-01T00:00:00+00:00",
            valid_to=None,
        )

        # Query for 2021 → should return first version
        result = bitemporal.as_of_valid_time("ent-006", "2021-06-15T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "2020-2023")

        # Query for 2024 → should return second version
        result = bitemporal.as_of_valid_time("ent-006", "2024-01-01T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "2023-present")

    def test_as_of_valid_time_null_interval(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version("ent-007", caption="Always true")

        # Null valid_from/valid_to → always matches
        result = bitemporal.as_of_valid_time("ent-007", "1999-01-01T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "Always true")

    def test_as_of_both(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()

        v1 = bitemporal.record_version(
            "ent-008",
            caption="Old fact",
            valid_from="2010-01-01T00:00:00+00:00",
            valid_to="2015-01-01T00:00:00+00:00",
        )
        t1 = v1["system_from"]

        v2 = bitemporal.record_version(
            "ent-008",
            caption="New fact",
            valid_from="2015-01-01T00:00:00+00:00",
            valid_to=None,
        )
        t2 = v2["system_from"]

        # At system T1, valid 2012 → old fact
        result = bitemporal.as_of_both("ent-008", t1, "2012-06-01T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "Old fact")

        # At system T2, valid 2020 → new fact
        result = bitemporal.as_of_both("ent-008", t2, "2020-06-01T00:00:00+00:00")
        self.assertIsNotNone(result)
        self.assertEqual(result["caption"], "New fact")

    def test_correct_valid_time(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version(
            "ent-009",
            caption="To correct",
            valid_from="2020-01-01T00:00:00+00:00",
            valid_to="2023-01-01T00:00:00+00:00",
        )

        success = bitemporal.correct_valid_time(
            "ent-009",
            1,
            valid_from="2019-06-01T00:00:00+00:00",
            valid_to="2023-12-31T00:00:00+00:00",
        )
        self.assertTrue(success)

        v = bitemporal.get_version("ent-009", 1)
        self.assertEqual(v["valid_from"], "2019-06-01T00:00:00+00:00")
        self.assertEqual(v["valid_to"], "2023-12-31T00:00:00+00:00")

    def test_correct_valid_time_not_found(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        self.assertFalse(
            bitemporal.correct_valid_time("nonexistent", 1, valid_from="x")
        )

    def test_bitemporal_stats(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version("stat-1", caption="A", change_type="create")
        bitemporal.record_version("stat-1", caption="B", change_type="upsert")
        bitemporal.record_version("stat-2", caption="C", change_type="create")

        stats = bitemporal.bitemporal_stats()
        self.assertEqual(stats["total_versions"], 3)
        self.assertEqual(stats["unique_entities"], 2)
        self.assertIn("create", stats["by_change_type"])
        self.assertIn("upsert", stats["by_change_type"])

    def test_system_to_closed_on_new_version(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version("ent-010", caption="V1")
        bitemporal.record_version("ent-010", caption="V2")

        # v1's system_to should be set (not NULL)
        v1_data = bitemporal.get_version("ent-010", 1)
        self.assertIsNotNone(v1_data["system_to"])

        # v2's system_to should be NULL (current)
        v2_data = bitemporal.get_version("ent-010", 2)
        self.assertIsNone(v2_data["system_to"])

    def test_properties_serialized(self):
        import bitemporal

        bitemporal._ensure_bitemporal_tables()
        bitemporal.record_version(
            "ent-011",
            caption="Props test",
            properties={"name": ["Alice"], "email": ["alice@test.com"]},
            datasets=["feed-a", "feed-b"],
        )

        v = bitemporal.get_version("ent-011", 1)
        self.assertEqual(v["properties"]["name"], ["Alice"])
        self.assertEqual(v["properties"]["email"], ["alice@test.com"])
        self.assertEqual(v["datasets"], ["feed-a", "feed-b"])


if __name__ == "__main__":
    unittest.main()
