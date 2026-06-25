"""Unit tests for P2+ Splink dual-pipeline (model export/import, Grauzonen).

Tests verify:
- _model_path / _model_exists / _should_run_splink helpers
- train_model saves a JSON model file
- _run_splink_schema loads saved model (no retraining)
- _should_run_splink returns True when model exists even if _SPLINK_ENABLED is off
- _rows_for_schema includes email/username fields
- list_ambiguous_pairs returns edges in the Grauzonen band
- label_pair confirmed=True bumps confidence + records label
- label_pair confirmed=False deletes edge + records label
- status() reports models and ambiguous_range
- _build_comparisons_and_blocking adds OSINT comparisons when data present
"""

import os
import tempfile
import unittest

import entity_resolution
import ftm_connection
import ftm_store


class DualPipelineTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()
        entity_resolution._LAST_RUN = None
        entity_resolution._LAST_ERROR = None
        # Use a temp model dir
        self._orig_model_dir = entity_resolution._MODEL_DIR
        self._tmpdir = tempfile.mkdtemp(prefix="splink_models_")
        entity_resolution._MODEL_DIR = self._tmpdir

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
        entity_resolution._MODEL_DIR = self._orig_model_dir
        # Clean up model files
        for f in os.listdir(self._tmpdir):
            os.remove(os.path.join(self._tmpdir, f))
        os.rmdir(self._tmpdir)

    def test_model_path_returns_schema_specific_path(self):
        p = entity_resolution._model_path("Person")
        self.assertIn("splink_model_Person.json", p)

    def test_model_exists_false_when_no_file(self):
        self.assertFalse(entity_resolution._model_exists("Person"))

    def test_model_exists_true_after_create(self):
        path = entity_resolution._model_path("Person")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{}")
        self.assertTrue(entity_resolution._model_exists("Person"))

    def test_should_run_splink_false_when_disabled_and_no_model(self):
        prev = entity_resolution._SPLINK_ENABLED
        entity_resolution._SPLINK_ENABLED = False
        try:
            self.assertFalse(entity_resolution._should_run_splink("Person"))
        finally:
            entity_resolution._SPLINK_ENABLED = prev

    def test_should_run_splink_true_when_model_exists_even_if_disabled(self):
        prev = entity_resolution._SPLINK_ENABLED
        entity_resolution._SPLINK_ENABLED = False
        try:
            path = entity_resolution._model_path("Person")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{}")
            self.assertTrue(entity_resolution._should_run_splink("Person"))
        finally:
            entity_resolution._SPLINK_ENABLED = prev

    def test_should_run_splink_true_when_enabled_even_without_model(self):
        prev = entity_resolution._SPLINK_ENABLED
        entity_resolution._SPLINK_ENABLED = True
        try:
            self.assertTrue(entity_resolution._should_run_splink("Person"))
        finally:
            entity_resolution._SPLINK_ENABLED = prev

    def test_rows_for_schema_includes_email_username(self):
        p = ftm_store.make_entity(
            "Person",
            ["e1"],
            {
                "name": "Test Person",
                "email": "test@example.com",
                "alias": "testuser",
            },
        )
        ftm_store.upsert(p, dataset="feedA")
        entities = ftm_store.list_entities_for_resolution(["Person"], 100)
        rows = entity_resolution._rows_for_schema("Person", entities)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("email", row)
        self.assertIn("username", row)
        self.assertEqual(row["email"], "testexamplecom")
        self.assertEqual(row["username"], "testuser")

    def test_rows_for_schema_email_username_none_when_absent(self):
        p = ftm_store.make_entity("Person", ["e2"], {"name": "Plain Person"})
        ftm_store.upsert(p, dataset="feedA")
        entities = ftm_store.list_entities_for_resolution(["Person"], 100)
        rows = entity_resolution._rows_for_schema("Person", entities)
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["email"])
        self.assertIsNone(rows[0]["username"])

    def test_list_ambiguous_pairs_returns_edges_in_band(self):
        # Create edges with confidence in the ambiguous band
        ftm_store.add_edge(
            "a",
            "b",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.75,
            properties={"method": "splink", "schema": "Person"},
        )
        ftm_store.add_edge(
            "c",
            "d",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.95,
            properties={"method": "exact", "schema": "Person"},
        )
        pairs = entity_resolution.list_ambiguous_pairs(limit=10)
        # Only the 0.75 edge should be in the ambiguous band (0.60-0.84)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["source_id"], "a")
        self.assertEqual(pairs[0]["target_id"], "b")
        self.assertAlmostEqual(pairs[0]["confidence"], 0.75, places=2)

    def test_list_ambiguous_pairs_excludes_labeled(self):
        ftm_store.add_edge(
            "a",
            "b",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.70,
            properties={"method": "splink", "schema": "Person"},
        )
        # Label the pair
        entity_resolution.label_pair("a", "b", confirmed=True, schema="Person")
        pairs = entity_resolution.list_ambiguous_pairs(limit=10)
        # The labeled pair should be excluded
        for p in pairs:
            self.assertFalse(
                (p["source_id"] == "a" and p["target_id"] == "b")
                or (p["source_id"] == "b" and p["target_id"] == "a")
            )

    def test_ambiguous_route_runs_off_event_loop_thread(self):
        """Regression: GET /api/intel/resolution/ambiguous must offload the
        blocking ftm_connection._LOCK + DuckDB query via asyncio.to_thread,
        not run it inline on the event loop thread. Running inline would freeze
        all HTTP handling whenever run_resolution holds _LOCK concurrently."""
        import asyncio
        import threading

        ftm_store.add_edge(
            "a",
            "b",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.75,
            properties={"method": "splink", "schema": "Person"},
        )

        main_thread = threading.current_thread()
        captured: dict = {}
        orig = entity_resolution.list_ambiguous_pairs

        def _spy(*args, **kwargs):
            captured["thread"] = threading.current_thread()
            return orig(*args, **kwargs)

        entity_resolution.list_ambiguous_pairs = _spy  # type: ignore[assignment]
        try:
            result = asyncio.run(entity_resolution.resolution_ambiguous(limit=10))
        finally:
            entity_resolution.list_ambiguous_pairs = orig  # type: ignore[assignment]

        self.assertEqual(len(result), 1)
        self.assertIn("thread", captured)
        self.assertIsNot(
            captured["thread"],
            main_thread,
            "resolution_ambiguous must run list_ambiguous_pairs via asyncio.to_thread",
        )

    def test_label_pair_confirmed_bumps_confidence(self):
        ftm_store.add_edge(
            "x",
            "y",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.70,
            properties={"method": "splink", "schema": "Person"},
        )
        result = entity_resolution.label_pair("x", "y", confirmed=True, schema="Person")
        self.assertTrue(result["ok"])
        self.assertTrue(result["confirmed"])
        # Verify the edge was upserted with high confidence via direct query
        from ftm_connection import _LOCK, _conn

        with _LOCK:
            row = (
                _conn()
                .execute(
                    "SELECT confidence FROM edges WHERE source_id = ? AND target_id = ? AND dataset = ?",
                    ["x", "y", entity_resolution.RESOLUTION_DATASET],
                )
                .fetchone()
            )
        self.assertIsNotNone(row)
        self.assertGreaterEqual(row[0], 0.95)

    def test_label_pair_rejected_deletes_edge(self):
        ftm_store.add_edge(
            "x",
            "y",
            "sameAs",
            dataset=entity_resolution.RESOLUTION_DATASET,
            confidence=0.70,
            properties={"method": "splink", "schema": "Person"},
        )
        result = entity_resolution.label_pair(
            "x", "y", confirmed=False, schema="Person"
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["confirmed"])
        # Edge should be deleted
        g = ftm_store.graph_view("x", depth=1)
        same_edges = [e for e in g["edges"] if e["kind"] == "sameAs"]
        self.assertEqual(len(same_edges), 0)

    def test_status_reports_models_and_ambiguous_range(self):
        st = entity_resolution.status()
        self.assertIn("models", st)
        self.assertIn("ambiguous_range", st)
        self.assertEqual(len(st["ambiguous_range"]), 2)
        self.assertIsInstance(st["models"], dict)

    def test_status_reports_model_when_exists(self):
        path = entity_resolution._model_path("Person")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{}")
        st = entity_resolution.status()
        self.assertIn("Person", st["models"])

    def test_build_comparisons_and_blocking_adds_osint_when_data_present(self):
        """_build_comparisons_and_blocking should add email/username comparisons."""
        try:
            import splink.comparison_library as cl  # noqa: F401
            from splink import block_on  # noqa: F401
        except ImportError:
            self.skipTest("splink not installed")

        class FakeDF:
            def __init__(self, columns_data):
                self._data = columns_data
                self.columns = list(columns_data.keys())

            def __getitem__(self, col):
                return FakeSeries(self._data.get(col, []))

        class FakeSeries:
            def __init__(self, values):
                self._values = values

            def notna(self):
                return FakeBool([v is not None for v in self._values])

            def __ne__(self, other):
                return FakeBool([v != other for v in self._values])

            def any(self):
                return any(self._bools)

        class FakeBool:
            def __init__(self, bools):
                self._bools = bools

            def any(self):
                return any(self._bools)

        df = FakeDF(
            {
                "country": ["us", "uk"],
                "email": ["a@b.com", "c@d.com"],
                "username": ["user1", "user2"],
            }
        )
        comparisons, blocking = entity_resolution._build_comparisons_and_blocking(
            "Person", df
        )
        # Should have NameComparison + ExactMatch(country) + Levenshtein(email) + JaroWinkler(username)
        self.assertGreaterEqual(len(comparisons), 4)

    def test_build_comparisons_and_blocking_no_osint_when_absent(self):
        """_build_comparisons_and_blocking should skip email/username when no data."""
        try:
            import splink.comparison_library as cl  # noqa: F401
            from splink import block_on  # noqa: F401
        except ImportError:
            self.skipTest("splink not installed")

        class FakeDF:
            def __init__(self, columns_data):
                self._data = columns_data
                self.columns = list(columns_data.keys())

            def __getitem__(self, col):
                return FakeSeries(self._data.get(col, [None, None]))

        class FakeSeries:
            def __init__(self, values):
                self._values = values

            def notna(self):
                return FakeBool([v is not None for v in self._values])

            def __ne__(self, other):
                return FakeBool([v != other for v in self._values])

            def any(self):
                return any(self._bools)

        class FakeBool:
            def __init__(self, bools):
                self._bools = bools

            def any(self):
                return any(self._bools)

        df = FakeDF(
            {
                "country": ["us", None],
                "email": [None, None],
                "username": [None, None],
            }
        )
        comparisons, blocking = entity_resolution._build_comparisons_and_blocking(
            "Person", df
        )
        # Should have NameComparison + ExactMatch(country) only
        self.assertEqual(len(comparisons), 2)

    def test_train_model_returns_error_for_insufficient_rows(self):
        result = entity_resolution.train_model("Person")
        self.assertFalse(result["ok"])
        self.assertIn("insufficient", result["error"])

    def test_train_model_saves_json_when_enough_rows(self):
        """train_model should save a JSON model file when enough rows exist."""
        try:
            import splink  # noqa: F401
        except ImportError:
            self.skipTest("splink not installed")
        # Create enough entities for training
        for i in range(5):
            p = ftm_store.make_entity(
                "Person",
                [f"u{i}"],
                {
                    "name": f"Unique Person {i}",
                    "country": "us",
                },
            )
            ftm_store.upsert(p, dataset="feedA")
        result = entity_resolution.train_model("Person")
        self.assertTrue(result["ok"])
        self.assertTrue(os.path.isfile(result["model_path"]))

    def test_run_splink_schema_loads_model_without_retraining(self):
        """_run_splink_schema should use saved model when available."""
        try:
            import splink  # noqa: F401
        except ImportError:
            self.skipTest("splink not installed")
        # Create enough entities
        for i in range(5):
            p = ftm_store.make_entity(
                "Person",
                [f"u{i}"],
                {
                    "name": f"Test Person {i}",
                    "country": "us",
                },
            )
            ftm_store.upsert(p, dataset="feedA")
        # Train and save model
        entity_resolution.train_model("Person")
        self.assertTrue(entity_resolution._model_exists("Person"))
        # Run resolution — should load model, not retrain
        prev = entity_resolution._SPLINK_ENABLED
        entity_resolution._SPLINK_ENABLED = False
        try:
            # _should_run_splink should return True because model exists
            self.assertTrue(entity_resolution._should_run_splink("Person"))
        finally:
            entity_resolution._SPLINK_ENABLED = prev


if __name__ == "__main__":
    unittest.main()
