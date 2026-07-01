"""Subgraph A/B — compare two intel subgraphs side-by-side.

Generates two subgraphs with different parameters (e.g. different time windows,
hop depths, seed limits, or regions) and computes structural diff metrics:

- Node/edge count delta
- Unique entities per side
- Shared entities (intersection)
- Schema distribution comparison
- Edge type distribution comparison
- Jaccard similarity (nodes, edges)
- Centrality shift (top-K entities by degree)

Endpoints:
  GET /api/subgraph-ab/compare  — run A/B comparison with two parameter sets
  GET /api/subgraph-ab/status   — module status

WORLDBASE_SUBGRAPH_AB=1 enables (default off).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Query
from structured_log import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/subgraph-ab", tags=["subgraph-ab"])


def subgraph_ab_enabled() -> bool:
    return os.getenv("WORLDBASE_SUBGRAPH_AB", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Subgraph fetch (delegates to intel_subgraph.build_subgraph)
# ---------------------------------------------------------------------------


def _fetch_subgraph(params: dict[str, Any]) -> dict[str, Any]:
    """Fetch a subgraph using intel_subgraph.build_subgraph."""
    from intel_subgraph import build_subgraph

    bbox = params.get("bbox")
    if isinstance(bbox, str) and bbox:
        bbox = [float(x.strip()) for x in bbox.split(",")]
        if len(bbox) != 4:
            bbox = None
    elif isinstance(bbox, list) and len(bbox) == 4:
        bbox = [float(x) for x in bbox]
    else:
        bbox = None

    return build_subgraph(
        bbox=bbox,
        region=params.get("region"),
        hops=int(params.get("hops", 2)),
        window_hours=int(params.get("window_hours", 24)),
        seed_limit=int(params.get("seed_limit", 30)),
        node_limit=int(params.get("node_limit", 80)),
    )


# ---------------------------------------------------------------------------
# Comparison metrics
# ---------------------------------------------------------------------------


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _schema_distribution(nodes: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for n in nodes:
        schema = n.get("schema", "Unknown")
        dist[schema] = dist.get(schema, 0) + 1
    return dist


def _edge_type_distribution(edges: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for e in edges:
        etype = e.get("type", e.get("edge_type", "Unknown"))
        dist[etype] = dist.get(etype, 0) + 1
    return dist


def _degree_centrality(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Compute degree centrality for each node."""
    degree: dict[str, int] = {}
    for n in nodes:
        if n.get("id"):
            degree[n["id"]] = 0
    for e in edges:
        src = e.get("source") or e.get("source_id")
        tgt = e.get("target") or e.get("target_id")
        if src in degree:
            degree[src] += 1
        if tgt in degree:
            degree[tgt] += 1
    return degree


def _top_k_by_degree(degree: dict[str, int], k: int = 10) -> list[dict[str, Any]]:
    """Return top-K entities by degree."""
    sorted_items = sorted(degree.items(), key=lambda x: x[1], reverse=True)[:k]
    return [{"id": nid, "degree": deg} for nid, deg in sorted_items]


