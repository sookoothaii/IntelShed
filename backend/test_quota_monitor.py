"""Unit tests for J5 — API Quota & Cost Monitor."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock


class QuotaMonitorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._old_db = os.environ.get("WORLDBASE_DB_PATH")
        self._old_monitor = os.environ.get("WORLDBASE_QUOTA_MONITOR")
        os.environ["WORLDBASE_DB_PATH"] = self._tmp.name
        os.environ["WORLDBASE_QUOTA_MONITOR"] = "1"

    def tearDown(self):
        import gc
        gc.collect()
        try:
            os.unlink(self._tmp.name)
        except PermissionError:
            pass
        if self._old_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._old_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)
        if self._old_monitor is not None:
            os.environ["WORLDBASE_QUOTA_MONITOR"] = self._old_monitor
        else:
            os.environ.pop("WORLDBASE_QUOTA_MONITOR", None)

    def test_init_quota_db(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        import sqlite3
        conn = sqlite3.connect(self._tmp.name)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_quota'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(tables)

    def test_record_call_increments_count(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        quota_monitor.record_call("test_source", "/api/test")
        usage = quota_monitor.get_usage("test_source")
        self.assertEqual(usage["count"], 1)
        quota_monitor.record_call("test_source", "/api/test")
        usage = quota_monitor.get_usage("test_source")
        self.assertEqual(usage["count"], 2)

    def test_record_call_disabled(self):
        import quota_monitor
        os.environ["WORLDBASE_QUOTA_MONITOR"] = "0"
        quota_monitor.init_quota_db()
        quota_monitor.record_call("test_source", "/api/test")
        usage = quota_monitor.get_usage("test_source")
        self.assertEqual(usage["count"], 0)
        os.environ["WORLDBASE_QUOTA_MONITOR"] = "1"

    def test_is_quota_exceeded_false_no_limit(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        # Source with no configured limit should never be exceeded
        self.assertFalse(quota_monitor.is_quota_exceeded("unknown_source"))

    def test_is_quota_exceeded_true_at_limit(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_TESTHIGH"] = "3"
        for _ in range(3):
            quota_monitor.record_call("testhigh", "/api/test")
        self.assertTrue(quota_monitor.is_quota_exceeded("testhigh"))
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_TESTHIGH", None)

    def test_is_quota_exceeded_false_below_limit(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_TESTLOW"] = "100"
        quota_monitor.record_call("testlow", "/api/test")
        self.assertFalse(quota_monitor.is_quota_exceeded("testlow"))
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_TESTLOW", None)

    def test_get_usage_returns_structure(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        quota_monitor.record_call("gdelt", "/api/v1/events")
        usage = quota_monitor.get_usage("gdelt")
        self.assertIn("source", usage)
        self.assertIn("count", usage)
        self.assertIn("limit", usage)
        self.assertIn("remaining", usage)
        self.assertIn("pct", usage)
        self.assertIn("cost_usd_est", usage)
        self.assertIn("exceeded", usage)
        self.assertIn("endpoints", usage)

    def test_get_quota_status(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        quota_monitor.record_call("gdelt", "/api/v1/events")
        status = quota_monitor.get_quota_status()
        self.assertIn("enabled", status)
        self.assertIn("sources", status)
        self.assertIn("quota_exceeded", status)
        self.assertIn("total_calls_today", status)
        self.assertIn("total_cost_today_usd", status)
        self.assertIn("trend_7d", status)
        self.assertTrue(status["enabled"])

    def test_check_alerts_empty_when_healthy(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        alerts = quota_monitor.check_alerts()
        # No calls recorded, no alerts expected
        self.assertEqual(len(alerts), 0)

    def test_check_alerts_fires_at_80_percent(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_TEST80"] = "10"
        for _ in range(8):
            quota_monitor.record_call("test80", "/api/test")
        alerts = quota_monitor.check_alerts()
        found = [a for a in alerts if a["source"] == "test80"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["alert"], "quota_80_percent")
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_TEST80", None)

    def test_check_alerts_fires_at_exceeded(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_TESTEX"] = "5"
        for _ in range(5):
            quota_monitor.record_call("testex", "/api/test")
        alerts = quota_monitor.check_alerts()
        found = [a for a in alerts if a["source"] == "testex"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["alert"], "quota_exceeded")
        self.assertEqual(found[0]["severity"], "critical")
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_TESTEX", None)

    def test_cost_tracking(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        # newsdata has a cost of 0.001 per call
        for _ in range(3):
            quota_monitor.record_call("newsdata", "/api/news")
        usage = quota_monitor.get_usage("newsdata")
        self.assertGreater(usage["cost_usd_est"], 0)

    def test_env_limit_override(self):
        import quota_monitor
        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_GDELT"] = "42"
        usage = quota_monitor.get_usage("gdelt")
        self.assertEqual(usage["limit"], 42)
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_GDELT", None)


class FeedConnectorQuotaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._old_db = os.environ.get("WORLDBASE_DB_PATH")
        self._old_monitor = os.environ.get("WORLDBASE_QUOTA_MONITOR")
        os.environ["WORLDBASE_DB_PATH"] = self._tmp.name
        os.environ["WORLDBASE_QUOTA_MONITOR"] = "1"

    def tearDown(self):
        import gc
        gc.collect()
        try:
            os.unlink(self._tmp.name)
        except PermissionError:
            pass
        if self._old_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._old_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)
        if self._old_monitor is not None:
            os.environ["WORLDBASE_QUOTA_MONITOR"] = self._old_monitor
        else:
            os.environ.pop("WORLDBASE_QUOTA_MONITOR", None)

    async def test_run_records_quota_call(self):
        import quota_monitor
        from feeds.runner import FeedConnector
        from feeds.envelope import FeedEnvelope

        quota_monitor.init_quota_db()
        connector = FeedConnector("test_quota_feed", ttl_sec=60, default_source="test")

        async def _fetch():
            return FeedEnvelope(count=1, updated="2026-06-25T00:00:00+00:00").merge(gauges=[])

        with mock.patch("feeds.runner.feed_registry.write_auto"):
            await connector.run(_fetch, persist=False)

        usage = quota_monitor.get_usage("test_quota_feed")
        self.assertEqual(usage["count"], 1)

    async def test_run_hard_stops_on_quota_exceeded(self):
        import quota_monitor
        from feeds.runner import FeedConnector
        from feeds.envelope import FeedEnvelope

        quota_monitor.init_quota_db()
        os.environ["WORLDBASE_QUOTA_LIMIT_BLOCKEDFEED"] = "1"
        # Record one call to hit the limit
        quota_monitor.record_call("blockedfeed", "/api/test")
        self.assertTrue(quota_monitor.is_quota_exceeded("blockedfeed"))

        connector = FeedConnector("blockedfeed", ttl_sec=60, default_source="test")
        fetch_called = False

        async def _fetch():
            nonlocal fetch_called
            fetch_called = True
            return FeedEnvelope(count=1).merge(gauges=[])

        with mock.patch("feeds.runner.feed_registry.write_auto"):
            result = await connector.run(_fetch, persist=False)

        self.assertFalse(fetch_called, "Fetch should not be called when quota exceeded")
        self.assertEqual(result.get("error"), "quota_exceeded")
        os.environ.pop("WORLDBASE_QUOTA_LIMIT_BLOCKEDFEED", None)


if __name__ == "__main__":
    import unittest.mock
    unittest.main()
