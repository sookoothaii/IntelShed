"""Unit tests for dynamic feature flags (J2).

Tests cover:
- env-only mode (WORLDBASE_ADMIN_FLAGS=0)
- SQLite override precedence
- TTL cache behavior
- set_flag + audit log
- WORLDBASE_FLAG_OVERRIDE=env
- init_feature_flags_db table creation
- get_all_flags merge
- unknown flag falls back to env
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import features


class TestFeatureFlags(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name
        self._patches = []
        # Patch DB_PATH in both features and sqlite_bootstrap
        self._patches.append(patch.object(features, "DB_PATH", self._db_path))
        # Also patch the import-time reference in features._get_conn
        self._patches.append(patch("sqlite_bootstrap.DB_PATH", self._db_path))
        for p in self._patches:
            p.start()

        features.init_feature_flags_db()
        features.clear_cache()
        # Ensure admin flags enabled by default
        os.environ.pop("WORLDBASE_FLAG_OVERRIDE", None)
        os.environ["WORLDBASE_ADMIN_FLAGS"] = "1"

    def tearDown(self):
        for p in self._patches:
            p.stop()
        features.clear_cache()
        os.environ.pop("WORLDBASE_ADMIN_FLAGS", None)
        os.environ.pop("WORLDBASE_FLAG_OVERRIDE", None)
        # Clean up test-specific env vars
        for key in list(os.environ):
            if key.startswith("WORLDBASE_TEST_"):
                os.environ.pop(key)
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def test_env_only_mode_reads_env(self):
        """When WORLDBASE_ADMIN_FLAGS=0, is_enabled reads env directly."""
        os.environ["WORLDBASE_ADMIN_FLAGS"] = "0"
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "1"
        features.clear_cache()
        self.assertTrue(features.is_enabled("duckdb_queue"))

        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "0"
        features.clear_cache()
        self.assertFalse(features.is_enabled("duckdb_queue"))

    def test_sqlite_override_takes_precedence(self):
        """SQLite flag overrides env default."""
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "0"
        features.clear_cache()
        self.assertFalse(features.is_enabled("duckdb_queue"))

        features.set_flag("duckdb_queue", True)
        features.clear_cache()
        self.assertTrue(features.is_enabled("duckdb_queue"))

    def test_sqlite_override_disabled(self):
        """SQLite flag set to False overrides env default of True."""
        os.environ["WORLDBASE_BRIEFING_AUTOPILOT"] = "1"
        features.clear_cache()
        self.assertTrue(features.is_enabled("briefing_autopilot"))

        features.set_flag("briefing_autopilot", False)
        features.clear_cache()
        self.assertFalse(features.is_enabled("briefing_autopilot"))

    def test_flag_override_env_forces_env_only(self):
        """WORLDBASE_FLAG_OVERRIDE=env ignores SQLite overrides."""
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "0"
        features.set_flag("duckdb_queue", True)
        features.clear_cache()

        os.environ["WORLDBASE_FLAG_OVERRIDE"] = "env"
        # Re-read the module-level variable
        import importlib

        importlib.reload(features)
        # Re-patch since reload re-imports
        patch.object(features, "DB_PATH", self._db_path).start()
        features.init_feature_flags_db()
        features.clear_cache()

        self.assertFalse(features.is_enabled("duckdb_queue"))

        os.environ.pop("WORLDBASE_FLAG_OVERRIDE", None)
        importlib.reload(features)
        patch.object(features, "DB_PATH", self._db_path).start()
        features.clear_cache()

    def test_set_flag_returns_old_and_new(self):
        """set_flag returns old_value and new_value."""
        result = features.set_flag("chat_agentic", True)
        self.assertTrue(result["new_value"])
        self.assertIsNone(result["old_value"])

        result = features.set_flag("chat_agentic", False)
        self.assertFalse(result["new_value"])
        self.assertTrue(result["old_value"])

    def test_audit_log_records_changes(self):
        """get_flag_log returns chronological audit entries."""
        features.set_flag("rag_rerank", True, "tester")
        features.set_flag("rag_rerank", False, "tester")

        log = features.get_flag_log()
        self.assertGreaterEqual(len(log), 2)

        # Most recent first
        self.assertEqual(log[0]["key"], "rag_rerank")
        self.assertFalse(bool(log[0]["new_value"]))
        self.assertTrue(bool(log[0]["old_value"]))
        self.assertEqual(log[0]["updated_by"], "tester")

    def test_cache_ttl(self):
        """is_enabled caches result for 5s — repeated calls don't hit DB."""
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "1"
        features.clear_cache()

        # First call populates cache
        self.assertTrue(features.is_enabled("duckdb_queue"))

        # Change env — cached value should persist
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "0"
        self.assertTrue(features.is_enabled("duckdb_queue"))

        # Clear cache — should read new env
        features.clear_cache()
        self.assertFalse(features.is_enabled("duckdb_queue"))

    def test_get_all_flags_merges_env_and_sqlite(self):
        """get_all_flags returns known flags with correct source."""
        os.environ["WORLDBASE_DUCKDB_QUEUE"] = "0"
        features.set_flag("chat_agentic", True)
        features.clear_cache()

        flags = features.get_all_flags()
        keys = {f["key"] for f in flags}

        self.assertIn("duckdb_queue", keys)
        self.assertIn("chat_agentic", keys)

        chat = next(f for f in flags if f["key"] == "chat_agentic")
        self.assertTrue(chat["enabled"])
        self.assertEqual(chat["source"], "sqlite")

        duckdb = next(f for f in flags if f["key"] == "duckdb_queue")
        self.assertFalse(duckdb["enabled"])
        self.assertEqual(duckdb["source"], "env")

    def test_unknown_flag_falls_back_to_env(self):
        """Unknown flag with no env var defaults to False."""
        result = features.is_enabled("nonexistent_flag_xyz")
        self.assertFalse(result)

    def test_unknown_flag_with_env_var(self):
        """Unknown flag reads env var if WORLDBASE_{KEY} is set."""
        os.environ["WORLDBASE_MY_CUSTOM_FLAG"] = "1"
        features.clear_cache()
        self.assertTrue(features.is_enabled("my_custom_flag"))
        os.environ.pop("WORLDBASE_MY_CUSTOM_FLAG", None)

    def test_init_creates_tables(self):
        """init_feature_flags_db creates both tables."""
        # Tables already created in setUp, verify they exist
        conn = sqlite3.connect(self._db_path)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        self.assertIn("feature_flags", tables)
        self.assertIn("feature_flag_log", tables)

    def test_set_flag_updates_existing_row(self):
        """Setting a flag that already exists updates it (no duplicate)."""
        features.set_flag("rag_spatial", True)
        features.set_flag("rag_spatial", False)
        features.set_flag("rag_spatial", True)

        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            "SELECT COUNT(*) FROM feature_flags WHERE key = ?", ("rag_spatial",)
        ).fetchone()
        conn.close()

        self.assertEqual(rows[0], 1)

    def test_get_all_flags_env_only_mode(self):
        """When WORLDBASE_ADMIN_FLAGS=0, get_all_flags returns env defaults only."""
        os.environ["WORLDBASE_ADMIN_FLAGS"] = "0"
        features.set_flag("chat_agentic", True)  # This still writes to SQLite
        features.clear_cache()

        flags = features.get_all_flags()
        chat = next(f for f in flags if f["key"] == "chat_agentic")
        # In env-only mode, SQLite override is ignored
        self.assertEqual(chat["source"], "env")


if __name__ == "__main__":
    unittest.main()
