"""Phase 0 — feed envelope contract tests (no network)."""

from __future__ import annotations

import unittest

from feeds.envelope import (
    extract_health_feed_meta,
    validate_feed_payload,
    validate_health_feed_row,
)

# Representative cached payloads (shapes from live bridges).
CVE_SAMPLE = {
    "count": 2,
    "source": "cisa.gov/kev",
    "updated": "2026-06-21T10:00:00+00:00",
    "stale": False,
    "error": None,
    "vulnerabilities": [],
}

OUTAGES_SAMPLE = {
    "count": 5,
    "sources": ["ioda"],
    "upstream": ["ioda.inetintel.cc.gatech.edu"],
    "updated": "2026-06-21T10:00:00+00:00",
    "cached_at": "2026-06-21T10:00:00+00:00",
    "items": [],
}

MARITIME_SAMPLE = {
    "count": 135,
    "stream_connected": True,
    "stream_buffer": 135,
    "cached_at": "2026-06-21T10:00:00+00:00",
    "vessels": [],
}

GDELT_PULSE_SAMPLE = {
    "count": 25,
    "source": "gdelt",
    "stale": False,
    "error": None,
    "articles": [{"title": "test"}],
    "region": "thailand",
}

WILDFIRES_SAMPLE = {
    "count": 10,
    "source": "nasa_firms",
    "updated": "2026-06-21T10:00:00+00:00",
    "stale": False,
    "fires": [],
}

CAMS_SAMPLE = {
    "count": 8,
    "elevated_count": 2,
    "source": "open-meteo/cams",
    "updated": "2026-06-21T10:00:00+00:00",
    "cities": [],
}

HUMANITARIAN_SAMPLE = {
    "count": 4,
    "source": "hdx",
    "updated": "2026-06-21T10:00:00+00:00",
    "datasets": [],
}

PEGEL_SAMPLE = {
    "count": 7,
    "source": "pegelonline.wsv.de",
    "updated": "2026-06-21T10:00:00+00:00",
    "gauges": [],
}

REPRESENTATIVE_FEEDS = {
    "cve": CVE_SAMPLE,
    "outages": OUTAGES_SAMPLE,
    "maritime": MARITIME_SAMPLE,
    "gdelt_pulse_local:thailand": GDELT_PULSE_SAMPLE,
    "wildfires": WILDFIRES_SAMPLE,
    "cams_haze": CAMS_SAMPLE,
    "humanitarian": HUMANITARIAN_SAMPLE,
    "pegel": PEGEL_SAMPLE,
}


class FeedEnvelopeContractTests(unittest.TestCase):
    def test_representative_feeds_pass_contract(self):
        for key, payload in REPRESENTATIVE_FEEDS.items():
            with self.subTest(feed=key):
                violations = validate_feed_payload(payload, endpoint=f"/api/{key}")
                self.assertEqual(violations, [], msg=f"{key}: {violations}")

    def test_missing_count_fails(self):
        bad = {"source": "test", "stale": False}
        self.assertTrue(validate_feed_payload(bad))

    def test_negative_count_fails(self):
        bad = {"count": -1, "source": "test"}
        self.assertTrue(validate_feed_payload(bad))

    def test_extract_health_meta_from_cve(self):
        meta = extract_health_feed_meta(CVE_SAMPLE)
        self.assertEqual(meta["count"], 2)
        self.assertEqual(meta["source"], "cisa.gov/kev")
        self.assertFalse(meta["stale"])

    def test_extract_health_meta_sources_plural(self):
        meta = extract_health_feed_meta(OUTAGES_SAMPLE)
        self.assertEqual(meta["source"], ["ioda"])

    def test_health_row_contract(self):
        row = {
            "cached_at": "2026-06-21T10:00:00+00:00",
            "age_sec": 12.0,
            "ttl_sec": 3600,
            "fresh": True,
            "status": "fresh",
            **extract_health_feed_meta(CVE_SAMPLE),
        }
        self.assertEqual(validate_health_feed_row(row, cache_key="cve"), [])

    def test_health_build_simulation(self):
        """Simulate /api/health feed rows built from cache + meta."""
        for cache_key, payload in REPRESENTATIVE_FEEDS.items():
            meta = extract_health_feed_meta(payload)
            row = {
                "cached_at": payload.get("cached_at") or payload.get("updated") or "2026-06-21T10:00:00+00:00",
                "age_sec": 30.0,
                "ttl_sec": 600,
                "fresh": True,
                "status": "fresh",
                **meta,
            }
            with self.subTest(cache_key=cache_key):
                self.assertEqual(validate_health_feed_row(row, cache_key=cache_key), [])
                self.assertEqual(validate_feed_payload(payload, endpoint=cache_key), [])


if __name__ == "__main__":
    unittest.main()
