"""Single round-trip bundle for Globe feed layers (parallel, cache-first)."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/globe", tags=["globe"])

_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 15.0
_REFRESH_LOCK = asyncio.Lock()

_ALL_LAYERS = frozenset({
    "quakes", "events", "nodes", "military", "spaceweather", "geopolitics",
    "wildfires", "lightning", "maritime", "gdacs", "hazards", "outages",
    "volcanoes", "airquality", "pegel", "energy",
})


async def _fetch_layer(name: str) -> tuple[str, dict | None]:
    try:
        if name == "quakes":
            from main import get_earthquakes
            return name, await get_earthquakes(period="day", magnitude="2.5")
        if name == "events":
            from main import get_events
            return name, await get_events(limit=120)
        if name == "nodes":
            from node_sync import list_nodes
            return name, await list_nodes()
        if name == "military":
            from feeds_extra import military_aircraft
            return name, await military_aircraft()
        if name == "spaceweather":
            from feeds_extra import space_weather
            return name, await space_weather()
        if name == "geopolitics":
            from feeds_extra import geopolitics
            return name, await geopolitics(limit=40)
        if name == "wildfires":
            from nasa_firms import get_wildfires
            return name, await get_wildfires()
        if name == "lightning":
            from blitzortung_bridge import get_lightning
            return name, await get_lightning()
        if name == "maritime":
            from ais_bridge import get_maritime
            return name, await get_maritime()
        if name == "gdacs":
            from feeds_extra import gdacs_alerts
            return name, await gdacs_alerts()
        if name == "hazards":
            from cap_bridge import hazards_active
            return name, await hazards_active(limit=80)
        if name == "outages":
            from outages_bridge import internet_outages
            return name, await internet_outages(hours=72, limit=35)
        if name == "volcanoes":
            from volcano_bridge import holocene_volcanoes
            return name, await holocene_volcanoes(active_only=False, limit=350)
        if name == "airquality":
            from feeds_extra import air_quality
            return name, await air_quality()
        if name == "pegel":
            from pegel_bridge import get_pegel
            return name, await get_pegel()
        if name == "energy":
            from smard_bridge import get_german_energy_globe
            return name, await get_german_energy_globe()
    except Exception as exc:
        return name, {"error": str(exc)}
    return name, None


@router.get("/snapshot")
async def globe_snapshot(layers: list[str] = Query(default=[])):
    """Return many globe layers in one JSON payload (parallel upstream/cache reads)."""
    wanted = [x.strip().lower() for x in layers if x.strip()]
    if not wanted:
        wanted = sorted(_ALL_LAYERS)
    else:
        wanted = [x for x in wanted if x in _ALL_LAYERS]
    if not wanted:
        return {"layers": [], "cached": False, "ts": time.time()}

    cache_key = ",".join(sorted(wanted))
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and (now - hit[0]) < _TTL:
        out = dict(hit[1])
        out["cached"] = True
        return out

    async with _REFRESH_LOCK:
        hit = _CACHE.get(cache_key)
        if hit and (time.time() - hit[0]) < _TTL:
            out = dict(hit[1])
            out["cached"] = True
            return out

        pairs = await asyncio.gather(*[_fetch_layer(name) for name in wanted])
        payload = {name: data for name, data in pairs if data is not None}
        result = {
            "layers": wanted,
            "cached": False,
            "ts": time.time(),
            **payload,
        }
        _CACHE[cache_key] = (time.time(), result)
        return result
