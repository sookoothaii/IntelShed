"""Unit tests for Blitzortung lightning bridge (no network)."""

from __future__ import annotations

import json
import unittest

from blitzortung_bridge import _parse_strike_line


class BlitzortungBridgeTests(unittest.TestCase):
    def test_parse_strike_line_valid(self):
        line = json.dumps(
            {
                "lat": 13.75,
                "lon": 100.5,
                "time": 1700000000000000,
                "sig": [1, 2, 3],
                "mds": 0.5,
                "status": "ok",
            }
        )
        result = _parse_strike_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["lat"], 13.75)
        self.assertEqual(result["lon"], 100.5)
        self.assertEqual(result["stations"], 3)
        self.assertEqual(result["participants"], 3)

    def test_parse_strike_line_empty(self):
        self.assertIsNone(_parse_strike_line(""))

    def test_parse_strike_line_invalid_json(self):
        self.assertIsNone(_parse_strike_line("not json"))

    def test_parse_strike_line_no_coords(self):
        line = json.dumps({"time": 1700000000000000})
        self.assertIsNone(_parse_strike_line(line))

    def test_parse_strike_line_bad_time(self):
        line = json.dumps(
            {
                "lat": 10.0,
                "lon": 20.0,
                "time": "bad",
            }
        )
        result = _parse_strike_line(line)
        self.assertIsNotNone(result)
        self.assertIsNone(result["time"])

    def test_parse_strike_line_no_sig(self):
        line = json.dumps(
            {
                "lat": 10.0,
                "lon": 20.0,
                "time": 1700000000000000,
            }
        )
        result = _parse_strike_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result["stations"], 0)


if __name__ == "__main__":
    unittest.main()
