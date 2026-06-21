"""Unit tests for GDELT adaptive backoff helpers (no network)."""

import unittest

import gdelt_bridge as gb


class TestGdeltBackoff(unittest.TestCase):
    def setUp(self):
        gb._GDELT_CONSECUTIVE_429 = 0
        gb._GDELT_BACKOFF_UNTIL = 0.0

    def test_backoff_escalates_on_repeated_429(self):
        gb._gdelt_rate_limited()
        first = gb._backoff_seconds()
        gb._gdelt_rate_limited()
        second = gb._backoff_seconds()
        self.assertGreater(second, first)

    def test_backoff_caps_at_max(self):
        gb._GDELT_CONSECUTIVE_429 = 20
        self.assertLessEqual(gb._backoff_seconds(), gb._GDELT_BACKOFF_MAX)

    def test_success_decays_backoff_counter(self):
        gb._GDELT_CONSECUTIVE_429 = 3
        gb._gdelt_success()
        self.assertEqual(gb._GDELT_CONSECUTIVE_429, 2)

    def test_resolve_region_defaults_to_operator(self):
        self.assertEqual(gb._resolve_region(None), gb._operator_region())

    def test_resolve_region_normalizes(self):
        self.assertEqual(gb._resolve_region(" Thailand "), "thailand")


class TestGdeltCache(unittest.TestCase):
    def test_stale_response_preserves_counts(self):
        key = "pulse:local:test"
        gb._CACHE[key] = (
            0.0,
            {"count": 12, "articles": [{"title": "x"}], "region": "test"},
        )
        out = gb._stale_response(key, error="rate limit")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["count"], 12)
        self.assertTrue(out["stale"])
        self.assertEqual(out["error"], "rate limit")
        gb._CACHE.pop(key, None)


if __name__ == "__main__":
    unittest.main()
