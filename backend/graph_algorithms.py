"""V4-24 Graph Algorithms — NetworkX on the FtM entity graph.

Loads edges from the DuckDB ``edges`` table into a NetworkX ``Graph`` and
computes:

* **PageRank** — iterative link analysis, identifies influential entities
* **Centrality** — degree, betweenness, closeness, eigenvector
* **Community detection** — greedy modularity communities (label propagation
  fallback for very large graphs)

CPU-only, 0 VRAM.  Graph is built on-demand and cached for 5 min.

Feature flag: ``WORLDBASE_GRAPH_ALGORITHMS=1`` (default on).

Endpoints:
    GET /api/graph/algorithms/overview   — graph stats + algorithm availability
    GET /api/graph/algorithms/pagerank   — top-N PageRank entities
    GET /api/graph/algorithms/centrality — top-N by centrality measure
    GET /api/graph/algorithms/communities — community detection results
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Query

from auth.security import verify_api_key
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/graph/algorithms", tags=["graph-algorithms"])

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300.0  # 5 min


def _enabled() -> bool:
    return os.getenv("WORLDBASE_GRAPH_ALGORITHMS", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_MAX_NODES = int(os.getenv("WORLDBASE_GRAPH_MAX_NODES", "50000"))
_MAX_EDGES = int(os.getenv("WORLDBASE_GRAPH_MAX_EDGES", "200000"))


def _load_edges() -> list[tuple[str, str, str, float]]:
    """Load all edges from DuckDB as (source, target, kind, confidence)."""
    from ftm_connection import _ro_conn

    con = _ro_conn()
    rows = con.execute(
        """
        SELECT source_id, target_id, kind, confidence
        FROM edges
        LIMIT ?
        """,
        [_MAX_EDGES],
    ).fetchall()
    return [(r[0], r[1], r[2], float(r[3]) if r[3] is not None else 1.0) for r in rows]


def _load_entity_captions(entity_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Fetch schema + caption for a set of entity IDs."""
    if not entity_ids:
        return {}
    from ftm_connection import _ro_conn

    con = _ro_conn()
    id_list = list(entity_ids)[:_MAX_NODES]
    placeholders = ", ".join("?" * len(id_list))
    rows = con.execute(
        f"""
        SELECT id, schema, caption, lat, lon
        FROM entities
        WHERE id IN ({placeholders})
        """,
        id_list,
    ).fetchall()
    return {
        r[0]: {
            "schema": r[1],
            "caption": r[2],
            "lat": r[3],
            "lon": r[4],
        }
        for r in rows
    }


def build_graph() -> "Any":
    """Build a NetworkX Graph from FtM edges.

    Returns a tuple (graph, edge_count, node_count).
    Caches for _CACHE_TTL seconds.
    """
    import networkx as nx

    cache_key = "graph"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _CACHE_TTL:
        return cached[1]

    edges = _load_edges()
    G = nx.Graph()

    for source, target, kind, confidence in edges:
        if G.has_edge(source, target):
            G[source][target]["weight"] = max(
                G[source][target].get("weight", 0), confidence
            )
            G[source][target]["kinds"].add(kind)
        else:
            G.add_edge(
                source,
                target,
                weight=confidence,
                kinds={kind},
            )

    result = (G, len(edges), G.number_of_nodes())
    _CACHE[cache_key] = (time.time(), result)
    return result


