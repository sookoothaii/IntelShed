"""LAN write-route auth — mutating POST endpoints gated when LAN-exposed."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _lan_env():
    return patch.dict(
        "os.environ",
        {
            "WORLDBASE_BIND_HOST": "0.0.0.0",
            "WORLDBASE_API_KEY": "test-api-key",
            "NODE_INGEST_TOKEN": "test-node-token",
        },
        clear=False,
    )


class LanWriteRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = _lan_env()
        self.env.start()
        self.api_key = patch("auth.security.API_KEY", "test-api-key")
        self.ingest_token = patch("auth.security.INGEST_TOKEN", "test-node-token")
        self.api_key.start()
        self.ingest_token.start()

    def tearDown(self):
        self.ingest_token.stop()
        self.api_key.stop()
        self.env.stop()

    def test_feeds_run_requires_auth_on_lan(self):
        import feed_ingest

        app = FastAPI()
        app.include_router(feed_ingest.router)
        client = TestClient(app)
        resp = client.post("/api/intel/feeds/run")
        self.assertEqual(resp.status_code, 401)

    def test_feeds_run_accepts_api_key(self):
        import feed_ingest

        app = FastAPI()
        app.include_router(feed_ingest.router)
        client = TestClient(app)
        with patch("feed_ingest.run_feed_ingest", return_value={"ok": True}):
            resp = client.post(
                "/api/intel/feeds/run",
                headers={"X-API-Key": "test-api-key"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_resolution_reset_requires_auth_on_lan(self):
        import entity_resolution

        app = FastAPI()
        app.include_router(entity_resolution.router)
        client = TestClient(app)
        resp = client.post("/api/intel/resolution/reset")
        self.assertEqual(resp.status_code, 401)

    def test_entity_import_requires_auth_on_lan(self):
        import ftm_store

        app = FastAPI()
        app.include_router(ftm_store.router)
        client = TestClient(app)
        resp = client.post("/api/entity/import", content='{"id":"x"}')
        self.assertEqual(resp.status_code, 401)

    def test_entity_import_accepts_node_token(self):
        import ftm_store

        app = FastAPI()
        app.include_router(ftm_store.router)
        client = TestClient(app)
        with patch("ftm_store.import_ndjson", return_value={"imported": 0}):
            resp = client.post(
                "/api/entity/import",
                content='{"id":"x"}',
                headers={"X-Node-Token": "test-node-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_sanctions_refresh_requires_auth_on_lan(self):
        import sanctions_bridge

        app = FastAPI()
        app.include_router(sanctions_bridge.router)
        client = TestClient(app)
        resp = client.post("/api/sanctions/refresh")
        self.assertEqual(resp.status_code, 401)

    def test_agent_camera_requires_auth_on_lan(self):
        import agent_bus

        app = FastAPI()
        app.include_router(agent_bus.router)
        client = TestClient(app)
        resp = client.post("/api/agent/camera", json={"lat": 0, "lon": 0, "height": 1000})
        self.assertEqual(resp.status_code, 401)


class LanWriteRouteLocalhostTests(unittest.TestCase):
    def test_feeds_run_open_on_localhost(self):
        import feed_ingest

        app = FastAPI()
        app.include_router(feed_ingest.router)
        client = TestClient(app)
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "127.0.0.1"}, clear=False):
            with patch("auth.security.API_KEY", "test-api-key"):
                with patch("feed_ingest.run_feed_ingest", return_value={"ok": True}):
                    resp = client.post("/api/intel/feeds/run")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
