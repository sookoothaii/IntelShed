"""Live aircraft endpoint — /api/aircraft.

Extracted from main.py (Phase 1 decortication). OpenSky (OAuth) when configured,
else adsb.lol/adsb.fi grid, via aircraft_provider. Uses the shared runtime_cache
store (key ``aircraft``) so /api/chat context and the boot warmup see the same
data. aircraft_warmup() is scheduled by main.on_startup().
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

import aircraft_provider
from runtime_cache import cache_get, cache_get_stale, cache_set

router = APIRouter(tags=["aircraft"])

_CACHE_KEY = "aircraft"
_AIRCRAFT_REFRESH_TASK: asyncio.Task | None = None


async def aircraft_warmup() -> None:
    """Prime aircraft cache on boot so first UI load is fast."""
    await asyncio.sleep(2)
    try:
        data, source = await aircraft_provider.fetch_live_states(timeout=14.0)
        cache_set(_CACHE_KEY, data)
        n = len(data.get("states") or [])
        print(f"[WARMUP] aircraft cache primed ({n} states, {source})", flush=True)
    except Exception as e:
        print(f"[WARMUP] aircraft cache skipped: {e}", flush=True)


async def _refresh_aircraft_cache() -> None:
    global _AIRCRAFT_REFRESH_TASK
    try:
        data, _source = await aircraft_provider.fetch_live_states(timeout=14.0)
        cache_set(_CACHE_KEY, data)
    except Exception:
        pass
    finally:
        _AIRCRAFT_REFRESH_TASK = None


@router.get("/api/aircraft")
async def get_aircraft(limit: int = 800):
    """Live aircraft: OpenSky (OAuth) when configured, else adsb.lol/adsb.fi grid."""
    global _AIRCRAFT_REFRESH_TASK

    cached = cache_get(_CACHE_KEY, ttl=45.0)
    source = "cache"
    if cached is None:
        stale = cache_get_stale(_CACHE_KEY) or aircraft_provider.last_known_states()
        if stale:
            if _AIRCRAFT_REFRESH_TASK is None or _AIRCRAFT_REFRESH_TASK.done():
                _AIRCRAFT_REFRESH_TASK = asyncio.create_task(_refresh_aircraft_cache())
            cached = stale
            source = stale.get("source", "stale")
        else:
            try:
                cached, source = await asyncio.wait_for(
                    aircraft_provider.fetch_live_states(timeout=12.0),
                    timeout=14.0,
                )
                cache_set(_CACHE_KEY, cached)
            except Exception as e:
                if stale:
                    cached = stale
                    source = cached.get("source", "stale")
                else:
                    return {
                        "count": 0,
                        "timestamp": None,
                        "states": [],
                        "source": None,
                        "error": (
                            f"Aircraft feeds unavailable ({e.__class__.__name__}). "
                            "Optional: OPENSKY_CLIENT_ID/SECRET in backend/.env; "
                            "otherwise adsb.fi / adsb.lol is used automatically."
                        ),
                    }
    else:
        source = cached.get("source", "cache")

    states = cached.get("states", []) or []
    with_pos = [s for s in states if len(s) > 6 and s[5] is not None and s[6] is not None]
    return {
        "count": len(with_pos),
        "timestamp": cached.get("time"),
        "source": source,
        "states": with_pos[: max(0, min(limit, 5000))],
    }
