"""Tests for feeds_extra — radar, commodities, space weather, markets."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import feeds_extra


class RadarTests(unittest.IsolatedAsyncioTestCase):
    async def test_radar_success(self):
        mock_data = {
            "host": "https://tilecache.rainviewer.net",
            "radar": {
                "past": [{"time": 1700000000, "path": "/v2/radar/1700000000"}],
                "nowcast": [{"time": 1700001000, "path": "/v2/radar/1700001000"}],
            },
            "satellite": {
                "infrared": [
                    {"time": 1700000000, "path": "/v2/satellite/infrared/1700000000"}
                ],
            },
        }
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: mock_data

        with (
            patch("feeds_extra._CACHE", {}),
            patch("feeds_extra._db_get", return_value=None),
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value = mock_client

                result = await feeds_extra.weather_radar()

        self.assertTrue(result["enabled"])
        self.assertIn("radar", result)
        self.assertIn("satellite", result)
        self.assertEqual(result["radar"]["past_count"], 1)
        self.assertIsNotNone(result["radar"]["latest_tile"])

    async def test_radar_fail_soft(self):
        with (
            patch("feeds_extra._CACHE", {}),
            patch("feeds_extra._db_get", return_value=None),
            patch("feeds_extra._db_stale", return_value=None),
        ):
            with patch("httpx.AsyncClient", side_effect=Exception("network error")):
                result = await feeds_extra.weather_radar()
        self.assertFalse(result["enabled"])
        self.assertIn("error", result)


class CommoditiesTests(unittest.IsolatedAsyncioTestCase):
    async def test_commodities_success(self):
        mock_fx = AsyncMock()
        mock_fx.status_code = 200
        mock_fx.json = lambda: {"rates": {"XAU": 0.0005, "XAG": 0.04}}

        mock_oil = AsyncMock()
        mock_oil.status_code = 200
        mock_oil.json = lambda: {"data": {"rates": {"BRENT": 0.012, "WTI": 0.013}}}

        with (
            patch("feeds_extra._CACHE", {}),
            patch("feeds_extra._db_get", return_value=None),
        ):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(side_effect=[mock_fx, mock_oil])
                mock_client_cls.return_value = mock_client

                result = await feeds_extra.commodities()

        self.assertIn("commodities", result)
        self.assertIn("gold_usd_oz", result["commodities"])
        self.assertIn("silver_usd_oz", result["commodities"])

    async def test_commodities_fail_soft(self):
        with (
            patch("feeds_extra._CACHE", {}),
            patch("feeds_extra._db_get", return_value=None),
            patch("feeds_extra._db_stale", return_value=None),
        ):
            with patch("httpx.AsyncClient", side_effect=Exception("network error")):
                result = await feeds_extra.commodities()
        self.assertIn("error", result)


class ProvenanceRadarCommoditiesTests(unittest.TestCase):
    def test_radar_reliability(self):
        import provenance

        self.assertGreaterEqual(provenance.source_reliability("radar"), 0.7)
        self.assertGreaterEqual(provenance.source_reliability("rainviewer"), 0.7)

    def test_commodities_reliability(self):
        import provenance

        self.assertGreaterEqual(provenance.source_reliability("commodities"), 0.6)

    def test_radar_connector_manifest(self):
        import connector_registry

        self.assertIn("radar", connector_registry.CONNECTOR_CATALOG)
        spec = connector_registry.CONNECTOR_CATALOG["radar"]
        self.assertEqual(spec.category, "environment")
        self.assertIn("/api/radar", spec.endpoints)

    def test_commodities_connector_manifest(self):
        import connector_registry

        self.assertIn("commodities", connector_registry.CONNECTOR_CATALOG)
        spec = connector_registry.CONNECTOR_CATALOG["commodities"]
        self.assertEqual(spec.category, "finance")
        self.assertIn("/api/commodities", spec.endpoints)


if __name__ == "__main__":
    unittest.main()
