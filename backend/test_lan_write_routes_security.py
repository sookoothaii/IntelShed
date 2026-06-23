"""LAN write-route auth — mutating POST endpoints require credentials when exposed."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Stub heavy optional imports before router modules load.
for _mod in (
    "followthemoney",
    "followthemoney.model",
    "sqlite_vec",
):
    sys.modules.setdefault(_mod, MagicMock())

from fastapi import FastAPI
from fastapi.testclient import TestClient

_LAN_ENV = {
    "WORLDBASE_BIND_HOST": "0.0.0.0",
    "WORLDBASE_API_KEY": "test-api-key",
    "NODE_INGEST_TOKEN": "test-node-token",
}

_WRITE_ROUTES: list[tuple[str, str, dict | None]] = [
    ("POST", "/api/entity/import", None),
    ("POST", "/api/intel/import/sanctions", None),
    ("POST", "/api/intel/feeds/run", None),
    ("POST", "/api/intel/resolution/run", None),
    ("POST", "/api/intel/resolution/reset", None),
    ("POST", "/api/intel/spatial/run", None),
    ("POST", "/api/intel/semantic/run", None),
    ("POST", "/api/intel/subgraph/export", None),
    ("POST", "/api/sanctions/refresh", None),
    ("POST", "/api/memory/index/pulse", None),
    ("POST", "/api/fusion/stage", None),
    ("POST", "/api/aircraft/trails/snapshot", None),
    ("POST", "/api/agent/publish", {"action": "noop"}),
    ("POST", "/api/agent/camera", {"lat": 13.7, "lon": 100.5, "height": 1e6}),
    ("POST", "/api/flowsint/export-investigation", {"pins": []}),
    ("POST", "/api/firewall/test", {"query": "hello"}),
]


def _app() -> FastAPI:
    import agent_bus
    import aircraft_trails
    import duckdb_fusion
    import entity_resolution
    import feed_ingest
    import firewall_bridge
    import flowsint_bridge
    import ftm_store
    import intel_graph_export
    import intel_proximity
    import intel_semantic_links
    import rag_memory
    import sanctions_bridge

    app = FastAPI()
    for mod in (
        ftm_store,
        feed_ingest,
        entity_resolution,
        intel_proximity,
        intel_semantic_links,
        intel_graph_export,
        sanctions_bridge,
        rag_memory,
        duckdb_fusion,
        aircraft_trails,
        agent_bus,
        flowsint_bridge,
        firewall_bridge,
    ):
        app.include_router(mod.router)
    return app


class LanWriteRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", _LAN_ENV, clear=False)
        self.api_key = patch("auth.security.API_KEY", "test-api-key")
        self.ingest_token = patch("auth.security.INGEST_TOKEN", "test-node-token")
        self.env.start()
        self.api_key.start()
        self.ingest_token.start()
        self.client = TestClient(_app())

    def tearDown(self):
        self.ingest_token.stop()
        self.api_key.stop()
        self.env.stop()

    def test_write_routes_reject_unauthenticated_on_lan(self):
        for method, path, body in _WRITE_ROUTES:
            with self.subTest(path=path):
                if method == "POST":
                    if body is None:
                        resp = self.client.post(path)
                    else:
                        resp = self.client.post(path, json=body)
                else:
                    resp = self.client.request(method, path, json=body)
                self.assertEqual(resp.status_code, 401, resp.text)

    def test_write_routes_accept_api_key_on_lan(self):
        patches = [
            patch("ftm_store.import_ndjson", return_value={"imported": 0}),
            patch("ftm_store.import_sanctions_csv", return_value={"imported": 0}),
            patch("feed_ingest.run_feed_ingest", new_callable=AsyncMock, return_value={"ok": True}),
            patch("entity_resolution.run_resolution", return_value={"ok": True}),
            patch("entity_resolution.ftm_store.delete_edges_for_dataset", return_value=0),
            patch("intel_proximity.link_proximity_edges", return_value={"edges_added": 0}),
            patch("intel_semantic_links.link_semantic_edges", return_value={"edges_added": 0}),
            patch(
                "intel_graph_export.export_operator_subgraph",
                return_value={"nodes": 0, "edges": 0},
            ),
            patch("rag_memory.ingest_pulse", new_callable=AsyncMock, return_value={"indexed": 0}),
            patch("duckdb_fusion.fss.stage_to_parquet", return_value={"rows": 0}),
            patch("aircraft_trails.snapshot_now", new_callable=AsyncMock, return_value={"ok": True}),
            patch("agent_bus.publish_action", new_callable=AsyncMock, return_value={"delivered": 0}),
            patch("agent_bus.agent_bus_enabled", return_value=True),
            patch("prompt_guard.slim_guard_enabled", return_value=False),
            patch("firewall_bridge.firewall_configured", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            headers = {"X-API-Key": "test-api-key"}
            cases = [
                ("POST", "/api/entity/import", b"{}"),
                ("POST", "/api/intel/import/sanctions", None),
                ("POST", "/api/intel/feeds/run", None),
                ("POST", "/api/intel/resolution/run", None),
                ("POST", "/api/intel/resolution/reset", None),
                ("POST", "/api/intel/spatial/run", None),
                ("POST", "/api/intel/semantic/run", None),
                ("POST", "/api/intel/subgraph/export", None),
                ("POST", "/api/sanctions/refresh", None),
                ("POST", "/api/memory/index/pulse", None),
                ("POST", "/api/fusion/stage", None),
                ("POST", "/api/aircraft/trails/snapshot", None),
                ("POST", "/api/agent/publish", {"action": "noop"}),
                ("POST", "/api/agent/camera", {"lat": 13.7, "lon": 100.5, "height": 1e6}),
                ("POST", "/api/flowsint/export-investigation", {"pins": []}),
                ("POST", "/api/firewall/test", {"query": "hello"}),
            ]
            for method, path, payload in cases:
                with self.subTest(path=path):
                    if isinstance(payload, dict):
                        resp = self.client.post(path, json=payload, headers=headers)
                    elif isinstance(payload, bytes):
                        resp = self.client.post(path, content=payload, headers=headers)
                    else:
                        resp = self.client.post(path, headers=headers)
                    self.assertIn(resp.status_code, (200, 202), resp.text)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_localhost_bind_skips_lan_auth(self):
        with patch.dict("os.environ", {"WORLDBASE_BIND_HOST": "127.0.0.1"}, clear=False):
            with patch("flowsint_bridge.export_investigation", new_callable=AsyncMock) as exp:
                exp.return_value = {"nodes": []}
                client = TestClient(_app())
                resp = client.post("/api/flowsint/export-investigation", json={"pins": []})
                self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
