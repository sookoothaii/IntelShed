"""Unit tests for Agent Bus (no SSE transport)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

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
                await publish_action(AgentPublishBody(action="fly_to", lat=1.0, lon=2.0))
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


if __name__ == "__main__":
    unittest.main()
