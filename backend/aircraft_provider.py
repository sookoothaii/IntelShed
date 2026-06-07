"""Unified live aircraft — OpenSky (if configured) with adsb.lol fallback."""

from __future__ import annotations

import asyncio
import os

import adsb_client
import opensky_client

_FETCH_LOCK = asyncio.Lock()


async def fetch_live_states(timeout: float = 30.0) -> tuple[dict, str]:
    """
    Return (opensky_json, source_label).
    source_label: opensky | adsb.lol | stale
    """
    mode = os.environ.get("AIRCRAFT_SOURCE", "auto").strip().lower()

    async with _FETCH_LOCK:
        if mode in ("opensky", "auto"):
            if mode == "opensky" or opensky_client.credentials_configured():
                try:
                    data = await opensky_client.fetch_states_all(timeout=timeout)
                    if data and data.get("states"):
                        data["source"] = "opensky"
                        return data, "opensky"
                except Exception:
                    if mode == "opensky":
                        raise

        data = await adsb_client.fetch_global_states()
        return data, "adsb.lol"
