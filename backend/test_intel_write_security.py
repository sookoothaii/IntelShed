"""LAN auth on intel write routes (no GLiNER / DuckDB load)."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

# Heavy optional deps — route auth tests only need FastAPI routers.
sys.modules.setdefault("duckdb", MagicMock())
_ftm = MagicMock()
_ftm.model = MagicMock()
sys.modules.setdefault("followthemoney", _ftm)

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


class IntelWriteSecurityTests(unittest.TestCase):
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
        with patch.object(feed_ingest, "run_feed_ingest", return_value={"ok": True}):
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

    def test_resolution_reset_accepts_node_token(self):
        import entity_resolution

        app = FastAPI()
        app.include_router(entity_resolution.router)
        client = TestClient(app)
        with patch("entity_resolution.ftm_store.delete_edges_for_dataset", return_value=3):
            resp = client.post(
                "/api/intel/resolution/reset",
                headers={"X-Node-Token": "test-node-token"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_entity_import_requires_auth_on_lan(self):
        import ftm_store

        app = FastAPI()
        app.include_router(ftm_store.router)
        client = TestClient(app)
        resp = client.post("/api/entity/import", content="{}")
        self.assertEqual(resp.status_code, 401)

    def test_entity_import_accepts_api_key(self):
        import ftm_store

        app = FastAPI()
        app.include_router(ftm_store.router)
        client = TestClient(app)
        with patch("ftm_store.import_ndjson", return_value={"imported": 0}):
            resp = client.post(
                "/api/entity/import",
                content='{"id":"x"}',
                headers={"X-API-Key": "test-api-key"},
            )
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
