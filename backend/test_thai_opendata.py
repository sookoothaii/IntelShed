"""Offline unit tests for thai_opendata connector.

All HTTP calls are mocked — no network access required.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("WORLDBASE_THAI_OPENDATA", "1")

from config import get_config  # noqa: E402

get_config.cache_clear()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from thai_opendata import (  # noqa: E402
    _enrich_ftm,
    _fetch_datasets,
    _fetch_environmental,
    gather_thai_digest,
)


def _mock_ckan_response(results: list, count: int | None = None, success: bool = True):
    """Build a mock CKAN API response."""
    return {
        "success": success,
        "result": {
            "results": results,
            "count": count if count is not None else len(results),
        },
    }


def _mock_httpx(json_data: dict, status_code: int = 200):
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    r.json = MagicMock(return_value=json_data)
    return r


class TestFetchDatasets(unittest.IsolatedAsyncioTestCase):
    """Test CKAN dataset fetch."""

    async def test_fetch_success(self):
        """Should parse CKAN package_search results."""
        ckan_data = _mock_ckan_response(
            [
                {
                    "id": "pkg-1",
                    "title": "Air Quality Bangkok",
                    "name": "air-quality-bangkok",
                    "notes": "PM2.5 data for Bangkok",
                    "groups": [{"name": "environment"}],
                    "organization": {"title": "PCD", "id": "org-1"},
                    "resources": [
                        {
                            "id": "r1",
                            "name": "data.csv",
                            "format": "CSV",
                            "url": "https://data.go.th/r1",
                            "size": 1024,
                        }
                    ],
                    "metadata_created": "2024-01-01T00:00:00Z",
                    "metadata_modified": "2024-06-01T00:00:00Z",
                    "tags": [{"name": "air"}, {"name": "pollution"}],
                }
            ]
        )
        mock_resp = _mock_httpx(ckan_data)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await _fetch_datasets(group="environment", limit=10, refresh=True)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["source"], "data.go.th")
            self.assertTrue(result["configured"])
            datasets = result["datasets"]
            self.assertEqual(len(datasets), 1)
            self.assertEqual(datasets[0]["title"], "Air Quality Bangkok")
            self.assertEqual(datasets[0]["org"], "PCD")
            self.assertEqual(len(datasets[0]["resources"]), 1)
            self.assertIn("air", datasets[0]["tags"])

    async def test_fetch_error_fail_soft(self):
        """Should fail-soft on HTTP errors."""
        mock_resp = _mock_httpx({}, status_code=500)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await _fetch_datasets(limit=5, refresh=True)
            self.assertEqual(result["count"], 0)
            self.assertIsNotNone(result.get("error"))

    async def test_fetch_ckan_error(self):
        """Should handle CKAN success=false."""
        ckan_data = {"success": False, "error": {"message": "Bad group"}}
        mock_resp = _mock_httpx(ckan_data)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await _fetch_datasets(group="badgroup", limit=5, refresh=True)
            self.assertEqual(result["count"], 0)
            self.assertIsNotNone(result.get("error"))


class TestFetchEnvironmental(unittest.IsolatedAsyncioTestCase):
    """Test environmental dataset fetch with geo-coding."""

    async def test_geocoding_from_title(self):
        """Should geo-code datasets based on city names in title."""
        ckan_data = _mock_ckan_response(
            [
                {
                    "id": "env-1",
                    "title": "AQI Bangkok Station",
                    "notes": "Air quality monitoring Bangkok",
                    "tags": [{"name": "aqi"}, {"name": "pm25"}],
                    "metadata_modified": "2024-06-01T00:00:00Z",
                    "resources": [{"id": "r1"}],
                },
                {
                    "id": "env-2",
                    "title": "Water Quality Chiang Mai",
                    "notes": "River monitoring",
                    "tags": [{"name": "water"}],
                    "metadata_modified": "2024-06-02T00:00:00Z",
                    "resources": [],
                },
                {
                    "id": "env-3",
                    "title": "Unknown Station Data",
                    "notes": "No city mentioned",
                    "tags": [],
                    "metadata_modified": "2024-06-03T00:00:00Z",
                    "resources": [],
                },
            ]
        )
        mock_resp = _mock_httpx(ckan_data)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await _fetch_environmental(limit=10, refresh=True)
            self.assertEqual(result["count"], 3)
            stations = result["stations"]
            # Bangkok should be geo-coded
            self.assertIsNotNone(stations[0]["lat"])
            self.assertAlmostEqual(stations[0]["lat"], 13.7563, places=3)
            # Chiang Mai should be geo-coded
            self.assertIsNotNone(stations[1]["lat"])
            self.assertAlmostEqual(stations[1]["lat"], 18.7883, places=3)
            # Unknown should not be geo-coded
            self.assertIsNone(stations[2]["lat"])
            self.assertGreaterEqual(result["geocoded"], 2)

    async def test_environmental_error(self):
        """Should fail-soft on network error."""
        mock_resp = _mock_httpx({}, status_code=503)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await _fetch_environmental(limit=5, refresh=True)
            self.assertEqual(result["count"], 0)
            self.assertIsNotNone(result.get("error"))


class TestFtmEnrichment(unittest.TestCase):
    """Test FtM Event entity creation."""

    def test_enrich_creates_events(self):
        """Should create FtM Event entities for geo-coded stations."""
        stations = [
            {
                "id": "s1",
                "title": "AQI Bangkok",
                "notes": "Air quality",
                "lat": 13.75,
                "lon": 100.50,
                "modified": "2024-01-01",
            },
            {
                "id": "s2",
                "title": "No Geo",
                "notes": "Unknown",
                "lat": None,
                "lon": None,
                "modified": "2024-01-02",
            },
        ]
        with patch("entity_store.upsert_entity") as mock_upsert:
            result = _enrich_ftm(stations)
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["ids"], ["thai-env-s1"])
            self.assertIsNone(result["error"])
            mock_upsert.assert_called_once()

    def test_enrich_fail_soft(self):
        """Should fail-soft on import errors."""
        stations = [{"id": "s1", "title": "Test", "lat": 13.0, "lon": 100.0}]
        with patch("builtins.__import__", side_effect=ImportError("no entity_store")):
            result = _enrich_ftm(stations)
            self.assertEqual(result["count"], 0)
            self.assertIsNotNone(result["error"])

    def test_enrich_skips_no_geo(self):
        """Should skip stations without geo-coordinates."""
        stations = [
            {"id": "s1", "title": "No Geo", "lat": None, "lon": None},
        ]
        with patch("entity_store.upsert_entity") as mock_upsert:
            result = _enrich_ftm(stations)
            self.assertEqual(result["count"], 0)
            mock_upsert.assert_not_called()


class TestEndpoints(unittest.TestCase):
    """API endpoint validation."""

    def _client(self):
        import thai_opendata as mod

        app = FastAPI()
        app.include_router(mod.router)
        return TestClient(app)

    def test_disabled_returns_error(self):
        """Should return error when disabled."""
        with patch.dict(os.environ, {"WORLDBASE_THAI_OPENDATA": "0"}):
            get_config.cache_clear()
            client = self._client()
            resp = client.get("/api/thai/opendata")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertFalse(data["configured"])
            self.assertIn("disabled", data["error"])
        get_config.cache_clear()

    def test_opendata_endpoint(self):
        """Should return datasets when enabled."""
        with patch.dict(os.environ, {"WORLDBASE_THAI_OPENDATA": "1"}):
            get_config.cache_clear()
            ckan_data = _mock_ckan_response(
                [
                    {
                        "id": "p1",
                        "title": "Test",
                        "name": "test",
                        "notes": "",
                        "groups": [],
                        "organization": {},
                        "resources": [],
                        "tags": [],
                    }
                ]
            )
            mock_resp = _mock_httpx(ckan_data)
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                client = self._client()
                resp = client.get("/api/thai/opendata?limit=5&refresh=true")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data["configured"])
                self.assertEqual(data["count"], 1)
            get_config.cache_clear()

    def test_environmental_endpoint(self):
        """Should return environmental stations when enabled."""
        with patch.dict(os.environ, {"WORLDBASE_THAI_OPENDATA": "1"}):
            get_config.cache_clear()
            ckan_data = _mock_ckan_response(
                [
                    {
                        "id": "e1",
                        "title": "Bangkok AQI",
                        "notes": "Air quality Bangkok",
                        "tags": [{"name": "aqi"}],
                        "metadata_modified": "2024-01-01",
                        "resources": [],
                    }
                ]
            )
            mock_resp = _mock_httpx(ckan_data)
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                client = self._client()
                resp = client.get("/api/thai/environmental?limit=5&refresh=true")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data["configured"])
                self.assertEqual(data["count"], 1)
                self.assertIsNotNone(data["stations"][0]["lat"])
            get_config.cache_clear()


class TestThaiDigest(unittest.IsolatedAsyncioTestCase):
    """Briefing digest for Thai open data."""

    async def test_digest_disabled_by_default(self):
        """gather_thai_digest should return disabled when briefing_thai is off."""
        with patch.dict(
            os.environ, {"WORLDBASE_BRIEFING_THAI": "0", "WORLDBASE_THAI_OPENDATA": "1"}
        ):
            get_config.cache_clear()
            result = await gather_thai_digest()
            self.assertFalse(result["enabled"])
        get_config.cache_clear()

    async def test_digest_enabled(self):
        """gather_thai_digest should return lines when enabled."""
        with patch.dict(
            os.environ, {"WORLDBASE_BRIEFING_THAI": "1", "WORLDBASE_THAI_OPENDATA": "1"}
        ):
            get_config.cache_clear()
            ckan_data = _mock_ckan_response(
                [
                    {
                        "id": "e1",
                        "title": "Bangkok AQI",
                        "notes": "Air quality Bangkok",
                        "tags": [{"name": "aqi"}],
                        "metadata_modified": "2024-01-01",
                        "resources": [],
                    }
                ]
            )
            mock_resp = _mock_httpx(ckan_data)
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(return_value=mock_resp)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client_cls.return_value = mock_client

                result = await gather_thai_digest()
                self.assertTrue(result["enabled"])
                self.assertGreaterEqual(result["count"], 1)
                joined = "\n".join(result["lines"])
                self.assertIn("Bangkok", joined)
            get_config.cache_clear()

    async def test_digest_fail_soft(self):
        """gather_thai_digest should fail-soft on errors."""
        with patch.dict(
            os.environ, {"WORLDBASE_BRIEFING_THAI": "1", "WORLDBASE_THAI_OPENDATA": "1"}
        ):
            get_config.cache_clear()
            with patch(
                "thai_opendata._fetch_environmental", side_effect=RuntimeError("boom")
            ):
                result = await gather_thai_digest()
                self.assertFalse(result["enabled"])
            get_config.cache_clear()


if __name__ == "__main__":
    unittest.main()
