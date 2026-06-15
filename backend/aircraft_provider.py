"""Unified live aircraft — OpenSky (if configured) with adsb.lol fallback."""

from __future__ import annotations

import asyncio
import os

import adsb_client
import opensky_client

_STALE: dict | None = None
_FETCH_TASK: asyncio.Task[tuple[dict, str]] | None = None


def last_known_states() -> dict | None:
    """Last successful payload (any age) for stale-while-revalidate callers."""
    return _STALE


async def _fetch_once(timeout: float) -> tuple[dict, str]:
    global _STALE
    mode = os.environ.get("AIRCRAFT_SOURCE", "auto").strip().lower()
    opensky_budget = min(6.0, timeout * 0.45)
    adsb_budget = max(4.0, timeout - opensky_budget)

    if mode in ("opensky", "auto"):
        if mode == "opensky" or opensky_client.credentials_configured():
            try:
                data = await asyncio.wait_for(
                    opensky_client.fetch_states_all(timeout=opensky_budget),
                    timeout=opensky_budget + 1.0,
                )
                if data and data.get("states"):
                    data["source"] = "opensky"
                    _STALE = data
                    return data, "opensky"
            except Exception:
                if mode == "opensky":
                    raise

    data = await adsb_client.fetch_global_states(timeout=adsb_budget)
    label = data.get("source") or "adsb"
    if not data.get("states") and _STALE:
        stale = dict(_STALE)
        stale["source"] = stale.get("source", "stale")
        return stale, "stale"
    _STALE = data
    return data, label


async def fetch_live_states(timeout: float = 12.0) -> tuple[dict, str]:
    """
    Return (opensky_json, source_label).
    Coalesces concurrent callers onto one in-flight fetch; returns stale on timeout.
    """
    global _FETCH_TASK

    if _FETCH_TASK and not _FETCH_TASK.done():
        try:
            return await asyncio.wait_for(asyncio.shield(_FETCH_TASK), timeout=timeout)
        except Exception:
            if _STALE:
                stale = dict(_STALE)
                return stale, stale.get("source", "stale")
            raise

    _FETCH_TASK = asyncio.create_task(_fetch_once(timeout))
    try:
        return await asyncio.wait_for(_FETCH_TASK, timeout=timeout)
    except Exception:
        if _STALE:
            stale = dict(_STALE)
            return stale, stale.get("source", "stale")
        raise
