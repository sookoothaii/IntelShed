"""HTTP surface for the FtM entity store.

Thin FastAPI router that delegates to ``ftm_query`` and ``ftm_sanctions``.
Mounted by ``routes/registry.py`` via ``ftm_store.router`` compat re-export.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from auth.security import verify_lan_auth
from ftm_query import (
    entities_for_briefing,
    get_entity,
    get_entity_full,
    graph_overview,
    graph_stats,
    graph_view,
    import_ndjson,
    list_entities_recent,
    stats,
)
from ftm_sanctions import import_sanctions_csv

router = APIRouter(prefix="/api", tags=["intel"])


@router.get("/intel/stats")
async def api_intel_stats():
    try:
        return stats()
    except Exception as exc:  # fail-soft
        return {"entities": 0, "statements": 0, "edges": 0, "error": str(exc)}


@router.get("/intel/entities")
async def api_intel_entities(
    limit: int = Query(50, ge=1, le=500),
    dataset: str | None = Query(None, description="Filter by provenance dataset tag"),
    geolocated: bool = Query(False, description="Only entities with lat/lon seen in window_hours"),
    window_hours: int = Query(24, ge=1, le=168),
):
    """Recent entities (compat route). Set geolocated=1 for FtM globe layer."""
    try:
        if geolocated:
            ents = entities_for_briefing(
                window_hours=window_hours,
                fetch_limit=limit,
                exclude_schemas=["Airplane"],
                include_same_as=False,
            )
            return {"count": len(ents), "entities": ents, "window_hours": window_hours}
        return list_entities_recent(limit, dataset)
    except Exception as exc:
        return {"count": 0, "entities": [], "error": str(exc)}


@router.get("/intel/subgraph")
async def api_intel_subgraph(
    bbox: str | None = Query(None, description="west,south,east,north — default operator region"),
    hops: int = Query(2, ge=1, le=3),
    window_hours: int = Query(24, ge=1, le=168),
    region: str | None = Query(None, description="Operator region preset when bbox omitted"),
):
    """2-hop FtM subgraph seeded by geolocated entities in bbox (Track 3)."""
    import intel_subgraph

    try:
        parsed = intel_subgraph.parse_bbox(bbox)
        return intel_subgraph.build_subgraph(
            bbox=parsed,
            region=region,
            hops=hops,
            window_hours=window_hours,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": str(exc)[:200],
            "error": str(exc)[:200],
            "nodes": [],
            "edges": [],
            "seeds": [],
        }


@router.get("/intel/graph/stats")
async def api_intel_graph_stats():
    """Graph + store roll-up (compat alias — prefer /api/intel/stats for counts only)."""
    try:
        return graph_stats()
    except Exception as exc:
        return {"entities": 0, "edges": 0, "error": str(exc)}


@router.post("/entity/import")
async def api_entity_import(
    request: Request,
    dataset: str = Query("import"),
    _auth: str | None = Depends(verify_lan_auth),
):
    """Round-trip an FtM entity stream (NDJSON, one JSON per line, or a JSON array)."""
    body = await request.body()
    text = body.decode("utf-8", "ignore")
    return await asyncio.to_thread(import_ndjson, text, dataset)


@router.post("/intel/import/sanctions")
async def api_import_sanctions(
    limit: int = Query(5000, ge=1, le=2_000_000),
    schema: str | None = Query(None, description="filter, e.g. Person/Company/Vessel"),
    _auth: str | None = Depends(verify_lan_auth),
):
    return await asyncio.to_thread(import_sanctions_csv, limit, schema)


@router.get("/intel/graph/overview")
async def api_graph_overview(
    limit: int = Query(100, ge=1, le=500),
    datasets: str | None = Query(None, description="Comma-separated dataset tags"),
    schemas: str | None = Query(None, description="Comma-separated FtM schemas"),
):
    ds = [d.strip() for d in datasets.split(",") if d.strip()] if datasets else None
    sch = [s.strip() for s in schemas.split(",") if s.strip()] if schemas else None
    try:
        return graph_overview(limit, ds, sch)
    except Exception as exc:
        return {"found": False, "nodes": [], "edges": [], "error": str(exc)}


@router.get("/entity/{entity_id}/graph")
async def api_entity_graph(
    entity_id: str,
    depth: int = Query(1, ge=1, le=3),
    limit: int = Query(200, ge=1, le=1000),
):
    try:
        return graph_view(entity_id, depth, limit)
    except Exception as exc:
        return {"root": entity_id, "found": False, "nodes": [], "edges": [], "error": str(exc)}


@router.get("/entity/{entity_id}")
async def api_get_entity(entity_id: str):
    """Canonical FtM JSON for one entity (additive to /entity/{id}/context)."""
    try:
        ent = get_entity_full(entity_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:200]}, status_code=503)
    if not ent:
        return {"id": entity_id, "found": False}
    return {**ent, "found": True}
