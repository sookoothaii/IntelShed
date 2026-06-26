"""Unit tests for the OpenAI-compatible WorldBase tool loop (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import chat_tools


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Async context-manager stand-in for httpx.AsyncClient (non-stream path)."""

    def __init__(self, responses: list[dict]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):  # noqa: A002 - mirror httpx signature
        self.calls.append({"url": url, "json": json})
        return _FakeResp(self._responses.pop(0))


class OpenAIToolLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_then_final_answer(self):
        responses = [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "focus_globe",
                                        "arguments": '{"lat": 13.75, "lon": 100.5, "title": "Bangkok"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "Focused on Bangkok."}}
                ]
            },
        ]
        fake = _FakeClient(responses)

        with (
            patch("chat_tools.httpx.AsyncClient", return_value=fake),
            patch(
                "chat_tools.execute_tool",
                new=AsyncMock(
                    return_value={
                        "tool": "focus_globe",
                        "result": {"ok": True},
                        "client_action": {
                            "type": "focus_globe",
                            "lat": 13.75,
                            "lon": 100.5,
                        },
                    }
                ),
            ) as exec_mock,
        ):
            final_msgs, actions = await chat_tools.run_openai_with_tools(
                "https://api.test/v1/chat/completions",
                {"Authorization": "Bearer x"},
                "gpt-4o",
                [{"role": "user", "content": "focus bangkok"}],
                max_rounds=4,
            )

        exec_mock.assert_awaited_once()
        self.assertEqual(final_msgs[-1]["content"], "Focused on Bangkok.")
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["type"], "focus_globe")
        # Second request must carry the tool result with matching tool_call_id.
        second_msgs = fake.calls[1]["json"]["messages"]
        tool_msg = [m for m in second_msgs if m.get("role") == "tool"]
        self.assertEqual(len(tool_msg), 1)
        self.assertEqual(tool_msg[0]["tool_call_id"], "call_1")

    async def test_no_tool_calls_returns_direct(self):
        fake = _FakeClient(
            [{"choices": [{"message": {"role": "assistant", "content": "hi"}}]}]
        )
        with (
            patch("chat_tools.httpx.AsyncClient", return_value=fake),
            patch("chat_tools.execute_tool", new=AsyncMock()) as exec_mock,
        ):
            final_msgs, actions = await chat_tools.run_openai_with_tools(
                "https://api.test/v1/chat/completions",
                {},
                "gpt-4o",
                [{"role": "user", "content": "hi"}],
            )
        exec_mock.assert_not_awaited()
        self.assertEqual(final_msgs[-1]["content"], "hi")
        self.assertEqual(actions, [])

    def test_accumulate_tool_call_deltas(self):
        acc: dict = {}
        chat_tools._accumulate_tool_call_deltas(
            acc, [{"index": 0, "id": "call_1", "function": {"name": "search_memory"}}]
        )
        chat_tools._accumulate_tool_call_deltas(
            acc, [{"index": 0, "function": {"arguments": '{"query":'}}]
        )
        chat_tools._accumulate_tool_call_deltas(
            acc, [{"index": 0, "function": {"arguments": '"flood"}'}}]
        )
        ordered = chat_tools._ordered_tool_calls(acc)
        self.assertEqual(len(ordered), 1)
        self.assertEqual(ordered[0]["name"], "search_memory")
        self.assertEqual(ordered[0]["args"], '{"query":"flood"}')
        self.assertEqual(ordered[0]["id"], "call_1")


class ChatToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_spatial_query_tool(self):
        """P6: spatial_query chat tool executes spatial reasoning and returns compact results."""
        fake_result = {
            "query": "within 50km of Bangkok",
            "enabled": True,
            "composition": "AND",
            "operations": [
                {
                    "operation": "within",
                    "target": "bangkok",
                    "params": {"radius_km": 50.0},
                }
            ],
            "resolved_entities": [
                {
                    "operation": "within",
                    "target": "bangkok",
                    "resolved": {"lat": 13.7563, "lon": 100.5018},
                }
            ],
            "result_count": 2,
            "results": [
                {
                    "id": "e1",
                    "schema": "Vessel",
                    "caption": "HOPE C",
                    "lat": 13.61,
                    "lon": 100.58,
                },
                {
                    "id": "e2",
                    "schema": "Airplane",
                    "caption": "THA941",
                    "lat": 13.69,
                    "lon": 100.76,
                },
            ],
        }
        with patch("spatial_reasoning.spatial_query", return_value=fake_result):
            out = await chat_tools.execute_tool(
                "spatial_query", {"query": "within 50km of Bangkok", "limit": 5}
            )
        self.assertEqual(out["tool"], "spatial_query")
        self.assertEqual(out["result"]["count"], 2)
        self.assertEqual(out["result"]["query"], "within 50km of Bangkok")
        self.assertEqual(len(out["result"]["results"]), 2)
        self.assertEqual(out["result"]["results"][0]["id"], "e1")


