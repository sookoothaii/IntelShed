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
    get_entity_full,
    get_entity_timeline,
    graph_overview,
    graph_stats,
    graph_view,
    import_ndjson,
    list_edges_by_type,
    list_entities_by_schema,
    list_entities_recent,
    stats,
)
from ftm_sanctions import import_sanctions_csv
from runtime_cache import cache_get, cache_set

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
    geolocated: bool = Query(
        False, description="Only entities with lat/lon seen in window_hours"
    ),
    window_hours: int = Query(24, ge=1, le=168),
    schema: str | None = Query(
        None,
        description="Filter by FtM schema name (e.g. Organization, IpAddress, Domain)",
    ),
):
    """Recent entities (compat route). Set geolocated=1 for FtM globe layer.
    Set schema= to filter by entity schema (e.g. IpAddress, Domain, Organization)."""
    try:
        if schema:
            return list_entities_by_schema(schema, limit=limit, dataset=dataset)
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
    bbox: str | None = Query(
        None, description="west,south,east,north — default operator region"
    ),
    hops: int = Query(2, ge=1, le=3),
    window_hours: int = Query(24, ge=1, le=168),
    region: str | None = Query(
        None, description="Operator region preset when bbox omitted"
    ),
):
    """2-hop FtM subgraph seeded by geolocated entities in bbox (Track 3)."""
    import intel_subgraph

    cache_key = f"subgraph:{bbox}:{hops}:{window_hours}:{region}"
    cached = cache_get(cache_key, ttl=30.0)
    if cached is not None:
        return cached

    try:
        parsed = intel_subgraph.parse_bbox(bbox)
        result = await asyncio.to_thread(
            intel_subgraph.build_subgraph,
            bbox=parsed,
            region=region,
            hops=hops,
            window_hours=window_hours,
        )
        cache_set(cache_key, result)
        return result
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
    cache_key = f"entity_graph:{entity_id}:{depth}:{limit}"
    cached = cache_get(cache_key, ttl=30.0)
    if cached is not None:
        return cached
    try:
        result = await asyncio.to_thread(graph_view, entity_id, depth, limit)
        cache_set(cache_key, result)
        return result
    except Exception as exc:
        return {
            "root": entity_id,
            "found": False,
            "nodes": [],
            "edges": [],
            "error": str(exc),
        }


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


# I6: Tiered storage — archive endpoints


@router.post("/intel/archive/run")
async def api_archive_run(dry_run: bool = Query(False)):
    """Trigger FtM archival of stale entities (zero-edge, older than archive_days)."""
    import ftm_archive

    return await asyncio.to_thread(ftm_archive.archive_stale_entities, dry_run)


@router.post("/intel/archive/reload")
async def api_archive_reload(month: str = Query(..., description="YYYY-MM")):
    """Reload archived entities from Parquet back into DuckDB."""
    import ftm_archive

    return await asyncio.to_thread(ftm_archive.reload_archive, month)


@router.get("/intel/archive/stats")
async def api_archive_stats():
    """Archive directory stats."""
    import ftm_archive

    return ftm_archive.archive_stats()


@router.get("/intel/impact")
async def api_impact(entity_id: str):
    """Get full downstream impact for an entity (J4)."""
    import impact_graph

    return impact_graph.get_impact(entity_id)


# ---------------------------------------------------------------------------
# P5 — FtM StatementEntity: per-value provenance API
# ---------------------------------------------------------------------------


@router.get("/intel/statements")
async def api_statements(entity_id: str):
    """Get per-value statements for an entity (P5)."""
    import ftm_query

    return {"statements": ftm_query.get_statements(entity_id)}


@router.get("/intel/statements/conflicts")
async def api_statement_conflicts(entity_id: str):
    """Detect per-value conflicts for an entity (P5)."""
    import ftm_query

    return {
        "entity_id": entity_id,
        "conflicts": ftm_query.detect_value_conflicts(entity_id),
    }


