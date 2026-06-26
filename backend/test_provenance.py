"""Offline unit tests for P4 Provenance scoring."""

from __future__ import annotations

import os
import unittest

from provenance import (
    feed_fusion_weight,
    ingestion_chain_hash,
    provenance_enabled,
    score_from_meta,
    score_provenance,
    source_reliability,
    SOURCE_RELIABILITY,
    temporal_consistency,
)


class TestSourceReliability(unittest.TestCase):
    """Static source reliability table lookups."""

    def test_known_sources(self):
        self.assertAlmostEqual(source_reliability("gdacs"), 0.90)
        self.assertAlmostEqual(source_reliability("quake"), 0.90)
        self.assertAlmostEqual(source_reliability("gdelt"), 0.70)

    def test_case_insensitive(self):
        self.assertEqual(source_reliability("GDACS"), source_reliability("gdacs"))
        self.assertEqual(source_reliability("Quake"), source_reliability("quake"))

    def test_gdelt_family_prefix(self):
        self.assertEqual(source_reliability("gdelt_pulse_local"), 0.70)
        self.assertEqual(source_reliability("gdelt_geo_local"), 0.70)

    def test_unknown_source_defaults(self):
        score = source_reliability("nonexistent_source")
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_empty_source(self):
        self.assertEqual(source_reliability(""), 0.50)
        self.assertEqual(source_reliability(None), 0.50)

    def test_all_reliability_values_in_range(self):
        for source, val in SOURCE_RELIABILITY.items():
            self.assertGreater(val, 0.0, f"{source} reliability must be positive")
            self.assertLessEqual(val, 1.0, f"{source} reliability must be <= 1.0")


class TestTemporalConsistency(unittest.TestCase):
    """Exponential decay function."""

    def test_zero_age_is_one(self):
        self.assertEqual(temporal_consistency(0), 1.0)
        self.assertEqual(temporal_consistency(-1), 1.0)

    def test_unknown_age_fail_open(self):
        self.assertEqual(temporal_consistency(None), 1.0)

    def test_half_life_decay(self):
        """At 6h (21600s), score should be ~0.5."""
        score = temporal_consistency(6 * 3600)
        self.assertAlmostEqual(score, 0.5, places=2)

    def test_monotonic_decrease(self):
        s1 = temporal_consistency(3600)
        s6 = temporal_consistency(6 * 3600)
        s24 = temporal_consistency(24 * 3600)
        self.assertGreater(s1, s6)
        self.assertGreater(s6, s24)

    def test_very_old_approaches_zero(self):
        score = temporal_consistency(72 * 3600)
        self.assertLess(score, 0.05)


class TestScoreProvenance(unittest.TestCase):
    """Core scoring function — boundaries and weighting."""

    def test_high_reliability_corroborated_fresh(self):
        score = score_provenance(
            source="gdacs",
            corroboration_count=3,
            age_sec=60,
            ingest_chain="abc123",
        )
        self.assertGreater(score, 0.7)

    def test_low_reliability_single_source_stale(self):
        score = score_provenance(
            source="blog",
            corroboration_count=0,
            age_sec=48 * 3600,
        )
        self.assertLess(score, 0.4)

    def test_conflict_penalty(self):
        base = score_provenance("gdacs", corroboration_count=2, age_sec=60)
        conflict = score_provenance(
            "gdacs", corroboration_count=2, age_sec=60, conflict=True
        )
        self.assertLess(conflict, base)
        self.assertAlmostEqual(base - conflict, 0.15, places=2)

    def test_corroboration_boost(self):
        s0 = score_provenance("gdelt", corroboration_count=0, age_sec=60)
        s1 = score_provenance("gdelt", corroboration_count=1, age_sec=60)
        s2 = score_provenance("gdelt", corroboration_count=2, age_sec=60)
        s3 = score_provenance("gdelt", corroboration_count=3, age_sec=60)
        self.assertGreater(s1, s0)
        self.assertGreater(s2, s1)
        self.assertGreaterEqual(s3, s2)

    def test_score_in_range(self):
        for source in ["gdacs", "blog", "unknown", ""]:
            for corr in range(4):
                for age in [0, 3600, 86400, None]:
                    score = score_provenance(source, corr, age)
                    self.assertGreaterEqual(score, 0.0)
                    self.assertLessEqual(score, 1.0)

    def test_ingest_chain_boost(self):
        with_chain = score_provenance("gdelt", 1, 60, ingest_chain="hash123")
        without = score_provenance("gdelt", 1, 60)
        self.assertGreater(with_chain, without)


class TestScoreFromMeta(unittest.TestCase):
    """Convenience function for digest_line_meta / insight dicts."""

    def test_basic_meta(self):
        meta = {
            "sources": ["gdacs", "quake"],
            "source_families": ["gdacs", "quake"],
            "conflict": False,
        }
        score = score_from_meta(meta)
        self.assertGreater(score, 0.5)

    def test_conflict_meta(self):
        meta = {
            "sources": ["gdelt"],
            "source_families": ["gdelt"],
            "conflict": True,
        }
        score = score_from_meta(meta)
        self.assertLess(score, 0.6)

    def test_empty_meta(self):
        score = score_from_meta({})
        self.assertGreater(score, 0.0)
        self.assertLess(score, 0.7)

    def test_with_observed_at(self):
        from datetime import datetime, timezone, timedelta

        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        meta = {"sources": ["gdacs"], "observed_at": recent}
        score_recent = score_from_meta(meta)

        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        meta_old = {"sources": ["gdacs"], "observed_at": old}
        score_old = score_from_meta(meta_old)

        self.assertGreater(score_recent, score_old)


