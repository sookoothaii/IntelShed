"""Offline unit tests for chat_context_enricher (P1) and synthesis directive (P2).

All tests are offline — no network, no Ollama, no live API.
Feed caches are monkeypatched to return deterministic test data.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

# Ensure env is clean for tests
os.environ.setdefault("WORLDBASE_CHAT_CONTEXT_ENRICH", "1")

from chat_context_enricher import (
    _briefing_chars,
    _enrich_enabled,
    _haversine_km,
    _location_matches,
    extract_query_entities,
    get_query_event_type,
    get_query_intent,
)
from chat_proxy import _build_synthesis_directive, _DOMAIN_TEMPLATES


class TestQueryEntityExtraction(unittest.TestCase):
    """Query parsing — locations, magnitudes, event types, CVEs, coordinates."""

    def test_location_extraction_country(self):
        entities = extract_query_entities("Analyze earthquake in Venezuela")
        self.assertIn("Venezuela", entities["locations"])

    def test_location_extraction_multiple(self):
        entities = extract_query_entities("Conflict near Thailand Myanmar border")
        self.assertIn("Thailand", entities["locations"])
        self.assertIn("Myanmar", entities["locations"])

    def test_location_extraction_proper_noun(self):
        entities = extract_query_entities("Analyze M4.4 earthquake near Morón")
        # "Morón" should be captured as a proper noun
        found = any("mor" in loc.lower() for loc in entities["locations"])
        self.assertTrue(
            found, f"Expected Morón in locations, got {entities['locations']}"
        )

    def test_magnitude_extraction(self):
        entities = extract_query_entities("Analyze M4.4 earthquake near Venezuela")
        self.assertAlmostEqual(entities["magnitude"], 4.4, places=1)

    def test_magnitude_extraction_decimal(self):
        entities = extract_query_entities("M7.2 quake in Japan")
        self.assertAlmostEqual(entities["magnitude"], 7.2, places=1)

    def test_event_type_earthquake(self):
        entities = extract_query_entities("Analyze M4.4 earthquake near Venezuela")
        self.assertEqual(entities["event_type"], "earthquake")

    def test_event_type_volcano(self):
        entities = extract_query_entities("Volcanic eruption in Iceland")
        self.assertEqual(entities["event_type"], "volcano")

    def test_event_type_cyber(self):
        entities = extract_query_entities("Ransomware attack on hospital")
        self.assertEqual(entities["event_type"], "cyber")

    def test_event_type_vessel(self):
        entities = extract_query_entities("Tanker incident near Strait of Malacca")
        self.assertEqual(entities["event_type"], "vessel")

    def test_event_type_none(self):
        entities = extract_query_entities("What is the weather today")
        self.assertIsNone(entities["event_type"])

    def test_cve_extraction(self):
        entities = extract_query_entities("Analyze CVE-2024-12345 exploit")
        self.assertIn("CVE-2024-12345", entities["cve_ids"])

    def test_cve_extraction_multiple(self):
        entities = extract_query_entities("CVE-2024-12345 and CVE-2023-99999")
        self.assertIn("CVE-2024-12345", entities["cve_ids"])
        self.assertIn("CVE-2023-99999", entities["cve_ids"])

    def test_coordinates_decimal(self):
        entities = extract_query_entities("Analyze event at lat: 10.5, lon: -67.0")
        self.assertIsNotNone(entities["coordinates"])
        self.assertAlmostEqual(entities["coordinates"][0], 10.5, places=1)
        self.assertAlmostEqual(entities["coordinates"][1], -67.0, places=1)

    def test_intent_analysis(self):
        entities = extract_query_entities("Analyze the earthquake situation")
        self.assertEqual(entities["intent"], "analysis")

    def test_intent_monitoring(self):
        entities = extract_query_entities("Monitor the status of the vessel")
        self.assertEqual(entities["intent"], "monitoring")

    def test_intent_general(self):
        entities = extract_query_entities("Hello world")
        self.assertEqual(entities["intent"], "general")

    def test_temporal_today(self):
        entities = extract_query_entities("Show me today's earthquakes")
        self.assertEqual(entities["temporal"], "today")

    def test_temporal_24h(self):
        entities = extract_query_entities("Earthquakes in last 24h")
        self.assertEqual(entities["temporal"], "24h")

    def test_empty_query(self):
        entities = extract_query_entities("")
        self.assertEqual(entities["locations"], [])
        self.assertIsNone(entities["magnitude"])
        self.assertIsNone(entities["event_type"])

    def test_short_query_no_match(self):
        entities = extract_query_entities("hi")
        self.assertEqual(entities["locations"], [])
        self.assertEqual(entities["intent"], "general")


class TestHaversine(unittest.TestCase):
    """Distance calculation utility."""

    def test_same_point(self):
        self.assertAlmostEqual(_haversine_km(0, 0, 0, 0), 0.0, places=2)

    def test_known_distance(self):
        # Bangkok to Chiang Mai ~580 km
        dist = _haversine_km(13.75, 100.5, 18.79, 98.99)
        self.assertGreater(dist, 500)
        self.assertLess(dist, 650)

    def test_antipode(self):
        # Opposite sides of earth ~20000 km
        dist = _haversine_km(0, 0, 0, 180)
        self.assertGreater(dist, 19000)


class TestLocationMatching(unittest.TestCase):
    """Location string + coordinate matching logic."""

    def test_string_match(self):
        self.assertTrue(_location_matches("Caracas, Venezuela", ["Venezuela"], None))

    def test_string_no_match(self):
        self.assertFalse(_location_matches("Tokyo, Japan", ["Venezuela"], None))

    def test_coord_match_within_500km(self):
        self.assertTrue(
            _location_matches(
                "Some place", [], (10.0, -67.0), event_lat=10.5, event_lon=-66.5
            )
        )

    def test_coord_no_match_beyond_500km(self):
        self.assertFalse(
            _location_matches(
                "Some place", [], (10.0, -67.0), event_lat=20.0, event_lon=-60.0
            )
        )

    def test_empty_place_no_coords(self):
        self.assertFalse(_location_matches("", [], None))


class TestEnvHelpers(unittest.TestCase):
    """Environment variable helpers."""

    def test_enrich_enabled_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_CHAT_CONTEXT_ENRICH", None)
            self.assertTrue(_enrich_enabled())

    def test_enrich_disabled(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_CONTEXT_ENRICH": "0"}):
            self.assertFalse(_enrich_enabled())

    def test_briefing_chars_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_CHAT_BRIEFING_CHARS", None)
            self.assertEqual(_briefing_chars(), 2500)

    def test_briefing_chars_custom(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_BRIEFING_CHARS": "4000"}):
            self.assertEqual(_briefing_chars(), 4000)

    def test_briefing_chars_invalid(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_BRIEFING_CHARS": "abc"}):
            self.assertEqual(_briefing_chars(), 2500)


class TestEnrichQuakes(unittest.TestCase):
    """Quake cache filtering by query entities."""

    def test_match_by_location_string(self):
        from chat_context_enricher import _enrich_quakes

        test_quakes = {
            "features": [
                {
                    "properties": {
                        "mag": 4.4,
                        "place": "Morón, Venezuela",
                        "tsunami": 0,
                        "felt": 10,
                        "time": "2024-01-01T00:00:00Z",
                    },
                    "geometry": {
                        "coordinates": [-67.0, 10.5, 10],
                    },
                },
                {
                    "properties": {
                        "mag": 5.2,
                        "place": "Tokyo, Japan",
                        "tsunami": 0,
                        "felt": 0,
                        "time": "2024-01-01T01:00:00Z",
                    },
                    "geometry": {
                        "coordinates": [139.7, 35.7, 30],
                    },
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_quakes):
            entities = extract_query_entities("M4.4 earthquake near Venezuela")
            result = _enrich_quakes(entities)
            self.assertIsNotNone(result)
            self.assertIn("Venezuela", result)
            self.assertIn("M4.4", result)
            self.assertNotIn("Tokyo", result)

    def test_match_by_coordinates(self):
        from chat_context_enricher import _enrich_quakes

        test_quakes = {
            "features": [
                {
                    "properties": {
                        "mag": 4.4,
                        "place": "Near coast",
                        "tsunami": 1,
                        "felt": 5,
                        "time": "2024-01-01T00:00:00Z",
                    },
                    "geometry": {
                        "coordinates": [-67.0, 10.5, 10],
                    },
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_quakes):
            entities = {
                "locations": [],
                "coordinates": (10.5, -67.0),
                "magnitude": None,
                "event_type": "earthquake",
            }
            result = _enrich_quakes(entities)
            self.assertIsNotNone(result)
            self.assertIn("Near coast", result)
            self.assertIn("Tsunami risk: yes", result)

    def test_match_by_magnitude(self):
        from chat_context_enricher import _enrich_quakes

        test_quakes = {
            "features": [
                {
                    "properties": {
                        "mag": 4.5,
                        "place": "Unknown location",
                        "tsunami": 0,
                        "felt": 0,
                        "time": "2024-01-01T00:00:00Z",
                    },
                    "geometry": {
                        "coordinates": [0, 0, 10],
                    },
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_quakes):
            entities = {
                "locations": [],
                "coordinates": None,
                "magnitude": 4.4,
                "event_type": "earthquake",
            }
            result = _enrich_quakes(entities)
            self.assertIsNotNone(result)
            self.assertIn("M4.5", result)

    def test_no_match_returns_none(self):
        from chat_context_enricher import _enrich_quakes

        test_quakes = {
            "features": [
                {
                    "properties": {
                        "mag": 4.4,
                        "place": "Tokyo, Japan",
                        "tsunami": 0,
                        "felt": 0,
                        "time": "2024-01-01T00:00:00Z",
                    },
                    "geometry": {
                        "coordinates": [139.7, 35.7, 30],
                    },
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_quakes):
            entities = {
                "locations": ["Venezuela"],
                "coordinates": (10.0, -67.0),
                "magnitude": None,
                "event_type": "earthquake",
            }
            result = _enrich_quakes(entities)
            self.assertIsNone(result)

    def test_empty_cache_returns_none(self):
        from chat_context_enricher import _enrich_quakes

        with patch("chat_context_enricher.cache_get", return_value=None):
            entities = extract_query_entities("Earthquake in Venezuela")
            result = _enrich_quakes(entities)
            self.assertIsNone(result)


class TestEnrichEonet(unittest.TestCase):
    """EONET natural events filtering."""

    def test_match_by_event_type(self):
        from chat_context_enricher import _enrich_eonet

        test_eonet = {
            "events": [
                {
                    "title": "Wildfire - California",
                    "categories": [{"id": "wildfires"}],
                    "geometry": [{"coordinates": [-120, 35]}],
                    "status": "open",
                },
                {
                    "title": "Flood - Bangladesh",
                    "categories": [{"id": "floods"}],
                    "geometry": [{"coordinates": [90, 24]}],
                    "status": "open",
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_eonet):
            entities = {
                "locations": [],
                "coordinates": None,
                "magnitude": None,
                "event_type": "fire",
            }
            result = _enrich_eonet(entities)
            self.assertIsNotNone(result)
            self.assertIn("Wildfire", result)
            self.assertNotIn("Flood", result)

    def test_no_match_returns_none(self):
        from chat_context_enricher import _enrich_eonet

        test_eonet = {
            "events": [
                {
                    "title": "Flood - Bangladesh",
                    "categories": [{"id": "floods"}],
                    "geometry": [{"coordinates": [90, 24]}],
                    "status": "open",
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_eonet):
            entities = {
                "locations": ["Venezuela"],
                "coordinates": None,
                "magnitude": None,
                "event_type": "earthquake",
            }
            result = _enrich_eonet(entities)
            self.assertIsNone(result)


class TestEnrichGdelt(unittest.IsolatedAsyncioTestCase):
    """GDELT event filtering by query location."""

    async def test_no_locations_returns_none(self):
        from chat_context_enricher import _enrich_gdelt

        entities = {"locations": [], "coordinates": None}
        result = await _enrich_gdelt(entities)
        self.assertIsNone(result)

    async def test_gdelt_bridge_unavailable(self):
        """When gdelt_bridge can't be imported, return None (fail-soft)."""
        from chat_context_enricher import _enrich_gdelt

        entities = {"locations": ["Venezuela"], "coordinates": None}
        # gdelt_bridge import will fail in test env if not in path
        # This is expected fail-soft behavior
        result = await _enrich_gdelt(entities)
        # Either None (import failed) or None (no data) — both acceptable
        self.assertIsNone(result)


