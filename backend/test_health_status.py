"""Unit tests for /api/health feed status thresholds."""

from __future__ import annotations

import unittest

from routes.health import _feed_status


class FeedStatusTests(unittest.TestCase):
    def test_maritime_ttl_aligned(self):
        self.assertEqual(_feed_status(20.0, 45.0), "fresh")
        self.assertEqual(_feed_status(40.0, 45.0), "warn")
        self.assertEqual(_feed_status(60.0, 45.0), "warn")
        self.assertEqual(_feed_status(100.0, 45.0), "stale")

    def test_newsdata_sources_long_ttl(self):
        ttl = 86400.0
        self.assertEqual(_feed_status(200.0, ttl), "fresh")
        self.assertEqual(_feed_status(3600.0, ttl), "warn")
        self.assertEqual(_feed_status(180000.0, ttl), "stale")


if __name__ == "__main__":
    unittest.main()
