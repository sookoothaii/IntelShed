"""Unit tests for operator briefing classification (no network)."""

from __future__ import annotations

import unittest

from operator_briefing import (
    _pm25_severity,
    _text_bucket,
    build_security_advisor_prompt,
    build_watch_items,
    classify_item,
    format_digest_sections,
    format_watch_items_block,
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

    def test_digest_skips_stale_gdelt_tourism_headlines(self):
        snap = {
            "gdelt_pulse_local": {
                "articles": [
                    {
                        "title": "Agoda . com celebrates Thai New Year with super special Songkran rates",
                        "seendate": "20260430T204500Z",
                    },
                    {
                        "title": "Bangkok flood warning for Chao Phraya districts",
                        "seendate": "20260622T120000Z",
                    },
                ],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        local_text = " ".join(digest["local"])
        self.assertNotIn("Songkran", local_text)
        self.assertNotIn("Agoda", local_text)
        self.assertIn("flood warning", local_text)
        self.assertIn("[22 Jun", local_text)

    def test_digest_lines_include_observed_at_meta(self):
        snap = {
            "airquality": {
                "updated": "2026-06-22T12:00:00+00:00",
                "cities": [{"city": "Bangkok", "lat": 13.75, "lon": 100.5, "pm25": 42.0}],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        self.assertTrue(any("[22 Jun" in line for line in digest["local"]))
        self.assertTrue(any(row.get("observed_at") for row in digest.get("digest_line_meta") or []))

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

    def test_digest_includes_newsdata_headlines(self):
        snap = {
            "newsdata": {
                "configured": True,
                "articles": [
                    {"title": "US-Iran peace talks continue in Switzerland"},
                    {"title": "Thailand tourism rebounds after floods"},
                ],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        combined = " ".join(digest["local"] + digest["regional"] + digest["global"])
        self.assertIn("News: US-Iran", combined)
        self.assertIn("News: Thailand", combined)

        from briefing_quality import build_digest_line_meta, corroborate_digest_item

        all_items = [
            {
                "severity": "low",
                "text": "News: US-Iran peace talks continue in Switzerland",
                "bucket": "global",
                "sources": ["newsdata"],
            }
        ]
        meta = corroborate_digest_item(all_items[0], all_items)
        self.assertIn("newsdata", meta["source_families"])

    def test_newsdata_reserved_slots_survive_severity_cap(self):
        """NewsData headlines keep slots even when higher-severity peers dominate."""
        snap = {
            "newsdata": {
                "configured": True,
                "articles": [{"title": "ASEAN security summit tensions rise in Singapore"}],
            },
            "humanitarian": {
                "datasets": [
                    {"title": f"Myanmar crisis dataset {i} Thailand border", "organization": "UNHCR"}
                    for i in range(8)
                ],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        combined = " ".join(digest["local"] + digest["regional"] + digest["global"])
        self.assertIn("News: ASEAN", combined)

    def test_newsdata_generic_headline_defaults_global_bucket(self):
        snap = {
            "newsdata": {
                "configured": True,
                "articles": [{"title": "Prime Day tech deals for smart home devices"}],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        self.assertIn("News: Prime Day", " ".join(digest["global"]))
        self.assertNotIn("News: Prime Day", " ".join(digest["regional"]))

    def test_digest_skips_sports_headlines(self):
        snap = {
            "newsdata": {
                "configured": True,
                "articles": [
                    {"title": "Liverpool win Premier League title on final day", "category": ["sports"]},
                    {"title": "Thailand flood relief expands in central provinces"},
                ],
            },
            "gdelt_pulse_local": {
                "articles": [
                    {"title": "NBA playoffs: Celtics advance to finals"},
                    {"title": "Bangkok air quality improves after rain"},
                ],
            },
        }
        digest = format_digest_sections(snap, [], "none", [])
        combined = " ".join(digest["local"] + digest["regional"] + digest["global"])
        self.assertIn("News: Thailand flood", combined)
        self.assertIn("Local news: Bangkok air", combined)
        self.assertNotIn("Premier League", combined)
        self.assertNotIn("NBA", combined)

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

    def test_build_watch_items_fusion_and_cams(self):
        snap = {
            "cams_haze": {
                "cities": [
                    {
                        "city": "Chiang Mai",
                        "lat": 18.79,
                        "lon": 98.98,
                        "pm25": 78.0,
                        "severity": "high",
                    }
                ],
            },
            "gdelt_pulse_local": {
                "articles": [{"title": f"Story {i}"} for i in range(5)],
            },
        }
        fusion = [
            {
                "lat": 13.0,
                "lon": 100.5,
                "score": 0.82,
                "sources": ["quakes", "gdacs"],
                "samples": [{"label": "M5.2 near Bangkok basin"}],
            }
        ]
        items = build_watch_items(snap, [], fusion)
        self.assertGreaterEqual(len(items), 2)
        titles = " ".join(i["title"] for i in items)
        self.assertIn("Chiang Mai", titles)
        self.assertIn("fusion", titles.lower())
        for item in items:
            self.assertIn("horizon_h", item)
            self.assertIn("confidence", item)
            self.assertIn("sources", item)
            self.assertIn("id", item)
        with_coords = [i for i in items if i.get("lat") is not None and i.get("lon") is not None]
        self.assertGreaterEqual(len(with_coords), 1)

    def test_enrich_watch_items_coords_from_cell_id(self):
        from operator_briefing import enrich_watch_items_coords

        raw = [{"id": "x", "cell_id": "13.75,100.50", "title": "test"}]
        out = enrich_watch_items_coords(raw)
        self.assertAlmostEqual(out[0]["lat"], 13.75)
        self.assertAlmostEqual(out[0]["lon"], 100.50)

    def test_watch_items_in_digest_and_prompt(self):
        snap = {
            "cams_haze": {
                "cities": [
                    {"city": "Bangkok", "lat": 13.75, "lon": 100.5, "pm25": 80.0, "severity": "high"},
                ],
            },
            "gdelt_pulse_local": {"articles": [{"title": "Thailand alert"}] * 5},
        }
        fusion = [{"lat": 14.0, "lon": 101.0, "score": 0.9, "sources": ["hazards"], "samples": [{"label": "Flood watch"}]}]
        digest = format_digest_sections(snap, [], "none", fusion)
        self.assertGreaterEqual(len(digest.get("watch_items") or []), 2)
        block = format_watch_items_block(digest["watch_items"])
        self.assertIn("horizon", block)
        prompt = build_security_advisor_prompt(digest)
        self.assertIn("WATCH ITEMS", prompt)
        self.assertIn("Bangkok", prompt)


if __name__ == "__main__":
    unittest.main()
