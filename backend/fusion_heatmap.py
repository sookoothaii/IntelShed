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
import json
import math
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/fusion", tags=["fusion-heatmap"])

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0
_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_SNAPSHOT_INTERVAL_S = float(
    os.getenv("WORLDBASE_FUSION_SNAPSHOT_INTERVAL_S", str(6 * 3600))
)
_COMPARE_TOLERANCE_H = float(os.getenv("WORLDBASE_FUSION_COMPARE_TOLERANCE_H", "3"))
_MAX_SNAPSHOT_AGE_D = float(os.getenv("WORLDBASE_FUSION_SNAPSHOT_RETAIN_D", "14"))
_COMPARE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*h(?:ours?)?$", re.I)


def _cell_key(lat: float, lon: float, cell_deg: float) -> tuple[float, float]:
    """Snap to the lower-left corner of the containing grid cell."""
    cell_lat = math.floor(lat / cell_deg) * cell_deg
    cell_lon = math.floor(lon / cell_deg) * cell_deg
    return round(cell_lat, 4), round(cell_lon, 4)


def fusion_cell_id(lat: float | None, lon: float | None) -> str | None:
    """Stable cell id (center lat/lon) — matches operator_briefing watch items."""
    if lat is None or lon is None:
        return None
    return f"{float(lat):.2f},{float(lon):.2f}"


def parse_compare_hours(compare: str | None) -> float | None:
    """Parse compare query values like ``24h`` or ``6hours``."""
    if not compare or not str(compare).strip():
        return None
    m = _COMPARE_RE.match(str(compare).strip())
    if not m:
        return None
    try:
        hours = float(m.group(1))
    except ValueError:
        return None
    return hours if hours > 0 else None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_fusion_snapshots_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fusion_grid_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cell_deg REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fusion_grid_snapshots_deg_time
                ON fusion_grid_snapshots(cell_deg, recorded_at);
        """)
        conn.commit()


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _compact_cells(cells: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in cells:
        lat, lon = c.get("lat"), c.get("lon")
        cid = c.get("cell_id") or fusion_cell_id(lat, lon)
        if not cid:
            continue
        out.append(
            {
                "cell_id": cid,
                "lat": lat,
                "lon": lon,
                "score": c.get("score"),
                "intensity": c.get("intensity"),
                "sources": c.get("sources") or [],
            }
        )
    return out


def _last_snapshot_at(cell_deg: float) -> datetime | None:
    init_fusion_snapshots_db()
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT recorded_at FROM fusion_grid_snapshots
            WHERE cell_deg = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (round(cell_deg, 4),),
        ).fetchone()
    return _parse_ts(row["recorded_at"]) if row else None


def record_snapshot_if_due(
    cell_deg: float, cells: list[dict], *, now: datetime | None = None
) -> bool:
    """Persist fusion grid snapshot at most every 6h (configurable). Returns True if stored."""
    now = now or datetime.now(timezone.utc)
    last = _last_snapshot_at(cell_deg)
    if last and (now - last).total_seconds() < _SNAPSHOT_INTERVAL_S:
        return False
    compact = _compact_cells(cells)
    if not compact:
        return False
    init_fusion_snapshots_db()
    payload = json.dumps({"cells": compact}, ensure_ascii=False, separators=(",", ":"))
    with _conn() as conn:
        conn.execute(
            "INSERT INTO fusion_grid_snapshots (cell_deg, recorded_at, payload) VALUES (?, ?, ?)",
            (round(cell_deg, 4), now.isoformat(), payload),
        )
        cutoff = (now - timedelta(days=_MAX_SNAPSHOT_AGE_D)).isoformat()
        conn.execute(
            "DELETE FROM fusion_grid_snapshots WHERE cell_deg = ? AND recorded_at < ?",
            (round(cell_deg, 4), cutoff),
        )
        conn.commit()
    return True


def _load_snapshot_near(cell_deg: float, target: datetime) -> dict | None:
    init_fusion_snapshots_db()
    tol = timedelta(hours=_COMPARE_TOLERANCE_H)
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT recorded_at, payload FROM fusion_grid_snapshots
            WHERE cell_deg = ?
            ORDER BY recorded_at DESC
            LIMIT 80
            """,
            (round(cell_deg, 4),),
        ).fetchall()
    best: dict | None = None
    best_delta = float("inf")
    for row in rows:
        ts = _parse_ts(row["recorded_at"])
        if not ts:
            continue
        delta = abs((ts - target).total_seconds())
        if delta > tol.total_seconds():
            continue
        if delta < best_delta:
            best_delta = delta
            try:
                payload = json.loads(row["payload"])
            except Exception:
                continue
            best = {
                "recorded_at": row["recorded_at"],
                "cells": payload.get("cells") or [],
            }
    return best