def _enrich_nodes(
    node_ids: list[str], scores: dict[str, float]
) -> list[dict[str, Any]]:
    """Attach entity metadata to scored nodes."""
    captions = _load_entity_captions(set(node_ids))
    out = []
    for nid in node_ids:
        meta = captions.get(nid, {})
        out.append(
            {
                "id": nid,
                "score": round(scores.get(nid, 0.0), 6),
                "schema": meta.get("schema"),
                "caption": meta.get("caption"),
                "lat": meta.get("lat"),
                "lon": meta.get("lon"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Algorithm functions
# ---------------------------------------------------------------------------


def compute_pagerank(top_n: int = 20) -> dict[str, Any]:
    """Compute PageRank and return top-N entities."""
    import networkx as nx

    G, edge_count, node_count = build_graph()
    if node_count == 0:
        return {"enabled": True, "nodes": [], "node_count": 0, "edge_count": 0}

    t0 = time.perf_counter()
    scores = nx.pagerank(G, weight="weight", max_iter=200, tol=1e-6)
    elapsed = round(time.perf_counter() - t0, 3)

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
    nodes = _enrich_nodes([n for n, _ in ranked], scores)

    return {
        "enabled": True,
        "algorithm": "pagerank",
        "node_count": node_count,
        "edge_count": edge_count,
        "elapsed_s": elapsed,
        "nodes": nodes,
    }


def compute_centrality(measure: str = "degree", top_n: int = 20) -> dict[str, Any]:
    """Compute centrality and return top-N entities.

    Supported measures: degree, betweenness, closeness, eigenvector.
    """
    import networkx as nx

    G, edge_count, node_count = build_graph()
    if node_count == 0:
        return {"enabled": True, "nodes": [], "node_count": 0, "edge_count": 0}

    t0 = time.perf_counter()

    if measure == "degree":
        scores = nx.degree_centrality(G)
    elif measure == "betweenness":
        scores = nx.betweenness_centrality(G, weight="weight", k=min(100, node_count))
    elif measure == "closeness":
        scores = nx.closeness_centrality(G, distance="weight")
    elif measure == "eigenvector":
        try:
            scores = nx.eigenvector_centrality(
                G, weight="weight", max_iter=300, tol=1e-6
            )
        except Exception:
            scores = nx.degree_centrality(G)
    else:
        scores = nx.degree_centrality(G)

    elapsed = round(time.perf_counter() - t0, 3)

    ranked = sorted(scores.items(), key=lambda x: -x[1])[:top_n]
    nodes = _enrich_nodes([n for n, _ in ranked], scores)

    return {
        "enabled": True,
        "algorithm": f"centrality_{measure}",
        "measure": measure,
        "node_count": node_count,
        "edge_count": edge_count,
        "elapsed_s": elapsed,
        "nodes": nodes,
    }


def compute_communities(top_n: int = 10, min_size: int = 3) -> dict[str, Any]:
    """Detect communities using greedy modularity maximization.

    Falls back to label propagation for very large graphs.
    Returns top-N communities by size, with member entity IDs.
    """
    import networkx as nx

    G, edge_count, node_count = build_graph()
    if node_count == 0:
        return {"enabled": True, "communities": [], "node_count": 0, "edge_count": 0}

    t0 = time.perf_counter()

    if node_count > 10000:
        communities_gen = nx.algorithms.community.label_propagation_communities(G)
        communities_list = list(communities_gen)
        method = "label_propagation"
    else:
        communities_list = nx.algorithms.community.greedy_modularity_communities(
            G, weight="weight"
        )
        method = "greedy_modularity"

    elapsed = round(time.perf_counter() - t0, 3)

    # Sort by size descending
    communities_list.sort(key=len, reverse=True)

    result_communities = []
    for i, comm in enumerate(communities_list[:top_n]):
        members = list(comm)
        if len(members) < min_size:
            break

        # Get entity metadata for first few members
        captions = _load_entity_captions(set(members[:20]))
        member_info = []
        for mid in members[:20]:
            meta = captions.get(mid, {})
            member_info.append(
                {
                    "id": mid,
                    "schema": meta.get("schema"),
                    "caption": meta.get("caption"),
                }
            )

        result_communities.append(
            {
                "index": i,
                "size": len(members),
                "members_sample": member_info,
                "member_ids": members[:50],
            }
        )

    return {
        "enabled": True,
        "algorithm": "community_detection",
        "method": method,
        "node_count": node_count,
        "edge_count": edge_count,
        "total_communities": len(communities_list),
        "elapsed_s": elapsed,
        "communities": result_communities,
    }


def graph_overview() -> dict[str, Any]:
    """Overview of graph stats and algorithm availability."""
    G, edge_count, node_count = build_graph()

    import networkx as nx

    density = nx.density(G) if node_count > 0 else 0
    connected = nx.is_connected(G) if node_count > 0 else False
    components = nx.number_connected_components(G) if node_count > 0 else 0

    return {
        "enabled": _enabled(),
        "node_count": node_count,
        "edge_count": edge_count,
        "density": round(density, 6),
        "is_connected": connected,
        "components": components,
        "algorithms": ["pagerank", "centrality", "communities"],
        "cache_ttl_s": _CACHE_TTL,
    }


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get("/overview")
async def overview_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    if not _enabled():
        return {
            "enabled": False,
            "error": "Graph algorithms disabled. Set WORLDBASE_GRAPH_ALGORITHMS=1.",
        }
    try:
        return graph_overview()
    except Exception as exc:
        log.warning("graph_overview_failed", error=str(exc)[:200])
        return {"enabled": True, "error": str(exc)[:200]}


@router.get("/pagerank")
async def pagerank_endpoint(
    top: int = Query(20, ge=1, le=200),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    if not _enabled():
        return {"enabled": False, "nodes": []}
    try:
        return compute_pagerank(top_n=top)
    except Exception as exc:
        log.warning("pagerank_failed", error=str(exc)[:200])
        return {"enabled": True, "error": str(exc)[:200], "nodes": []}


@router.get("/centrality")
async def centrality_endpoint(
    measure: str = Query(
        "degree",
        pattern="^(degree|betweenness|closeness|eigenvector)$",
    ),
    top: int = Query(20, ge=1, le=200),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    if not _enabled():
        return {"enabled": False, "nodes": []}
    try:
        return compute_centrality(measure=measure, top_n=top)
    except Exception as exc:
        log.warning("centrality_failed", error=str(exc)[:200])
        return {"enabled": True, "error": str(exc)[:200], "nodes": []}


@router.get("/communities")
async def communities_endpoint(
    top: int = Query(10, ge=1, le=50),
    min_size: int = Query(3, ge=2, le=100),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    if not _enabled():
        return {"enabled": False, "communities": []}
    try:
        return compute_communities(top_n=top, min_size=min_size)
    except Exception as exc:
        log.warning("communities_failed", error=str(exc)[:200])
        return {"enabled": True, "error": str(exc)[:200], "communities": []}