def compare_subgraphs(
    params_a: dict[str, Any], params_b: dict[str, Any]
) -> dict[str, Any]:
    """Run A/B comparison between two subgraph parameter sets."""
    sg_a = _fetch_subgraph(params_a)
    sg_b = _fetch_subgraph(params_b)

    nodes_a = sg_a.get("nodes", [])
    nodes_b = sg_b.get("nodes", [])
    edges_a = sg_a.get("edges", [])
    edges_b = sg_b.get("edges", [])

    ids_a = {n.get("id") for n in nodes_a if n.get("id")}
    ids_b = {n.get("id") for n in nodes_b if n.get("id")}

    edge_keys_a = {
        (
            e.get("source") or e.get("source_id"),
            e.get("target") or e.get("target_id"),
            e.get("type", e.get("edge_type", "")),
        )
        for e in edges_a
    }
    edge_keys_b = {
        (
            e.get("source") or e.get("source_id"),
            e.get("target") or e.get("target_id"),
            e.get("type", e.get("edge_type", "")),
        )
        for e in edges_b
    }

    shared_nodes = ids_a & ids_b
    unique_a = ids_a - ids_b
    unique_b = ids_b - ids_a
    shared_edges = edge_keys_a & edge_keys_b

    node_jaccard = _jaccard(ids_a, ids_b)
    edge_jaccard = _jaccard(edge_keys_a, edge_keys_b)

    schema_a = _schema_distribution(nodes_a)
    schema_b = _schema_distribution(nodes_b)
    edge_types_a = _edge_type_distribution(edges_a)
    edge_types_b = _edge_type_distribution(edges_b)

    deg_a = _degree_centrality(nodes_a, edges_a)
    deg_b = _degree_centrality(nodes_b, edges_b)
    top_a = _top_k_by_degree(deg_a)
    top_b = _top_k_by_degree(deg_b)

    # Schema delta
    all_schemas = set(schema_a) | set(schema_b)
    schema_delta = {
        s: {
            "a": schema_a.get(s, 0),
            "b": schema_b.get(s, 0),
            "delta": schema_b.get(s, 0) - schema_a.get(s, 0),
        }
        for s in sorted(all_schemas)
    }

    # Edge type delta
    all_edge_types = set(edge_types_a) | set(edge_types_b)
    edge_type_delta = {
        et: {
            "a": edge_types_a.get(et, 0),
            "b": edge_types_b.get(et, 0),
            "delta": edge_types_b.get(et, 0) - edge_types_a.get(et, 0),
        }
        for et in sorted(all_edge_types)
    }

    return {
        "available": True,
        "params_a": params_a,
        "params_b": params_b,
        "metrics": {
            "nodes_a": len(nodes_a),
            "nodes_b": len(nodes_b),
            "edges_a": len(edges_a),
            "edges_b": len(edges_b),
            "shared_nodes": len(shared_nodes),
            "unique_a_nodes": len(unique_a),
            "unique_b_nodes": len(unique_b),
            "shared_edges": len(shared_edges),
            "node_jaccard": round(node_jaccard, 4),
            "edge_jaccard": round(edge_jaccard, 4),
        },
        "schema_distribution": schema_delta,
        "edge_type_distribution": edge_type_delta,
        "top_entities_a": top_a,
        "top_entities_b": top_b,
        "shared_node_ids": list(shared_nodes)[:50],
        "unique_a_node_ids": list(unique_a)[:50],
        "unique_b_node_ids": list(unique_b)[:50],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def status() -> dict[str, Any]:
    return {"enabled": subgraph_ab_enabled()}


@router.get("/compare")
async def compare(
    region_a: str = Query("thailand", description="Region for subgraph A"),
    region_b: str = Query("west-asia", description="Region for subgraph B"),
    hops_a: int = Query(2, ge=1, le=3),
    hops_b: int = Query(2, ge=1, le=3),
    window_a: int = Query(24, ge=1, le=168, alias="window_hours_a"),
    window_b: int = Query(48, ge=1, le=168, alias="window_hours_b"),
    seed_limit_a: int = Query(30, ge=5, le=100),
    seed_limit_b: int = Query(30, ge=5, le=100),
    node_limit_a: int = Query(80, ge=10, le=300),
    node_limit_b: int = Query(80, ge=10, le=300),
) -> dict[str, Any]:
    """Compare two intel subgraphs with different parameters.

    Returns structural diff metrics: node/edge counts, Jaccard similarity,
    schema distribution, edge type distribution, centrality shift.
    """
    if not subgraph_ab_enabled():
        return {
            "available": False,
            "reason": "Subgraph A/B disabled — set WORLDBASE_SUBGRAPH_AB=1",
        }

    params_a = {
        "region": region_a,
        "hops": hops_a,
        "window_hours": window_a,
        "seed_limit": seed_limit_a,
        "node_limit": node_limit_a,
    }
    params_b = {
        "region": region_b,
        "hops": hops_b,
        "window_hours": window_b,
        "seed_limit": seed_limit_b,
        "node_limit": node_limit_b,
    }

    try:
        return compare_subgraphs(params_a, params_b)
    except Exception as e:
        log.error("subgraph_ab_failed", error=repr(e))
        return {
            "available": False,
            "error": str(e),
            "params_a": params_a,
            "params_b": params_b,
        }