def apply_compare(
    cells: list[dict], cell_deg: float, compare_hours: float
) -> dict[str, Any]:
    """Attach baseline_score and delta_score to cells vs snapshot near now-compare_hours."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(hours=compare_hours)
    baseline = _load_snapshot_near(cell_deg, target)
    baseline_map = {
        c["cell_id"]: c for c in (baseline or {}).get("cells") or [] if c.get("cell_id")
    }
    top_delta: dict | None = None
    for c in cells:
        cid = c.get("cell_id") or fusion_cell_id(c.get("lat"), c.get("lon"))
        c["cell_id"] = cid
        base = baseline_map.get(cid) if cid else None
        if base is not None:
            try:
                b_score = float(base.get("score") or 0)
                c_score = float(c.get("score") or 0)
            except (TypeError, ValueError):
                b_score, c_score = 0.0, 0.0
            c["baseline_score"] = round(b_score, 4)
            c["delta_score"] = round(c_score - b_score, 4)
        elif cid and float(c.get("score") or 0) >= 0.35:
            c["baseline_score"] = None
            c["delta_score"] = round(float(c.get("score") or 0), 4)
        else:
            c["baseline_score"] = None
            c["delta_score"] = None
        ds = c.get("delta_score")
        if ds is not None and (
            top_delta is None or ds > top_delta.get("delta_score", -1)
        ):
            top_delta = {
                "cell_id": cid,
                "delta_score": ds,
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "score": c.get("score"),
            }
    snapshots_stored = 0
    init_fusion_snapshots_db()
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM fusion_grid_snapshots WHERE cell_deg = ?",
            (round(cell_deg, 4),),
        ).fetchone()
        snapshots_stored = int(row["n"]) if row else 0
    return {
        "hours": compare_hours,
        "available": baseline is not None,
        "baseline_at": (baseline or {}).get("recorded_at"),
        "target_at": target.isoformat(),
        "snapshots_stored": snapshots_stored,
        "top_delta": top_delta,
    }


def extract_delta_watch_cells(
    cells: list[dict],
    *,
    min_delta: float = 0.12,
    top: int = 5,
) -> list[dict]:
    """Cells with meaningful positive delta for anticipatory watch items."""
    ranked = [
        c
        for c in cells
        if c.get("delta_score") is not None and float(c["delta_score"]) >= min_delta
    ]
    ranked.sort(key=lambda x: -float(x.get("delta_score") or 0))
    return ranked[:top]


def fusion_compare_summary(cell_deg: float = 2.0, compare_hours: float = 24.0) -> dict:
    """Lightweight compare meta for trust probes (uses last in-memory grid if fresh)."""
    now_ts = time.time()
    prefix = f"{cell_deg:.2f}|"
    cells: list[dict] = []
    for key, (cached_at, payload) in _CACHE.items():
        if not key.startswith(prefix):
            continue
        if (now_ts - cached_at) >= _CACHE_TTL:
            continue
        cells = list(payload.get("cells") or [])
        if cells:
            break
    if not cells:
        return {
            "available": False,
            "hours": compare_hours,
            "detail": "no recent grid cache",
            "snapshots_stored": 0,
        }
    meta = apply_compare([dict(c) for c in cells], cell_deg, compare_hours)
    top = meta.get("top_delta")
    detail = "no baseline yet"
    if meta.get("available") and top:
        detail = f"top Δ={top.get('delta_score')} cell={top.get('cell_id')}"
    elif meta.get("available"):
        detail = "baseline ok, no rising cells"
    return {
        "available": bool(meta.get("available")),
        "hours": compare_hours,
        "baseline_at": meta.get("baseline_at"),
        "snapshots_stored": meta.get("snapshots_stored", 0),
        "top_delta": top,
        "detail": detail,
    }


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
        from routes.core_feeds import get_earthquakes

        data = await get_earthquakes(period="day", magnitude="2.5")
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
        out.append(
            {
                "lat": ll[0],
                "lon": ll[1],
                "weight": weight,
                "source": "quake",
                "label": f"M{mag_f:.1f} {q.get('place', '')}".strip(),
            }
        )
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
        out.append(
            {
                "lat": ll[0],
                "lon": ll[1],
                "weight": w,
                "source": "gdacs",
                "label": a.get("title", "GDACS alert"),
            }
        )
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
        out.append(
            {
                "lat": ll[0],
                "lon": ll[1],
                "weight": w,
                "source": "hazard",
                "label": h.get("event") or h.get("headline") or "Hazard",
            }
        )
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
        recent = v.get("last_eruption") or ""
        boost = (
            2.0
            if recent and any(x in str(recent) for x in ("2024", "2025", "2026"))
            else 1.0
        )
        out.append(
            {
                "lat": ll[0],
                "lon": ll[1],
                "weight": 1.5 * boost,
                "source": "volcano",
                "label": v.get("name", "Volcano"),
            }
        )
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
        out.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "weight": w,
                "source": "anomaly",
                "label": f"Anomaly {a.get('callsign') or a.get('icao24', '')}".strip(),
            }
        )
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
        out.append(
            {
                "lat": ll[0],
                "lon": ll[1],
                "weight": 2.0,
                "source": "outage",
                "label": o.get("name") or o.get("location") or "Outage",
            }
        )
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
        out.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "weight": w,
                "source": "pegel",
                "label": f"Pegel {g.get('name')}: {g.get('value')}{g.get('unit', '')}",
            }
        )
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
        out.append(
            {
                "lat": lat + cell_deg / 2,
                "lon": lon + cell_deg / 2,
                "weight": math.log2(n) * 0.5,
                "source": "aircraft_density",
                "label": f"~{n} aircraft / {cell_deg:g}° cell",
            }
        )
    return out


async def _compute_grid(cell_deg: float, top: int) -> tuple[list[dict], dict, int, int]:
    """Gather feeds, aggregate grid — returns (ranked_cells, contributors, total_points, total_cells)."""
    (
        quakes,
        gdacs,
        hazards,
        volcs,
        anoms,
        outages,
        pegel,
        density,
    ) = await asyncio.gather(
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

    # P4: apply source reliability weighting when provenance enabled
    try:
        from provenance import provenance_enabled, feed_fusion_weight

        _use_provenance = provenance_enabled()
    except Exception:
        _use_provenance = False

    cells: dict[tuple[float, float], dict] = {}
    for pt in all_points:
        try:
            k = _cell_key(pt["lat"], pt["lon"], cell_deg)
        except (KeyError, TypeError, ValueError):
            continue
        cell = cells.setdefault(
            k,
            {
                "lat": k[0] + cell_deg / 2,
                "lon": k[1] + cell_deg / 2,
                "intensity": 0.0,
                "contributions": {},
                "samples": [],
            },
        )
        weight = pt["weight"]
        if _use_provenance:
            weight = feed_fusion_weight(pt["source"], weight)
        cell["intensity"] += weight
        cell["contributions"][pt["source"]] = (
            cell["contributions"].get(pt["source"], 0) + 1
        )
        if len(cell["samples"]) < 4:
            cell["samples"].append({"source": pt["source"], "label": pt["label"]})

    ranked = sorted(cells.values(), key=lambda c: -c["intensity"])[:top]
    max_intensity = ranked[0]["intensity"] if ranked else 0.0
    for c in ranked:
        c["score"] = (
            round(c["intensity"] / max_intensity, 4) if max_intensity > 0 else 0.0
        )
        c["intensity"] = round(c["intensity"], 4)
        c["sources"] = sorted(c["contributions"].keys())
        c["cell_id"] = fusion_cell_id(c["lat"], c["lon"])

    contributors = {
        "quakes": len(quakes),
        "gdacs": len(gdacs),
        "hazards": len(hazards),
        "volcanoes": len(volcs),
        "aircraft_anomalies": len(anoms),
        "outages": len(outages),
        "pegel": len(pegel),
        "aircraft_density": len(density),
    }
    return ranked, contributors, len(all_points), len(cells)


@router.get("/heatmap")
async def fusion_heatmap(
    cell_deg: float = Query(
        2.0, ge=0.5, le=10.0, description="Grid cell size in degrees"
    ),
    top: int = Query(60, ge=10, le=400, description="Return at most N hottest cells"),
    include_geojson: int = Query(
        0, ge=0, le=1, description="Include GeoJSON polygons (heavier)"
    ),
    compare: str | None = Query(
        None,
        description="Compare to grid snapshot N hours ago (e.g. 24h) — adds delta_score per cell",
    ),
):
    """Aggregate every WorldBase spatial feed onto a single intensity grid."""
    compare_hours = parse_compare_hours(compare)
    cache_key = f"{cell_deg:.2f}|{top}|{include_geojson}|{compare_hours or ''}"
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        out = dict(cached[1])
        out["cached"] = True
        return out

    ranked, contributors, total_points, total_cells = await _compute_grid(cell_deg, top)
    record_snapshot_if_due(cell_deg, ranked)

    compare_meta: dict | None = None
    if compare_hours is not None:
        compare_meta = apply_compare(ranked, cell_deg, compare_hours)
        ranked.sort(
            key=lambda c: -(
                abs(float(c.get("delta_score") or 0))
                if c.get("delta_score") is not None
                else float(c.get("score") or 0)
            ),
        )

    max_intensity = ranked[0]["intensity"] if ranked else 0.0
    payload = {
        "cell_deg": cell_deg,
        "max_intensity": round(max_intensity, 4),
        "total_points": total_points,
        "total_cells": total_cells,
        "returned": len(ranked),
        "cells": ranked,
        "contributors": contributors,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }
    if compare_meta is not None:
        payload["compare"] = compare_meta

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
            feats.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "score": c["score"],
                        "intensity": c["intensity"],
                        "sources": c["sources"],
                        "contributions": c["contributions"],
                        "samples": c["samples"],
                    },
                }
            )
        payload["geojson"] = {"type": "FeatureCollection", "features": feats}

    _CACHE[cache_key] = (now, payload)
    return payload


def _lat_lon_label(lat: float, lon: float) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.1f}°{ns} {abs(lon):.1f}°{ew}"


def format_hotspots_for_llm(cells: list[dict], top: int = 3) -> str:
    """Top fusion-grid cells as plain text for LLM briefing / chat context."""
    if not cells:
        return "- No ranked fusion hotspots."
    lines: list[str] = []
    for i, c in enumerate(cells[:top], 1):
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        score = c.get("score", 0)
        sources = ", ".join(c.get("sources") or [])
        samples = "; ".join(
            (s.get("label") or "")[:60]
            for s in (c.get("samples") or [])[:2]
            if s.get("label")
        )
        tail = f" — {samples}" if samples else ""
        lines.append(
            f"- #{i} {_lat_lon_label(float(lat), float(lon))} score={score:.2f} "
            f"[{sources}]{tail}"
        )
    return "\n".join(lines) or "- No ranked fusion hotspots."


def rank_cells_for_operator(cells: list[dict], *, top: int = 3) -> list[dict]:
    """Re-rank fusion cells: operator home region first, then ASEAN, then global."""
    from operator_briefing import (
        OPERATOR_REGION,
        _ASEAN_BBOX,
        _region_bbox,
        classify_item,
    )

    local_bbox = _region_bbox(OPERATOR_REGION)
    regional_bbox = _ASEAN_BBOX if OPERATOR_REGION == "thailand" else local_bbox

    def _tier(cell: dict) -> int:
        lat, lon = cell.get("lat"), cell.get("lon")
        if lat is None or lon is None:
            return 3
        bucket = classify_item(float(lat), float(lon), "", local_bbox, regional_bbox)
        return {"local": 0, "regional": 1, "global": 2}.get(bucket, 2)

    ranked = sorted(
        cells,
        key=lambda c: (
            _tier(c),
            -float(c.get("score") or 0),
            -float(c.get("intensity") or 0),
        ),
    )
    return ranked[:top]


def slim_hotspot_cells(cells: list[dict], top: int = 3) -> list[dict]:
    """Compact fusion cells for JSON (briefing sources, Pi pull)."""
    out: list[dict] = []
    for c in cells[:top]:
        lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        out.append(
            {
                "lat": lat,
                "lon": lon,
                "score": c.get("score"),
                "intensity": c.get("intensity"),
                "sources": c.get("sources") or [],
                "cell_id": c.get("cell_id"),
                "delta_score": c.get("delta_score"),
                "samples": [
                    {"source": s.get("source"), "label": (s.get("label") or "")[:80]}
                    for s in (c.get("samples") or [])[:2]
                ],
            }
        )
    return out


async def top_hotspots_for_llm(
    cell_deg: float = 2.0,
    top: int = 3,
    *,
    compare_hours: float | None = 24.0,
) -> tuple[list[dict], str, list[dict]]:
    """Fetch ranked fusion cells, LLM text, and delta-ranked cells for watch items."""
    compare_arg = f"{compare_hours:g}h" if compare_hours else None
    data = await fusion_heatmap(
        cell_deg=cell_deg,
        top=max(top, 10),
        include_geojson=0,
        compare=compare_arg,
    )
    cells = (data.get("cells") or [])[: max(top, 10)]
    operator_cells = rank_cells_for_operator(cells, top=top)
    deltas = extract_delta_watch_cells(cells, top=top)
    return (
        slim_hotspot_cells(operator_cells, top=top),
        format_hotspots_for_llm(operator_cells, top=top),
        deltas,
    )
