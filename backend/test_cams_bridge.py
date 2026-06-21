"""Unit tests for CAMS haze bridge (no network)."""

from __future__ import annotations

import unittest

from cams_bridge import _haze_severity


class CamsBridgeTests(unittest.TestCase):
    def test_haze_severity_high_pm25(self):
        self.assertEqual(_haze_severity(80.0, None, None), "high")

    def test_haze_severity_medium_dust(self):
        self.assertEqual(_haze_severity(20.0, 50.0, None), "medium")

    def test_haze_severity_low_clear(self):
        self.assertEqual(_haze_severity(10.0, 5.0, 0.1), "low")


if __name__ == "__main__":
    unittest.main()
