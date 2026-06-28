"""Unit tests for briefing_quality (no network)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from briefing_quality import score_briefing


class BriefingQualityTests(unittest.TestCase):
    def test_high_score_with_local_intel_gdelt(self):
        now = datetime.now(timezone.utc).isoformat()
        text = "LOCAL (Thailand)\n- Bangkok flood watch\nINTEL: entity linked\nGDELT local news"
        sources = {
            "digest": {
                "local_count": 2,
                "intel_count": 3,
                "regional_count": 1,
                "global_count": 2,
            },
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
        q = score_briefing(
            text="GLOBAL only", sources={"digest": {"local_count": 0}}, created_at=old
        )
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
        q = score_briefing(
            text="LOCAL\n- Local news: test", sources=sources, created_at=now
        )
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

    def test_stale_filtered_blocker(self):
        # Raw articles present (feed_operator>0) but all dropped by collection
        # filters → collected=0. Distinguishes a stale cache from a dead feed.
        snap = {"gdelt_pulse_local": {"count": 25, "articles": [{}] * 25}}
        digest = {"local": ["- Air quality Bangkok"], "_gdelt_collected": 0}
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertEqual(meta["feed_operator_available"], 25)
        self.assertEqual(meta["pipeline_blocker"], "stale_filtered")
        self.assertFalse(meta["pipeline_ok"])

    def test_count_gdelt_with_date_tag_prefix(self):
        from briefing_quality import count_gdelt_digest_items, item_is_gdelt

        item = {
            "text": "[23 Jun 01:45 UTC] Local news: Bangkok flood warning",
            "sources": ["gdelt_pulse_local"],
            "bucket": "local",
        }
        self.assertTrue(item_is_gdelt(item))
        self.assertEqual(count_gdelt_digest_items([item]), 1)

    def test_pipeline_counts_date_tagged_digest_lines(self):
        snap = {"gdelt_pulse_local": {"articles": [{"title": "x"}]}}
        digest = {
            "local": ["- [23 Jun 01:45 UTC] Local news: Bangkok flood"],
            "_gdelt_collected": 1,
        }
        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertEqual(meta["digest_gdelt_lines"], 1)


class CorroborationTests(unittest.TestCase):
    def test_quake_gdacs_dual_source(self):
        from briefing_quality import corroborate_digest_item

        lat, lon = 13.75, 100.5
        quake = {
            "severity": "medium",
            "text": "M5.4 — 10 km NE of Bangkok",
            "bucket": "local",
            "sources": ["earthquakes"],
            "lat": lat,
            "lon": lon,
        }
        gdacs = {
            "severity": "medium",
            "text": "Orange earthquake alert Thailand",
            "bucket": "local",
            "sources": ["gdacs"],
            "lat": lat,
            "lon": lon,
        }
        pool = [quake, gdacs]
        meta = corroborate_digest_item(quake, pool)
        self.assertGreaterEqual(meta["corroboration"], 0.8)
        self.assertEqual(meta["label"], "corroborated")
        self.assertIn("earthquakes", meta["sources"])
        self.assertIn("gdacs", meta["sources"])

    def test_single_source_local_blocker(self):
        from briefing_quality import build_digest_line_meta, corroboration_summary

        picked = [
            {
                "severity": "low",
                "text": "Air quality Bangkok: PM2.5 12 µg/m³",
                "bucket": "local",
                "sources": ["airquality"],
                "lat": 13.75,
                "lon": 100.5,
            },
            {
                "severity": "low",
                "text": "Air quality Chiang Mai: PM2.5 14 µg/m³",
                "bucket": "local",
                "sources": ["airquality"],
                "lat": 18.79,
                "lon": 98.98,
            },
            {
                "severity": "low",
                "text": "Air quality Phuket: PM2.5 9 µg/m³",
                "bucket": "local",
                "sources": ["airquality"],
                "lat": 7.88,
                "lon": 98.39,
            },
        ]
        meta = build_digest_line_meta(picked, {"local": picked})
        summary = corroboration_summary(meta)
        self.assertIsNotNone(summary["corroboration_avg_local"])
        self.assertLess(summary["corroboration_avg_local"], 0.5)
        self.assertEqual(summary["corroboration_blocker"], "single_source_local")

    def test_corroboration_penalizes_quality_score(self):
        now = datetime.now(timezone.utc).isoformat()
        meta_rows = [
            {
                "bucket": "local",
                "corroboration": 0.35,
                "source_families": ["airquality"],
                "label": "single-source",
            }
        ] * 3
        sources = {
            "digest": {"local_count": 3},
            "digest_line_meta": meta_rows,
        }
        q = score_briefing(text="LOCAL\n- lines", sources=sources, created_at=now)
        self.assertEqual(q["meta"]["corroboration_blocker"], "single_source_local")
        self.assertLess(q["score"], 0.96)

    def test_newsdata_infer_and_gdelt_corroboration(self):
        from briefing_quality import (
            _infer_feed_sources,
            _source_family,
            corroborate_digest_item,
        )

        self.assertEqual(
            _infer_feed_sources({"text": "News: Thailand floods"}), ["newsdata"]
        )
        self.assertEqual(_source_family("newsdata"), "newsdata")
        self.assertNotEqual(
            _source_family("newsdata"), _source_family("gdelt_pulse_local")
        )

        news = {
            "severity": "low",
            "text": "News: US-Iran peace talks continue in Switzerland",
            "bucket": "global",
            "sources": ["newsdata"],
        }
        gdelt = {
            "severity": "low",
            "text": "Local news: Iran US negotiations continue Switzerland talks",
            "bucket": "global",
            "sources": ["gdelt_pulse_local"],
        }
        row = corroborate_digest_item(news, [news, gdelt])
        self.assertGreaterEqual(row["corroboration"], 0.75)
        self.assertEqual(row["label"], "corroborated")
        self.assertIn("newsdata", row["source_families"])
        self.assertIn("gdelt", row["source_families"])

    def test_ftm_gdacs_source_inference(self):
        from briefing_quality import _infer_feed_sources, corroborate_digest_item

        ftm = {
            "severity": "medium",
            "text": "[22 Jun 12:00 UTC] [FtM Event/gdacs] Flood in Malaysia, Thailand",
            "bucket": "local",
        }
        gdacs = {
            "severity": "medium",
            "text": "[22 Jun 11:00 UTC] Flood in Malaysia, Thailand",
            "bucket": "local",
            "sources": ["gdacs"],
        }
        self.assertEqual(_infer_feed_sources(ftm), ["ftm", "gdacs"])
        row = corroborate_digest_item(ftm, [ftm, gdacs])
        self.assertIn("gdacs", row["source_families"])
        self.assertIn("ftm", row["source_families"])
        self.assertNotIn("unknown", row["source_families"])


class SecondPassQualityGateTests(unittest.TestCase):
    """Lücke 4: Briefing quality gate with second-pass retry."""

    def test_should_retry_low_score(self):
        from briefing_quality import should_retry_briefing

        quality = {"score": 0.3, "checks": {"local_present": False, "fresh": True}}
        retry, missing = should_retry_briefing(quality)
        self.assertTrue(retry)
        self.assertIn("local_present", missing)

    def test_should_not_retry_high_score(self):
        from briefing_quality import should_retry_briefing

        quality = {"score": 0.9, "checks": {"local_present": True, "fresh": True}}
        retry, missing = should_retry_briefing(quality)
        self.assertFalse(retry)
        self.assertEqual(missing, [])

    def test_should_not_retry_when_disabled(self):
        import os

        with patch.dict(os.environ, {"WORLDBASE_BRIEFING_SECOND_PASS": "0"}):
            # Need to reimport to pick up the env var
            import importlib
            import briefing_quality

            importlib.reload(briefing_quality)
            quality = {"score": 0.1, "checks": {"local_present": False}}
            retry, _ = briefing_quality.should_retry_briefing(quality)
            self.assertFalse(retry)
        # Reload again to restore default
        importlib.reload(briefing_quality)

    def test_build_second_pass_prompt_contains_missing_aspects(self):
        from briefing_quality import build_second_pass_prompt

        quality = {"score": 0.3, "checks": {}}
        missing = ["has_local_section", "has_intel"]
        prompt = build_second_pass_prompt("ORIGINAL PROMPT", quality, missing)
        self.assertIn("ORIGINAL PROMPT", prompt)
        self.assertIn("SECOND PASS", prompt)
        self.assertIn("LOCAL SITUATION", prompt)
        self.assertIn("INTELLIGENCE", prompt)

    def test_build_second_pass_prompt_general_fallback(self):
        from briefing_quality import build_second_pass_prompt

        quality = {"score": 0.2, "checks": {}}
        prompt = build_second_pass_prompt("BASE", quality, [])
        self.assertIn("BASE", prompt)
        self.assertIn("general quality", prompt)

    def test_second_pass_enabled_by_default(self):
        from briefing_quality import second_pass_enabled

        self.assertTrue(second_pass_enabled())

    def test_threshold_default_is_0_65(self):
        import briefing_quality

        # The default threshold should be 0.65
        self.assertAlmostEqual(briefing_quality._SECOND_PASS_THRESHOLD, 0.65, places=2)


if __name__ == "__main__":
    unittest.main()
