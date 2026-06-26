"""Offline unit tests for domain_intel bridge (P10).

All tests are offline — no network, no live API.
HTTP calls are mocked via unittest.mock.patch on httpx.AsyncClient.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("WORLDBASE_DOMAIN_INTEL", "1")

from domain_intel import (
    _domain_cache_get,
    _domain_cache_set,
    _enabled,
    _fetch_crt_sh,
    _fetch_rdap,
    _fetch_wayback,
    _gather_domain_intel,
)


def _mock_response(*, status_code=200, json_data=None, text=None):
    """Build a mock httpx.Response."""
    r = MagicMock()
    r.status_code = status_code
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    if json_data is not None:
        r.json.return_value = json_data
    if text is not None:
        r.text = text
    r.content = json.dumps(json_data).encode() if json_data else b""
    return r


class TestEnvHelpers(unittest.TestCase):
    """Environment variable helpers."""

    def test_enabled_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_DOMAIN_INTEL", None)
            self.assertTrue(_enabled())

    def test_disabled(self):
        with patch.dict(os.environ, {"WORLDBASE_DOMAIN_INTEL": "0"}):
            self.assertFalse(_enabled())


class TestCrtSh(unittest.IsolatedAsyncioTestCase):
    """crt.sh CT log fetching."""

    async def test_fetch_crt_sh_success(self):
        mock_data = [
            {
                "id": 12345,
                "ca": {"name": "Let's Encrypt"},
                "common_name": "example.com",
                "name_value": "example.com\nwww.example.com\napi.example.com",
                "not_before": "2024-01-01T00:00:00",
                "not_after": "2024-04-01T00:00:00",
            },
            {
                "id": 12346,
                "ca": {"name": "DigiCert"},
                "common_name": "example.com",
                "name_value": "example.com\nwww.example.com",
                "not_before": "2024-02-01T00:00:00",
                "not_after": "2025-02-01T00:00:00",
            },
        ]
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=mock_data))
        result = await _fetch_crt_sh("example.com", client)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["count"], 2)
        self.assertIn("example.com", result["unique_subdomains"])
        self.assertIn("www.example.com", result["unique_subdomains"])
        self.assertIn("api.example.com", result["unique_subdomains"])
        self.assertEqual(result["subdomain_count"], 3)

    async def test_fetch_crt_sh_dedup(self):
        """Duplicate common_name + name_value should be deduplicated."""
        mock_data = [
            {
                "id": 1,
                "ca": {"name": "CA1"},
                "common_name": "example.com",
                "name_value": "example.com\nwww.example.com",
                "not_before": "2024-01-01",
                "not_after": "2024-04-01",
            },
            {
                "id": 2,
                "ca": {"name": "CA2"},
                "common_name": "example.com",
                "name_value": "example.com\nwww.example.com",
                "not_before": "2024-02-01",
                "not_after": "2024-05-01",
            },
        ]
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=mock_data))
        result = await _fetch_crt_sh("example.com", client)
        self.assertEqual(result["count"], 1)  # Deduplicated

    async def test_fetch_crt_sh_error(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(status_code=500))
        result = await _fetch_crt_sh("example.com", client)
        self.assertFalse(result["enabled"])
        self.assertEqual(result["count"], 0)
        self.assertIsNotNone(result["error"])

    async def test_fetch_crt_sh_empty(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=[]))
        result = await _fetch_crt_sh("example.com", client)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["count"], 0)


class TestWayback(unittest.IsolatedAsyncioTestCase):
    """Wayback CDX fetching."""

    async def test_fetch_wayback_success(self):
        mock_data = [
            ["timestamp", "original", "statuscode", "mimetype"],
            ["20200615123456", "https://example.com/", "200", "text/html"],
            ["20210620120000", "https://example.com/about", "301", "text/html"],
        ]
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=mock_data))
        result = await _fetch_wayback("example.com", client, limit=50)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["snapshots"][0]["timestamp"], "2020-06-15T12:34:56Z")
        self.assertEqual(result["snapshots"][1]["timestamp"], "2021-06-20T12:00:00Z")
        self.assertEqual(result["first_seen"], "2020-06-15T12:34:56Z")
        self.assertEqual(result["last_seen"], "2021-06-20T12:00:00Z")

    async def test_fetch_wayback_empty(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=[]))
        result = await _fetch_wayback("example.com", client)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["count"], 0)

    async def test_fetch_wayback_error(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(status_code=503))
        result = await _fetch_wayback("example.com", client)
        self.assertFalse(result["enabled"])
        self.assertIsNotNone(result["error"])


class TestRdap(unittest.IsolatedAsyncioTestCase):
    """RDAP domain registration fetching."""

    async def test_fetch_rdap_success(self):
        mock_data = {
            "ldhName": "EXAMPLE.COM",
            "events": [
                {"eventAction": "registration", "eventDate": "2010-01-01T00:00:00Z"},
                {"eventAction": "expiration", "eventDate": "2025-01-01T00:00:00Z"},
                {"eventAction": "last changed", "eventDate": "2024-06-01T00:00:00Z"},
            ],
            "entities": [
                {
                    "roles": ["registrar"],
                    "handle": "REG1",
                    "vcardArray": [
                        "vcard",
                        [["fn", {}, "text", "Example Registrar Inc"]],
                    ],
                },
                {
                    "roles": ["registrant"],
                    "handle": "REG2",
                    "vcardArray": ["vcard", [["fn", {}, "text", "John Doe"]]],
                },
            ],
            "nameservers": [
                {"ldhName": "NS1.EXAMPLE.COM"},
                {"ldhName": "NS2.EXAMPLE.COM"},
            ],
            "status": ["client transfer prohibited", "server delete prohibited"],
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(json_data=mock_data))
        result = await _fetch_rdap("example.com", client)
        self.assertTrue(result["enabled"])
        self.assertTrue(result["registered"])
        self.assertEqual(result["registrar"], "Example Registrar Inc")
        self.assertEqual(result["registrant"], "John Doe")
        self.assertEqual(result["registration_date"], "2010-01-01T00:00:00Z")
        self.assertEqual(result["expiration_date"], "2025-01-01T00:00:00Z")
        self.assertIn("NS1.EXAMPLE.COM", result["nameservers"])
        self.assertEqual(len(result["status"]), 2)

    async def test_fetch_rdap_not_found(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(status_code=404))
        result = await _fetch_rdap("nonexistent.example", client)
        self.assertTrue(result["enabled"])
        self.assertFalse(result["registered"])

    async def test_fetch_rdap_error(self):
        client = MagicMock()
        client.get = AsyncMock(return_value=_mock_response(status_code=503))
        result = await _fetch_rdap("example.com", client)
        self.assertFalse(result["enabled"])
        self.assertIsNotNone(result["error"])


class TestGatherDomainIntel(unittest.IsolatedAsyncioTestCase):
    """Combined intel gathering with parallel fetch."""

    async def test_gather_all_sources(self):
        with patch(
            "domain_intel._fetch_crt_sh", new_callable=AsyncMock
        ) as mock_crt, patch(
            "domain_intel._fetch_wayback", new_callable=AsyncMock
        ) as mock_wb, patch(
            "domain_intel._fetch_rdap", new_callable=AsyncMock
        ) as mock_rdap:
            mock_crt.return_value = {
                "enabled": True,
                "count": 5,
                "certificates": [],
                "unique_subdomains": ["a.example.com", "b.example.com"],
                "subdomain_count": 2,
                "error": None,
            }
            mock_wb.return_value = {
                "enabled": True,
                "count": 10,
                "snapshots": [],
                "first_seen": "2020-01-01T00:00:00Z",
                "last_seen": "2024-06-01T00:00:00Z",
                "error": None,
            }
            mock_rdap.return_value = {
                "enabled": True,
                "registered": True,
                "registrar": "Test Registrar",
                "error": None,
            }

            result = await _gather_domain_intel("example.com")
            self.assertEqual(result["domain"], "example.com")
            self.assertEqual(result["summary"]["subdomains_found"], 2)
            self.assertEqual(result["summary"]["wayback_snapshots"], 10)
            self.assertTrue(result["summary"]["registered"])
            self.assertEqual(result["summary"]["registrar"], "Test Registrar")
            self.assertEqual(result["summary"]["first_seen"], "2020-01-01T00:00:00Z")

    async def test_gather_partial_failure(self):
        """One source failing should not break the others."""
        with patch(
            "domain_intel._fetch_crt_sh", new_callable=AsyncMock
        ) as mock_crt, patch(
            "domain_intel._fetch_wayback", new_callable=AsyncMock
        ) as mock_wb, patch(
            "domain_intel._fetch_rdap", new_callable=AsyncMock
        ) as mock_rdap:
            mock_crt.return_value = {"enabled": False, "error": "timeout", "count": 0}
            mock_wb.return_value = {
                "enabled": True,
                "count": 3,
                "snapshots": [],
                "first_seen": None,
                "last_seen": None,
                "error": None,
            }
            mock_rdap.return_value = {
                "enabled": True,
                "registered": True,
                "error": None,
            }

            result = await _gather_domain_intel("example.com")
            self.assertFalse(result["certs"]["enabled"])
            self.assertTrue(result["wayback"]["enabled"])
            self.assertTrue(result["rdap"]["enabled"])
            self.assertEqual(result["summary"]["subdomains_found"], 0)
            self.assertEqual(result["summary"]["wayback_snapshots"], 3)


class TestDomainCache(unittest.TestCase):
    """Module-local domain cache."""

    def test_cache_set_get(self):
        _domain_cache_set("test.com", {"domain": "test.com", "cached": True})
        result = _domain_cache_get("test.com")
        self.assertIsNotNone(result)
        self.assertEqual(result["domain"], "test.com")

    def test_cache_miss(self):
        result = _domain_cache_get("nonexistent.com")
        self.assertIsNone(result)

    def test_cache_keyed_separately(self):
        _domain_cache_set("certs:a.com", {"type": "certs"})
        _domain_cache_set("rdap:a.com", {"type": "rdap"})
        self.assertEqual(_domain_cache_get("certs:a.com")["type"], "certs")
        self.assertEqual(_domain_cache_get("rdap:a.com")["type"], "rdap")


class TestEndpointValidation(unittest.IsolatedAsyncioTestCase):
    """Endpoint input validation via TestClient."""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import domain_intel

        app = FastAPI()
        app.include_router(domain_intel.router)
        return TestClient(app)

    def test_invalid_domain_no_dot(self):
        client = self._client()
        resp = client.get("/api/domain/intel", params={"domain": "invalid"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("error", data)
        self.assertEqual(data["count"], 0)

    def test_invalid_domain_empty(self):
        client = self._client()
        resp = client.get("/api/domain/intel", params={"domain": ""})
        data = resp.json()
        # Empty string passes Query validation but fails our domain check
        self.assertIn("error", data)

    def test_disabled_returns_error(self):
        with patch.dict(os.environ, {"WORLDBASE_DOMAIN_INTEL": "0"}):
            client = self._client()
            resp = client.get("/api/domain/intel", params={"domain": "example.com"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