@router.get("/intel/statements/provenance/summary")
async def api_statement_provenance_summary(entity_id: str):
    """Per-entity provenance summary with scored statements (P5)."""
    import ftm_query
    from provenance import statement_provenance_summary

    statements = ftm_query.get_statements(entity_id)
    summary = statement_provenance_summary(statements)
    summary["entity_id"] = entity_id
    return summary


@router.get("/intel/statements/provenance")
async def api_query_provenance(
    dataset: str,
    prop: str | None = None,
    limit: int = 100,
):
    """Query statements by source dataset (P5)."""
    import ftm_query

    return {"results": ftm_query.query_by_provenance(dataset, prop, limit)}


@router.get("/intel/statements/stats")
async def api_statement_stats():
    """Statement table statistics (P5)."""
    import ftm_query

    return ftm_query.statement_stats()


@router.get("/intel/entity/{entity_id}/provenance")
async def api_entity_provenance(entity_id: str):
    """Full per-entity provenance breakdown (P5)."""
    import ftm_query

    return ftm_query.get_entity_provenance(entity_id)


# ---------------------------------------------------------------------------
# P5+ — Dynamic Knowledge Graph: external edge review API
# ---------------------------------------------------------------------------


@router.get("/intel/edges")
async def api_list_edges(
    external: bool = Query(False, description="Only external (review) edges"),
    confirmed: bool | None = None,
    limit: int = 100,
    type: str | None = Query(
        None,
        description="Filter by edge kind (e.g. worksFor, ownsAsset, linkedTo, mentionedIn)",
    ),
    dataset: str | None = Query(None, description="Filter by provenance dataset tag"),
):
    """List edges; set external=1 for P5+ review queue.
    Set type= to filter by edge kind (e.g. worksFor, ownsAsset, linkedTo)."""
    if type:
        try:
            return list_edges_by_type(type, limit=limit, dataset=dataset)
        except Exception as exc:
            return {"count": 0, "edges": [], "error": str(exc)}
    import edge_review

    if external:
        return {
            "edges": edge_review.list_external_edges(confirmed=confirmed, limit=limit)
        }
    # Default: return graph overview edges (no raw edge list available)
    return {"edges": [], "note": "external=1 for review queue, type= for kind filter"}


@router.get("/intel/edges/external")
async def api_list_external_edges(
    confirmed: bool | None = None,
    limit: int = 100,
):
    """List external edges for review (P5+)."""
    import edge_review

    return {"edges": edge_review.list_external_edges(confirmed=confirmed, limit=limit)}


@router.post("/intel/edges/approve")
async def api_approve_edge(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str,
):
    """Approve an external edge (P5+)."""
    import edge_review

    ok = edge_review.approve_edge(source_id, target_id, kind, dataset)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Edge not found"})
    return {"ok": True, "approved": True}


@router.post("/intel/edges/reject")
async def api_reject_edge(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str,
):
    """Reject an external edge — deletes it (P5+)."""
    import edge_review

    ok = edge_review.reject_edge(source_id, target_id, kind, dataset)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Edge not found"})
    return {"ok": True, "rejected": True}


@router.get("/intel/edges/review/stats")
async def api_edge_review_stats():
    """Edge review statistics (P5+)."""
    import edge_review

    return edge_review.edge_review_stats()


# ---------------------------------------------------------------------------
# Session 7 — Entity Timeline
# ---------------------------------------------------------------------------


@router.get("/intel/entities/{entity_id}/timeline")
async def api_entity_timeline(entity_id: str):
    """Chronological timeline for an entity (statements + edges + intel_edges)."""
    try:
        return await asyncio.to_thread(get_entity_timeline, entity_id)
    except Exception as exc:
        return JSONResponse(
            {"entity_id": entity_id, "found": False, "error": str(exc)[:200]},
            status_code=503,
        )
