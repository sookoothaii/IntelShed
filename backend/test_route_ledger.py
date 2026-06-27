"""Tests for P6a — Route Outcome Ledger."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


class TestRouteLedger(unittest.TestCase):
    """Tests for the route outcome ledger module."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_route_ledger.db")
        self._patch = patch.dict(os.environ, {"WORLDBASE_DB_PATH": self._db_path})
        self._patch.start()

        for mod in list(sys.modules):
            if mod in ("route_ledger", "config"):
                del sys.modules[mod]

    def tearDown(self) -> None:
        self._patch.stop()
        for mod in list(sys.modules):
            if mod in ("route_ledger", "config"):
                del sys.modules[mod]

    def _config_stub(self, enabled: bool = True, recompute_n: int = 50):
        class _Stub:
            route_ledger_enabled = enabled
            route_ledger_recompute_n = recompute_n

        return _Stub()

    def test_init_creates_table(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        import sqlite3

        conn = sqlite3.connect(self._db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        self.assertIn(("route_outcomes",), tables)

    def test_record_outcome_inserts_row(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        with patch.object(route_ledger, "get_config", return_value=self._config_stub()):
            route_ledger.record_outcome(
                "test query", "vector", hit_count=3, block_chars=500, duration_ms=42
            )

        import sqlite3

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM route_outcomes").fetchall()
        conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["route"], "vector")
        self.assertEqual(rows[0]["hit_count"], 3)
        self.assertEqual(rows[0]["block_chars"], 500)

    def test_record_outcome_ignores_invalid_route(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        with patch.object(route_ledger, "get_config", return_value=self._config_stub()):
            route_ledger.record_outcome("test", "invalid_route")

        import sqlite3

        conn = sqlite3.connect(self._db_path)
        count = conn.execute("SELECT COUNT(*) FROM route_outcomes").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_record_outcome_disabled(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        with patch.object(
            route_ledger, "get_config", return_value=self._config_stub(enabled=False)
        ):
            route_ledger.record_outcome("test", "vector")

        import sqlite3

        conn = sqlite3.connect(self._db_path)
        count = conn.execute("SELECT COUNT(*) FROM route_outcomes").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_recompute_weights_returns_dict(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        with patch.object(route_ledger, "get_config", return_value=self._config_stub()):
            for i in range(5):
                route_ledger.record_outcome(
                    f"query {i}", "vector", hit_count=3, block_chars=500
                )
            for i in range(5):
                route_ledger.record_outcome(
                    f"query {i}", "graph", hit_count=0, block_chars=50
                )

            weights = route_ledger.recompute_weights()
            self.assertIn("vector", weights)
            self.assertIn("graph", weights)
            # Vector should have higher weight than graph
            self.assertGreater(weights["vector"], weights["graph"])

    def test_get_route_weights_lazy_recompute(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        # Reset internal state
        route_ledger._pending_records = 0
        route_ledger._route_weights = {r: 1.0 / 5 for r in route_ledger._VALID_ROUTES}

        with patch.object(
            route_ledger,
            "get_config",
            return_value=self._config_stub(recompute_n=3),
        ):
            # Record 2 outcomes — below threshold
            route_ledger.record_outcome("q1", "vector", hit_count=3, block_chars=500)
            route_ledger.record_outcome("q2", "vector", hit_count=2, block_chars=300)
            self.assertEqual(route_ledger._pending_records, 2)

            # Record 1 more — hits threshold
            route_ledger.record_outcome("q3", "vector", hit_count=1, block_chars=200)
            self.assertEqual(route_ledger._pending_records, 3)

            # get_route_weights should trigger recompute
            route_ledger.get_route_weights()
            # After recompute, pending should be reset
            self.assertEqual(route_ledger._pending_records, 0)

    def test_get_route_weights_disabled_returns_uniform(self) -> None:
        import route_ledger

        with patch.object(
            route_ledger, "get_config", return_value=self._config_stub(enabled=False)
        ):
            weights = route_ledger.get_route_weights()
            for r in route_ledger._VALID_ROUTES:
                self.assertAlmostEqual(weights[r], 0.2)

    def test_get_route_stats(self) -> None:
        import route_ledger

        route_ledger.init_route_ledger_db()
        with patch.object(route_ledger, "get_config", return_value=self._config_stub()):
            route_ledger.record_outcome(
                "q1", "vector", hit_count=3, block_chars=500, success=1
            )
            route_ledger.record_outcome(
                "q2", "vector", hit_count=0, block_chars=50, success=0
            )

            stats = route_ledger.get_route_stats()
            self.assertIn("vector", stats)
            self.assertEqual(stats["vector"]["total"], 2)
            self.assertEqual(stats["vector"]["success_rate"], 0.5)
            self.assertIn("_meta", stats)

    def test_record_outcome_fail_soft(self) -> None:
        # Should not raise even with bad DB path
        with patch.dict(os.environ, {"WORLDBASE_DB_PATH": "/nonexistent/path/db.db"}):
            for mod in list(sys.modules):
                if mod == "route_ledger":
                    del sys.modules[mod]
            import route_ledger as rl2

            with patch.object(rl2, "get_config", return_value=self._config_stub()):
                rl2.record_outcome("test", "vector")  # should not raise


if __name__ == "__main__":
    unittest.main()
