"""Offline unit tests for RAG BGE reranker (no model download)."""

from __future__ import annotations

import unittest

from rag_rerank import rerank_enabled, rerank_hits, search_mode_label


def _hit(cid: int, text: str) -> dict:
    return {
        "id": cid,
        "source": "test",
        "source_id": str(cid),
        "text": text,
        "score": 0.5,
        "meta": {},
        "created_at": "t",
        "rank_source": "hybrid_rrf",
    }


class RagRerankTests(unittest.TestCase):
    def test_rerank_reorders_by_injected_scores(self):
        hits = [
            _hit(1, "Bangkok flood warning"),
            _hit(2, "Thailand weather forecast"),
            _hit(3, "Malaysia trade news"),
        ]

        def score_fn(_query: str, texts: list[str]) -> list[float]:
            # Prefer the flood headline regardless of RRF order.
            return [2.0 if "flood" in t else 0.1 for t in texts]

        out = rerank_hits("Bangkok flood", hits, top_k=2, score_fn=score_fn)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["id"], 1)
        self.assertEqual(out[0]["rank_source"], "hybrid_rrf_rerank")
        self.assertGreater(out[0]["rerank_score"], out[1]["rerank_score"])

    def test_rerank_empty_and_single(self):
        self.assertEqual(rerank_hits("q", [], top_k=3, score_fn=lambda q, t: []), [])
        single = rerank_hits(
            "q", [_hit(1, "only")], top_k=3, score_fn=lambda q, t: [1.0]
        )
        self.assertEqual(len(single), 1)
        self.assertEqual(single[0]["rank_source"], "hybrid_rrf_rerank")

    def test_search_mode_label_follows_env(self):
        # Default in test env is RAG_RERANK unset → hybrid_rrf.
        if rerank_enabled():
            self.assertEqual(search_mode_label(), "hybrid_rrf_rerank")
        else:
            self.assertEqual(search_mode_label(), "hybrid_rrf")


if __name__ == "__main__":
    unittest.main()
