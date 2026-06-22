"""CRAG-lite chat augmentation — low RAG confidence → live feeds + FtM subgraph (Track R1.2)."""

from __future__ import annotations

import asyncio
import os


def crag_enabled() -> bool:
    return os.getenv("RAG_CRAG", "1").strip().lower() not in ("0", "false", "no", "off")


def min_confidence_score() -> float:
    try:
        return float(os.getenv("RAG_CRAG_MIN_SCORE", "0.35"))
    except ValueError:
        return 0.35


def top_hit_score(results: list[dict]) -> float:
    best = 0.0
    for row in results:
        try:
            sc = float(row.get("rerank_score") or row.get("score") or 0)
        except (TypeError, ValueError):
            sc = 0.0
        best = max(best, sc)
    return best


def format_rag_hits(results: list[dict], *, limit: int = 6, max_chars: int = 450) -> list[str]:
    lines: list[str] = []
    for row in results[:limit]:
        src = row.get("source") or "?"
        txt = (row.get("text") or "")[:max_chars]
        lines.append(f"- [{src}] {txt}")
    return lines


async def build_rag_crag_block(query: str) -> str:
    """Build RAG block for chat context; augment with live intel when confidence is low."""
    if not crag_enabled() or not (query or "").strip():
        return ""

    import rag_memory
    from rag_spatial import operator_search_bbox, spatial_enabled

    bbox = operator_search_bbox() if spatial_enabled() else None
    results = await rag_memory.search(query.strip(), k=6, bbox=bbox)
    threshold = min_confidence_score()
    top_score = top_hit_score(results)
    low_confidence = not results or top_score < threshold

    lines: list[str] = []
    if results and not low_confidence:
        lines.append("=== RAG MEMORY (high confidence) ===")
        lines.extend(format_rag_hits(results))
        return "\n".join(lines)

    lines.append("=== RAG MEMORY (CRAG fallback — low retrieval confidence) ===")
    if results:
        lines.append("Weak memory hits:")
        lines.extend(format_rag_hits(results, limit=3, max_chars=200))

    try:
        from situations import unified_situations

        sit = await unified_situations()
        items = (sit.get("items") or [])[:8]
        if items:
            lines.append("\nLIVE SITUATIONS (top):")
            for it in items:
                lines.append(
                    f"- [{it.get('severity', '?')}] {(it.get('title') or '')[:120]}"
                )
    except Exception:
        pass

    try:
        import intel_subgraph

        sg = await asyncio.to_thread(intel_subgraph.build_subgraph, hops=2)
        block = intel_subgraph.format_subgraph_prompt_block(sg)
        if block:
            lines.append("\nINTEL SUBGRAPH:")
            lines.append(block)
    except Exception:
        pass

    return "\n".join(lines)