class TestFeedFusionWeight(unittest.TestCase):
    """Fusion heatmap source weighting."""

    def test_reliable_source_high_multiplier(self):
        weight = feed_fusion_weight("gdacs", 6.0)
        # reliability 0.90 → multiplier = 0.4 + 0.6*0.9 = 0.94
        self.assertAlmostEqual(weight, 6.0 * 0.94, places=2)

    def test_less_reliable_source_dampened(self):
        weight = feed_fusion_weight("anomaly", 5.0)
        # reliability 0.65 → multiplier = 0.4 + 0.6*0.65 = 0.79
        self.assertAlmostEqual(weight, 5.0 * 0.79, places=2)

    def test_unknown_source_moderate(self):
        weight = feed_fusion_weight("unknown_source", 3.0)
        # reliability 0.50 → multiplier = 0.4 + 0.6*0.5 = 0.70
        self.assertAlmostEqual(weight, 3.0 * 0.70, places=2)

    def test_reliable_greater_than_unknown(self):
        w_reliable = feed_fusion_weight("gdacs", 5.0)
        w_unknown = feed_fusion_weight("mystery", 5.0)
        self.assertGreater(w_reliable, w_unknown)


class TestIngestionChainHash(unittest.TestCase):
    """Deterministic content hash."""

    def test_deterministic(self):
        h1 = ingestion_chain_hash("gdacs", "alert-123", "Earthquake in Turkey")
        h2 = ingestion_chain_hash("gdacs", "alert-123", "Earthquake in Turkey")
        self.assertEqual(h1, h2)

    def test_different_inputs_different_hash(self):
        h1 = ingestion_chain_hash("gdacs", "alert-123", "Earthquake")
        h2 = ingestion_chain_hash("gdelt", "alert-123", "Earthquake")
        self.assertNotEqual(h1, h2)

    def test_hash_length(self):
        h = ingestion_chain_hash("gdacs", "1", "text")
        self.assertEqual(len(h), 16)


class TestEnvFlag(unittest.TestCase):
    """WORLDBASE_PROVENANCE env toggle."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_default_enabled(self):
        os.environ.pop("WORLDBASE_PROVENANCE", None)
        self.assertTrue(provenance_enabled())

    def test_disabled(self):
        os.environ["WORLDBASE_PROVENANCE"] = "0"
        self.assertFalse(provenance_enabled())
        os.environ.pop("WORLDBASE_PROVENANCE", None)

    def test_enabled_explicit(self):
        os.environ["WORLDBASE_PROVENANCE"] = "1"
        self.assertTrue(provenance_enabled())
        os.environ.pop("WORLDBASE_PROVENANCE", None)


class TestBriefingQualityIntegration(unittest.TestCase):
    """Verify build_digest_line_meta adds integrity field."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_integrity_field_present(self):
        from briefing_quality import build_digest_line_meta

        items = [
            {
                "text": "Local news: flooding in Bangkok",
                "bucket": "local",
                "sources": ["gdelt_pulse_local"],
                "severity": "high",
            },
            {
                "text": "GDACS alert: earthquake near Thailand",
                "bucket": "local",
                "sources": ["gdacs"],
                "severity": "high",
            },
        ]
        picked = {"local": items}
        meta = build_digest_line_meta(items, picked)
        self.assertEqual(len(meta), 2)
        for row in meta:
            self.assertIn("integrity", row)
            self.assertGreater(row["integrity"], 0.0)
            self.assertLessEqual(row["integrity"], 1.0)

    def test_integrity_absent_when_disabled(self):
        os.environ["WORLDBASE_PROVENANCE"] = "0"
        try:
            from briefing_quality import build_digest_line_meta

            items = [
                {"text": "Local news: test", "bucket": "local", "sources": ["gdelt"]},
            ]
            meta = build_digest_line_meta(items, {"local": items})
            self.assertEqual(len(meta), 1)
            self.assertNotIn("integrity", meta[0])
        finally:
            os.environ.pop("WORLDBASE_PROVENANCE", None)


class TestInsightsIntegration(unittest.TestCase):
    """Verify insights carry provenance field."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_synthesize_insights_has_provenance(self):
        from insights import synthesize_insights

        hotspots = [
            {
                "lat": 13.0,
                "lon": 100.0,
                "score": 0.8,
                "sources": ["gdacs", "quake"],
                "samples": [{"source": "gdacs", "label": "Test alert"}],
            },
        ]
        result = synthesize_insights(hotspots, top=5, with_entities=False)
        self.assertEqual(len(result), 1)
        self.assertIn("provenance", result[0])
        self.assertIsNotNone(result[0]["provenance"])
        self.assertGreater(result[0]["provenance"], 0.0)


if __name__ == "__main__":
    unittest.main()
