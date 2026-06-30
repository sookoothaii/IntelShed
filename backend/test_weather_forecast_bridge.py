"""Unit tests for weather forecast bridge (no network)."""

from __future__ import annotations

import unittest

from weather_forecast_bridge import (
    _wmo_label,
    _is_severe,
    _severity_level,
    gather_forecast_weather_digest,
)


class WeatherForecastTests(unittest.TestCase):
    def test_wmo_label_known(self):
        self.assertEqual(_wmo_label(0), "Clear sky")
        self.assertEqual(_wmo_label(95), "Thunderstorm")
        self.assertEqual(_wmo_label(65), "Heavy rain")

    def test_wmo_label_unknown(self):
        self.assertEqual(_wmo_label(999), "Code 999")
        self.assertEqual(_wmo_label(None), "Unknown")

    def test_is_severe_thunderstorm(self):
        self.assertTrue(_is_severe(95, None, None))

    def test_is_severe_heavy_rain(self):
        self.assertTrue(_is_severe(65, None, None))

    def test_is_severe_high_wind(self):
        self.assertTrue(_is_severe(None, 65.0, None))

    def test_is_severe_heavy_precip(self):
        self.assertTrue(_is_severe(None, None, 55.0))

    def test_is_severe_clear(self):
        self.assertFalse(_is_severe(0, 10.0, 1.0))

    def test_severity_level_high_thunderstorm(self):
        self.assertEqual(_severity_level(95, None, None), "high")

    def test_severity_level_high_wind(self):
        self.assertEqual(_severity_level(None, 90.0, None), "high")

    def test_severity_level_medium(self):
        self.assertEqual(_severity_level(65, None, None), "medium")

    def test_severity_level_low(self):
        self.assertEqual(_severity_level(0, 10.0, 1.0), "low")

    def test_gather_digest_empty_cache(self):
        digest = gather_forecast_weather_digest()
        self.assertFalse(digest["enabled"])
        self.assertEqual(digest["count"], 0)


if __name__ == "__main__":
    unittest.main()
