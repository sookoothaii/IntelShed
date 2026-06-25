"""Tests for I10 — WebSocket Gateway."""

from __future__ import annotations

import asyncio
import os
import unittest


class TestWSGateway(unittest.TestCase):
    """WebSocket gateway module."""

    def test_ws_disabled_by_default(self):
        from ws_gateway import ws_enabled

        os.environ.pop("WORLDBASE_WEBSOCKET", None)
        self.assertFalse(ws_enabled())

    def test_ws_enabled_when_configured(self):
        from ws_gateway import ws_enabled

        os.environ["WORLDBASE_WEBSOCKET"] = "1"
        self.assertTrue(ws_enabled())
        os.environ.pop("WORLDBASE_WEBSOCKET", None)

    def test_ws_status_route_exists(self):
        from ws_gateway import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/ws/status", paths)
        self.assertIn("/api/ws", paths)

    def test_ws_connection_class(self):
        from ws_gateway import WSConnection
        from unittest.mock import MagicMock

        conn = WSConnection(MagicMock())
        # No bbox → all events pass
        self.assertTrue(conn.in_viewport(13.0, 100.0))
        # Set bbox
        conn.bbox = (95.0, 5.0, 105.0, 20.0)
        self.assertTrue(conn.in_viewport(13.0, 100.0))
        self.assertFalse(conn.in_viewport(50.0, 10.0))

    def test_ws_connection_layer_filter(self):
        from ws_gateway import WSConnection
        from unittest.mock import MagicMock

        conn = WSConnection(MagicMock())
        # No layers → all pass
        self.assertTrue(conn.subscribed("maritime"))
        conn.layers = {"maritime", "quakes"}
        self.assertTrue(conn.subscribed("maritime"))
        self.assertFalse(conn.subscribed("weather"))

    def test_broadcast_no_connections(self):
        from ws_gateway import broadcast_event

        result = asyncio.run(broadcast_event("test", {"foo": "bar"}))
        self.assertEqual(result, 0)

    def test_broadcast_ais_delta_empty(self):
        from ws_gateway import broadcast_ais_delta

        result = asyncio.run(broadcast_ais_delta([]))
        self.assertEqual(result, 0)

    def test_broadcast_briefing_ready(self):
        from ws_gateway import broadcast_briefing_ready

        result = asyncio.run(broadcast_briefing_ready("test-id", 0.95))
        self.assertEqual(result, 0)


class TestConfigWebSocket(unittest.TestCase):
    """Config integration."""

    def test_config_ws_default_off(self):
        os.environ.pop("WORLDBASE_WEBSOCKET", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.websocket_enabled)

    def test_config_ws_enabled(self):
        os.environ["WORLDBASE_WEBSOCKET"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.websocket_enabled)
        finally:
            os.environ.pop("WORLDBASE_WEBSOCKET", None)


if __name__ == "__main__":
    unittest.main()
