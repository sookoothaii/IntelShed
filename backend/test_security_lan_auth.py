"""Unit tests for LAN-bound auth helpers (no live HTTP)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from auth.security import lan_auth_required, lan_exposed


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


if __name__ == "__main__":
    unittest.main()