class TestEnrichReliefweb(unittest.TestCase):
    """ReliefWeb crisis filtering by query region."""

    def test_match_by_country(self):
        from chat_context_enricher import _enrich_reliefweb

        test_rw = {
            "data": [
                {
                    "fields": {
                        "name": "Earthquake in Venezuela",
                        "status": "active",
                        "country": [{"name": "Venezuela"}],
                        "date": {"created": "2024-01-01"},
                    }
                },
                {
                    "fields": {
                        "name": "Flood in Bangladesh",
                        "status": "active",
                        "country": [{"name": "Bangladesh"}],
                        "date": {"created": "2024-01-02"},
                    }
                },
            ]
        }

        with patch("chat_context_enricher.cache_get", return_value=test_rw):
            entities = {
                "locations": ["Venezuela"],
                "coordinates": None,
            }
            result = _enrich_reliefweb(entities)
            self.assertIsNotNone(result)
            self.assertIn("Venezuela", result)
            self.assertNotIn("Bangladesh", result)

    def test_no_locations_returns_none(self):
        from chat_context_enricher import _enrich_reliefweb

        with patch("chat_context_enricher.cache_get", return_value={"data": []}):
            entities = {"locations": [], "coordinates": None}
            result = _enrich_reliefweb(entities)
            self.assertIsNone(result)


