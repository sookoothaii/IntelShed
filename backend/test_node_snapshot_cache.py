"""Unit tests for briefing snapshot cache (no network)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import node_sync


class SnapshotCacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        node_sync.invalidate_snapshot_cache()

    async def test_cache_hit_skips_uncached_fetch(self):
        calls = {"n": 0}

        async def fake_uncached():
            calls["n"] += 1
            return {"earthquakes": {"earthquakes": []}}

        with patch.object(node_sync, "_gather_snapshot_uncached", side_effect=fake_uncached):
            with patch.object(node_sync, "_snapshot_cache_ttl_sec", return_value=90.0):
                first = await node_sync._gather_snapshot()
                second = await node_sync._gather_snapshot()

        self.assertIs(first, second)
        self.assertEqual(calls["n"], 1)

    async def test_force_bypasses_cache(self):
        calls = {"n": 0}

        async def fake_uncached():
            calls["n"] += 1
            return {"nodes": {"nodes": []}}

        with patch.object(node_sync, "_gather_snapshot_uncached", side_effect=fake_uncached):
            with patch.object(node_sync, "_snapshot_cache_ttl_sec", return_value=90.0):
                await node_sync._gather_snapshot()
                await node_sync._gather_snapshot(force=True)

        self.assertEqual(calls["n"], 2)

    async def test_invalidate_clears_cache(self):
        node_sync._SNAPSHOT_CACHE = {"cve": {}}
        node_sync._SNAPSHOT_CACHE_AT = 1.0
        node_sync.invalidate_snapshot_cache()
        self.assertIsNone(node_sync._SNAPSHOT_CACHE)
        self.assertEqual(node_sync._SNAPSHOT_CACHE_AT, 0.0)


if __name__ == "__main__":
    unittest.main()
