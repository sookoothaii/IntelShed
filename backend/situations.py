"""Unified situation board — fuses correlations, anomalies, GDACS, pegel, Pi sensors."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter

import entity_store
import feeds_extra
import node_sync
import pegel_bridge
import anomaly_river

router = APIRouter(prefix="/api", tags=["situations"])

_CACHE: dict = {"ts": 0.0, "payload": None}
_CACHE_TTL = 45.0


def _loc(item: dict) -> dict | None:
    loc = item.get("location") or {}
    lat = loc.get("lat")
    lon = loc.get("lon")
    if lat is None or lon is None:
        return None
    return {"lat": float(lat), "lon": float(lon), "place": loc.get("place", "")}


def _append_entity_item(
    items: list,
    *,
    eid: str,
    entity_type: str,
    label: str,
    lat,
    lon,
    source_feed: str,
    external_id: str,
    meta: dict,
    row: dict,
):
    entity_store.upsert_entity(
        eid,
        entity_type,
        label=label,
        lat=lat,
        lon=lon,
        source_feed=source_feed,
        external_id=external_id,
        meta=meta,
    )
    items.append(row)


async def _items_correlations() -> list[dict]:
    items = []
    try:
        corr = await feeds_extra.cross_feed_correlations()
        for i, s in enumerate(corr.get("situations") or []):
            loc = _loc(s)
            eid = entity_store.entity_id_for_situation("correlation", str(i))
            _append_entity_item(
                items,
                eid=eid,
                entity_type="situation",
                label=s.get("title", ""),
                lat=loc["lat"] if loc else None,
                lon=loc["lon"] if loc else None,
                source_feed="correlations",
                external_id=str(i),
                meta={
                    "severity": s.get("severity"),
                    "type": s.get("type"),
                    "details": s.get("details"),
                },
                row={
                    "id": f"corr:{i}",
                    "entity_id": eid,
                    "category": "correlation",
                    "severity": s.get("severity", "medium"),
                    "type": s.get("type", ""),
                    "title": s.get("title", ""),
                    "source": "correlations",
                    "location": loc,
                    "details": s.get("details"),
                },
            )
    except Exception:
        pass
    return items


async def _items_anomalies() -> list[dict]:
    items = []
    try:
        anom = await feeds_extra.aircraft_anomalies()
        for i, a in enumerate((anom.get("anomalies") or [])[:40]):
            lat, lon = a.get("lat"), a.get("lon")
            if lat is None or lon is None:
                continue
            icao = a.get("icao24", "")
            eid = entity_store.entity_id_for_aircraft(icao)
            _append_entity_item(
                items,
                eid=eid,
                entity_type="aircraft",
                label=a.get("callsign") or icao,
                lat=float(lat),
                lon=float(lon),
                source_feed="anomalies",
                external_id=icao,
                meta={"reasons": a.get("reasons")},
                row={
                    "id": f"anom:{icao}:{i}",
                    "entity_id": eid,
                    "category": "anomaly",
                    "severity": "high"
                    if "emergency_squawk" in str(a.get("reasons"))
                    else "medium",
                    "type": "aircraft_anomaly",
                    "title": f"Anomaly {a.get('callsign') or icao}",
                    "source": "anomalies",
                    "location": {"lat": float(lat), "lon": float(lon), "place": ""},
                    "details": a,
                },
            )
    except Exception:
        pass
    return items


async def _items_gdacs() -> list[dict]:
    items = []
    try:
        gdacs = await feeds_extra.gdacs_alerts()
        for i, d in enumerate((gdacs.get("alerts") or [])[:15]):
            lat, lon = d.get("lat"), d.get("lon")
            if lat is None or lon is None:
                continue
            eid = entity_store.entity_id_for_situation("gdacs", str(i))
            title = d.get("title", "GDACS alert")
            sev = "high" if "red" in title.lower() else "medium"
            _append_entity_item(
                items,
                eid=eid,
                entity_type="gdacs",
                label=title,
                lat=float(lat),
                lon=float(lon),
                source_feed="gdacs",
                external_id=str(i),
                meta=d,
                row={
                    "id": f"gdacs:{i}",
                    "entity_id": eid,
                    "category": "disaster",
                    "severity": sev,
                    "type": "gdacs",
                    "title": title,
                    "source": "gdacs",
                    "location": {"lat": float(lat), "lon": float(lon), "place": ""},
                    "details": d,
                },
            )
    except Exception:
        pass
    return items


async def _items_pegel() -> list[dict]:
    items = []
    try:
        peg = await pegel_bridge.get_pegel()
        for st in peg.get("gauges") or []:
            sev = st.get("severity", "normal")
            if sev not in ("high", "critical"):
                continue
            uuid = st.get("uuid", st.get("name", ""))
            eid = entity_store.entity_id_for_pegel(uuid)
            _append_entity_item(
                items,
                eid=eid,
                entity_type="pegel",
                label=st.get("name", "Gauge"),
                lat=st.get("lat"),
                lon=st.get("lon"),
                source_feed="pegel",
                external_id=uuid,
                meta=st,
                row={
                    "id": f"pegel:{uuid}",
                    "entity_id": eid,
                    "category": "infrastructure",
                    "severity": sev,
                    "type": "river_gauge",
                    "title": f"Pegel {st.get('name')}: {st.get('value')}{st.get('unit', '')}",
                    "source": "pegel",
                    "location": {
                        "lat": st["lat"],
                        "lon": st["lon"],
                        "place": st.get("water", ""),
                    },
                    "details": st,
                },
            )
    except Exception:
        pass
    return items


async def _items_sensors() -> list[dict]:
    items = []
    try:
        alerts = await node_sync.list_sensor_alerts(limit=30)
        for a in alerts.get("alerts") or []:
            node_id = a.get("node_id", "pi")
            eid = entity_store.entity_id_for_situation(
                "sensor", f"{node_id}:{a.get('id', a.get('sensor'))}"
            )
            items.append(
                {
                    "id": f"sensor:{node_id}:{a.get('sensor')}:{a.get('created_at', '')}",
                    "entity_id": eid,
                    "category": "sensor",
                    "severity": a.get("severity", "warn"),
                    "type": "pi_sensor",
                    "title": f"{node_id}: {a.get('sensor')} {a.get('value')}",
                    "source": "node_sync",
                    "location": None,
                    "details": a,
                }
            )
    except Exception:
        pass
    return items


async def _items_river() -> list[dict]:
    items = []
    try:
        scan = await anomaly_river.get_river_state(90.0)
        for i, sig in enumerate(scan.get("anomalies") or []):
            feed = sig.get("feed", "feed")
            eid = entity_store.entity_id_for_situation("river", feed)
            items.append(
                {
                    "id": f"river:{feed}:{i}",
                    "entity_id": eid,
                    "category": "anomaly",
                    "severity": "high" if sig.get("score", 0) >= 0.8 else "medium",
                    "type": "feed_anomaly",
                    "title": f"Unusual {feed.replace('_', ' ')} (score {sig.get('score')})",
                    "source": "river",
                    "location": None,
                    "details": sig,
                }
            )
    except Exception:
        pass
    return items


@router.get("/situations")
async def unified_situations():
    """Single timeline for the Situation Board (parallel fetch + 45s cache)."""
    now = time.time()
    if _CACHE["payload"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["payload"]

    corr, anom, gdacs, pegel, sensors, river = await asyncio.gather(
        _items_correlations(),
        _items_anomalies(),
        _items_gdacs(),
        _items_pegel(),
        _items_sensors(),
        _items_river(),
    )
    items = corr + anom + gdacs + pegel + sensors + river

    sev_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "warn": 3,
        "low": 4,
        "normal": 5,
    }
    items.sort(key=lambda x: sev_order.get(x.get("severity", "medium"), 3))

    payload = {
        "count": len(items),
        "items": items,
        "updated": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    _CACHE["payload"] = {**payload, "cached": True}
    _CACHE["ts"] = now
    return payload


@router.get("/entity/{entity_id}/context")
async def entity_context(entity_id: str):
    """Palantir-style context panel data for one entity."""
    return entity_store.get_entity_context(entity_id)
