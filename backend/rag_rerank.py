"""BGE cross-encoder reranker after hybrid RRF (CPU-first)."""

from __future__ import annotations

import os
from typing import Callable

_RERANK_ENABLED = os.getenv("RAG_RERANK", "0").strip().lower() in ("1", "true", "yes")
_RERANK_MODEL = os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-base")
_RERANK_DEVICE = os.getenv("RAG_RERANK_DEVICE", "cpu")

_model = None


def rerank_enabled() -> bool:
    return _RERANK_ENABLED


def search_mode_label() -> str:
    return "hybrid_rrf_rerank" if _RERANK_ENABLED else "hybrid_rrf"


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise RuntimeError(
                "RAG_RERANK=1 requires sentence-transformers — pip install sentence-transformers"
            ) from e
        print(
            f"[RAG] Loading reranker {_RERANK_MODEL} on {_RERANK_DEVICE}...", flush=True
        )
        _model = CrossEncoder(_RERANK_MODEL, device=_RERANK_DEVICE)
        print("[RAG] Reranker ready.", flush=True)
    return _model


def rerank_hits(
    query: str,
    hits: list[dict],
    *,
    top_k: int,
    score_fn: Callable[[str, list[str]], list[float]] | None = None,
) -> list[dict]:
    """Re-order candidate hits by cross-encoder relevance; score_fn injectable for tests."""
    if not hits:
        return []
    if len(hits) <= 1:
        out = [dict(hits[0])]
        if score_fn is not None or _RERANK_ENABLED:
            out[0]["rank_source"] = "hybrid_rrf_rerank"
        return out[:top_k]

    texts = [h.get("text") or "" for h in hits]
    if score_fn is not None:
        scores = score_fn(query, texts)
    else:
        model = _get_model()
        pairs = [(query, t) for t in texts]
        scores = model.predict(pairs, show_progress_bar=False)

    scored: list[dict] = []
    for hit, sc in zip(hits, scores):
        row = dict(hit)
        row["rerank_score"] = round(float(sc), 4)
        row["score"] = row["rerank_score"]
        row["rank_source"] = "hybrid_rrf_rerank"
        scored.append(row)

    scored.sort(key=lambda h: h["rerank_score"], reverse=True)
    return scored[:top_k]
