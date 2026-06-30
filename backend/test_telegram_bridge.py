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
        with (
            patch.object(telegram_bridge._tg_config, "configured", return_value=True),
            patch.object(
                type(telegram_bridge._tg_config),
                "channels",
                new_callable=PropertyMock,
                return_value=[],
            ),
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


class TelegramEntityMatchingTests(unittest.TestCase):
    """3.5 — Telegram → FtM Mention deep integration tests."""

    def test_match_post_to_entities_by_name(self):
        """Post text containing entity name should match."""
        entities = [
            {
                "id": "ent1",
                "schema": "Person",
                "name": "Prayut Chan-o-cha",
                "properties": {},
            },
            {"id": "ent2", "schema": "Organization", "name": "PTT", "properties": {}},
        ]
        post = {"text": "Prayut Chan-o-cha announces new policy today", "hashtags": []}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["entity_id"], "ent1")
        self.assertEqual(matches[0]["schema"], "Person")

    def test_match_post_to_entities_by_alias(self):
        """Post text containing alias should match."""
        entities = [
            {
                "id": "ent1",
                "schema": "Person",
                "name": "Hun Sen",
                "properties": {"alias": ["Hun Xen", "PM Hun Sen"]},
            },
        ]
        post = {"text": "Hun Xen visits Bangkok for trade talks", "hashtags": []}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["matched_alias"], "Hun Xen")

    def test_match_post_no_match(self):
        """Post text with no entity names should return empty list."""
        entities = [
            {
                "id": "ent1",
                "schema": "Person",
                "name": "Prayut Chan-o-cha",
                "properties": {},
            },
        ]
        post = {"text": "Weather update for Bangkok today", "hashtags": []}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 0)

    def test_match_post_case_insensitive(self):
        """Matching should be case-insensitive."""
        entities = [
            {"id": "ent1", "schema": "Organization", "name": "PTT", "properties": {}},
        ]
        post = {"text": "ptt announces new pipeline project", "hashtags": []}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 1)

    def test_match_post_skips_short_names(self):
        """Names shorter than 3 chars should be skipped to avoid false positives."""
        entities = [
            {"id": "ent1", "schema": "Person", "name": "Li", "properties": {}},
        ]
        post = {"text": "Li visits Bangkok", "hashtags": []}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 0)

    def test_match_post_with_hashtags(self):
        """Hashtags should be included in matching text."""
        entities = [
            {
                "id": "ent1",
                "schema": "Organization",
                "name": "Thailand",
                "properties": {},
            },
        ]
        post = {"text": "News update today", "hashtags": ["#bangkok", "#thailand"]}
        matches = telegram_bridge.match_post_to_entities(post, entities)
        self.assertEqual(len(matches), 1)

    def test_list_person_org_entities_empty(self):
        """Should return empty list when ftm_query unavailable (fail-soft)."""
        import builtins

        orig_import = builtins.__import__

        def _fail_import(name, *args, **kwargs):
            if name == "ftm_query":
                raise ImportError("no ftm")
            return orig_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=_fail_import):
            result = telegram_bridge._list_person_org_entities()
        self.assertEqual(result, [])

    def test_ingest_returns_linked_entities(self):
        """Ingest should return linked_entities list (even if empty)."""
        import ftm_query as real_ftm

        with (
            patch.object(telegram_bridge._tg_config, "configured", return_value=True),
            patch.object(telegram_bridge, "_list_person_org_entities", return_value=[]),
            patch.object(real_ftm, "upsert", side_effect=lambda e, **kw: e),
            patch.object(real_ftm, "add_edge", side_effect=lambda **kw: None),
        ):
            posts = [
                {
                    "id": "p1",
                    "text": "Test post",
                    "channel": "test",
                    "date": "2026-06-27T00:00:00Z",
                    "url": "https://t.me/test/1",
                    "channel_title": "Test",
                }
            ]
            result = telegram_bridge.ingest_posts(posts, dataset="telegram")
        self.assertTrue(result["enabled"])
        self.assertIn("linked_entities", result)
        self.assertIsInstance(result["linked_entities"], list)


if __name__ == "__main__":
    unittest.main()
