"""Tests for MCP per-tool quota tracking and enforcement (E-06).

Covers:
- Quota disabled by default (no-op)
- Daily quota enforcement
- Hourly quota enforcement
- Env var overrides for limits
- QuotaExceeded exception
- get_tool_usage / get_quota_status
- check_alerts at 80% and 100%
- Fail-soft on DB errors
- init_quota_db table creation
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

import mcp_quota
from mcp_quota import QuotaExceeded, check_and_record, get_quota_status, get_tool_usage


def _make_temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["WORLDBASE_DB_PATH"] = path
    os.environ["WORLDBASE_MCP_QUOTA"] = "1"
    mcp_quota.init_quota_db()
    return path


def _cleanup_db(path):
    try:
        os.unlink(path)
    except OSError:
        pass


class TestQuotaDisabled(unittest.IsolatedAsyncioTestCase):
    def test_disabled_by_default(self):
        os.environ.pop("WORLDBASE_MCP_QUOTA", None)
        self.assertFalse(mcp_quota.quota_enabled())

    async def test_no_op_when_disabled(self):
        os.environ.pop("WORLDBASE_MCP_QUOTA", None)
        for _ in range(100):
            await check_and_record("worldbase_chat")


class TestDailyQuota(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._db_path = _make_temp_db()

    def tearDown(self):
        _cleanup_db(self._db_path)

    async def test_daily_limit_enforced(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "3"
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "100"
        for _ in range(3):
            await check_and_record("worldbase_chat")
        with self.assertRaises(QuotaExceeded) as exc:
            await check_and_record("worldbase_chat")
        self.assertEqual(exc.exception.window, "daily")
        self.assertEqual(exc.exception.count, 3)
        self.assertEqual(exc.exception.limit, 3)

    async def test_no_limit_no_block(self):
        os.environ.pop("WORLDBASE_MCP_QUOTA_DAILY_HEALTH", None)
        for _ in range(100):
            await check_and_record("worldbase_health")


class TestHourlyQuota(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._db_path = _make_temp_db()

    def tearDown(self):
        _cleanup_db(self._db_path)

    async def test_hourly_limit_enforced(self):
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "2"
        for _ in range(2):
            await check_and_record("worldbase_chat")
        with self.assertRaises(QuotaExceeded) as exc:
            await check_and_record("worldbase_chat")
        self.assertEqual(exc.exception.window, "hourly")


class TestUsageStatus(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._db_path = _make_temp_db()

    def tearDown(self):
        _cleanup_db(self._db_path)

    async def test_get_tool_usage(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "10"
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "100"
        await check_and_record("worldbase_chat")
        await check_and_record("worldbase_chat")
        usage = get_tool_usage("worldbase_chat")
        self.assertEqual(usage["tool"], "worldbase_chat")
        self.assertEqual(usage["daily"]["count"], 2)
        self.assertEqual(usage["daily"]["limit"], 10)
        self.assertEqual(usage["daily"]["remaining"], 8)
        self.assertFalse(usage["daily"]["exceeded"])

    async def test_get_quota_status(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "5"
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "100"
        await check_and_record("worldbase_chat")
        status = get_quota_status()
        self.assertTrue(status["enabled"])
        self.assertGreater(len(status["tools"]), 0)
        self.assertEqual(status["quota_exceeded"], [])


class TestAlerts(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._db_path = _make_temp_db()

    def tearDown(self):
        _cleanup_db(self._db_path)

    async def test_alert_at_80_percent(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "10"
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "100"
        for _ in range(8):
            await check_and_record("worldbase_chat")
        alerts = mcp_quota.check_alerts()
        self.assertGreaterEqual(len(alerts), 1)
        self.assertTrue(any(a["alert"] == "mcp_quota_80_percent" for a in alerts))

    async def test_alert_at_exceeded(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "2"
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_CHAT"] = "100"
        for _ in range(2):
            await check_and_record("worldbase_chat")
        alerts = mcp_quota.check_alerts()
        self.assertTrue(any(a["alert"] == "mcp_quota_exceeded" for a in alerts))

    def test_no_alerts_when_disabled(self):
        os.environ.pop("WORLDBASE_MCP_QUOTA", None)
        alerts = mcp_quota.check_alerts()
        self.assertEqual(alerts, [])


class TestFailSoft(unittest.IsolatedAsyncioTestCase):
    async def test_db_error_does_not_block(self):
        os.environ["WORLDBASE_MCP_QUOTA"] = "1"
        os.environ["WORLDBASE_DB_PATH"] = "/nonexistent/path/db.sqlite"
        # Should not raise — fail-soft
        await check_and_record("worldbase_chat")


class TestInitDb(unittest.TestCase):
    def test_creates_table(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.environ["WORLDBASE_DB_PATH"] = path
        mcp_quota.init_quota_db()
        conn = sqlite3.connect(path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mcp_quota'"
        ).fetchall()
        conn.close()
        os.unlink(path)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0][0], "mcp_quota")


class TestEnvOverrides(unittest.TestCase):
    def test_daily_override(self):
        os.environ["WORLDBASE_MCP_QUOTA_DAILY_CHAT"] = "42"
        self.assertEqual(mcp_quota._get_daily_limit("worldbase_chat"), 42)

    def test_hourly_override(self):
        os.environ["WORLDBASE_MCP_QUOTA_HOURLY_BRIEFING_GENERATE"] = "7"
        self.assertEqual(mcp_quota._get_hourly_limit("worldbase_briefing_generate"), 7)

    def test_default_daily_for_unconfigured_tool(self):
        os.environ.pop("WORLDBASE_MCP_QUOTA_DAILY_HEALTH", None)
        self.assertEqual(mcp_quota._get_daily_limit("worldbase_health"), 0)
