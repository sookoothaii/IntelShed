"""Semantic FtM edges in operator bbox (Track 3+ Sprint 1).

Adds cross-dataset links beyond haversine ``nearby`` proximity:
- samePlace — entities at the same coordinates
- nearEvent — vessel within range of a disaster/event
- sanctioned — vessel matched to sanctions index (optional, async)
"""

from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import ftm_store

DATASET_COLOCATED = "feed-correlation"
DATASET_CONTEXT = "spatial-context"
DATASET_SANCTIONS = "sanctions"


def enabled() -> bool:
    return os.getenv("WORLDBASE_INTEL_SEMANTIC_EDGES", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def sanctions_enabled() -> bool:
    return os.getenv("WORLDBASE_INTEL_SANCTION_EDGES", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _max_km() -> float:
    try:
        return max(5.0, float(os.getenv("WORLDBASE_INTEL_SEMANTIC_MAX_KM", "120")))
    except ValueError:
        return 120.0


def _entity_cap() -> int:
    try:
        return max(20, min(300, int(os.getenv("WORLDBASE_INTEL_SEMANTIC_MAX_ENTITIES", "120"))))
    except ValueError:
        return 120


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _fetch_bbox_entities(
    bbox: list[float],
    *,
    window_hours: int,
    cap: int,
    exclude_schemas: set[str],
) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))).isoformat()
    clauses = [
        "e.lat IS NOT NULL",
        "e.lon IS NOT NULL",
        "e.last_seen IS NOT NULL",
        "e.last_seen >= ?",
        "e.lat BETWEEN ? AND ?",
        "e.lon BETWEEN ? AND ?",
    ]
    params: list[Any] = [cutoff, south, north, west, east]
    if exclude_schemas:
        placeholders = ", ".join("?" * len(exclude_schemas))
        clauses.append(f"e.schema NOT IN ({placeholders})")
        params.extend(sorted(exclude_schemas))
    params.append(cap)
    rows = ftm_store.run_query(
        f"""
        SELECT e.id, e.schema, e.caption, e.lat, e.lon, e.datasets
        FROM entities e
        WHERE {" AND ".join(clauses)}
        ORDER BY e.last_seen DESC
        LIMIT ?
        """,
        params,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat, lon = float(row[3]), float(row[4])
        except (TypeError, ValueError):
            continue
        out.append({
            "id": row[0],
            "schema": row[1],
            "caption": row[2],
            "lat": lat,
            "lon": lon,
            "datasets": row[5],
        })
    return out


def _grid_key(lat: float, lon: float, precision: int = 3) -> tuple[float, float]:
    return round(lat, precision), round(lon, precision)


def link_colocated_entities(
    entities: list[dict[str, Any]],
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    """Link entities sharing the same geogrid cell (cross-dataset duplicates)."""
    if refresh:
        ftm_store.delete_edges_for_dataset(DATASET_COLOCATED)

    groups: dict[tuple[float, float], list[dict[str, Any]]] = {}
    for ent in entities:
        groups.setdefault(_grid_key(ent["lat"], ent["lon"]), []).append(ent)

    edges_added = 0
    seen_at = datetime.now(timezone.utc).isoformat()
    for cell, group in groups.items():
        if len(group) < 2:
            continue
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                if left["id"] == right["id"]:
                    continue
                before = ftm_store.count_edges_for_dataset(DATASET_COLOCATED)
                ftm_store.add_edge(
                    left["id"],
                    right["id"],
                    "samePlace",
                    dataset=DATASET_COLOCATED,
                    confidence=0.92,
                    properties={
                        "method": "geogrid",
                        "cell": list(cell),
                        "schemas": [left.get("schema"), right.get("schema")],
                    },
                    seen_at=seen_at,
                )
                if ftm_store.count_edges_for_dataset(DATASET_COLOCATED) > before:
                    edges_added += 1

    return {
        "ok": True,
        "kind": "samePlace",
        "dataset": DATASET_COLOCATED,
        "cells_with_pairs": sum(1 for g in groups.values() if len(g) > 1),
        "edges_added": edges_added,
    }


def link_vessels_near_events(
    entities: list[dict[str, Any]],
    *,
    max_km: float | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Link AIS vessels to nearby disaster/event entities."""
    limit_km = max_km if max_km is not None else _max_km()
    events = [e for e in entities if e.get("schema") in ("Event", "Thing")]
    vessels = [e for e in entities if e.get("schema") == "Vessel"]
    if refresh:
        ftm_store.delete_edges_for_dataset(DATASET_CONTEXT)

    edges_added = 0
    pairs = 0
    seen_at = datetime.now(timezone.utc).isoformat()
    for vessel in vessels:
        best_event = None
        best_km = limit_km + 1
        for event in events:
            km = _haversine_km(vessel["lat"], vessel["lon"], event["lat"], event["lon"])
            if km <= limit_km and km < best_km:
                best_km = km
                best_event = event
        if not best_event:
            continue
        pairs += 1
        conf = round(max(0.55, 0.95 - (best_km / max(1.0, limit_km)) * 0.35), 3)
        before = ftm_store.count_edges_for_dataset(DATASET_CONTEXT)
        ftm_store.add_edge(
            vessel["id"],
            best_event["id"],
            "nearEvent",
            dataset=DATASET_CONTEXT,
            confidence=conf,
            properties={"distance_km": round(best_km, 2), "method": "haversine"},
            seen_at=seen_at,
        )
        if ftm_store.count_edges_for_dataset(DATASET_CONTEXT) > before:
            edges_added += 1

    return {
        "ok": True,
        "kind": "nearEvent",
        "dataset": DATASET_CONTEXT,
        "vessels_linked": pairs,
        "edges_added": edges_added,
        "max_km": limit_km,
    }


def _sanction_entity_id(hit: dict) -> str:
    sanction = hit.get("sanction") or {}
    raw = str(sanction.get("id") or sanction.get("caption") or hit.get("matched_term") or "")
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"sanctions:{digest}"


async def link_sanction_edges(
    entities: list[dict[str, Any]] | None = None,
    *,
    bbox: list[float] | None = None,
    region: str | None = None,
    window_hours: int = 24,
    min_score: float = 0.85,
    refresh: bool = True,
) -> dict[str, Any]:
    """Write sanctioned edges for vessels in bbox (requires sanctions index / Yente)."""
    if not sanctions_enabled():
        return {"ok": False, "skipped": True, "reason": "disabled"}

    import intel_subgraph
    import sanctions_bridge

    if not ftm_store.init_store():
        return {"ok": False, "edges_added": 0, "error": "ftm unavailable"}

    target_bbox = list(bbox) if bbox else intel_subgraph.operator_bbox(region)
    pool = entities or _fetch_bbox_entities(
        target_bbox,
        window_hours=window_hours,
        cap=_entity_cap(),
        exclude_schemas=intel_subgraph._exclude_schemas(),
    )
    vessels = [
        {
            "mmsi": None,
            "name": v.get("caption"),
            "lat": v.get("lat"),
            "lon": v.get("lon"),
            "_ftm_id": v.get("id"),
        }
        for v in pool
        if v.get("schema") == "Vessel"
    ]
    if not vessels:
        return {"ok": True, "edges_added": 0, "vessels_screened": 0}

    if refresh:
        ftm_store.delete_edges_for_dataset(DATASET_SANCTIONS)

    hits = await sanctions_bridge.screen_vessels(vessels, min_score=min_score)
    edges_added = 0
    seen_at = datetime.now(timezone.utc).isoformat()
    id_by_name = {v.get("caption", "").lower(): v["_ftm_id"] for v in vessels if v.get("caption")}

    for hit in hits:
        vessel_info = hit.get("vessel") or {}
        vessel_id = id_by_name.get((vessel_info.get("name") or "").lower())
        if not vessel_id:
            continue
        sanction = hit.get("sanction") or {}
        sid = _sanction_entity_id(hit)
        caption = str(sanction.get("caption") or sanction.get("name") or "Sanctioned target")[:200]
        proxy = ftm_store._proxy_with_id(sid, "Organization", {"name": [caption]})
        ftm_store.upsert(proxy, dataset=DATASET_SANCTIONS)
        before = ftm_store.count_edges_for_dataset(DATASET_SANCTIONS)
        ftm_store.add_edge(
            vessel_id,
            sid,
            "sanctioned",
            dataset=DATASET_SANCTIONS,
            confidence=float(sanction.get("score") or min_score),
            properties={"matched_term": hit.get("matched_term"), "source": sanction.get("dataset")},
            seen_at=seen_at,
        )
        if ftm_store.count_edges_for_dataset(DATASET_SANCTIONS) > before:
            edges_added += 1

    return {
        "ok": True,
        "dataset": DATASET_SANCTIONS,
        "vessels_screened": len(vessels),
        "hits": len(hits),
        "edges_added": edges_added,
    }


def link_semantic_edges(
    *,
    bbox: list[float] | None = None,
    region: str | None = None,
    window_hours: int = 24,
) -> dict[str, Any]:
    """Rebuild colocated + vessel-event semantic edges in operator bbox."""
    from intel_subgraph import _exclude_schemas, operator_bbox

    if not enabled():
        return {"ok": False, "skipped": True, "reason": "disabled"}
    if not ftm_store.init_store():
        return {"ok": False, "error": ftm_store.store_status().get("error")}

    target_bbox = list(bbox) if bbox else operator_bbox(region)
    entities = _fetch_bbox_entities(
        target_bbox,
        window_hours=window_hours,
        cap=_entity_cap(),
        exclude_schemas=_exclude_schemas(),
    )
    colocated = link_colocated_entities(entities, refresh=True)
    context = link_vessels_near_events(entities, refresh=True)
    return {
        "ok": True,
        "bbox": target_bbox,
        "window_hours": window_hours,
        "entities_scanned": len(entities),
        "colocated": colocated,
        "near_event": context,
        "edges_added": colocated.get("edges_added", 0) + context.get("edges_added", 0),
    }


from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: E402

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/intel/semantic", tags=["intel"])


@router.get("/status")
async def semantic_status():
    return {
        "enabled": enabled(),
        "sanctions_enabled": sanctions_enabled(),
        "max_km": _max_km(),
        "datasets": [DATASET_COLOCATED, DATASET_CONTEXT, DATASET_SANCTIONS],
        "edges": {
            DATASET_COLOCATED: ftm_store.count_edges_for_dataset(DATASET_COLOCATED)
            if ftm_store.init_store()
            else 0,
            DATASET_CONTEXT: ftm_store.count_edges_for_dataset(DATASET_CONTEXT)
            if ftm_store.init_store()
            else 0,
            DATASET_SANCTIONS: ftm_store.count_edges_for_dataset(DATASET_SANCTIONS)
            if ftm_store.init_store()
            else 0,
        },
    }


@router.post("/run")
async def semantic_run(
    window_hours: int = Query(24, ge=1, le=168),
    include_sanctions: bool = Query(True),
    _auth: str | None = Depends(verify_lan_auth),
):
    if not enabled():
        raise HTTPException(status_code=503, detail="semantic intel edges disabled")
    try:
        out = link_semantic_edges(window_hours=window_hours)
        if include_sanctions and sanctions_enabled():
            out["sanctions"] = await link_sanction_edges(window_hours=window_hours)
            out["edges_added"] = out.get("edges_added", 0) + out["sanctions"].get("edges_added", 0)
        return out
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"semantic link failed: {exc}") from exc
