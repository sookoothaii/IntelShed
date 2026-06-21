"""Internet outage signals — IODA (free) + optional Cloudflare Radar."""

from __future__ import annotations

import os
import re
import time

import httpx
from fastapi import APIRouter

import geo_centroids

from feeds.envelope import FeedEnvelope, utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/outages", tags=["outages"])

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT)"}
_IODA = "https://api.ioda.inetintel.cc.gatech.edu/v2"
_CF_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
_CONNECTOR = FeedConnector("outages", ttl_sec=300.0)

_ISO2_ISO3 = {
    "US": "USA", "DE": "DEU", "GB": "GBR", "UK": "GBR", "FR": "FRA", "IT": "ITA",
    "ES": "ESP", "UA": "UKR", "RU": "RUS", "CN": "CHN", "IN": "IND", "BR": "BRA",
    "VE": "VEN", "SY": "SYR", "IR": "IRN", "IL": "ISR", "TR": "TUR", "MX": "MEX",
    "CA": "CAN", "AU": "AUS", "JP": "JPN", "KR": "KOR", "EG": "EGY", "SD": "SDN",
    "MM": "MMR", "YE": "YEM", "PK": "PAK", "AF": "AFG", "NG": "NGA", "ZA": "ZAF",
    "NL": "NLD", "BE": "BEL", "PL": "POL", "SE": "SWE", "NO": "NOR", "FI": "FIN",
}


def _iso2_from_entity(entity: dict, location: str = "") -> str | None:
    etype = (entity.get("type") or "").lower()
    code = str(entity.get("code") or "")
    if etype == "country" and len(code) == 2:
        return code.upper()
    m = re.search(r"-([A-Z]{2})$", code)
    if m:
        return m.group(1)
    m = re.search(r"country/([a-z]{2})", location.lower())
    if m:
        return m.group(1).upper()
    return None


def _coords_for_entity(entity: dict, location: str = "", name: str = "") -> tuple[float | None, float | None]:
    iso2 = _iso2_from_entity(entity, location)
    if iso2 and iso2 in _ISO2_ISO3:
        lat, lon = geo_centroids.resolve_lat_lon(iso3=_ISO2_ISO3[iso2])
        if lat is not None:
            return lat, lon
    lat, lon = geo_centroids.resolve_lat_lon(name=name or entity.get("name") or "")
    return lat, lon


def _parse_ioda_alerts(data: list) -> list[dict]:
    out = []
    for row in data or []:
        if (row.get("level") or "").lower() not in ("critical", "warning"):
            continue
        ent = row.get("entity") or {}
        name = ent.get("name") or ""
        lat, lon = _coords_for_entity(ent, name=name)
        if lat is None:
            continue
        out.append({
            "source": "ioda",
            "title": name[:120],
            "level": row.get("level"),
            "datasource": row.get("datasource"),
            "condition": row.get("condition"),
            "value": row.get("value"),
            "time": row.get("time"),
            "lat": lat,
            "lon": lon,
            "entity_type": ent.get("type"),
        })
    return out


def _parse_ioda_events(data: list, limit: int) -> list[dict]:
    out = []
    for row in sorted(data or [], key=lambda x: -(x.get("score") or 0))[:limit]:
        loc = row.get("location") or ""
        name = row.get("location_name") or loc
        parts = loc.split("/")
        entity = {"type": parts[0] if parts else "", "code": parts[-1] if parts else ""}
        lat, lon = _coords_for_entity(entity, location=loc, name=name)
        if lat is None:
            continue
        dur = int(row.get("duration") or 0)
        out.append({
            "source": "ioda",
            "kind": "event",
            "title": name[:120],
            "score": row.get("score"),
            "duration_sec": dur,
            "duration_h": round(dur / 3600, 1),
            "start": row.get("start"),
            "datasource": row.get("datasource"),
            "lat": lat,
            "lon": lon,
        })
    return out


