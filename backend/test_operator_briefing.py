"""Unit tests for operator briefing classification (no network)."""

from __future__ import annotations

import unittest

from operator_briefing import (
    _pm25_severity,
    _text_bucket,
    classify_item,
    format_digest_sections,
)


class OperatorBriefingTests(unittest.TestCase):
    def test_text_bucket_local_keywords(self):
        self.assertEqual(_text_bucket("Flooding in Bangkok metro"), "local")
        self.assertEqual(_text_bucket("ASEAN summit in Singapore"), "regional")
        self.assertEqual(_text_bucket("Wildfire in California"), None)

    def test_classify_item_in_local_bbox(self):
        bbox = [97.3, 5.6, 105.65, 20.46]  # Thailand
        self.assertEqual(
            classify_item(13.75, 100.5, "Bangkok traffic", bbox, bbox),
            "local",
        )
        self.assertEqual(
            classify_item(1.35, 103.8, "Singapore port", bbox, bbox),
            "regional",
        )

    def test_pm25_severity_bands(self):
        self.assertEqual(_pm25_severity(80), "high")
        self.assertEqual(_pm25_severity(40), "medium")
        self.assertEqual(_pm25_severity(10), "low")

    def test_digest_includes_local_air_quality(self):
        snap = {
            "airquality": {
                "cities": [{"city": "Bangkok", "lat": 13.75, "lon": 100.5, "pm25": 42.0}],
            },
            "gdelt_pulse_local": {
                "articles": [{"title": "Thailand tourism update"}],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        local_text = " ".join(digest["local"])
        self.assertIn("Bangkok", local_text)
        self.assertIn("Local news", local_text)
        self.assertNotIn("No local signals", local_text)

    def test_digest_includes_cams_haze_and_humanitarian(self):
        snap = {
            "cams_haze": {
                "cities": [
                    {
                        "city": "Chiang Mai",
                        "lat": 18.79,
                        "lon": 98.98,
                        "pm25": 55.0,
                        "dust": 60.0,
                        "severity": "medium",
                    }
                ],
            },
            "humanitarian": {
                "datasets": [
                    {"title": "Myanmar refugee response Thailand border", "organization": "UNHCR"},
                ],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        local_text = " ".join(digest["local"])
        regional_text = " ".join(digest["regional"])
        self.assertIn("CAMS haze", local_text)
        self.assertIn("Chiang Mai", local_text)
        combined = local_text + " " + regional_text
        self.assertIn("Humanitarian", combined)
        self.assertIn("Myanmar", combined)

    def test_local_gdelt_reserved_slots_survive_severity_cap(self):
        """GDELT local news keeps LOCAL slots even when AQ/CAMS outrank on severity."""
        snap = {
            "airquality": {
                "cities": [
                    {"city": f"City{i}", "lat": 13.75, "lon": 100.5, "pm25": 80.0}
                    for i in range(6)
                ],
            },
            "gdelt_pulse_local": {
                "articles": [{"title": f"Thailand story {i}"} for i in range(4)],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        gdelt_lines = [ln for ln in digest["local"] if "Local news" in ln]
        self.assertGreaterEqual(len(gdelt_lines), 2, digest["local"])

        from briefing_quality import gdelt_digest_pipeline_meta

        meta = gdelt_digest_pipeline_meta(snap, digest)
        self.assertGreaterEqual(meta["digest_gdelt_lines"], 2)
        self.assertTrue(meta["pipeline_placed_ok"])
        self.assertIsNone(meta["pipeline_blocker"])


if __name__ == "__main__":
    unittest.main()
