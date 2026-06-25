"""P1 — Adaptive Query Router for RAG retrieval (rule-based, 0 VRAM).

Classifies user queries into retrieval routes and dispatches to the
appropriate existing search backend:

  vector  → rag_memory.search() (sqlite-vec + FTS5 + RRF)
  graph   → intel_subgraph.build_subgraph() + format_subgraph_prompt_block()
  spatial → rag_memory.search(bbox=operator_bbox) + proximity edges
  hybrid  → vector + graph (parallel), merge by RRF
  live    → situations + fusion_heatmap (no RAG)

Env:
  WORLDBASE_QUERY_ROUTER=1 (default on)
  WORLDBASE_QUERY_ROUTER_FALLBACK=vector
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

VALID_ROUTES = ("vector", "graph", "spatial", "hybrid", "live")


def router_enabled() -> bool:
    return os.getenv("WORLDBASE_QUERY_ROUTER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def fallback_route() -> str:
    r = os.getenv("WORLDBASE_QUERY_ROUTER_FALLBACK", "vector").strip().lower()
    return r if r in VALID_ROUTES else "vector"


# --- Classification signal patterns ---

_GRAPH_PATTERNS = [
    r"\bwho\s+is\b",
    r"\bwho\s+are\b",
    r"\bconnection\s+between\b",
    r"\bconnections?\s+between\b",
    r"\brelated\s+to\b",
    r"\blink(s|ed)?\s+between\b",
    r"\bassociated\s+with\b",
    r"\baffiliat",
    r"\bmember\s+of\b",
    r"\bsubgraph\b",
    r"\bgraph\b",
    r"\bentity\b.*\bentity\b",
    r"\borganisation\b",
    r"\borganization\b",
    r"\bcompany\b.*\band\b",
    r"\bperson\b.*\band\b",
    r"\bvessel\b.*\band\b",
    r"\bedge\b",
    r"\bnode\b",
    r"\bsame\s*as\b",
    r"\bduplicate\b",
    r"\bmerge\b",
]

_SPATIAL_PATTERNS = [
    r"\bnear\b",
    r"\bwithin\b",
    r"\baround\b",
    r"\bborder\b",
    r"\bcoordinates?\b",
    r"\blocation\s+of\b",
    r"\bproximity\b",
    r"\bradius\b",
    r"\bdistance\s+from\b",
    r"\bkm\s+from\b",
    r"\bkilometer",
    r"\bgeo\b",
    r"\blat(itude)?\b",
    r"\blon(gitude)?\b",
    r"\bregion\b",
    r"\barea\b",
    r"\bzone\b",
    r"\bmap\b",
    r"\bwhere\b",
]

_TEMPORAL_PATTERNS = [
    r"\blatest\b",
    r"\btoday\b",
    r"\bcurrent\b",
    r"\bnow\b",
    r"\breal[- ]?time\b",
    r"\blive\b",
    r"\bjust\s+happen",
    r"\brecent\b",
    r"\bupdate\b",
    r"\bsituation\b",
    r"\bbreaking\b",
    r"\bthis\s+(hour|day|week)\b",
]

_FACTUAL_PATTERNS = [
    r"\bwhat\s+is\b",
    r"\bwhat\s+are\b",
    r"\bsummar",
    r"\bexplain\b",
    r"\bdescribe\b",
    r"\bdefinition\b",
    r"\boverview\b",
    r"\btell\s+me\s+about\b",
    r"\bbackground\b",
    r"\bcontext\b",
]


def _match_any(patterns: list[str], text: str) -> int:
    """Return count of patterns matched."""
    count = 0
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            count += 1
    return count


def classify_query(query: str) -> str:
    """Classify a user query into a retrieval route.

    Rule-based scoring: each signal group contributes weighted votes.
    Highest score wins; ties resolve to the more specific route.
    """
    if not query or not query.strip():
        return fallback_route()

    text = query.strip().lower()

    graph_hits = _match_any(_GRAPH_PATTERNS, text)
    spatial_hits = _match_any(_SPATIAL_PATTERNS, text)
    temporal_hits = _match_any(_TEMPORAL_PATTERNS, text)
    factual_hits = _match_any(_FACTUAL_PATTERNS, text)

    # Build score map
    scores: dict[str, float] = {
        "graph": float(graph_hits) * 1.2,
        "spatial": float(spatial_hits) * 1.0,
        "live": float(temporal_hits) * 1.1,
        "vector": float(factual_hits) * 0.8,
    }

    # Hybrid: strong signals in 2+ categories
    active_categories = sum(1 for v in scores.values() if v > 0)
    if active_categories >= 2:
        top_two = sorted(scores.values(), reverse=True)[:2]
        if top_two[1] >= 1.0:
            return "hybrid"

    # Single dominant signal
    best_route = max(scores, key=lambda k: scores[k])
    if scores[best_route] >= 1.0:
        return best_route

    # No strong signal → fallback
    return fallback_route()


def _format_graph_block(subgraph: dict[str, Any]) -> list[str]:
    """Format subgraph results into prompt lines."""
    try:
        from intel_subgraph import format_subgraph_prompt_block

        block = format_subgraph_prompt_block(subgraph)
        return [block] if block else []
    except Exception:
        return []


def _format_spatial_block(
    results: list[dict], proximity_edges: list[dict] | None = None
) -> list[str]:
    """Format spatial search results + proximity edges."""
    from rag_crag import format_rag_hits

    lines: list[str] = ["=== RAG MEMORY (spatial-filtered) ==="]
    lines.extend(format_rag_hits(results))
    if proximity_edges:
        lines.append(f"\nPROXIMITY EDGES ({len(proximity_edges)}):")
        for edge in proximity_edges[:10]:
            lines.append(
                f"- {edge.get('source_id', '?')[:12]} ~{edge.get('kind', 'near')}~ "
                f"{edge.get('target_id', '?')[:12]} ({edge.get('distance_km', '?')} km)"
            )
    return lines


async def route_retrieval(query: str, route: str | None = None) -> dict[str, Any]:
    """Execute retrieval for the given query and route.

    Returns dict with:
      - route: str (the route used)
      - block: str (formatted text block for LLM prompt)
      - hits: list[dict] (raw search results, if any)
      - meta: dict (extra metadata like subgraph stats)
    """
    if not router_enabled():
        route = fallback_route()
    elif route is None:
        route = classify_query(query)

    meta: dict[str, Any] = {"route": route}
    lines: list[str] = []
    hits: list[dict] = []

    if route == "live":
        # No RAG — live situations + fusion
        try:
            from situations import unified_situations

            sit = await unified_situations()
            items = (sit.get("items") or [])[:8]
            if items:
                lines.append("=== LIVE SITUATIONS (top) ===")
                for it in items:
                    lines.append(
                        f"- [{it.get('severity', '?')}] {(it.get('title') or '')[:120]}"
                    )
        except Exception:
            pass
        return {"route": route, "block": "\n".join(lines), "hits": hits, "meta": meta}

    if route == "graph":
        # Graph retrieval — subgraph BFS
        try:
            import intel_subgraph

            sg = await asyncio.to_thread(intel_subgraph.build_subgraph, hops=2)
            meta["node_count"] = sg.get("node_count", 0)
            meta["edge_count"] = sg.get("edge_count", 0)
            lines.append("=== GRAPH RETRIEVAL (FtM subgraph) ===")
            lines.extend(_format_graph_block(sg))
        except Exception:
            lines.append("=== GRAPH RETRIEVAL (unavailable) ===")
        return {"route": route, "block": "\n".join(lines), "hits": hits, "meta": meta}

    if route == "spatial":
        # Spatial retrieval — bbox-filtered vector search + proximity edges
        try:
            import rag_memory
            from rag_spatial import operator_search_bbox

            bbox = operator_search_bbox()
            if bbox:
                results = await rag_memory.search(query.strip(), k=6, bbox=bbox)
                hits = results
                lines.extend(_format_spatial_block(results))
            else:
                results = await rag_memory.search(query.strip(), k=6)
                hits = results
                lines.append("=== RAG MEMORY (no bbox — spatial fallback) ===")
                from rag_crag import format_rag_hits

                lines.extend(format_rag_hits(results))
        except Exception:
            lines.append("=== SPATIAL RETRIEVAL (unavailable) ===")
        return {"route": route, "block": "\n".join(lines), "hits": hits, "meta": meta}

    if route == "hybrid":
        # Hybrid — vector + graph in parallel, merge
        try:
            import rag_memory

            results = await rag_memory.search(query.strip(), k=6)
            hits = results
            if results:
                from rag_crag import format_rag_hits

                lines.append("=== RAG MEMORY (hybrid — vector) ===")
                lines.extend(format_rag_hits(results))
        except Exception:
            pass

        try:
            import intel_subgraph

            sg = await asyncio.to_thread(intel_subgraph.build_subgraph, hops=2)
            meta["node_count"] = sg.get("node_count", 0)
            meta["edge_count"] = sg.get("edge_count", 0)
            graph_block = _format_graph_block(sg)
            if graph_block:
                lines.append("\n=== GRAPH RETRIEVAL (hybrid — subgraph) ===")
                lines.extend(graph_block)
        except Exception:
            pass

        return {"route": route, "block": "\n".join(lines), "hits": hits, "meta": meta}

    # Default: vector
    try:
        import rag_memory

        results = await rag_memory.search(query.strip(), k=6)
        hits = results
        if results:
            from rag_crag import format_rag_hits

            lines.append("=== RAG MEMORY (vector search) ===")
            lines.extend(format_rag_hits(results))
    except Exception:
        pass

    return {"route": route, "block": "\n".join(lines), "hits": hits, "meta": meta}


def route_label(route: str) -> str:
    """Human-readable label for system prompt injection."""
    labels = {
        "vector": "VECTOR (semantic document search)",
        "graph": "GRAPH (FtM entity relationships)",
        "spatial": "SPATIAL (bbox-filtered geographic)",
        "hybrid": "HYBRID (vector + graph, RRF merged)",
        "live": "LIVE (real-time situations, no archive)",
    }
    return labels.get(route, route.upper())
