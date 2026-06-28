"""Unit tests for Agent Bus (no SSE transport)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import agent_bus
from agent_bus import (
    GLOBE_LAYER_KEYS,
    AgentPublishBody,
    agent_bus_enabled,
    get_camera_state,
    publish_action,
    publish_fly_to,
    publish_toggle_layer,
)
from fastapi import HTTPException


def _fake_request(host: str = "127.0.0.1", headers: dict | None = None):
    class _Client:
        def __init__(self, h):
            self.host = h

    class _Req:
        def __init__(self, h, hdrs):
            self.client = _Client(h)
            self.headers = hdrs or {}

    return _Req(host, headers)


class AgentBusConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict("os.environ", {"WORLDBASE_AGENT_BUS": "0"}, clear=False):
            self.assertFalse(agent_bus_enabled())

    def test_enabled_when_set(self):
        with patch.dict("os.environ", {"WORLDBASE_AGENT_BUS": "1"}, clear=False):
            self.assertTrue(agent_bus_enabled())


class AgentBusPublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_fly_to_broadcasts(self):
        with patch("agent_bus.agent_bus_enabled", return_value=True):
            out = await publish_fly_to(lat=13.75, lon=100.5, title="Bangkok")
        self.assertTrue(out["ok"])
        self.assertEqual(out["message"]["action"], "fly_to")
        self.assertEqual(out["message"]["title"], "Bangkok")

    async def test_toggle_layer_validates(self):
        with patch("agent_bus.agent_bus_enabled", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await publish_toggle_layer(layer="not_a_layer")
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_toggle_known_layer(self):
        with patch("agent_bus.agent_bus_enabled", return_value=True):
            out = await publish_toggle_layer(layer="aircraft", enabled=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["message"]["layer"], "aircraft")
        self.assertTrue(out["message"]["enabled"])

    async def test_disabled_returns_503(self):
        with patch("agent_bus.agent_bus_enabled", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                await publish_action(
                    AgentPublishBody(action="fly_to", lat=1.0, lon=2.0)
                )
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_fly_to_requires_coords(self):
        with patch("agent_bus.agent_bus_enabled", return_value=True):
            with self.assertRaises(HTTPException) as ctx:
                await publish_action(AgentPublishBody(action="fly_to"))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_layer_keys_include_core_feeds(self):
        for key in ("aircraft", "quakes", "wildfires", "nodes"):
            self.assertIn(key, GLOBE_LAYER_KEYS)


class AgentBusCameraTests(unittest.TestCase):
    def test_camera_empty_by_default(self):
        self.assertEqual(get_camera_state(), {})


class AgentStreamAuthTests(unittest.TestCase):
    """_verify_stream_auth aligns with the HUD verify_lan_auth philosophy."""

    def test_open_when_no_api_key(self):
        with patch.object(agent_bus, "API_KEY", ""):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                # No raise.
                agent_bus._verify_stream_auth(_fake_request(host="9.9.9.9"))

    def test_open_on_default_dev_loopback_bind(self):
        # API_KEY set, but not LAN-exposed (default PC dev) → HUD stays open.
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=False):
                agent_bus._verify_stream_auth(_fake_request(host="127.0.0.1"))

    def test_lan_exposed_loopback_client_open(self):
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                agent_bus._verify_stream_auth(_fake_request(host="127.0.0.1"))

    def test_lan_exposed_remote_without_key_rejected(self):
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                with self.assertRaises(HTTPException) as ctx:
                    agent_bus._verify_stream_auth(_fake_request(host="10.0.0.5"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_lan_exposed_remote_with_header_key_open(self):
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                agent_bus._verify_stream_auth(
                    _fake_request(host="10.0.0.5", headers={"x-api-key": "secret"})
                )

    def test_lan_exposed_remote_with_token_query_open(self):
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                agent_bus._verify_stream_auth(
                    _fake_request(host="10.0.0.5"), token="secret"
                )

    def test_lan_exposed_remote_wrong_key_rejected(self):
        with patch.object(agent_bus, "API_KEY", "secret"):
            with patch.object(agent_bus, "lan_exposed", return_value=True):
                with self.assertRaises(HTTPException) as ctx:
                    agent_bus._verify_stream_auth(
                        _fake_request(host="10.0.0.5", headers={"x-api-key": "wrong"})
                    )
        self.assertEqual(ctx.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