async def _fetch_ioda(client: httpx.AsyncClient, hours: int, limit: int) -> tuple[list[dict], str | None]:
    until = int(time.time())
    from_ts = until - hours * 3600
    alerts: list[dict] = []
    events: list[dict] = []
    err = None
    try:
        r = await client.get(
            f"{_IODA}/outages/alerts",
            params={"from": from_ts, "until": until, "limit": min(limit * 3, 80)},
            headers=_UA,
            timeout=45.0,
        )
        r.raise_for_status()
        alerts = _parse_ioda_alerts(r.json().get("data"))
    except Exception as e:
        err = f"ioda_alerts: {e}"

    try:
        r = await client.get(
            f"{_IODA}/outages/events",
            params={"from": from_ts, "until": until, "limit": limit},
            headers=_UA,
            timeout=45.0,
        )
        r.raise_for_status()
        events = _parse_ioda_events(r.json().get("data"), limit)
    except Exception as e:
        err = (err + "; " if err else "") + f"ioda_events: {e}"

    merged = events + [a for a in alerts if a not in events]
    return merged[:limit], err


async def _fetch_cloudflare(
    client: httpx.AsyncClient, limit: int, hours: int = 72
) -> tuple[list[dict], str | None]:
    if not _CF_TOKEN:
        return [], "cloudflare: set CLOUDFLARE_API_TOKEN for Radar anomalies (free account)"
    days = max(1, min(30, (hours + 23) // 24))
    try:
        r = await client.get(
            "https://api.cloudflare.com/client/v4/radar/traffic_anomalies",
            params={
                "limit": limit,
                "dateRange": f"{days}d",
            },
            headers={"Authorization": f"Bearer {_CF_TOKEN}", **_UA},
            timeout=30.0,
        )
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            return [], f"cloudflare: {body.get('errors')}"
        out = []
        rows = body.get("result", {}).get("trafficAnomalies") or body.get("result") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            locs = row.get("locations") or {}
            asn_locs = (row.get("asnDetails") or {}).get("locations") or {}
            loc_detail = row.get("locationDetails") or {}
            code = locs.get("code") or asn_locs.get("code") or loc_detail.get("code")
            name = (
                locs.get("name")
                or asn_locs.get("name")
                or loc_detail.get("name")
                or (row.get("asnDetails") or {}).get("name")
                or row.get("title")
                or "Traffic anomaly"
            )
            iso2 = (code or "")[:2].upper() if code else None
            lat, lon = (None, None)
            if iso2 and iso2 in _ISO2_ISO3:
                lat, lon = geo_centroids.resolve_lat_lon(iso3=_ISO2_ISO3[iso2])
            if lat is None:
                lat, lon = geo_centroids.resolve_lat_lon(name=name)
            if lat is None:
                continue
            out.append({
                "source": "cloudflare",
                "title": str(name)[:120],
                "status": row.get("status"),
                "type": row.get("type"),
                "start": row.get("startDate"),
                "end": row.get("endDate"),
                "lat": lat,
                "lon": lon,
            })
        return out[:limit], None
    except Exception as e:
        return [], f"cloudflare: {e}"


async def _fetch_outages(hours: int, limit: int) -> dict:
    notes: list[str] = []
    items: list[dict] = []
    async with httpx.AsyncClient() as client:
        ioda, ioda_err = await _fetch_ioda(client, hours, limit)
        items.extend(ioda)
        if ioda_err:
            notes.append(ioda_err)
        cf, cf_note = await _fetch_cloudflare(client, max(10, limit // 2), hours)
        if cf:
            items.extend(cf)
        elif cf_note:
            notes.append(cf_note)

    geocoded = sum(1 for i in items if i.get("lat") is not None)
    now_iso = utc_now_iso()
    return FeedEnvelope(
        count=len(items),
        sources=["ioda"] + (["cloudflare"] if _CF_TOKEN else []),
        upstream=["ioda.inetintel.cc.gatech.edu"] + (["cloudflare.com/radar"] if _CF_TOKEN else []),
        updated=now_iso,
        cached_at=now_iso,
        geocoded=geocoded,
        error=notes[0] if notes and not items else None,
    ).merge(
        items=items,
        hours=hours,
        notes=notes or None,
    )


@router.get("")
async def internet_outages(hours: int = 72, limit: int = 40):
    """
    Macro internet outages — IODA alerts/events (no key).
    Optional Cloudflare Radar when CLOUDFLARE_API_TOKEN is set.
    """
    subkey = f"outages:{hours}"
    return await _CONNECTOR.run(
        lambda: _fetch_outages(hours, limit),
        subkey=subkey,
    )
