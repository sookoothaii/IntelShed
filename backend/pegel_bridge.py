"""River gauge levels — Pegelonline (WSV Germany, no API key).

Adds 24h history endpoint for sparkline rendering in the dashboard.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api", tags=["pegel"])

_BASE = "https://www.pegelonline.wsv.de/webservices/rest-api/v2"
_UA = {"User-Agent": "WorldBase/1.0 (research dashboard)"}
_TTL = 900.0
_CONNECTOR = FeedConnector("pegel", ttl_sec=_TTL, default_source="pegelonline.wsv.de")

# Curated major gauges (uuid, series W = water level cm, Q = flow m3/s)
_STATIONS = [
    {
        "uuid": "a6ee8177-107b-47dd-bcfd-30960ccc6e9c",
        "name": "Köln",
        "water": "RHEIN",
        "lon": 6.9633,
        "lat": 50.9369,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "a37a9aa3-45e9-4d90-9df6-109f3a28a5af",
        "name": "Mainz",
        "water": "RHEIN",
        "lon": 8.2753,
        "lat": 50.0040,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "8f7e5f92-1153-4f93-acba-ca48670c8ca9",
        "name": "Düsseldorf",
        "water": "RHEIN",
        "lon": 6.7699,
        "lat": 51.2255,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "9f12c405-35ac-4d90-9b7b-023be355867e",
        "name": "Passau",
        "water": "DONAU",
        "lon": 13.4591,
        "lat": 48.5761,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "ccccb57f-a2f9-4183-ae88-5710d3afaefd",
        "name": "Magdeburg",
        "water": "ELBE",
        "lon": 11.6443,
        "lat": 52.1297,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "d488c5cc-4de9-4631-8ce1-0db0e700b546",
        "name": "Hamburg",
        "water": "ELBE",
        "lon": 9.9700,
        "lat": 53.5454,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "70272185-b2b3-4178-96b8-43bea330dcae",
        "name": "Dresden",
        "water": "ELBE",
        "lon": 13.7388,
        "lat": 51.0545,
        "series": "Q",
        "unit": "m³/s",
    },
    {
        "uuid": "b475386c-30cc-453a-b3b7-1d17ace13595",
        "name": "Celle",
        "water": "ALLER",
        "lon": 10.0622,
        "lat": 52.6227,
        "series": "W",
        "unit": "cm",
    },
    {
        "uuid": "070b1eb4-3872-4e07-b2e5-e25fd9251b93",
        "name": "Wittenberg",
        "water": "ELBE",
        "lon": 12.6463,
        "lat": 51.8565,
        "series": "W",
        "unit": "cm",
    },
]


def _severity(state_mnw: str | None, state_nsw: str | None) -> str:
    parts = " ".join((state_mnw or "", state_nsw or "")).lower()
    if (
        "flood" in parts
        or "very_high" in parts
        or "very high" in parts
        or "hw" in parts
    ):
        return "critical"
    if "high" in parts:
        return "high"
    if "very_low" in parts or "very low" in parts or "low" in parts:
        return "low"
    return "normal"


async def _fetch_one(client: httpx.AsyncClient, st: dict) -> dict | None:
    series = st["series"]
    url = f"{_BASE}/stations/{st['uuid']}/{series}/currentmeasurement.json"
    try:
        r = await client.get(url, timeout=12.0)
        if r.status_code != 200:
            return None
        m = r.json()
    except Exception:
        return None
    val = m.get("value")
    if val is None:
        return None
    sm = m.get("stateMnwMhw")
    sn = m.get("stateNswHsw")
    return {
        "uuid": st["uuid"],
        "name": st["name"],
        "water": st["water"],
        "lon": st["lon"],
        "lat": st["lat"],
        "series": series,
        "unit": st["unit"],
        "value": float(val),
        "timestamp": m.get("timestamp"),
        "state_mnw_mhw": sm,
        "state_nsw_hsw": sn,
        "severity": _severity(sm, sn),
    }


async def _fetch_pegel_payload() -> dict[str, Any]:
    async with httpx.AsyncClient(headers=_UA, follow_redirects=True) as client:
        results = await asyncio.gather(*[_fetch_one(client, st) for st in _STATIONS])

    gauges = [g for g in results if g is not None]
    alerts = [g for g in gauges if g["severity"] in ("critical", "high")]
    err = None if gauges else "No gauge data returned"
    return FeedEnvelope(
        count=len(gauges),
        error=err,
        updated=utc_now_iso(),
    ).merge(
        alerts=len(alerts),
        gauges=gauges,
    )


@router.get("/pegel")
async def get_pegel():
    """Current levels at curated German river gauges. Cached 15 min."""
    return await _CONNECTOR.run(_fetch_pegel_payload)


# ---------------------------------------------------------------------------
# 24h history for sparklines (no key required — pegelonline measurements.json)
# ---------------------------------------------------------------------------
_HISTORY_TTL = 600.0
_HISTORY_CACHE: dict[str, tuple[float, dict]] = {}


def _station_by_uuid(uuid: str) -> dict | None:
    for st in _STATIONS:
        if st["uuid"].lower() == uuid.lower():
            return st
    return None


@router.get("/pegel/{uuid}/history")
async def pegel_history(uuid: str, hours: int = Query(24, ge=1, le=168)):
    """Return the last N hours of W/Q measurements for one curated gauge.

    Falls back to whichever series is configured for the station (most are W,
    a few are Q like Dresden). Caches per (uuid, hours) for 10 minutes.
    """
    import time

    st = _station_by_uuid(uuid)
    if not st:
        raise HTTPException(
            404, f"unknown gauge uuid {uuid} — call /api/pegel first to discover ids"
        )
    key = f"{uuid}|{hours}"
    now = time.time()
    cached = _HISTORY_CACHE.get(key)
    if cached and (now - cached[0]) < _HISTORY_TTL:
        return cached[1]

    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M%z"
    )
    url = f"{_BASE}/stations/{uuid}/{st['series']}/measurements.json"
    params = {"start": start}
    try:
        async with httpx.AsyncClient(
            headers=_UA, follow_redirects=True, timeout=15.0
        ) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                raise HTTPException(
                    r.status_code, f"pegelonline returned {r.status_code}"
                )
            raw = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"pegelonline fetch failed: {e}") from e

    series = []
    for m in raw or []:
        ts = m.get("timestamp")
        val = m.get("value")
        if ts is None or val is None:
            continue
        try:
            series.append({"t": ts, "v": float(val)})
        except (ValueError, TypeError):
            continue

    values = [p["v"] for p in series]
    summary = None
    if values:
        summary = {
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "first": round(values[0], 2),
            "last": round(values[-1], 2),
            "delta": round(values[-1] - values[0], 2),
        }

    payload = {
        "uuid": uuid,
        "name": st["name"],
        "water": st["water"],
        "series_kind": st["series"],
        "unit": st["unit"],
        "hours": hours,
        "count": len(series),
        "points": series,
        "summary": summary,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    _HISTORY_CACHE[key] = (now, payload)
    return payload
