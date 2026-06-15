"""Fusion heatmap — aggregates every spatial WorldBase signal onto a grid.

This is the "single number per cell" view that turns 6+ independent feeds
into one situational-awareness layer the operator can scan in 2 seconds.

Each input feed contributes weighted points to a regular lat/lon grid; cells
are then ranked, sorted, and returned as both a flat list (great for plotting
canvases or simple SVG) and a coarse GeoJSON FeatureCollection (for any 2D
viewer that can consume polygons).

Inputs (all already cached in their own bridges):

* USGS earthquakes — weighted by magnitude
* GDACS humanitarian alerts — weighted by red/orange/green
* NWS / Meteoalarm hazards — weighted by severity
* Active Holocene volcanoes (Smithsonian) — flat weight, recent eruption boost
* Aircraft anomalies — weighted by emergency squawk
* IODA / Cloudflare outages — flat weight per country centroid
* OpenSky / adsb.lol aircraft *density* (top regional clusters only)

Endpoint: ``GET /api/fusion/heatmap?cell_deg=2.0&top=50&include_geojson=1``

The endpoint is **read-only** and never writes back to the bridges; it just
asyncio.gathers them. A 30s in-memory cache keeps the cost negligible.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/fusion", tags=["fusion-heatmap"])

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0


def _cell_key(lat: float, lon: float, cell_deg: float) -> tuple[float, float]:
    """Snap to the lower-left corner of the containing grid cell."""
    cell_lat = math.floor(lat / cell_deg) * cell_deg
    cell_lon = math.floor(lon / cell_deg) * cell_deg
    return round(cell_lat, 4), round(cell_lon, 4)


def _safe_lat_lon(d: dict) -> tuple[float, float] | None:
    lat = d.get("lat") if "lat" in d else (d.get("location") or {}).get("lat")
    lon = d.get("lon") if "lon" in d else (d.get("location") or {}).get("lon")
    if lat is None or lon is None:
        return None
    try:
        return float(lat), float(lon)
    except (ValueError, TypeError):
        return None


async def _gather_quakes() -> list[dict]:
    """Earthquakes weighted by magnitude (M2.5+). Reads main app endpoint."""
    out: list[dict] = []
    try:
        import main as worldbase_main
        data = await worldbase_main.get_earthquakes(period="day", magnitude="2.5")
    except Exception:
        return []
    for q in (data.get("earthquakes") or [])[:500]:
        ll = _safe_lat_lon(q)
        if not ll:
            continue
        mag = q.get("mag") if q.get("mag") is not None else q.get("magnitude")
        try:
            mag_f = float(mag) if mag is not None else 2.5
        except (ValueError, TypeError):
            mag_f = 2.5
        weight = max(0.5, mag_f - 2.0) ** 1.5
        out.append({
            "lat": ll[0], "lon": ll[1], "weight": weight,
            "source": "quake", "label": f"M{mag_f:.1f} {q.get('place', '')}".strip(),
        })
    return out


async def _gather_gdacs() -> list[dict]:
    out: list[dict] = []
    try:
        import feeds_extra
        data = await feeds_extra.gdacs_alerts()
    except Exception:
        return []
    for a in (data.get("alerts") or [])[:200]:
        ll = _safe_lat_lon(a)
        if not ll:
            continue
        title = (a.get("title") or "").lower()
        w = 6.0 if "red" in title else 3.0 if "orange" in title else 1.5
        out.append({"lat": ll[0], "lon": ll[1], "weight": w, "source": "gdacs", "label": a.get("title", "GDACS alert")})
    return out


async def _gather_hazards() -> list[dict]:
    out: list[dict] = []
    try:
        import cap_bridge
        data = await cap_bridge.hazards_active(limit=300)
    except Exception:
        return []
    for h in (data.get("alerts") or [])[:300]:
        ll = _safe_lat_lon(h)
        if not ll:
            continue
        sev = (h.get("severity") or "").lower()
        w = 5.0 if "extreme" in sev else 3.0 if "severe" in sev else 1.5
        out.append({"lat": ll[0], "lon": ll[1], "weight": w, "source": "hazard", "label": h.get("event") or h.get("headline") or "Hazard"})
    return out


async def _gather_volcanoes() -> list[dict]:
    out: list[dict] = []
    try:
        import volcano_bridge
        data = await volcano_bridge.holocene_volcanoes(active_only=True, limit=400)
    except Exception:
        return []
    for v in (data.get("volcanoes") or [])[:400]:
        ll = _safe_lat_lon(v)
        if not ll:
            continue
        recent = (v.get("last_eruption") or "")
        boost = 2.0 if recent and any(x in str(recent) for x in ("2024", "2025", "2026")) else 1.0
        out.append({"lat": ll[0], "lon": ll[1], "weight": 1.5 * boost, "source": "volcano", "label": v.get("name", "Volcano")})
    return out


async def _gather_anomalies() -> list[dict]:
    out: list[dict] = []
    try:
        import feeds_extra
        data = await feeds_extra.aircraft_anomalies()
    except Exception:
        return []
    for a in (data.get("anomalies") or [])[:200]:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None:
            continue
        reasons = str(a.get("reasons") or "")
        w = 5.0 if "emergency" in reasons.lower() else 2.0
        out.append({"lat": float(lat), "lon": float(lon), "weight": w, "source": "anomaly", "label": f"Anomaly {a.get('callsign') or a.get('icao24', '')}".strip()})
    return out


async def _gather_outages() -> list[dict]:
    """IODA outages — coarse country-level signal only."""
    out: list[dict] = []
    try:
        import outages_bridge
        data = await outages_bridge.internet_outages(hours=72, limit=120)
    except Exception:
        return []
    for o in (data.get("items") or data.get("events") or [])[:120]:
        ll = _safe_lat_lon(o)
        if not ll:
            continue
        out.append({"lat": ll[0], "lon": ll[1], "weight": 2.0, "source": "outage", "label": o.get("name") or o.get("location") or "Outage"})
    return out


async def _gather_pegel() -> list[dict]:
    out: list[dict] = []
    try:
        import pegel_bridge
        data = await pegel_bridge.get_pegel()
    except Exception:
        return []
    for g in (data.get("gauges") or [])[:200]:
        sev = (g.get("severity") or "").lower()
        if sev not in ("high", "critical"):
            continue
        lat, lon = g.get("lat"), g.get("lon")
        if lat is None or lon is None:
            continue
        w = 4.0 if sev == "critical" else 2.5
        out.append({"lat": float(lat), "lon": float(lon), "weight": w, "source": "pegel", "label": f"Pegel {g.get('name')}: {g.get('value')}{g.get('unit', '')}"})
    return out


async def _gather_aircraft_density(cell_deg: float) -> list[dict]:
    """Count aircraft per coarse cell — only feeds back significant clusters."""
    out: list[dict] = []
    try:
        import aircraft_provider
        data = aircraft_provider.last_known_states()
        if not data or not data.get("states"):
            data, _src = await aircraft_provider.fetch_live_states(timeout=10.0)
    except Exception:
        return []
    counts: dict[tuple[float, float], int] = {}
    for s in (data.get("states") or [])[:6000]:
        if not s or len(s) < 7:
            continue
        lon, lat = s[5], s[6]
        if lon is None or lat is None:
            continue
        try:
            k = _cell_key(float(lat), float(lon), cell_deg)
        except (ValueError, TypeError):
            continue
        counts[k] = counts.get(k, 0) + 1
    avg = sum(counts.values()) / max(len(counts), 1)
    thresh = max(15.0, avg * 3)
    for (lat, lon), n in counts.items():
        if n < thresh:
            continue
        out.append({
            "lat": lat + cell_deg / 2,
            "lon": lon + cell_deg / 2,
            "weight": math.log2(n) * 0.5,
            "source": "aircraft_density",
            "label": f"~{n} aircraft / {cell_deg:g}° cell",
        })
    return out


@router.get("/heatmap")
async def fusion_heatmap(
    cell_deg: float = Query(2.0, ge=0.5, le=10.0, description="Grid cell size in degrees"),
    top: int = Query(60, ge=10, le=400, description="Return at most N hottest cells"),
    include_geojson: int = Query(0, ge=0, le=1, description="Include GeoJSON polygons (heavier)"),
):
    """Aggregate every WorldBase spatial feed onto a single intensity grid."""
    cache_key = f"{cell_deg:.2f}|{top}|{include_geojson}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        out = dict(cached[1])
        out["cached"] = True
        return out

    quakes, gdacs, hazards, volcs, anoms, outages, pegel, density = await asyncio.gather(
        _gather_quakes(),
        _gather_gdacs(),
        _gather_hazards(),
        _gather_volcanoes(),
        _gather_anomalies(),
        _gather_outages(),
        _gather_pegel(),
        _gather_aircraft_density(cell_deg),
    )

    all_points = quakes + gdacs + hazards + volcs + anoms + outages + pegel + density
    cells: dict[tuple[float, float], dict] = {}
    for pt in all_points:
        try:
            k = _cell_key(pt["lat"], pt["lon"], cell_deg)
        except (KeyError, TypeError, ValueError):
            continue
        cell = cells.setdefault(k, {
            "lat": k[0] + cell_deg / 2,
            "lon": k[1] + cell_deg / 2,
            "intensity": 0.0,
            "contributions": {},
            "samples": [],
        })
        cell["intensity"] += pt["weight"]
        cell["contributions"][pt["source"]] = cell["contributions"].get(pt["source"], 0) + 1
        if len(cell["samples"]) < 4:
            cell["samples"].append({"source": pt["source"], "label": pt["label"]})

    ranked = sorted(cells.values(), key=lambda c: -c["intensity"])[:top]
    max_intensity = ranked[0]["intensity"] if ranked else 0.0
    for c in ranked:
        c["score"] = round(c["intensity"] / max_intensity, 4) if max_intensity > 0 else 0.0
        c["intensity"] = round(c["intensity"], 4)
        c["sources"] = sorted(c["contributions"].keys())

    payload = {
        "cell_deg": cell_deg,
        "max_intensity": round(max_intensity, 4),
        "total_points": len(all_points),
        "total_cells": len(cells),
        "returned": len(ranked),
        "cells": ranked,
        "contributors": {
            "quakes": len(quakes),
            "gdacs": len(gdacs),
            "hazards": len(hazards),
            "volcanoes": len(volcs),
            "aircraft_anomalies": len(anoms),
            "outages": len(outages),
            "pegel": len(pegel),
            "aircraft_density": len(density),
        },
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }

    if include_geojson and ranked:
        feats = []
        for c in ranked:
            half = cell_deg / 2
            lat, lon = c["lat"], c["lon"]
            ring = [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "score": c["score"],
                    "intensity": c["intensity"],
                    "sources": c["sources"],
                    "contributions": c["contributions"],
                    "samples": c["samples"],
                },
            })
        payload["geojson"] = {"type": "FeatureCollection", "features": feats}

    _CACHE[cache_key] = (now, payload)
    return payload
