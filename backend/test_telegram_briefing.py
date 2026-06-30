"""Tests for telegram_briefing SOCMINT digest bridge (K3)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from telegram_briefing import (
    build_telegram_watch_items,
    gather_telegram_briefing,
    _post_bucket,
)


class TelegramBriefingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_when_feature_off(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.telegram_enabled = False
            cfg.briefing_telegram = True
            gc.return_value = cfg
            digest = await gather_telegram_briefing()
            self.assertFalse(digest["enabled"])
            self.assertEqual(digest["count"], 0)

    async def test_disabled_when_briefing_off(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.telegram_enabled = True
            cfg.briefing_telegram = False
            gc.return_value = cfg
            digest = await gather_telegram_briefing()
            self.assertFalse(digest["enabled"])

    async def test_gather_recent_posts(self):
        now = datetime.now(timezone.utc).isoformat()
        with (
            patch("telegram_briefing.get_config") as gc,
            patch("telegram_briefing.telegram_bridge") as tb,
        ):
            cfg = MagicMock()
            cfg.telegram_enabled = True
            cfg.briefing_telegram = True
            gc.return_value = cfg
            tb.get_cached_posts_sync.return_value = [
                {
                    "id": "a1",
                    "channel": "bkkbangkoknews",
                    "text": "Protest in Bangkok today.",
                    "date": now,
                    "score": 0.75,
                    "countries": ["thailand"],
                    "cities": ["bangkok"],
                }
            ]
            digest = await gather_telegram_briefing()
            self.assertTrue(digest["enabled"])
            self.assertEqual(digest["count"], 1)
            self.assertIn("Bangkok", digest["lines"][0])

    def test_post_bucket_local(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.operator_region = "thailand"
            gc.return_value = cfg
            p = {"countries": ["thailand"], "cities": []}
            self.assertEqual(_post_bucket(p), "local")

    def test_post_bucket_regional(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.operator_region = "thailand"
            gc.return_value = cfg
            p = {"countries": ["myanmar"], "cities": []}
            self.assertEqual(_post_bucket(p), "regional")

    def test_post_bucket_global(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.operator_region = "thailand"
            gc.return_value = cfg
            p = {"countries": ["germany"], "cities": []}
            self.assertEqual(_post_bucket(p), "global")

    def test_build_watch_items(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.operator_region = "thailand"
            gc.return_value = cfg
            digest = {
                "enabled": True,
                "posts": [
                    {
                        "id": "p1",
                        "channel": "bkkbangkoknews",
                        "text": "Bangkok protest.",
                        "date": datetime.now(timezone.utc).isoformat(),
                        "score": 0.8,
                        "countries": ["thailand"],
                        "cities": ["bangkok"],
                    }
                ],
            }
            items = build_telegram_watch_items(digest)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["prefix"], "telegram")
            self.assertEqual(items[0]["bucket"], "local")
            self.assertGreater(items[0]["confidence"], 0.7)

    def test_build_watch_items_low_score_filtered(self):
        with patch("telegram_briefing.get_config") as gc:
            cfg = MagicMock()
            cfg.operator_region = "thailand"
            gc.return_value = cfg
            digest = {
                "enabled": True,
                "posts": [
                    {
                        "id": "p2",
                        "channel": "random",
                        "text": "Something vague.",
                        "score": 0.3,
                        "countries": [],
                        "cities": [],
                    }
                ],
            }
            items = build_telegram_watch_items(digest)
            self.assertEqual(len(items), 0)


if __name__ == "__main__":
    unittest.main()
