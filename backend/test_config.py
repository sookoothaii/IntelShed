"""Unit tests for backend/config.py."""

from __future__ import annotations

import os
import unittest

import config


class TestWorldBaseConfig(unittest.TestCase):
    def tearDown(self) -> None:
        config.get_config.cache_clear()

    def test_defaults(self) -> None:
        cfg = config.WorldBaseConfig()
        self.assertEqual(cfg.feed_ingest_interval, 600)
        self.assertEqual(cfg.operator_region, "thailand")
        self.assertTrue(cfg.feed_ingest_autopilot)
        self.assertFalse(cfg.entity_resolution_after_feeds)
        self.assertTrue(cfg.rag_feed_ingest)

    def test_from_env(self) -> None:
        env = {
            "WORLDBASE_FEED_INGEST_INTERVAL": "300",
            "WORLDBASE_OPERATOR_REGION": " Germany ",
            "WORLDBASE_FEED_INGEST_AUTOPILOT": "0",
            "WORLDBASE_ENTITY_RESOLUTION_AFTER_FEEDS": "true",
            "RAG_FEED_INGEST": "no",
        }
        for key, value in env.items():
            os.environ[key] = value
        try:
            cfg = config.WorldBaseConfig.from_env()
            self.assertEqual(cfg.feed_ingest_interval, 300)
            self.assertEqual(cfg.operator_region, "germany")
            self.assertFalse(cfg.feed_ingest_autopilot)
            self.assertTrue(cfg.entity_resolution_after_feeds)
            self.assertFalse(cfg.rag_feed_ingest)
        finally:
            for key in env:
                os.environ.pop(key, None)

    def test_cached_get_config(self) -> None:
        config.get_config.cache_clear()
        first = config.get_config()
        second = config.get_config()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
