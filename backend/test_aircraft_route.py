"""Unit tests for /api/aircraft fail-soft behavior (no network)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import routes.aircraft as ac


class AircraftRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_empty_envelope_when_no_cache_and_fetch_fails(self):
        with patch.object(ac, "cache_get", return_value=None), patch.object(
            ac, "cache_get_stale", return_value=None
        ), patch.object(
            ac.aircraft_provider, "last_known_states", return_value=None
        ), patch.object(
            ac.aircraft_provider,
            "fetch_live_states",
            AsyncMock(side_effect=TimeoutError("slow")),
        ):
            out = await ac.get_aircraft(limit=10)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["states"], [])
        self.assertIn("error", out)

    async def test_returns_stale_when_fetch_fails(self):
        stale = {
            "time": 1,
            "source": "adsb",
            "states": [
                [
                    "abc",
                    "TEST",
                    None,
                    None,
                    None,
                    100.5,
                    13.7,
                    9000,
                    False,
                    200,
                    90,
                    0,
                    None,
                    None,
                    None,
                    False,
                    0,
                ]
            ],
        }
        with patch.object(ac, "cache_get", return_value=None), patch.object(
            ac, "cache_get_stale", return_value=stale
        ), patch.object(
            ac.aircraft_provider,
            "fetch_live_states",
            AsyncMock(side_effect=TimeoutError("slow")),
        ):
            out = await ac.get_aircraft(limit=10)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["source"], "adsb")

    async def test_cancelled_returns_stale_not_500(self):
        stale = {
            "time": 1,
            "source": "stale",
            "states": [
                [
                    "abc",
                    "TEST",
                    None,
                    None,
                    None,
                    100.5,
                    13.7,
                    9000,
                    False,
                    200,
                    90,
                    0,
                    None,
                    None,
                    None,
                    False,
                    0,
                ]
            ],
        }
        with patch.object(
            ac, "cache_get", side_effect=asyncio.CancelledError()
        ), patch.object(ac, "cache_get_stale", return_value=stale):
            out = await ac.get_aircraft(limit=5)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["source"], "stale")


if __name__ == "__main__":
    unittest.main()
