"""Unit tests for trigger_engine (3.4, no network)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import trigger_engine as te


class TriggerEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._db_path = self.tmp.name
        self._orig = te._DB_PATH
        te._DB_PATH = self._db_path
        te.init_trigger_db()
        # Create node tables needed for push tests
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS node_state (
                    node_id TEXT PRIMARY KEY,
                    name TEXT,
                    lat REAL,
                    lon REAL,
                    updated_at TEXT,
                    payload TEXT
                );
                CREATE TABLE IF NOT EXISTS node_commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    command TEXT NOT NULL,
                    args TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    acked_at TEXT,
                    result TEXT
                );
            """)
            conn.commit()

    def tearDown(self):
        te._DB_PATH = self._orig
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def test_default_rules_seeded(self):
        rules = te.list_rules()
        self.assertGreaterEqual(len(rules), 5)
        names = {r["name"] for r in rules}
        self.assertIn("high_fusion_cell", names)
        self.assertIn("rising_fusion_delta", names)
        self.assertIn("quake_m6_plus", names)

    def test_create_and_delete_rule(self):
        te.create_rule(
            "custom_rule",
            "fusion_score >= 0.5",
            min_confidence=0.4,
            severity="info",
            cooldown_min=30,
        )
        rules = te.list_rules(include_disabled=True)
        names = {r["name"] for r in rules}
        self.assertIn("custom_rule", names)

        te.delete_rule("custom_rule")
        rules = te.list_rules(include_disabled=True)
        names = {r["name"] for r in rules}
        self.assertNotIn("custom_rule", names)

    def test_evaluate_fusion_score_triggers(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["hazard"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        # high_fusion_cell rule should fire (score >= 0.7)
        rule_names = {t["rule_name"] for t in fired}
        self.assertIn("high_fusion_cell", rule_names)

    def test_evaluate_fusion_delta_triggers(self):
        cells = [
            {
                "cell_id": "10.00,99.00",
                "lat": 10.0,
                "lon": 99.0,
                "score": 0.55,
                "delta_score": 0.35,
                "sources": ["anomaly"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        rule_names = {t["rule_name"] for t in fired}
        self.assertIn("rising_fusion_delta", rule_names)

    def test_evaluate_watch_item_triggers(self):
        watches = [
            {
                "id": "w001",
                "prefix": "quake",
                "title": "Aftershock watch — M6.5",
                "confidence": 0.85,
                "bucket": "regional",
                "cell_id": "13.75,100.50",
                "sources": ["earthquakes"],
            },
        ]
        fired = te.evaluate_triggers([], watches)
        rule_names = {t["rule_name"] for t in fired}
        self.assertIn("quake_m6_plus", rule_names)

    def test_no_trigger_below_min_confidence(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.4,
                "delta_score": 0.05,
                "sources": ["hazard"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        self.assertEqual(len(fired), 0)

    def test_cooldown_prevents_repeat(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["hazard"],
            },
        ]
        # First evaluation fires
        fired1 = te.evaluate_triggers(cells, [])
        self.assertGreater(len(fired1), 0)
        # Second evaluation should not fire (cooldown)
        fired2 = te.evaluate_triggers(cells, [])
        rule_names2 = {t["rule_name"] for t in fired2}
        self.assertNotIn("high_fusion_cell", rule_names2)

    def test_context_block_contains_severity(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["hazard"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        self.assertGreater(len(fired), 0)
        ctx = fired[0]["context"]
        self.assertIn("[CRITICAL]", ctx)
        self.assertIn("0.85", ctx)
        self.assertIn("high_fusion_cell", ctx)

    def test_dismiss_trigger(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["hazard"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        self.assertGreater(len(fired), 0)
        # Get the log entry
        recent = te.list_recent_triggers()
        self.assertGreater(len(recent), 0)
        log_id = recent[0]["id"]
        result = te.dismiss_trigger(log_id, reason="false positive")
        self.assertTrue(result["dismissed"])
        # Verify it's dismissed
        active = te.list_recent_triggers(include_dismissed=False)
        ids = {t["id"] for t in active}
        self.assertNotIn(log_id, ids)

    def test_trigger_stats(self):
        cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["hazard"],
            },
        ]
        te.evaluate_triggers(cells, [])
        stats = te.trigger_stats()
        self.assertGreater(stats["total_fires"], 0)
        self.assertGreater(stats["active"], 0)
        self.assertGreaterEqual(stats["enabled_rules"], 5)

    def test_bucket_filter(self):
        watches = [
            {
                "id": "w_cams",
                "prefix": "cams",
                "title": "Haze — Bangkok PM2.5 80",
                "confidence": 0.75,
                "bucket": "local",
                "cell_id": "13.75,100.50",
                "sources": ["cams_haze"],
            },
        ]
        # high_haze_regional has bucket_filter='regional' — should not fire for 'local'
        fired = te.evaluate_triggers([], watches)
        rule_names = {t["rule_name"] for t in fired}
        self.assertNotIn("high_haze_regional", rule_names)

    def test_condition_eval_safe(self):
        """Condition eval should not allow arbitrary code execution."""
        te.create_rule(
            "evil_rule",
            "__import__('os').system('echo hacked')",
            min_confidence=0.0,
            severity="info",
            cooldown_min=1,
        )
        cells = [
            {
                "cell_id": "test",
                "lat": 0,
                "lon": 0,
                "score": 0.99,
                "delta_score": 0.5,
                "sources": ["test"],
            },
        ]
        # Should not fire (eval fails safely)
        fired = te.evaluate_triggers(cells, [])
        rule_names = {t["rule_name"] for t in fired}
        self.assertNotIn("evil_rule", rule_names)
        te.delete_rule("evil_rule")

    def test_push_trigger_to_nodes_no_nodes(self):
        """No registered nodes → 0 queued."""
        cells = [
            {
                "cell_id": "test",
                "lat": 0,
                "lon": 0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["test"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        self.assertGreater(len(fired), 0)
        queued = te.push_trigger_to_nodes(fired)
        self.assertEqual(queued, 0)

    def test_push_trigger_to_nodes_with_node(self):
        """With a registered node → commands queued."""
        # Register a fake node
        import json as _json

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO node_state (node_id, name, lat, lon, updated_at, payload) VALUES (?, ?, ?, ?, ?, ?)",
                ("test-pi", "Test Pi", 13.75, 100.50, "2026-06-27T00:00:00Z", "{}"),
            )
            conn.commit()

        cells = [
            {
                "cell_id": "test",
                "lat": 0,
                "lon": 0,
                "score": 0.85,
                "delta_score": 0.1,
                "sources": ["test"],
            },
        ]
        fired = te.evaluate_triggers(cells, [])
        self.assertGreater(len(fired), 0)
        queued = te.push_trigger_to_nodes(fired)
        self.assertGreater(queued, 0)

        # Verify command was queued
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT command, args FROM node_commands WHERE node_id = ? ORDER BY id DESC LIMIT 1",
                ("test-pi",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "notify")
        args = _json.loads(row[1])
        self.assertIn("severity", args)
        self.assertIn("context", args)

    def test_push_empty_triggers(self):
        """Empty fired list → 0 queued."""
        result = te.push_trigger_to_nodes([])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
