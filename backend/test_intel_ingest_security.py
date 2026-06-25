"""Intel ingest auth and upload limits (no GLiNER load)."""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client() -> TestClient:
    import intel_ingest

    app = FastAPI()
    app.include_router(intel_ingest.router)
    return TestClient(app)


class IntelIngestSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            "os.environ",
            {
                "WORLDBASE_BIND_HOST": "0.0.0.0",
                "WORLDBASE_API_KEY": "test-api-key",
                "NODE_INGEST_TOKEN": "test-node-token",
            },
            clear=False,
        )
        self.env.start()
        self.api_key = patch("auth.security.API_KEY", "test-api-key")
        self.ingest_token = patch("auth.security.INGEST_TOKEN", "test-node-token")
        self.api_key.start()
        self.ingest_token.start()

    def tearDown(self):
        self.ingest_token.stop()
        self.api_key.stop()
        self.env.stop()

    def test_status_open_without_auth(self):
        client = _client()
        resp = client.get("/api/intel/ingest/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("loaded", resp.json())

    def test_text_requires_auth_on_lan(self):
        import intel_ingest
        from auth.security import verify_lan_auth
        from fastapi import HTTPException

        app = FastAPI()
        app.include_router(intel_ingest.router)

        async def _reject():
            raise HTTPException(status_code=401, detail="auth required")

        app.dependency_overrides[verify_lan_auth] = _reject
        client = TestClient(app)
        resp = client.post("/api/intel/ingest/text", json={"text": "probe"})
        self.assertEqual(resp.status_code, 401)

    def test_text_rejects_empty_payload(self):
        client = _client()
        resp = client.post(
            "/api/intel/ingest/text",
            json={"text": "   "},
            headers={"X-API-Key": "test-api-key"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_text_accepts_api_key(self):
        client = _client()
        fake = {
            "ok": True,
            "counts": {"entities": 1, "edges": 0, "mentions": 1, "relations": 0},
        }
        with patch("intel_ingest._to_thread", return_value=fake):
            resp = client.post(
                "/api/intel/ingest/text",
                json={"text": "Bangkok Thailand"},
                headers={"X-API-Key": "test-api-key"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_text_accepts_node_token(self):
        client = _client()
        fake = {
            "ok": True,
            "counts": {"entities": 1, "edges": 0, "mentions": 1, "relations": 0},
        }
        with patch("intel_ingest._to_thread", return_value=fake):
            resp = client.post(
                "/api/intel/ingest/text",
                json={"text": "Bangkok Thailand"},
                headers={"X-Node-Token": "test-node-token"},
            )
        self.assertEqual(resp.status_code, 200)

    def test_document_rejects_oversized_upload(self):
        client = _client()
        big = b"x" * (10 * 1024 * 1024 + 1)
        resp = client.post(
            "/api/intel/ingest/document",
            files={"file": ("big.bin", io.BytesIO(big), "application/octet-stream")},
            data={"dataset": "test"},
            headers={"X-API-Key": "test-api-key"},
        )
        self.assertEqual(resp.status_code, 413)
        self.assertIn("10485760", resp.json()["detail"])


class CommandHistorySecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_history_requires_admin_on_lan(self):
        from node_sync import command_history
        from fastapi import HTTPException, Request

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/node/offgrid-pi/command-history",
            "headers": [],
        }
        request = Request(scope)

        with patch.dict(
            "os.environ",
            {
                "WORLDBASE_BIND_HOST": "0.0.0.0",
                "NODE_ADMIN_TOKEN": "admin-secret",
            },
            clear=False,
        ):
            with patch("node_sync.lan_exposed", return_value=True):
                with self.assertRaises(HTTPException) as ctx:
                    await command_history(request, node_id="offgrid-pi", limit=5)
                self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
