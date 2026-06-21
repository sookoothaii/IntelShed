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

    def test_watch_count_in_quality_meta(self):
        now = datetime.now(timezone.utc).isoformat()
        sources = {
            "watch_items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "digest": {"local_count": 1},
        }
        q = score_briefing(text="LOCAL\n- test", sources=sources, created_at=now)
        self.assertEqual(q["meta"]["watch_count"], 3)

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

    def test_gdelt_pipeline_meta_in_quality(self):
        now = datetime.now(timezone.utc).isoformat()
        sources = {
            "digest": {"local_count": 3},
            "gdelt": {
                "feed_operator_available": 10,
                "gdelt_collected": 4,
                "digest_gdelt_lines": 2,
                "pipeline_yield": 0.4,
                "placement_yield": 0.5,
                "pipeline_ok": True,
                "pipeline_placed_ok": True,
            },
        }
        q = score_briefing(text="LOCAL\n- Local news: test", sources=sources, created_at=now)
        self.assertEqual(q["meta"]["gdelt_collected"], 4)
        self.assertEqual(q["meta"]["gdelt_digest_lines"], 2)
        self.assertEqual(q["meta"]["gdelt_pipeline_yield"], 0.4)
        self.assertTrue(q["meta"]["gdelt_pipeline_ok"])


class GdeltPipelineMetaTests(unittest.TestCase):
    def test_pipeline_counts_digest_lines(self):
        snap = {
            "gdelt_pulse_local": {"count": 8, "articles": [{}] * 8},
            "gdelt_geo_local": {"count": 2, "events": [{}, {}]},
        }
        digest = {
            "local": ["- Local news: Bangkok flood", "- Air quality Bangkok"],
            "regional": ["- Regional media heat: Myanmar border"],
            "global": ["- News: Global headline"],
            "_gdelt_collected": 12,
        }
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertEqual(meta["digest_gdelt_lines"], 3)
        self.assertEqual(meta["gdelt_collected"], 12)
        self.assertEqual(meta["feed_operator_available"], 10)
        self.assertEqual(meta["pipeline_yield"], 1.0)
        self.assertEqual(meta["placement_yield"], 0.25)
        self.assertTrue(meta["pipeline_ok"])
        self.assertTrue(meta["pipeline_placed_ok"])

    def test_pipeline_ok_when_no_feed(self):
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta({}, {"local": ["- Air quality only"]})
        self.assertTrue(meta["pipeline_ok"])
        self.assertIsNone(meta["pipeline_yield"])

    def test_empty_feed_body_blocker(self):
        snap = {
            "gdelt_pulse_local": {"count": 25, "articles": [], "error": "rate limit"},
        }
        digest = {"local": ["- Air quality Bangkok"], "_gdelt_collected": 0}
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertEqual(meta["feed_operator_available"], 0)
        self.assertEqual(meta["pipeline_blocker"], "empty_feed_body")
        self.assertFalse(meta["pipeline_ok"])

    def test_bucket_cap_blocker(self):
        snap = {"gdelt_pulse_local": {"articles": [{}] * 5}}
        digest = {
            "local": ["- Air quality only"],
            "_gdelt_collected": 5,
        }
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertEqual(meta["pipeline_blocker"], "bucket_cap")
        self.assertTrue(meta["pipeline_ok"])
        self.assertFalse(meta["pipeline_placed_ok"])


if __name__ == "__main__":
    unittest.main()
