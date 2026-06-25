"""Edge review module for P5+ Dynamic Knowledge Graph.

Wraps ftm_query external edge functions with review workflow.
"""

from __future__ import annotations

import os
from typing import Any


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def dynamic_graph_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_DYNAMIC_GRAPH", "0"))


def list_external_edges(confirmed: bool | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """List external edges for review."""
    from ftm_query import list_external_edges as _list

    return _list(confirmed=confirmed, limit=limit)


def approve_edge(source_id: str, target_id: str, kind: str, dataset: str) -> bool:
    """Approve an external edge — sets confirmed=true, confidence=0.9."""
    from ftm_query import approve_external_edge

    return approve_external_edge(source_id, target_id, kind, dataset)


def reject_edge(source_id: str, target_id: str, kind: str, dataset: str) -> bool:
    """Reject an external edge — deletes it."""
    from ftm_query import reject_external_edge

    return reject_external_edge(source_id, target_id, kind, dataset)


def add_external_edge(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str = "user-query",
    *,
    confidence: float = 0.6,
    properties: dict | None = None,
) -> None:
    """Add an external edge (agent-derived hypothesis)."""
    from ftm_query import add_external_edge as _add

    _add(
        source_id, target_id, kind, dataset,
        confidence=confidence, properties=properties,
    )


def edge_review_stats() -> dict[str, Any]:
    """Get edge review statistics."""
    from ftm_query import list_external_edges

    all_edges = list_external_edges(limit=10000)
    confirmed = [e for e in all_edges if e.get("confirmed")]
    pending = [e for e in all_edges if not e.get("confirmed")]

    return {
        "enabled": dynamic_graph_enabled(),
        "total_external": len(all_edges),
        "confirmed": len(confirmed),
        "pending_review": len(pending),
        "max_confidence": float(os.getenv("WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE", "0.7")),
    }
