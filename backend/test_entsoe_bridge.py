"""Unit tests for ENTSO-E bridge helpers (no live API)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import entsoe_bridge as eb


class EntsoeHelperTests(unittest.TestCase):
    def test_period_format_utc_hour_aligned(self):
        start, end = eb._period_start_end()
        self.assertEqual(len(start), 12)
        self.assertEqual(len(end), 12)
        self.assertTrue(start.endswith("00"))
        self.assertTrue(end.endswith("00"))

    def test_de_area_code_is_de_lu_zone(self):
        self.assertEqual(eb.AREA_CODES["de"], "10Y1001A1001A82H")

    def test_scrub_token_redacts_from_errors(self):
        with patch.dict("os.environ", {"ENTSOE_SECURITY_TOKEN": "secret-token"}, clear=False):
            msg = eb._scrub_token("failed for secret-token in url")
        self.assertNotIn("secret-token", msg)
        self.assertIn("REDACTED", msg)

    def test_parse_pt15m_prices(self):
        uri = eb.NS_URI
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <Publication_MarketDocument xmlns="{uri}">
          <TimeSeries>
            <Period>
              <resolution>PT15M</resolution>
              <timeInterval><start>2026-06-23T00:00Z</start></timeInterval>
              <Point><position>1</position><price.amount>10.0</price.amount></Point>
              <Point><position>2</position><price.amount>20.0</price.amount></Point>
              <Point><position>5</position><price.amount>50.0</price.amount></Point>
            </Period>
          </TimeSeries>
        </Publication_MarketDocument>"""
        pts = eb._parse_price_xml(xml)
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0]["price_eur_mwh"], 10.0)
        self.assertEqual(pts[1]["price_eur_mwh"], 50.0)

    def test_period_realised_is_past_window(self):
        start, end = eb._period_start_end_realised()
        self.assertEqual(len(start), 12)
        self.assertEqual(len(end), 12)
        self.assertLess(int(start), int(end))

    def test_parse_generation_pt15m(self):
        uri = eb.NS_URI
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
        <Publication_MarketDocument xmlns="{uri}">
          <TimeSeries>
            <MktPSRType><psrType>B16</psrType></MktPSRType>
            <Period>
              <resolution>PT15M</resolution>
              <Point><position>1</position><quantity>100</quantity></Point>
              <Point><position>5</position><quantity>400</quantity></Point>
            </Period>
          </TimeSeries>
        </Publication_MarketDocument>"""
        pts = eb._parse_generation_xml(xml)
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0]["source"], "B16")
        self.assertEqual(pts[0]["mw"], 100)
        self.assertEqual(pts[1]["mw"], 400)


if __name__ == "__main__":
    unittest.main()
