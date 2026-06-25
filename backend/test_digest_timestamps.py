"""Unit tests for digest_timestamps (no network)."""

import unittest
from datetime import datetime, timezone

import digest_timestamps as dt


class TestDigestTimestamps(unittest.TestCase):
    def test_parse_gdelt_seendate(self):
        parsed = dt.parse_observed_at("20260622T120000Z")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.day, 22)
        self.assertEqual(parsed.month, 6)

    def test_format_digest_date_tag(self):
        when = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(dt.format_digest_date_tag(when), "[22 Jun 12:00 UTC]")

    def test_apply_observed_at_prefixes_text(self):
        body, iso = dt.apply_observed_at(
            "Local news: flood warning", "20260622T120000Z"
        )
        self.assertIn("[22 Jun", body)
        self.assertIn("flood warning", body)
        self.assertIsNotNone(iso)

    def test_apply_observed_at_missing_date(self):
        body, iso = dt.apply_observed_at("Air quality Bangkok", None)
        self.assertEqual(body, "Air quality Bangkok")
        self.assertIsNone(iso)


if __name__ == "__main__":
    unittest.main()
