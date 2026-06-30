"""Unit tests for OSM Overpass bridge (no network)."""

from __future__ import annotations

import unittest

from osm_bridge import (
    _build_overpass_query,
    _parse_element,
    _INFRA_TAGS,
    gather_osm_digest,
)


class OsmBridgeTests(unittest.TestCase):
    def test_build_query_includes_all_types(self):
        bbox = (13.0, 100.0, 14.0, 101.0)
        query = _build_overpass_query(bbox, list(_INFRA_TAGS.keys()))
        self.assertIn("amenity=hospital", query)
        self.assertIn("power=plant", query)
        self.assertIn("aeroway=aerodrome", query)
        self.assertIn("bridge=yes", query)
        self.assertIn("[out:json]", query)

    def test_build_query_subset(self):
        bbox = (5.0, 97.0, 21.0, 106.0)
        query = _build_overpass_query(bbox, ["hospital", "airport"])
        self.assertIn("amenity=hospital", query)
        self.assertIn("aeroway=aerodrome", query)
        self.assertNotIn("power=plant", query)

    def test_parse_element_node(self):
        el = {
            "type": "node",
            "id": 12345,
            "lat": 13.75,
            "lon": 100.5,
            "tags": {"name": "Bangkok Hospital", "amenity": "hospital"},
        }
        result = _parse_element(el, "hospital")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Bangkok Hospital")
        self.assertEqual(result["type"], "hospital")
        self.assertEqual(result["lat"], 13.75)
        self.assertEqual(result["lon"], 100.5)

    def test_parse_element_way_with_center(self):
        el = {
            "type": "way",
            "id": 67890,
            "center": {"lat": 18.79, "lon": 98.98},
            "tags": {"name": "Chiang Mai Airport", "aeroway": "aerodrome"},
        }
        result = _parse_element(el, "airport")
        self.assertIsNotNone(result)
        self.assertEqual(result["lat"], 18.79)
        self.assertEqual(result["lon"], 98.98)

    def test_parse_element_no_coords(self):
        el = {"type": "way", "id": 1, "tags": {"name": "No coords"}}
        result = _parse_element(el, "hospital")
        self.assertIsNone(result)

    def test_parse_element_fallback_name(self):
        el = {
            "type": "node",
            "id": 99,
            "lat": 1.0,
            "lon": 2.0,
            "tags": {"amenity": "police"},
        }
        result = _parse_element(el, "police")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Police")

    def test_gather_digest_empty_cache(self):
        digest = gather_osm_digest()
        self.assertFalse(digest["enabled"])
        self.assertEqual(digest["count"], 0)


if __name__ == "__main__":
    unittest.main()
