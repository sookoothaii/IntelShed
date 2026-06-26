"""Tests for telegram_bridge (K3) — fail-soft, parsing, scoring, ingest."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch

import telegram_bridge
from telegram_bridge import (
    _apply_geo_enrichment,
    _apply_sea_scoring,
    _extract_hashtags,
    _extract_urls,
    _first_sentence,
    _post_id,
    ingest_posts,
)


class TelegramBridgeTests(unittest.TestCase):
    def test_extract_urls(self):
        text = "Check https://t.me/bkkbangkoknews/123 and http://example.com/path"
        urls = _extract_urls(text)
        self.assertEqual(len(urls), 2)
        self.assertIn("https://t.me/bkkbangkoknews/123", urls)

    def test_extract_hashtags(self):
        self.assertEqual(
            _extract_hashtags("#bangkok #protest #Bangkok"), ["#bangkok", "#protest"]
        )

    def test_first_sentence(self):
        self.assertEqual(_first_sentence("Hello world. More text."), "Hello world.")
        self.assertEqual(_first_sentence("No punctuation here"), "No punctuation here")
        self.assertEqual(_first_sentence(""), "")

    def test_post_id_deterministic(self):
        self.assertEqual(_post_id("chan", 42), _post_id("chan", 42))
        self.assertNotEqual(_post_id("chan", 42), _post_id("chan", 43))

    def test_geo_enrichment(self):
        posts = [
            {
                "text": "Protest in Bangkok, Thailand. Myanmar border tension.",
                "hashtags": [],
            }
        ]
        _apply_geo_enrichment(posts)
        p = posts[0]
        self.assertIn("thailand", p["countries"])
        self.assertIn("myanmar", p["countries"])
        self.assertIn("bangkok", p["cities"])

    def test_sea_scoring(self):
        posts = [
            {
                "text": "",
                "countries": ["thailand"],
                "cities": ["bangkok"],
                "keywords": ["protest"],
                "views": 5000,
                "forwards": 0,
                "media_type": None,
            },
        ]
        _apply_geo_enrichment(posts)
        _apply_sea_scoring(posts)
        self.assertGreater(posts[0]["score"], 0.5)

    def test_ingest_disabled_without_config(self):
        with patch.object(telegram_bridge._tg_config, "configured", return_value=False):
            result = ingest_posts([{"id": "x"}], dataset="telegram")
            self.assertFalse(result["enabled"])

    def test_apply_geo_enrichment_preserves_structure(self):
        posts = [{"text": "Hello world", "hashtags": []}]
        _apply_geo_enrichment(posts)
        self.assertEqual(posts[0]["countries"], [])
        self.assertEqual(posts[0]["cities"], [])
        self.assertEqual(posts[0]["keywords"], [])


class TelegramBridgeAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_disabled_without_config(self):
        with patch.object(telegram_bridge._tg_config, "configured", return_value=False):
            result = await telegram_bridge.refresh_telegram_posts()
            self.assertFalse(result["enabled"])
            self.assertEqual(result["count"], 0)

    async def test_refresh_no_channels(self):
        with patch.object(
            telegram_bridge._tg_config, "configured", return_value=True
        ), patch.object(
            type(telegram_bridge._tg_config),
            "channels",
            new_callable=PropertyMock,
            return_value=[],
        ):
            result = await telegram_bridge.refresh_telegram_posts()
            self.assertTrue(result["enabled"])
            self.assertEqual(result["count"], 0)
            self.assertEqual(result["error"], "no channels configured")

    async def test_posts_cached_filters(self):
        with patch.object(telegram_bridge._tg_config, "configured", return_value=True):
            telegram_bridge._POSTS = [
                {
                    "id": "p1",
                    "channel": "a",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "score": 0.9,
                },
                {
                    "id": "p2",
                    "channel": "b",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "score": 0.2,
                },
            ]
            result = await telegram_bridge.get_cached_posts(channel="a", min_score=0.5)
            self.assertEqual(len(result["posts"]), 1)
            self.assertEqual(result["posts"][0]["id"], "p1")


if __name__ == "__main__":
    unittest.main()
