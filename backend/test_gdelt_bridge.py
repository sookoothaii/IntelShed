"""Unit tests for GDELT adaptive backoff helpers (no network)."""

import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

import gdelt_bridge as gb


def _gdelt_seendate(hours_ago: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return ts.strftime("%Y%m%dT%H%M%SZ")


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


class TestGdeltLocalPulseFilter(unittest.TestCase):
    def test_parse_gdelt_seendate(self):
        dt = gb.parse_gdelt_seendate("20260430T204500Z")
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 4)

    def test_filter_drops_stale_songkran_and_tourism(self):
        articles = [
            {
                "title": "Agoda . com celebrates Thai New Year with super special Songkran rates",
                "seendate": _gdelt_seendate(6),
            },
            {
                "title": "Top 8 Must - See Destinations When Exploring Thailand",
                "seendate": _gdelt_seendate(48),
            },
            {
                "title": "Bangkok authorities issue flood warning for Chao Phraya",
                "seendate": _gdelt_seendate(4),
            },
        ]
        kept = gb.filter_local_pulse_articles(articles)
        self.assertEqual(len(kept), 1)
        self.assertIn("flood warning", kept[0]["title"].lower())

    def test_finalize_local_pulse_updates_count(self):
        out = gb.finalize_local_pulse(
            {
                "count": 2,
                "articles": [
                    {"title": "Songkran festival deals", "seendate": _gdelt_seendate(6)},
                    {"title": "M5.2 earthquake near Chiang Rai", "seendate": _gdelt_seendate(2)},
                ],
            }
        )
        self.assertEqual(out["count"], 1)
        self.assertNotIn("Songkran", out["articles"][0]["title"])

    def test_finalize_stale_pulse_skips_freshness_guard(self):
        out = gb.finalize_local_pulse(
            {
                "stale": True,
                "count": 2,
                "articles": [
                    {"title": "Bangkok flood warning", "seendate": "20260414T230000Z"},
                    {"title": "Chiang Mai haze alert", "seendate": "20260410T120000Z"},
                ],
            }
        )
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["stale"])

    def test_load_pulse_local_registry_preserves_aged_articles(self):
        reg = "thailand"
        payload = {
            "count": 2,
            "articles": [
                {"title": "Bangkok flood warning", "seendate": "20260414T230000Z"},
                {"title": "Chiang Mai haze alert", "seendate": "20260410T120000Z"},
            ],
        }
        with unittest.mock.patch.object(gb.feed_registry, "read", return_value=payload):
            out = gb._load_pulse_local_registry(reg)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["stale"])


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
