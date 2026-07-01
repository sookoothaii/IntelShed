"""Tests for V4-10 — Classification labels and federation gate."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class TestClassification(unittest.TestCase):
    """Classification levels, entity labeling, and federation gate."""

    _test_counter = 0

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        os.environ["WORLDBASE_DB_PATH"] = os.path.join(
            cls._tmpdir.name, "test_classification.db"
        )

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("WORLDBASE_DB_PATH", None)
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        TestClassification._test_counter += 1
        self._db_path = os.path.join(
            self._tmpdir.name,
            f"test_classification_{TestClassification._test_counter}.db",
        )
        os.environ["WORLDBASE_DB_PATH"] = self._db_path

    def test_classification_level_enum(self):
        from classification import ClassificationLevel

        self.assertEqual(ClassificationLevel.UNCLASSIFIED, 0)
        self.assertEqual(ClassificationLevel.CONFIDENTIAL, 1)
        self.assertEqual(ClassificationLevel.SECRET, 2)
        self.assertEqual(ClassificationLevel.TOP_SECRET, 3)

    def test_from_string(self):
        from classification import ClassificationLevel

        self.assertEqual(
            ClassificationLevel.from_string("UNCLASSIFIED"),
            ClassificationLevel.UNCLASSIFIED,
        )
        self.assertEqual(
            ClassificationLevel.from_string("confidential"),
            ClassificationLevel.CONFIDENTIAL,
        )
        self.assertEqual(
            ClassificationLevel.from_string("Secret"), ClassificationLevel.SECRET
        )
        self.assertEqual(
            ClassificationLevel.from_string("top-secret"),
            ClassificationLevel.TOP_SECRET,
        )
        self.assertEqual(
            ClassificationLevel.from_string("top secret"),
            ClassificationLevel.TOP_SECRET,
        )

    def test_from_string_invalid(self):
        from classification import ClassificationLevel

        with self.assertRaises(ValueError):
            ClassificationLevel.from_string("ULTRA_SECRET")

    def test_label(self):
        from classification import ClassificationLevel

        self.assertEqual(ClassificationLevel.SECRET.label(), "SECRET")
        self.assertEqual(ClassificationLevel.UNCLASSIFIED.label(), "UNCLASSIFIED")

    def test_ensure_tables(self):
        import classification

        classification._ensure_classification_tables()
        conn = sqlite3.connect(self._db_path)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        conn.close()
        self.assertIn("entity_classification", tables)
        self.assertIn("dataset_classification", tables)
        self.assertIn("federation_nodes", tables)

    def test_classify_entity(self):
        import classification

        classification._ensure_classification_tables()
        result = classification.classify_entity(
            "ent-001", "SECRET", reason="sensitive source"
        )
        self.assertEqual(result["entity_id"], "ent-001")
        self.assertEqual(result["level_label"], "SECRET")
        self.assertEqual(result["level"], 2)
        self.assertEqual(result["reason"], "sensitive source")

    def test_get_entity_classification(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("ent-002", "CONFIDENTIAL")
        result = classification.get_entity_classification("ent-002")
        self.assertEqual(result["level_label"], "CONFIDENTIAL")
        self.assertEqual(result["level"], 1)

    def test_get_entity_classification_default(self):
        import classification

        classification._ensure_classification_tables()
        result = classification.get_entity_classification("nonexistent-ent")
        self.assertIsNotNone(result)
        self.assertEqual(result["level"], 0)
        self.assertEqual(result["reason"], "default")

    def test_bulk_classify(self):
        import classification

        classification._ensure_classification_tables()
        count = classification.bulk_classify_entities(
            ["ent-a", "ent-b", "ent-c"], "CONFIDENTIAL"
        )
        self.assertEqual(count, 3)

        for eid in ["ent-a", "ent-b", "ent-c"]:
            result = classification.get_entity_classification(eid)
            self.assertEqual(result["level_label"], "CONFIDENTIAL")

    def test_remove_entity_classification(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("ent-rm", "SECRET")
        self.assertTrue(classification.remove_entity_classification("ent-rm"))
        result = classification.get_entity_classification("ent-rm")
        self.assertEqual(result["reason"], "default")

    def test_dataset_default(self):
        import classification

        classification._ensure_classification_tables()
        result = classification.set_dataset_default("osint-feeds", "CONFIDENTIAL")
        self.assertEqual(result["default_level_label"], "CONFIDENTIAL")

        result = classification.get_dataset_default("osint-feeds")
        self.assertEqual(result["default_level_label"], "CONFIDENTIAL")

    def test_dataset_default_unset(self):
        import classification

        classification._ensure_classification_tables()
        result = classification.get_dataset_default("nonexistent-dataset")
        self.assertEqual(result["default_level"], 0)

    def test_federation_node_register(self):
        import classification

        classification._ensure_classification_tables()
        result = classification.register_federation_node(
            "node-alpha", "SECRET", node_name="Alpha Node"
        )
        self.assertEqual(result["node_id"], "node-alpha")
        self.assertEqual(result["max_clearance_label"], "SECRET")
        self.assertEqual(result["max_clearance"], 2)

    def test_federation_node_list(self):
        import classification

        classification._ensure_classification_tables()
        classification.register_federation_node("node-1", "UNCLASSIFIED")
        classification.register_federation_node("node-2", "SECRET")
        nodes = classification.list_federation_nodes()
        self.assertEqual(len(nodes), 2)

    def test_federation_node_remove(self):
        import classification

        classification._ensure_classification_tables()
        classification.register_federation_node("node-rm", "CONFIDENTIAL")
        self.assertTrue(classification.remove_federation_node("node-rm"))
        nodes = classification.list_federation_nodes()
        self.assertEqual(len(nodes), 0)

    def test_federation_gate_allows(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("ent-public", "UNCLASSIFIED")
        classification.classify_entity("ent-secret", "SECRET")

        allowed, blocked = classification.federation_gate(
            ["ent-public", "ent-secret"], "CONFIDENTIAL"
        )
        self.assertIn("ent-public", allowed)
        self.assertIn("ent-secret", blocked)

    def test_federation_gate_all_pass(self):
        import classification

        classification._ensure_classification_tables()
        allowed, blocked = classification.federation_gate(
            ["ent-1", "ent-2", "ent-3"], "TOP_SECRET"
        )
        self.assertEqual(len(allowed), 3)
        self.assertEqual(len(blocked), 0)

    def test_federation_gate_all_blocked(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("ent-ts", "TOP_SECRET")
        allowed, blocked = classification.federation_gate(["ent-ts"], "UNCLASSIFIED")
        self.assertEqual(len(allowed), 0)
        self.assertEqual(len(blocked), 1)

    def test_federation_gate_int_level(self):
        import classification

        classification._ensure_classification_tables()
        allowed, _ = classification.federation_gate(["ent-x"], 0)
        self.assertIn("ent-x", allowed)

    def test_filter_entities_by_clearance(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("ent-filter-1", "SECRET")
        entities = [
            {"id": "ent-filter-1", "caption": "Secret Entity"},
            {"id": "ent-filter-2", "caption": "Public Entity"},
        ]
        filtered = classification.filter_entities_by_clearance(entities, "CONFIDENTIAL")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "ent-filter-2")

    def test_filter_empty_list(self):
        import classification

        result = classification.filter_entities_by_clearance([], "SECRET")
        self.assertEqual(result, [])

    def test_classification_stats(self):
        import classification

        classification._ensure_classification_tables()
        classification.classify_entity("stat-1", "UNCLASSIFIED")
        classification.classify_entity("stat-2", "SECRET")
        classification.classify_entity("stat-3", "SECRET")

        stats = classification.classification_stats()
        self.assertEqual(stats["total_classified_entities"], 3)
        by_level = {b["label"]: b["count"] for b in stats["by_level"]}
        self.assertEqual(by_level.get("SECRET"), 2)
        self.assertEqual(by_level.get("UNCLASSIFIED"), 1)


if __name__ == "__main__":
    unittest.main()
