"""Unit tests for ACLED conflict events bridge (no network)."""

from __future__ import annotations

import unittest

from acled_bridge import (
    _parse_event,
    _severity_for_event,
    gather_acled_digest,
    _ASEAN_CODES,
)


class AcledBridgeTests(unittest.TestCase):
    def test_severity_high_fatalities(self):
        self.assertEqual(_severity_for_event("Battle", 15), "high")

    def test_severity_medium_fatalities(self):
        self.assertEqual(_severity_for_event("Protest", 3), "medium")

    def test_severity_by_event_type_battle(self):
        self.assertEqual(_severity_for_event("Battle", 0), "high")

    def test_severity_by_event_type_protest(self):
        self.assertEqual(_severity_for_event("Protest", 0), "low")

    def test_severity_unknown_type(self):
        self.assertEqual(_severity_for_event(None, 0), "low")

    def test_parse_event_full(self):
        row = {
            "data_id": "12345",
            "event_date": "2026-06-30",
            "event_type": "Battle",
            "sub_event_type": "Armed clash",
            "country": "Thailand",
            "admin1": "Chiang Mai",
            "admin2": "Chiang Mai",
            "latitude": "18.79",
            "longitude": "98.98",
            "fatalities": "5",
            "notes": "Heavy fighting reported",
            "source": "Reuters",
        }
        result = _parse_event(row)
        self.assertEqual(result["id"], "12345")
        self.assertEqual(result["event_type"], "Battle")
        self.assertEqual(result["country"], "Thailand")
        self.assertEqual(result["lat"], 18.79)
        self.assertEqual(result["lon"], 98.98)
        self.assertEqual(result["fatalities"], 5)
        self.assertEqual(result["severity"], "medium")

    def test_parse_event_missing_coords(self):
        row = {
            "event_type": "Protest",
            "country": "Myanmar",
            "fatalities": "0",
        }
        result = _parse_event(row)
        self.assertIsNone(result["lat"])
        self.assertIsNone(result["lon"])
        self.assertEqual(result["fatalities"], 0)
        self.assertEqual(result["severity"], "low")

    def test_parse_event_bad_fatalities(self):
        row = {
            "event_type": "Riot",
            "fatalities": "N/A",
        }
        result = _parse_event(row)
        self.assertEqual(result["fatalities"], 0)

    def test_parse_event_truncates_notes(self):
        long_notes = "A" * 1000
        row = {"event_type": "Battle", "notes": long_notes}
        result = _parse_event(row)
        self.assertEqual(len(result["notes"]), 500)

    def test_asean_codes_includes_thailand(self):
        self.assertIn("THA", _ASEAN_CODES)
        self.assertIn("MMR", _ASEAN_CODES)
        self.assertIn("PHL", _ASEAN_CODES)

    def test_gather_digest_empty_cache(self):
        digest = gather_acled_digest()
        self.assertFalse(digest["enabled"])
        self.assertEqual(digest["count"], 0)


if __name__ == "__main__":
    unittest.main()
