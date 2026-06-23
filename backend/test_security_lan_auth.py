"""Unit tests for LAN-bound auth helpers (no live HTTP)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from auth.security import (
    lan_auth_required,
    lan_exposed,
    mcp_request_authorized,
)


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


class MCPAuthHeaderTests(unittest.TestCase):
    def test_empty_api_key_rejected_on_lan(self):
        with patch("auth.security.API_KEY", ""):
            with patch("auth.security.INGEST_TOKEN", ""):
                with patch("auth.security.lan_auth_required", return_value=True):
                    self.assertFalse(mcp_request_authorized({"x-api-key": ""}))

    def test_valid_api_key_accepted(self):
        with patch("auth.security.API_KEY", "secret"):
            with patch("auth.security.lan_auth_required", return_value=True):
                self.assertTrue(mcp_request_authorized({"x-api-key": "secret"}))

    def test_valid_node_token_accepted(self):
        with patch("auth.security.API_KEY", ""):
            with patch("auth.security.INGEST_TOKEN", "node-secret"):
                with patch("auth.security.lan_auth_required", return_value=True):
                    self.assertTrue(mcp_request_authorized({"x-node-token": "node-secret"}))


if __name__ == "__main__":
    unittest.main()
