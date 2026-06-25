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

        with patch("chat_tools.httpx.AsyncClient", return_value=fake), patch(
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
        ) as exec_mock:
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
        with patch("chat_tools.httpx.AsyncClient", return_value=fake), patch(
            "chat_tools.execute_tool", new=AsyncMock()
        ) as exec_mock:
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


if __name__ == "__main__":
    unittest.main()
