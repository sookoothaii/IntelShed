"""Chat context builder — briefing injection must await async latest_briefing()."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from routes import chat


class BuildChatContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_includes_briefing_when_available(self):
        fake = {"text": "Flood warning near Bangkok", "created_at": "2026-06-23T00:00:00Z"}
        with patch("node_sync.latest_briefing", new=AsyncMock(return_value=fake)):
            ctx = await chat.build_chat_context()
        self.assertIn("SITUATION BRIEFING", ctx)
        self.assertIn("Flood warning near Bangkok", ctx)

    async def test_skips_briefing_when_empty(self):
        with patch("node_sync.latest_briefing", new=AsyncMock(return_value={"text": ""})):
            ctx = await chat.build_chat_context()
        self.assertNotIn("SITUATION BRIEFING", ctx)


if __name__ == "__main__":
    unittest.main()
