"""Unit tests for ENTSO-E bridge XML parsing (no network)."""

from __future__ import annotations

import unittest

from entsoe_bridge import _normalize_prices_to_hourly, _parse_generation_xml, _parse_price_xml

NS = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"

PRICE_PT15M_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="{NS}">
  <TimeSeries>
    <Period>
      <timeInterval>
        <start>2026-06-23T00:00Z</start>
        <end>2026-06-23T02:00Z</end>
      </timeInterval>
      <resolution>PT15M</resolution>
      <Point><position>1</position><price.amount>100.0</price.amount></Point>
      <Point><position>2</position><price.amount>104.0</price.amount></Point>
      <Point><position>3</position><price.amount>108.0</price.amount></Point>
      <Point><position>4</position><price.amount>112.0</price.amount></Point>
      <Point><position>5</position><price.amount>120.0</price.amount></Point>
      <Point><position>6</position><price.amount>124.0</price.amount></Point>
      <Point><position>7</position><price.amount>128.0</price.amount></Point>
      <Point><position>8</position><price.amount>132.0</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""

PRICE_PT60M_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="{NS}">
  <TimeSeries>
    <Period>
      <timeInterval>
        <start>2026-06-23T00:00Z</start>
        <end>2026-06-23T03:00Z</end>
      </timeInterval>
      <resolution>PT60M</resolution>
      <Point><position>1</position><price.amount>85.5</price.amount></Point>
      <Point><position>2</position><price.amount>90.0</price.amount></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""

GENERATION_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="{NS}">
  <TimeSeries>
    <MktPSRType><psrType>B16</psrType></MktPSRType>
    <Period>
      <resolution>PT15M</resolution>
      <Point><position>1</position><quantity>1200</quantity></Point>
      <Point><position>2</position><quantity>1300</quantity></Point>
    </Period>
  </TimeSeries>
  <TimeSeries>
    <MktPSRType><psrType>B19</psrType></MktPSRType>
    <Period>
      <resolution>PT15M</resolution>
      <Point><position>2</position><quantity>4500</quantity></Point>
    </Period>
  </TimeSeries>
</Publication_MarketDocument>
"""


class EntsoeBridgeTests(unittest.TestCase):
    def test_parse_price_pt15m_aggregates_to_hourly(self):
        prices = _parse_price_xml(PRICE_PT15M_XML)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0]["price_eur_mwh"], 106.0)  # avg of 100..112
        self.assertEqual(prices[1]["price_eur_mwh"], 126.0)  # avg of 120..132
        self.assertTrue(prices[0]["start_time"].startswith("2026-06-23T00"))

    def test_parse_price_pt60m_keeps_hourly_points(self):
        prices = _parse_price_xml(PRICE_PT60M_XML)
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices[0]["price_eur_mwh"], 85.5)
        self.assertEqual(prices[1]["price_eur_mwh"], 90.0)

    def test_parse_generation_by_source(self):
        points = _parse_generation_xml(GENERATION_XML)
        self.assertEqual(len(points), 3)
        solar = [p for p in points if p["source"] == "B16"]
        wind = [p for p in points if p["source"] == "B19"]
        self.assertEqual(solar[0]["mw"], 1200)
        self.assertEqual(wind[0]["mw"], 4500)

    def test_normalize_prices_to_hourly_empty(self):
        self.assertEqual(_normalize_prices_to_hourly([]), [])


if __name__ == "__main__":
    unittest.main()
