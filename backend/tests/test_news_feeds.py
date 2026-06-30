"""Unit tests for news_feeds.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import news_feeds
from runtime_cache import cache_get, cache_set


class RssParseTests(unittest.TestCase):
    def test_extract_titles(self):
        xml = """<?xml version="1.0"?>
<rss><channel>
<item><title><![CDATA[First Headline]]></title></item>
<item><title>Second Headline</title></item>
</channel></rss>
"""
        items = news_feeds._parse_rss_items(xml, "Test")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["text"], "First Headline")
        self.assertEqual(items[0]["source"], "Test")

    def test_strips_html_tags(self):
        xml = "<item><title>&lt;b&gt;Bold&lt;/b&gt; News</title></item>"
        items = news_feeds._parse_rss_items(xml, "Test")
        self.assertEqual(items[0]["text"], "Bold News")


class EnvFeedsTests(unittest.TestCase):
    def test_default_feeds(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_NEWS_RSS_FEEDS", None)
            feeds = news_feeds._rss_feeds_from_env()
        self.assertEqual(len(feeds), 3)
        self.assertEqual(feeds[0][0], "BBC World")

    def test_env_override(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_NEWS_RSS_FEEDS": "Custom|http://example.com/rss"},
        ):
            feeds = news_feeds._rss_feeds_from_env()
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0][0], "Custom")
        self.assertEqual(feeds[0][1], "http://example.com/rss")


class FormatContextTests(unittest.TestCase):
    def setUp(self):
        self._orig_relief = cache_get("reliefweb", ttl=999999)
        self._orig_rss = cache_get("rss_news", ttl=999999)

    def tearDown(self):
        if self._orig_relief is not None:
            cache_set("reliefweb", self._orig_relief)
        if self._orig_rss is not None:
            cache_set("rss_news", self._orig_rss)

    def test_reliefweb_context_from_cache(self):
        cache_set(
            "reliefweb",
            {
                "data": [
                    {"name": "Flood in Thailand", "status": "ongoing"},
                    {"name": "Drought in Myanmar", "status": "alert"},
                ]
            },
        )
        lines = news_feeds.get_reliefweb_context()
        self.assertTrue(any("Flood in Thailand" in line for line in lines))
        self.assertTrue(any("ACTIVE CRISES" in line for line in lines))

    def test_rss_context_from_cache(self):
        cache_set(
            "rss_news",
            {
                "data": [
                    {"source": "BBC", "text": "Breaking news"},
                ]
            },
        )
        lines = news_feeds.get_rss_context()
        self.assertTrue(any("Breaking news" in line for line in lines))
        self.assertTrue(any("HEADLINES" in line for line in lines))

    def test_empty_cache_returns_empty(self):
        cache_set("reliefweb", {"data": []})
        cache_set("rss_news", {"data": []})
        self.assertEqual(news_feeds.get_reliefweb_context(), [])
        self.assertEqual(news_feeds.get_rss_context(), [])


class RefreshNewsFeedsTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_stores_in_cache(self):
        with (
            patch.object(
                news_feeds,
                "fetch_reliefweb_disasters",
                new=AsyncMock(return_value={"count": 1, "data": []}),
            ),
            patch.object(
                news_feeds,
                "fetch_rss_headlines",
                new=AsyncMock(return_value={"count": 1, "data": []}),
            ),
        ):
            result = await news_feeds.refresh_news_feeds()
        self.assertEqual(result["reliefweb"]["count"], 1)
        self.assertEqual(result["rss"]["count"], 1)
        self.assertIsNotNone(cache_get("reliefweb", ttl=999999))
        self.assertIsNotNone(cache_get("rss_news", ttl=999999))


if __name__ == "__main__":
    unittest.main()
