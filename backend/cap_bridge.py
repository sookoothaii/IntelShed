"""NWS / Meteoalarm hazard alerts — CAP + GeoJSON, no API key."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter

import geo_centroids

router = APIRouter(prefix="/api/hazards", tags=["hazards"])

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT; contact@localhost)"}
_CACHE: dict[str, tuple[float, dict]] = {}

NWS_GEOJSON = "https://api.weather.gov/alerts/active"
METEOALARM_ATOM = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom"

# US state centroids (lat, lon) for CAP entries without geometry
_US_STATE: dict[str, tuple[float, float]] = {
    "alabama": (32.8, -86.8),
    "alaska": (64.2, -152.5),
    "arizona": (34.3, -111.7),
    "arkansas": (34.8, -92.2),
    "california": (36.8, -119.4),
    "colorado": (39.0, -105.5),
    "connecticut": (41.6, -72.7),
    "delaware": (39.0, -75.5),
    "florida": (27.7, -81.7),
    "georgia": (32.2, -83.4),
    "hawaii": (20.8, -156.3),
    "idaho": (44.1, -114.7),
    "illinois": (40.0, -89.0),
    "indiana": (39.8, -86.1),
    "iowa": (42.0, -93.5),
    "kansas": (38.5, -98.4),
    "kentucky": (37.5, -85.3),
    "louisiana": (31.0, -92.0),
    "maine": (45.3, -69.4),
    "maryland": (39.0, -76.8),
    "massachusetts": (42.4, -71.4),
    "michigan": (43.3, -84.5),
    "minnesota": (46.3, -94.3),
    "mississippi": (32.7, -89.7),
    "missouri": (38.5, -92.4),
    "montana": (47.0, -109.6),
    "nebraska": (41.5, -99.8),
    "nevada": (39.3, -116.6),
    "new hampshire": (43.2, -71.5),
    "new jersey": (40.1, -74.7),
    "new mexico": (34.5, -106.0),
    "new york": (43.0, -75.5),
    "north carolina": (35.5, -79.4),
    "north dakota": (47.5, -100.5),
    "ohio": (40.4, -82.8),
    "oklahoma": (35.5, -97.5),
    "oregon": (44.0, -120.5),
    "pennsylvania": (40.9, -77.8),
    "rhode island": (41.7, -71.5),
    "south carolina": (33.9, -81.0),
    "south dakota": (44.4, -100.2),
    "tennessee": (35.8, -86.3),
    "texas": (31.5, -99.3),
    "utah": (39.3, -111.7),
    "vermont": (44.0, -72.7),
    "virginia": (37.5, -78.7),
    "washington": (47.4, -120.5),
    "west virginia": (38.6, -80.6),
    "wisconsin": (44.5, -89.5),
    "wyoming": (43.0, -107.5),
    "district of columbia": (38.9, -77.0),
    "puerto rico": (18.2, -66.5),
}

_SEVERITY_SCORE = {
    "extreme": 0.95,
    "severe": 0.75,
    "moderate": 0.5,
    "minor": 0.3,
    "unknown": 0.35,
}


def _geom_centroid(geom: dict | None) -> tuple[float | None, float | None]:
    if not geom:
        return None, None
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None, None
    points: list[tuple[float, float]] = []

    def ring(c):
        for pt in c:
            if isinstance(pt[0], (int, float)):
                points.append((float(pt[0]), float(pt[1])))
            else:
                ring(pt)

    if gtype == "Point":
        return float(coords[1]), float(coords[0])
    if gtype in ("Polygon", "MultiPolygon"):
        if gtype == "Polygon":
            ring(coords[0] if coords else [])
        else:
            for poly in coords:
                if poly:
                    ring(poly[0])
    if not points:
        return None, None
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def _area_centroid(area_desc: str) -> tuple[float | None, float | None]:
    low = (area_desc or "").lower()
    for state, (lat, lon) in _US_STATE.items():
        if re.search(rf"\b{re.escape(state)}\b", low):
            return lat, lon
    return geo_centroids.resolve_lat_lon(name=area_desc)


def _parse_nws_feature(f: dict) -> dict | None:
    props = f.get("properties") or {}
    event = props.get("event") or props.get("headline") or ""
    if not event:
        return None
    lat, lon = _geom_centroid(f.get("geometry"))
    if lat is None:
        lat, lon = _area_centroid(props.get("areaDesc") or props.get("area_desc") or "")
    sev = (props.get("severity") or "unknown").lower()
    return {
        "event": str(event)[:120],
        "headline": (props.get("headline") or "")[:200],
        "severity": sev,
        "urgency": (props.get("urgency") or "unknown").lower(),
        "score": _SEVERITY_SCORE.get(sev, 0.35),
        "area_desc": (props.get("areaDesc") or "")[:160],
        "effective": (props.get("effective") or props.get("sent") or "")[:32],
        "expires": (props.get("expires") or "")[:32],
        "feed": "nws",
        "lat": lat,
        "lon": lon,
        "link": props.get("@id") or props.get("id"),
    }


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if tag else ""


def _find_cap_text(parent, names: tuple) -> str:
    for el in parent.iter():
        if _local_tag(el.tag) in names and el.text:
            return el.text.strip()
    return ""


def _parse_atom_entry(entry_el, feed_id: str) -> dict | None:
    event = _find_cap_text(entry_el, ("event",))
    severity_raw = _find_cap_text(entry_el, ("severity",)).lower()
    area = _find_cap_text(entry_el, ("areaDesc", "areadesc", "area_desc"))
    headline = _find_cap_text(entry_el, ("headline",))
    if not event and not headline:
        return None
    lat, lon = _area_centroid(area)
    return {
        "event": (event or headline)[:120],
        "headline": headline[:200],
        "severity": severity_raw or "unknown",
        "urgency": _find_cap_text(entry_el, ("urgency",)).lower() or "unknown",
        "score": _SEVERITY_SCORE.get(severity_raw, 0.35),
        "area_desc": area[:160],
        "effective": _find_cap_text(entry_el, ("effective", "sent", "onset"))[:32],
        "expires": _find_cap_text(entry_el, ("expires", ""))[:32],
        "feed": feed_id,
        "lat": lat,
        "lon": lon,
        "link": None,
    }


async def _fetch_nws(client: httpx.AsyncClient, limit: int) -> list[dict]:
    r = await client.get(NWS_GEOJSON, headers={**_UA, "Accept": "application/geo+json"})
    r.raise_for_status()
    out = []
    for f in r.json().get("features") or []:
        row = _parse_nws_feature(f)
        if row and row.get("lat") is not None:
            out.append(row)
        if len(out) >= limit:
            break
    return out


async def _fetch_meteoalarm(client: httpx.AsyncClient, limit: int) -> list[dict]:
    r = await client.get(METEOALARM_ATOM, headers=_UA)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns) or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    out = []
    for entry in entries:
        row = _parse_atom_entry(entry, "meteoalarm")
        if row and row.get("lat") is not None:
            out.append(row)
        if len(out) >= limit:
            break
    return out


@router.get("")
async def hazards_active(limit: int = 80):
    """
    Active weather/hazard alerts (NWS GeoJSON + Meteoalarm CAP).
    Cached 5 minutes. No API key.
    """
    key = "active"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 300:
        return cached[1]

    alerts: list[dict] = []
    errors: list[str] = []
    per_feed = max(20, limit // 2)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            alerts.extend(await _fetch_nws(client, per_feed))
        except Exception as e:
            errors.append(f"nws: {e}")
        try:
            alerts.extend(await _fetch_meteoalarm(client, per_feed))
        except Exception as e:
            errors.append(f"meteoalarm: {e}")

    alerts.sort(key=lambda a: -float(a.get("score") or 0))
    geocoded = sum(1 for a in alerts if a.get("lat") is not None)
    out = {
        "count": len(alerts),
        "geocoded": geocoded,
        "alerts": alerts[:limit],
        "sources": ["nws", "meteoalarm"],
        "errors": errors or None,
        "cached_at": time.time(),
        "source": "nws+meteoalarm",
    }
    _CACHE[key] = (time.time(), out)
    try:
        import feed_registry

        feed_registry.write_auto("hazards", out)
    except Exception:
        pass
    return out
