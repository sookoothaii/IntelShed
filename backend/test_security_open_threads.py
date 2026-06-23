"""Security regressions for Slack open-thread findings (2026-06-23)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import chat_routing as cr
from routes.core_feeds import _normalize_satellite_group, _tle_disk_path


class ProviderUrlGuardTests(unittest.TestCase):
    def test_allows_loopback_proxy(self):
        self.assertEqual(
            cr.validate_provider_base_url("http://127.0.0.1:8080/v1"),
            "http://127.0.0.1:8080/v1",
        )

    def test_blocks_metadata_ip(self):
        with self.assertRaises(cr.UnsafeProviderUrl):
            cr.validate_provider_base_url("http://169.254.169.254/latest/meta-data")

    def test_blocks_private_lan(self):
        with self.assertRaises(cr.UnsafeProviderUrl):
            cr.validate_provider_base_url("https://192.168.1.1/v1")

    def test_blocks_http_public_host(self):
        with self.assertRaises(cr.UnsafeProviderUrl):
            cr.validate_provider_base_url("http://evil.example/v1")

    def test_hud_override_rejects_private_before_env(self):
        with self.assertRaises(cr.UnsafeProviderUrl):
            cr.select_base_url(
                "openai",
                {"openai": "http://192.168.1.50/v1"},
                "https://operator-proxy.local/v1",
                cr.DEFAULT_BASE_URLS["openai"],
            )

    def test_env_base_not_validated(self):
        url = cr.select_base_url(
            "openai",
            None,
            "https://operator-proxy.local/v1",
            cr.DEFAULT_BASE_URLS["openai"],
        )
        self.assertEqual(url, "https://operator-proxy.local/v1")


class SatelliteGroupGuardTests(unittest.TestCase):
    def test_valid_groups(self):
        for g in ("starlink", "gps-ops", "active", "weather"):
            self.assertEqual(_normalize_satellite_group(g), g)

    def test_rejects_path_traversal(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            _normalize_satellite_group("../../etc/passwd")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_disk_path_stays_in_tle_dir(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tle_dir:
            path = _tle_disk_path(tle_dir, "starlink")
            self.assertTrue(path.startswith(os.path.realpath(tle_dir)))


class NodeRouteSecurityTests(unittest.TestCase):
    def _node_client(self) -> TestClient:
        import node_sync

        app = FastAPI()
        app.include_router(node_sync.router)
        return TestClient(app)

    def test_list_nodes_requires_auth_on_lan(self):
        client = self._node_client()
        with patch.dict(
            "os.environ",
            {"WORLDBASE_BIND_HOST": "0.0.0.0", "WORLDBASE_API_KEY": "test-api-key"},
            clear=False,
        ):
            with patch("auth.security.API_KEY", "test-api-key"):
                resp = client.get("/api/nodes")
        self.assertEqual(resp.status_code, 401)

    def test_list_nodes_accepts_api_key_on_lan(self):
        import node_sync

        node_sync.init_node_db()
        client = self._node_client()
        with patch.dict(
            "os.environ",
            {"WORLDBASE_BIND_HOST": "0.0.0.0", "WORLDBASE_API_KEY": "test-api-key"},
            clear=False,
        ):
            with patch("auth.security.API_KEY", "test-api-key"):
                resp = client.get("/api/nodes", headers={"X-API-Key": "test-api-key"})
        self.assertEqual(resp.status_code, 200)

    def test_ingest_rejects_unsigned_on_lan_without_token_env(self):
        client = self._node_client()
        body = json.dumps({"node_id": "probe"}).encode()
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "0.0.0.0"}, clear=False):
            with patch("auth.security.INGEST_TOKEN", ""):
                with patch("node_sync.INGEST_TOKEN", ""):
                    resp = client.post(
                        "/api/node/ingest",
                        content=body,
                        headers={"Content-Type": "application/json"},
                    )
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
