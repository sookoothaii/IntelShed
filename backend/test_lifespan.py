"""Unit tests for startup warmup / briefing autopilot coordination."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _load_lifespan():
    """Import lifespan with heavy optional deps stubbed (CI-friendly)."""
    stubs = (
        "aircraft_trails",
        "anomaly_river",
        "entity_resolution",
        "entity_store",
        "feed_ingest",
        "ftm_store",
        "fusion_heatmap",
        "node_sync",
        "rag_memory",
        "sanctions_bridge",
        "situations",
        "stac_bridge",
        "sqlite_bootstrap",
        "routes.aircraft",
        "feed_drift",
        "prediction_ledger",
        "ais_bridge",
        "ollama_config",
    )
    saved = {name: sys.modules.get(name) for name in stubs}
    mock = MagicMock()
    mock.fusion_heatmap = AsyncMock(return_value={"cells": [{}]})
    mock.warm_snapshot_cache = AsyncMock(return_value={"cve": {}})
    mock.generate_briefing_internal = AsyncMock(return_value={})
    for name in stubs:
        if name == "fusion_heatmap":
            sys.modules[name] = mock
        elif name == "node_sync":
            sys.modules[name] = mock
        else:
            sys.modules[name] = MagicMock()
    sys.modules["routes"] = types.ModuleType("routes")
    sys.modules["routes.aircraft"] = MagicMock()
    if "lifespan" in sys.modules:
        del sys.modules["lifespan"]
    import lifespan as mod

    for name, prev in saved.items():
        if prev is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prev
    return mod


class BriefingAutopilotWarmupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.lifespan = _load_lifespan()
        self.lifespan._STACK_WARMUP_DONE.clear()

    async def test_autopilot_waits_for_warmup_before_first_generate(self):
        calls: list[dict] = []

        async def fake_generate(*, force_snapshot: bool = False):
            calls.append({"force_snapshot": force_snapshot})
            return {"created_at": "2026-06-23T16:00:00+00:00"}

        self.lifespan.node_sync.generate_briefing_internal = fake_generate
        with patch.object(self.lifespan, "_BRIEFING_INTERVAL", 3600):
            task = asyncio.create_task(self.lifespan._briefing_autopilot())
            await asyncio.sleep(0.05)
            self.assertEqual(calls, [])
            self.lifespan._STACK_WARMUP_DONE.set()
            await asyncio.sleep(0.05)
            self.assertEqual(len(calls), 1)
            self.assertTrue(calls[0]["force_snapshot"])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_stack_warmup_sets_done_event(self):
        self.lifespan._STACK_WARMUP_DONE.clear()
        with patch("gdelt_bridge.warmup_local_pulse", AsyncMock(return_value={"count": 1})):
            with patch("gdelt_bridge.warmup_global_pulse", AsyncMock(return_value={"count": 1})):
                with patch("gdelt_bridge._GDELT_MIN_INTERVAL", 0.0):
                    with patch("traffic_bridge.warm_traffic_cams", AsyncMock(return_value=None)):
                        with patch("ais_bridge.warm_maritime", AsyncMock(return_value=None)):
                            with patch("cams_bridge.get_haze", AsyncMock(return_value={"count": 1})):
                                with patch("feeds_extra.air_quality", AsyncMock(return_value={})):
                                    with patch("windy_bridge.fetch_point_weather", AsyncMock(return_value={})):
                                        with patch.object(
                                            self.lifespan.asyncio,
                                            "sleep",
                                            AsyncMock(),
                                        ):
                                            await self.lifespan._stack_warmup()
        self.assertTrue(self.lifespan._STACK_WARMUP_DONE.is_set())


if __name__ == "__main__":
    unittest.main()
