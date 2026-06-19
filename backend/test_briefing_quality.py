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


if __name__ == "__main__":
    unittest.main()
