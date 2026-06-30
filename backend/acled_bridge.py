"""ACLED conflict events connector (free for research, requires API key).

ACLED (Armed Conflict Location & Event Data) provides real-time data on
political violence and protests across the world. Free for non-commercial
research use with registration.

Register at https://developer.acleddata.com/ to get email + key.
Set ACLED_EMAIL and ACLED_KEY in .env.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Query

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/acled", tags=["acled"])

_TTL = float(os.getenv("WORLDBASE_ACLED_CACHE_SEC", "3600"))
_FETCH_TIMEOUT = 25.0
_REFRESH_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector("acled_events", ttl_sec=_TTL, default_source="acled")

_ACLED_API = "https://api.acleddata.com/acled/read"
_ACLED_EMAIL = os.getenv("ACLED_EMAIL", "").strip()
_ACLED_KEY = os.getenv("ACLED_KEY", "").strip()

# ASEAN country codes for ACLED (ISO 3-letter)
_ASEAN_CODES = {
    "THA",
    "MMR",
    "LAO",
    "KHM",
    "VNM",
    "PHL",
    "MYS",
    "SGP",
    "BRN",
    "IDN",
}

# Event type severity mapping
_EVENT_SEVERITY: dict[str, str] = {
    "Battle": "high",
    "Explosion/Remote violence": "high",
    "Violence against civilians": "high",
    "Armed clash": "high",
    "Attack": "high",
    "Protest": "low",
    "Riot": "medium",
    "Strategic development": "low",
}


def _severity_for_event(event_type: str | None, fatalities: int | None) -> str:
    if fatalities is not None and fatalities >= 10:
        return "high"
    if fatalities is not None and fatalities >= 1:
        return "medium"
    if event_type and event_type in _EVENT_SEVERITY:
        return _EVENT_SEVERITY[event_type]
    return "low"


def _parse_event(row: dict) -> dict:
    event_type = row.get("event_type") or ""
    sub_type = row.get("sub_event_type") or ""
    fatalities = row.get("fatalities")
    try:
        fatalities = int(fatalities) if fatalities is not None else 0
    except (ValueError, TypeError):
        fatalities = 0
    lat = row.get("latitude")
    lon = row.get("longitude")
    try:
        lat = float(lat) if lat else None
    except (ValueError, TypeError):
        lat = None
    try:
        lon = float(lon) if lon else None
    except (ValueError, TypeError):
        lon = None
    return {
        "id": row.get("data_id") or row.get("event_id_cnty"),
        "date": row.get("event_date"),
        "event_type": event_type,
        "sub_event_type": sub_type,
        "country": row.get("country"),
        "admin1": row.get("admin1"),
        "admin2": row.get("admin2"),
        "lat": lat,
        "lon": lon,
        "fatalities": fatalities,
        "notes": (row.get("notes") or "")[:500],
        "source": row.get("source") or "ACLED",
        "severity": _severity_for_event(event_type, fatalities),
    }


async def fetch_events(
    *,
    country: str | None = None,
    region: str = "asean",
    limit: int = 100,
    days: int = 7,
) -> dict:
    """Fetch ACLED events for a region or country."""
    if not _ACLED_EMAIL or not _ACLED_KEY:
        return {
            "count": 0,
            "events": [],
            "source": "acled",
            "updated": utc_now_iso(),
            "error": "ACLED credentials missing",
            "hint": "Register at https://developer.acleddata.com/ and set ACLED_EMAIL + ACLED_KEY in .env",
        }

    from datetime import timedelta

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    date_str = f"{start_date.strftime('%Y-%m-%d')}|{end_date.strftime('%Y-%m-%d')}"

    params: dict[str, str | int] = {
        "key": _ACLED_KEY,
        "email": _ACLED_EMAIL,
        "event_date": date_str,
        "event_date_where": "BETWEEN",
        "limit": min(limit, 500),
        "fields": (
            "data_id|event_id_cnty|event_date|event_type|sub_event_type|"
            "country|admin1|admin2|latitude|longitude|fatalities|notes|source"
        ),
        "format": "json",
    }

    if country:
        params["country"] = country
    elif region == "asean":
        params["country"] = "|".join(sorted(_ASEAN_CODES))

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            r = await client.get(_ACLED_API, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return {
            "count": 0,
            "events": [],
            "source": "acled",
            "updated": utc_now_iso(),
            "error": str(exc),
        }

    rows = data.get("data") or []
    events = [_parse_event(row) for row in rows]
    high_severity = [e for e in events if e["severity"] == "high"]
    total_fatalities = sum(e.get("fatalities", 0) for e in events)

    return {
        "count": len(events),
        "high_severity_count": len(high_severity),
        "total_fatalities": total_fatalities,
        "events": events,
        "region": region,
        "country": country,
        "source": "acled",
        "updated": utc_now_iso(),
    }


def _wrap_events_payload(
    raw: dict, *, stale: bool = False, error: str | None = None
) -> dict:
    return _CONNECTOR.build(
        FeedEnvelope(
            count=int(raw.get("count") or 0),
            stale=stale,
            error=error or raw.get("error"),
        ),
        persist=bool(raw.get("events")) and not stale and not error,
        events=raw.get("events") or [],
        high_severity_count=raw.get("high_severity_count", 0),
        total_fatalities=raw.get("total_fatalities", 0),
        region=raw.get("region", "asean"),
        hint=raw.get("hint"),
    )


async def get_events(
    *,
    refresh: bool = False,
    country: str | None = None,
    region: str = "asean",
    limit: int = 100,
    days: int = 7,
) -> dict:
    subkey = f"{region}:{country or 'all'}:{days}d"
    if not refresh:
        hit = _CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    async with _REFRESH_LOCK:
        if not refresh:
            hit = _CONNECTOR.get_cached(subkey)
            if hit is not None:
                return hit

        stale_hit = _CONNECTOR.peek_memory(subkey)
        try:
            raw = await asyncio.wait_for(
                fetch_events(country=country, region=region, limit=limit, days=days),
                timeout=_FETCH_TIMEOUT + 5,
            )
        except asyncio.TimeoutError:
            if stale_hit:
                return _wrap_events_payload(
                    stale_hit,
                    stale=True,
                    error="upstream timeout — serving stale cache",
                )
            return _CONNECTOR.build(
                FeedEnvelope(count=0, error="upstream timeout"),
                persist=False,
                events=[],
                region=region,
            )

        if raw.get("events") or raw.get("error"):
            return _wrap_events_payload(raw)
        if stale_hit:
            return _wrap_events_payload(stale_hit, stale=True)
        return _wrap_events_payload(raw)


def gather_acled_digest() -> dict:
    """Synchronous digest for briefing integration (reads memory cache)."""
    cached = _CONNECTOR.peek_memory()
    if not cached:
        return {"enabled": False, "count": 0, "lines": []}
    if cached.get("error"):
        return {"enabled": False, "count": 0, "lines": [], "error": cached["error"]}
    events = cached.get("events") or []
    if not events:
        return {"enabled": True, "count": 0, "lines": []}

    lines: list[str] = []
    high = [e for e in events if e.get("severity") == "high"]
    for ev in high[:5]:
        lines.append(
            f"{ev.get('date', '?')} {ev.get('country', '?')}: "
            f"{ev.get('event_type', '?')} — {ev.get('sub_event_type', '')}, "
            f"fatalities: {ev.get('fatalities', 0)}"
        )
    if not high:
        for ev in events[:3]:
            lines.append(
                f"{ev.get('date', '?')} {ev.get('country', '?')}: "
                f"{ev.get('event_type', '?')}, fatalities: {ev.get('fatalities', 0)}"
            )
    return {
        "enabled": True,
        "count": len(events),
        "high_severity_count": cached.get("high_severity_count", 0),
        "total_fatalities": cached.get("total_fatalities", 0),
        "lines": lines[:10],
    }


@router.get("/events")
async def acled_events(
    refresh: bool = Query(False),
    country: str | None = Query(None, description="ISO 3-letter country code"),
    region: str = Query("asean", description="Region preset: asean or global"),
    limit: int = Query(100, ge=1, le=500),
    days: int = Query(7, ge=1, le=30, description="Lookback days"),
):
    """ACLED conflict events (free for research, requires ACLED_EMAIL + ACLED_KEY)."""
    return await get_events(
        refresh=refresh, country=country, region=region, limit=limit, days=days
    )
