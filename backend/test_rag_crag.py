"""Offline unit tests for CRAG-lite helpers (Track R1.2)."""

from __future__ import annotations

import unittest

from rag_crag import format_rag_hits, min_confidence_score, top_hit_score


class RagCragTests(unittest.TestCase):
    def test_top_hit_score_uses_rerank(self):
        results = [
            {"score": 0.2, "rerank_score": 0.91},
            {"score": 0.5},
        ]
        self.assertAlmostEqual(top_hit_score(results), 0.91)

    def test_format_rag_hits_truncates(self):
        rows = format_rag_hits(
            [{"source": "briefing", "text": "x" * 500}],
            limit=1,
            max_chars=80,
        )
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]), 100)

    def test_min_confidence_default(self):
        self.assertGreater(min_confidence_score(), 0.0)


if __name__ == "__main__":
    unittest.main()
