"""Unit tests for WorldBase MCP read helpers (no MCP transport)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from mcp_server import (
    FEED_SAMPLE_ALLOWLIST,
    fetch_briefing_latest,
    fetch_feed_sample,
    fetch_health,
    mcp_auth_required,
)


class MCPAuthTests(unittest.TestCase):
    def test_auth_when_api_key_set(self):
        with patch.dict("os.environ", {"WORLDBASE_API_KEY": "secret", "WORLDBASE_BIND_HOST": "127.0.0.1"}, clear=False):
            with patch("mcp_server.API_KEY", "secret"):
                self.assertTrue(mcp_auth_required())

    def test_auth_when_lan_bind_without_key(self):
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "0.0.0.0"}, clear=False):
            with patch("mcp_server.API_KEY", ""):
                self.assertTrue(mcp_auth_required())

    def test_no_auth_localhost_without_key(self):
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "127.0.0.1"}, clear=False):
            with patch("mcp_server.API_KEY", ""):
                self.assertFalse(mcp_auth_required())


class MCPFeedSampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_feed_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            await fetch_feed_sample("not_a_real_feed", limit=3)
        self.assertIn("not_a_real_feed", str(ctx.exception))

    async def test_allowlist_includes_core_feeds(self):
        for fid in ("earthquakes", "gdacs", "wildfires", "aircraft"):
            self.assertIn(fid, FEED_SAMPLE_ALLOWLIST)

    async def test_cache_hit_returns_sample(self):
        sample = {"count": 2, "items": [{"a": 1}, {"b": 2}]}
        with patch("feed_registry.read", return_value=sample):
            out = await fetch_feed_sample("gdacs", limit=1)
        self.assertEqual(out["source"], "feed_cache")
        self.assertEqual(out["feed_id"], "gdacs")
        self.assertEqual(len(out["sample"]["items"]), 1)


class MCPBriefingTests(unittest.IsolatedAsyncioTestCase):
    async def test_briefing_preview_truncates_long_text(self):
        long_text = "x" * 5000
        fake = {
            "created_at": "2026-01-01T00:00:00+00:00",
            "text": long_text,
            "alerts": [],
            "fusion_hotspots": [],
            "digest": {"region": "thailand"},
            "intel": {"count": 3, "enabled": True},
            "style": "security_advisor_24h",
        }
        with patch("node_sync.latest_briefing", new=AsyncMock(return_value=fake)):
            out = await fetch_briefing_latest(include_full_text=False)
        self.assertTrue(out["text_truncated"])
        self.assertEqual(len(out["text_preview"]), 4000)
        self.assertNotIn("text", out)

    async def test_briefing_full_text_optional(self):
        fake = {
            "created_at": "t",
            "text": "short",
            "alerts": [],
            "fusion_hotspots": [],
            "digest": {},
            "intel": {},
        }
        with patch("node_sync.latest_briefing", new=AsyncMock(return_value=fake)):
            out = await fetch_briefing_latest(include_full_text=True)
        self.assertEqual(out["text"], "short")


class MCPHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_shape(self):
        with patch("sqlite3.connect") as mock_conn:
            mock_conn.return_value.execute.return_value.fetchone.return_value = (7,)
            out = await fetch_health()
        self.assertEqual(out["status"], "ok")
        self.assertIn("time", out)
        self.assertEqual(out["feed_cache_count"], 7)


if __name__ == "__main__":
    unittest.main()
