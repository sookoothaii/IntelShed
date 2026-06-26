"""Semantic FtM edges in operator bbox (Track 3+ Sprint 1).

Adds cross-dataset links beyond haversine ``nearby`` proximity:
- samePlace — entities at the same coordinates
- nearEvent — vessel within range of a disaster/event
- sanctioned — vessel matched to sanctions index (optional, async)
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import ftm_store
from config import get_config

logger = logging.getLogger(__name__)

DATASET_COLOCATED = "feed-correlation"
DATASET_CONTEXT = "spatial-context"
DATASET_SANCTIONS = "sanctions"
DATASET_EVENT_CORRELATION = "event-correlation"

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "in",
        "of",
        "on",
        "at",
        "to",
        "for",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "by",
        "with",
        "from",
        "as",
        "this",
        "that",
        "it",
        "its",
        "has",
        "have",
        "had",
        "not",
        "but",
        "near",
        "off",
        "over",
        "into",
        "than",
        "then",
        "so",
        "if",
        "no",
    }
)


def enabled() -> bool:
    return get_config().intel_semantic_edges_enabled


def sanctions_enabled() -> bool:
    return get_config().intel_sanction_edges_enabled


def _max_km() -> float:
    return max(5.0, get_config().intel_semantic_max_km)


def _entity_cap() -> int:
    return max(20, min(300, get_config().intel_semantic_max_entities))


def _event_corr_max_km() -> float:
    """Max distance for cross-feed event correlation (global events can be far apart)."""
    return max(50.0, get_config().intel_event_corr_max_km)


def _event_corr_min_shared_words() -> int:
    """Min shared caption words for event correlation (1 = country name suffices)."""
    return max(1, get_config().intel_event_corr_min_words)


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
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    ).isoformat()
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
        out.append(
            {
                "id": row[0],
                "schema": row[1],
                "caption": row[2],
                "lat": lat,
                "lon": lon,
                "datasets": row[5],
            }
        )
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
    raw = str(
        sanction.get("id") or sanction.get("caption") or hit.get("matched_term") or ""
    )
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
    id_by_name = {
        v.get("caption", "").lower(): v["_ftm_id"] for v in vessels if v.get("caption")
    }

    for hit in hits:
        vessel_info = hit.get("vessel") or {}
        vessel_id = id_by_name.get((vessel_info.get("name") or "").lower())
        if not vessel_id:
            continue
        sanction = hit.get("sanction") or {}
        sid = _sanction_entity_id(hit)
        caption = str(
            sanction.get("caption") or sanction.get("name") or "Sanctioned target"
        )[:200]
        proxy = ftm_store._proxy_with_id(sid, "Organization", {"name": [caption]})
        ftm_store.upsert(proxy, dataset=DATASET_SANCTIONS)
        before = ftm_store.count_edges_for_dataset(DATASET_SANCTIONS)
        ftm_store.add_edge(
            vessel_id,
            sid,
            "sanctioned",
            dataset=DATASET_SANCTIONS,
            confidence=float(sanction.get("score") or min_score),
            properties={
                "matched_term": hit.get("matched_term"),
                "source": sanction.get("dataset"),
            },
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


def _tokenize_caption(text: str) -> set[str]:
    """Extract significant lowercase word tokens from a caption."""
    import re

    raw = re.split(r"[^a-z0-9]+", (text or "").lower())
    return {w for w in raw if len(w) >= 3 and w not in _STOP_WORDS}


def _datasets_for_entity(ent: dict[str, Any]) -> set[str]:
    """Parse the datasets column (JSON list or comma string) into a set."""
    ds = ent.get("datasets")
    if isinstance(ds, list):
        return {str(d) for d in ds if d}
    if isinstance(ds, str):
        try:
            import json

            parsed = json.loads(ds)
            if isinstance(parsed, list):
                return {str(d) for d in parsed if d}
        except (json.JSONDecodeError, ValueError):
            pass
        return {d.strip() for d in ds.split(",") if d.strip()}
    return set()


def _fetch_events_for_correlation(
    bbox: list[float] | None = None,
    *,
    window_hours: int,
    cap: int = 300,
) -> list[dict[str, Any]]:
    """Fetch Event/Thing entities in bbox (or worldwide if bbox is None)."""
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    ).isoformat()
    if bbox is None:
        rows = ftm_store.run_query(
            """
            SELECT e.id, e.schema, e.caption, e.lat, e.lon, e.datasets
            FROM entities e
            WHERE e.last_seen IS NOT NULL
              AND e.last_seen >= ?
              AND e.schema IN ('Event', 'Thing')
            ORDER BY e.last_seen DESC
            LIMIT ?
            """,
            [cutoff, cap],
        )
    else:
        west, south, east, north = bbox
        rows = ftm_store.run_query(
            """
            SELECT e.id, e.schema, e.caption, e.lat, e.lon, e.datasets
            FROM entities e
            WHERE e.lat IS NOT NULL
              AND e.lon IS NOT NULL
              AND e.last_seen IS NOT NULL
              AND e.last_seen >= ?
              AND e.lat BETWEEN ? AND ?
              AND e.lon BETWEEN ? AND ?
              AND e.schema IN ('Event', 'Thing')
            ORDER BY e.last_seen DESC
            LIMIT ?
            """,
            [cutoff, south, north, west, east, cap],
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            lat = float(row[3]) if row[3] is not None else None
            lon = float(row[4]) if row[4] is not None else None
        except (TypeError, ValueError):
            lat, lon = None, None
        out.append(
            {
                "id": row[0],
                "schema": row[1],
                "caption": row[2],
                "lat": lat,
                "lon": lon,
                "datasets": row[5],
            }
        )
    return out


def link_related_events(
    entities: list[dict[str, Any]],
    *,
    max_km: float | None = None,
    min_shared_words: int | None = None,
    refresh: bool = True,
) -> dict[str, Any]:
    """Link Event entities from different feeds that share caption words + spatial proximity.

    Connects e.g. a GDACS flood alert with a GDELT news event about the same situation
    when they share key terms (e.g. "flood", "Thailand") and are within max_km.
    """
    limit_km = max_km if max_km is not None else _event_corr_max_km()
    if min_shared_words is None:
        min_shared_words = _event_corr_min_shared_words()
    events = [
        e
        for e in entities
        if e.get("schema") in ("Event", "Thing") and e.get("caption")
    ]
    if refresh:
        ftm_store.delete_edges_for_dataset(DATASET_EVENT_CORRELATION)

    # Pre-compute token sets
    for ev in events:
        ev["_tokens"] = _tokenize_caption(ev.get("caption", ""))

    edges_added = 0
    pairs_checked = 0
    text_only_edges = 0
    seen_at = datetime.now(timezone.utc).isoformat()
    for i, left in enumerate(events):
        left_ds = _datasets_for_entity(left)
        left_has_geo = left.get("lat") is not None and left.get("lon") is not None
        for right in events[i + 1 :]:
            right_ds = _datasets_for_entity(right)
            # Skip if from same feed (we want cross-feed correlations only)
            if left_ds and right_ds and (left_ds & right_ds):
                continue
            # Must share enough significant words
            shared = left["_tokens"] & right["_tokens"]
            if len(shared) < min_shared_words:
                continue
            right_has_geo = (
                right.get("lat") is not None and right.get("lon") is not None
            )
            # Spatial proximity check (skip if either event lacks coordinates)
            km = None
            if left_has_geo and right_has_geo:
                km = _haversine_km(left["lat"], left["lon"], right["lat"], right["lon"])
                if km > limit_km:
                    continue
            pairs_checked += 1
            # Confidence: base on word overlap + distance (text-only gets penalty)
            overlap_ratio = len(shared) / max(
                1, min(len(left["_tokens"]), len(right["_tokens"]))
            )
            if km is not None:
                dist_factor = 1.0 - (km / max(1.0, limit_km)) * 0.3
                conf = round(min(0.90, 0.55 + overlap_ratio * 0.3 * dist_factor), 3)
                method = "text_overlap"
            else:
                # Text-only match (one or both events lack coordinates)
                conf = round(min(0.75, 0.40 + overlap_ratio * 0.3), 3)
                method = "text_overlap_no_geo"
                text_only_edges += 1
            before = ftm_store.count_edges_for_dataset(DATASET_EVENT_CORRELATION)
            ftm_store.add_edge(
                left["id"],
                right["id"],
                "relatedEvent",
                dataset=DATASET_EVENT_CORRELATION,
                confidence=conf,
                properties={
                    "method": method,
                    "shared_words": sorted(shared)[:8],
                    "distance_km": round(km, 2) if km is not None else None,
                    "datasets": sorted(left_ds | right_ds)[:4],
                },
                seen_at=seen_at,
            )
            if ftm_store.count_edges_for_dataset(DATASET_EVENT_CORRELATION) > before:
                edges_added += 1

    return {
        "ok": True,
        "kind": "relatedEvent",
        "dataset": DATASET_EVENT_CORRELATION,
        "events_scanned": len(events),
        "pairs_checked": pairs_checked,
        "edges_added": edges_added,
        "text_only_edges": text_only_edges,
        "min_shared_words": min_shared_words,
        "max_km": limit_km,
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
    # Fetch Events globally — they're often outside operator bbox
    event_entities = _fetch_events_for_correlation(None, window_hours=window_hours)
    related = link_related_events(event_entities, refresh=True)
    return {
        "ok": True,
        "bbox": target_bbox,
        "window_hours": window_hours,
        "entities_scanned": len(entities),
        "colocated": colocated,
        "near_event": context,
        "related_events": related,
        "edges_added": colocated.get("edges_added", 0)
        + context.get("edges_added", 0)
        + related.get("edges_added", 0),
    }


from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: E402

from auth.security import verify_lan_auth  # noqa: E402

router = APIRouter(prefix="/api/intel/semantic", tags=["intel"])


@router.get("/status")
async def semantic_status():
    return {
        "enabled": enabled(),
        "sanctions_enabled": sanctions_enabled(),
        "max_km": _max_km(),
        "datasets": [
            DATASET_COLOCATED,
            DATASET_CONTEXT,
            DATASET_SANCTIONS,
            DATASET_EVENT_CORRELATION,
        ],
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
            DATASET_EVENT_CORRELATION: ftm_store.count_edges_for_dataset(
                DATASET_EVENT_CORRELATION
            )
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
            out["edges_added"] = out.get("edges_added", 0) + out["sanctions"].get(
                "edges_added", 0
            )
        return out
    except Exception as exc:
        logger.exception("semantic link failed")
        raise HTTPException(status_code=503, detail="semantic link failed") from exc
