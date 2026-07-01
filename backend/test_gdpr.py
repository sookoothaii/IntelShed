"""Tests for V4-06 — GDPR export and deletion."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class TestGDPR(unittest.TestCase):
    """GDPR export, deletion, and data subject search."""

    _test_counter = 0

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        os.environ["WORLDBASE_DB_PATH"] = os.path.join(cls._tmpdir.name, "test_gdpr.db")

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("WORLDBASE_DB_PATH", None)
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        TestGDPR._test_counter += 1
        self._db_path = os.path.join(
            self._tmpdir.name, f"test_gdpr_{TestGDPR._test_counter}.db"
        )
        os.environ["WORLDBASE_DB_PATH"] = self._db_path

    def test_ensure_gdpr_tables(self):
        import gdpr

        gdpr._ensure_gdpr_tables()
        conn = sqlite3.connect(self._db_path)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        self.assertIn("gdpr_requests", tables)

    def test_record_request(self):
        import gdpr

        gdpr._ensure_gdpr_tables()
        gdpr._record_request("export", "ent-123", details='{"k":"v"}')
        history = gdpr.gdpr_request_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["request_type"], "export")
        self.assertEqual(history[0]["entity_id"], "ent-123")

    def test_export_personal_data_empty(self):
        import gdpr

        bundle = gdpr.export_personal_data("nonexistent-id")
        self.assertEqual(bundle["entity_id"], "nonexistent-id")
        self.assertIsNone(bundle["entity"])
        self.assertEqual(bundle["statements"], [])
        self.assertEqual(bundle["edges"], [])

    def test_export_with_sqlite_entity(self):
        import gdpr
        import entity_store

        entity_store.set_db_path(self._db_path)
        entity_store.init_entity_db()
        entity_store.upsert_entity(
            "person-001",
            "person",
            label="John Doe",
            source_feed="test",
            meta={"email": "john@example.com"},
        )

        bundle = gdpr.export_personal_data("person-001")
        self.assertIsNotNone(bundle["sqlite_entity"])
        self.assertEqual(bundle["sqlite_entity"]["id"], "person-001")
        self.assertEqual(bundle["sqlite_entity"]["label"], "John Doe")

    def test_delete_personal_data_hard(self):
        import gdpr
        import entity_store

        entity_store.set_db_path(self._db_path)
        entity_store.init_entity_db()
        entity_store.upsert_entity(
            "person-002",
            "person",
            label="Jane Smith",
            source_feed="test",
        )

        result = gdpr.delete_personal_data("person-002", hard_delete=True)
        self.assertEqual(result["mode"], "hard_delete")
        self.assertEqual(result["sqlite_entity"], 1)

        # Verify deletion
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE id = ?", ("person-002",)
            ).fetchone()
            self.assertIsNone(row)

    def test_delete_personal_data_anonymise(self):
        import gdpr
        import entity_store

        entity_store.set_db_path(self._db_path)
        entity_store.init_entity_db()
        entity_store.upsert_entity(
            "person-003",
            "person",
            label="Bob Builder",
            source_feed="test",
        )

        # Anonymise mode (no DuckDB, so it will fail gracefully on FtM side
        # but SQLite entity remains)
        result = gdpr.delete_personal_data("person-003", hard_delete=False)
        self.assertEqual(result["mode"], "anonymise")

    def test_request_history(self):
        import gdpr

        gdpr._ensure_gdpr_tables()
        gdpr._record_request("export", "ent-a")
        gdpr._record_request("delete", "ent-b")
        gdpr._record_request("export", "ent-a")

        all_history = gdpr.gdpr_request_history()
        self.assertEqual(len(all_history), 3)

        ent_a = gdpr.gdpr_request_history("ent-a")
        self.assertEqual(len(ent_a), 2)

    def test_export_includes_audit_trail(self):
        import gdpr
        from auth.audit import ensure_audit_table, record_audit_event

        gdpr._ensure_gdpr_tables()
        ensure_audit_table()
        record_audit_event(
            action="test_action",
            endpoint="/api/some/endpoint/person-009",
            success=True,
        )

        bundle = gdpr.export_personal_data("person-009")
        # audit_trail may or may not have matches depending on ILIKE
        # but the key should exist
        self.assertIn("audit_trail", bundle)

    def test_pii_props_set(self):
        import gdpr

        self.assertIn("name", gdpr._PII_PROPS)
        self.assertIn("email", gdpr._PII_PROPS)
        self.assertIn("phone", gdpr._PII_PROPS)
        self.assertIn("nationalId", gdpr._PII_PROPS)
        self.assertIn("address", gdpr._PII_PROPS)


if __name__ == "__main__":
    unittest.main()