class GeocodeToolTests(unittest.IsolatedAsyncioTestCase):
    """Tests for focus_globe with place geocoding and geocode_place tool."""

    async def test_focus_globe_with_place_geocodes(self):
        """focus_globe with 'place' should geocode via Nominatim and return client_action."""
        fake_geo = {
            "lat": 52.5173885,
            "lon": 13.3951309,
            "display_name": "Berlin, Deutschland",
            "boundingbox": ["52.3382448", "52.6755087", "13.0883450", "13.7611609"],
            "place_rank": 8,
            "osm_type": "relation",
            "osm_id": 62422,
        }
        with patch("chat_tools._geocode_place", new=AsyncMock(return_value=fake_geo)):
            out = await chat_tools.execute_tool(
                "focus_globe", {"place": "Berlin", "title": "Berlin"}
            )
        self.assertTrue(out["result"]["ok"])
        self.assertAlmostEqual(out["result"]["lat"], 52.5173885)
        self.assertAlmostEqual(out["result"]["lon"], 13.3951309)
        self.assertEqual(out["client_action"]["type"], "focus_globe")
        self.assertEqual(out["client_action"]["lat"], 52.5173885)
        self.assertEqual(out["client_action"]["lon"], 13.3951309)

    async def test_focus_globe_with_place_uses_display_name_as_title(self):
        """When title is not provided, display_name from geocoding should be used."""
        fake_geo = {
            "lat": 13.7563,
            "lon": 100.5018,
            "display_name": "Bangkok, Thailand",
        }
        with patch("chat_tools._geocode_place", new=AsyncMock(return_value=fake_geo)):
            out = await chat_tools.execute_tool("focus_globe", {"place": "Bangkok"})
        self.assertTrue(out["result"]["ok"])
        self.assertEqual(out["client_action"]["title"], "Bangkok, Thailand")

    async def test_focus_globe_geocode_failure_returns_error(self):
        """focus_globe with place but geocoding fails should return ok=False."""
        with patch("chat_tools._geocode_place", new=AsyncMock(return_value=None)):
            out = await chat_tools.execute_tool(
                "focus_globe", {"place": "NonexistentPlace123", "title": "X"}
            )
        self.assertFalse(out["result"]["ok"])
        self.assertNotIn("client_action", out)

    async def test_focus_globe_place_ignores_llm_guessed_latlon(self):
        """If place is provided with wrong lat/lon, geocoding wins and ignores the guess."""
        fake_geo = {
            "lat": 52.5173885,
            "lon": 13.3951309,
            "display_name": "Berlin, Deutschland",
        }
        with patch(
            "chat_tools._geocode_place", new=AsyncMock(return_value=fake_geo)
        ) as geo_mock:
            out = await chat_tools.execute_tool(
                "focus_globe",
                {"place": "Berlin", "title": "Berlin", "lat": 55.5, "lon": 12.5},
            )
        geo_mock.assert_awaited_once()
        self.assertTrue(out["result"]["ok"])
        self.assertAlmostEqual(out["result"]["lat"], 52.5173885)
        self.assertAlmostEqual(out["result"]["lon"], 13.3951309)
        self.assertEqual(out["client_action"]["lat"], 52.5173885)
        self.assertEqual(out["client_action"]["lon"], 13.3951309)

    async def test_focus_globe_with_explicit_coords_still_works(self):
        """focus_globe with explicit lat/lon (no place) should not geocode."""
        with patch("chat_tools._geocode_place", new=AsyncMock()) as geo_mock:
            out = await chat_tools.execute_tool(
                "focus_globe", {"lat": 13.75, "lon": 100.5, "title": "Bangkok"}
            )
        geo_mock.assert_not_awaited()
        self.assertTrue(out["result"]["ok"])
        self.assertEqual(out["client_action"]["lat"], 13.75)
        self.assertEqual(out["client_action"]["lon"], 100.5)

    async def test_focus_globe_no_place_no_coords_returns_error(self):
        """focus_globe without place or lat/lon should return ok=False."""
        out = await chat_tools.execute_tool("focus_globe", {"title": "Nowhere"})
        self.assertFalse(out["result"]["ok"])

    async def test_geocode_place_tool(self):
        """geocode_place tool should return coordinates from Nominatim."""
        fake_geo = {
            "lat": 52.5173885,
            "lon": 13.3951309,
            "display_name": "Berlin, Deutschland",
        }
        with patch("chat_tools._geocode_place", new=AsyncMock(return_value=fake_geo)):
            out = await chat_tools.execute_tool(
                "geocode_place", {"query": "Berlin, Germany"}
            )
        self.assertTrue(out["result"]["ok"])
        self.assertAlmostEqual(out["result"]["lat"], 52.5173885)
        self.assertAlmostEqual(out["result"]["lon"], 13.3951309)

    async def test_geocode_place_empty_query(self):
        """geocode_place with empty query should return ok=False."""
        out = await chat_tools.execute_tool("geocode_place", {"query": ""})
        self.assertFalse(out["result"]["ok"])


if __name__ == "__main__":
    unittest.main()