class TestSynthesisDirective(unittest.TestCase):
    """P2: _build_synthesis_directive generates all sections."""

    def test_default_directive_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("ANALYSIS DIRECTIVE", directive)

    def test_sats_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("STRUCTURED ANALYTIC TECHNIQUES", directive)
        self.assertIn("KEY ASSUMPTIONS CHECK", directive)
        self.assertIn("COMPETING HYPOTHESES", directive)
        self.assertIn("DEVIL'S ADVOCACY", directive)
        self.assertIn("INDICATORS & WARNINGS", directive)

    def test_evidence_weighting_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("EVIDENCE WEIGHTING", directive)
        self.assertIn("[HIGH", directive)
        self.assertIn("[SINGLE-SOURCE", directive)

    def test_red_team_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("BLIND SPOTS & LIMITATIONS", directive)

    def test_actionable_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("RECOMMENDED ACTIONS", directive)
        self.assertIn("MONITOR:", directive)
        self.assertIn("VERIFY:", directive)
        self.assertIn("ALERT:", directive)
        self.assertIn("ESCALATE:", directive)

    def test_fusion_matrix_present(self):
        directive = _build_synthesis_directive()
        self.assertIn("FUSION MATRIX", directive)
        self.assertIn("USGS", directive)
        self.assertIn("GDELT", directive)

    def test_domain_template_earthquake(self):
        directive = _build_synthesis_directive(event_type="earthquake")
        self.assertIn("DOMAIN TEMPLATE (seismic event)", directive)
        self.assertIn("Magnitude/depth", directive)
        self.assertIn("tsunami risk", directive)

    def test_domain_template_cyber(self):
        directive = _build_synthesis_directive(event_type="cyber")
        self.assertIn("DOMAIN TEMPLATE (cyber event)", directive)
        self.assertIn("CVE/exploit", directive)

    def test_domain_template_vessel(self):
        directive = _build_synthesis_directive(event_type="vessel")
        self.assertIn("DOMAIN TEMPLATE (maritime event)", directive)
        self.assertIn("AIS data", directive)

    def test_domain_template_unknown_type(self):
        directive = _build_synthesis_directive(event_type="unknown_type")
        # Should not include a domain template for unknown types
        self.assertNotIn("DOMAIN TEMPLATE", directive)

    def test_domain_template_none(self):
        directive = _build_synthesis_directive(event_type=None)
        self.assertNotIn("DOMAIN TEMPLATE", directive)

    def test_disable_synthesis_directive(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_SYNTHESIS_DIRECTIVE": "0"}):
            directive = _build_synthesis_directive()
            self.assertNotIn("ANALYSIS DIRECTIVE", directive)

    def test_disable_sats(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_SATS": "0"}):
            directive = _build_synthesis_directive()
            self.assertNotIn("STRUCTURED ANALYTIC TECHNIQUES", directive)

    def test_disable_red_team(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_RED_TEAM": "0"}):
            directive = _build_synthesis_directive()
            self.assertNotIn("BLIND SPOTS", directive)

    def test_disable_actionable(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_ACTIONABLE": "0"}):
            directive = _build_synthesis_directive()
            self.assertNotIn("RECOMMENDED ACTIONS", directive)

    def test_disable_fusion_matrix(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_FUSION_MATRIX": "0"}):
            directive = _build_synthesis_directive()
            self.assertNotIn("FUSION MATRIX", directive)

    def test_all_domain_templates_have_content(self):
        for key, template in _DOMAIN_TEMPLATES.items():
            self.assertIsInstance(key, str)
            self.assertIsInstance(template, str)
            self.assertGreater(len(template), 20)
            self.assertIn("DOMAIN TEMPLATE", template)


class TestQueryHelpers(unittest.TestCase):
    """Helper functions get_query_intent and get_query_event_type."""

    def test_get_query_intent(self):
        self.assertEqual(get_query_intent("Analyze the situation"), "analysis")
        self.assertEqual(get_query_intent("Monitor the vessel"), "monitoring")
        self.assertEqual(get_query_intent("Hello"), "general")

    def test_get_query_event_type(self):
        self.assertEqual(get_query_event_type("Earthquake in Japan"), "earthquake")
        self.assertEqual(get_query_event_type("Ransomware attack"), "cyber")
        self.assertIsNone(get_query_event_type("What is the weather"))


if __name__ == "__main__":
    unittest.main()
