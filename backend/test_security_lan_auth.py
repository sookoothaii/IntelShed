"""Unit tests for LAN-bound auth helpers (no live HTTP)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from auth.security import lan_auth_required, lan_exposed, verify_lan_auth
from fastapi import HTTPException, Request


class LanExposureTests(unittest.TestCase):
    def test_localhost_bind_not_exposed(self):
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "127.0.0.1"}, clear=False):
            self.assertFalse(lan_exposed())

    def test_lan_bind_exposed(self):
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "0.0.0.0"}, clear=False):
            self.assertTrue(lan_exposed())

    def test_mcp_auth_when_api_key_on_localhost(self):
        with patch.dict(
            "os.environ",
            {"WORLDBASE_BIND_HOST": "127.0.0.1"},
            clear=False,
        ):
            with patch("auth.security.API_KEY", "secret"):
                self.assertTrue(lan_auth_required())

    def test_rest_open_on_localhost_even_with_api_key(self):
        with patch.dict(
            "os.environ",
            {"WORLDBASE_BIND_HOST": "127.0.0.1"},
            clear=False,
        ):
            with patch("auth.security.API_KEY", "secret"):
                self.assertFalse(lan_exposed())


class VerifyLanAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_loopback_client_skips_auth_when_lan_exposed(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/briefing",
            "headers": [],
            "client": ("127.0.0.1", 12345),
        }
        request = Request(scope)
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "0.0.0.0"}, clear=False):
            with patch("auth.security.API_KEY", "secret"):
                with patch("auth.security.INGEST_TOKEN", "node-secret"):
                    auth = await verify_lan_auth(request, api_key=None, x_node_token=None)
        self.assertEqual(auth, "loopback")

    async def test_remote_client_requires_credentials_when_lan_exposed(self):
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/briefing",
            "headers": [],
            "client": ("192.168.1.50", 12345),
        }
        request = Request(scope)
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "0.0.0.0"}, clear=False):
            with patch("auth.security.API_KEY", "secret"):
                with patch("auth.security.INGEST_TOKEN", "node-secret"):
                    with self.assertRaises(HTTPException) as ctx:
                        await verify_lan_auth(request, api_key=None, x_node_token=None)
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
