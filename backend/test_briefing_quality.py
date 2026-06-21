"""Unit tests for briefing_quality (no network)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from briefing_quality import score_briefing


class BriefingQualityTests(unittest.TestCase):
    def test_high_score_with_local_intel_gdelt(self):
        now = datetime.now(timezone.utc).isoformat()
        text = "LOCAL (Thailand)\n- Bangkok flood watch\nINTEL: entity linked\nGDELT local news"
        sources = {
            "digest": {"local_count": 2, "intel_count": 3, "regional_count": 1, "global_count": 2},
            "intel": {"count": 3},
        }
        q = score_briefing(text=text, sources=sources, created_at=now)
        self.assertGreaterEqual(q["score"], 0.6)
        self.assertTrue(q["checks"]["local_present"])
        self.assertTrue(q["checks"]["ftm_present"])
        self.assertTrue(q["checks"]["gdelt_present"])
        self.assertTrue(q["checks"]["fresh"])

    def test_low_score_stale_empty(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        q = score_briefing(text="GLOBAL only", sources={"digest": {"local_count": 0}}, created_at=old)
        self.assertLess(q["score"], 0.5)
        self.assertFalse(q["checks"]["fresh"])

    def test_score_bounded(self):
        q = score_briefing(text="", sources={}, created_at=None)
        self.assertGreaterEqual(q["score"], 0.0)
        self.assertLessEqual(q["score"], 1.0)

    def test_gdelt_from_feed_metadata(self):
        now = datetime.now(timezone.utc).isoformat()
        text = "LOCAL (Thailand)\n- Bangkok update"
        sources = {
            "digest": {"local_count": 2, "intel_count": 1},
            "intel": {"count": 1},
            "gdelt": {"local_pulse_count": 5, "geo_local_count": 0, "stale": False},
        }
        q = score_briefing(text=text, sources=sources, created_at=now)
        self.assertTrue(q["checks"]["gdelt_present"])
        self.assertEqual(q["meta"]["gdelt_local_pulse"], 5)

    def test_gdelt_stale_with_counts_still_counts(self):
        now = datetime.now(timezone.utc).isoformat()
        sources = {
            "digest": {"local_count": 1},
            "gdelt": {"local_pulse_count": 3, "stale": True, "error": "rate limit"},
        }
        q = score_briefing(text="LOCAL\n- item", sources=sources, created_at=now)
        self.assertTrue(q["checks"]["gdelt_present"])

    def test_gdelt_stale_empty_not_counted(self):
        now = datetime.now(timezone.utc).isoformat()
        sources = {
            "digest": {"local_count": 1},
            "gdelt": {"local_pulse_count": 0, "geo_local_count": 0, "stale": True},
        }
        q = score_briefing(text="LOCAL\n- item", sources=sources, created_at=now)
        self.assertFalse(q["checks"]["gdelt_present"])


if __name__ == "__main__":
    unittest.main()
