"""Unit tests for RAG hybrid search helpers (no Ollama)."""

from __future__ import annotations

import unittest

from rag_hybrid import (
    format_embed_text,
    format_prediction_watch_text,
    fts_query,
    rrf_merge,
)


class RagMemoryHybridTests(unittest.TestCase):
    def test_chunk_prefix_includes_source_and_meta(self):
        out = format_embed_text(
            "briefing", "Local flood warning.", {"region": "thailand"}
        )
        self.assertIn("SOURCE: operator security briefing", out)
        self.assertIn("region: thailand", out)
        self.assertIn("Local flood warning", out)

    def test_prediction_watch_text_pending(self):
        text = format_prediction_watch_text(
            {
                "claim": "Elevated GDELT attention",
                "prefix": "gdelt",
                "bucket": "local",
                "horizon_h": 24,
                "issued_at": "2026-06-22T12:00:00+00:00",
                "due_at": "2026-06-23T12:00:00+00:00",
                "sources": ["gdelt_pulse_local"],
                "hit": None,
            }
        )
        self.assertIn("Status: pending", text)
        self.assertIn("Elevated GDELT attention", text)

    def test_fts_query_tokenizes(self):
        q = fts_query("Bangkok flood warning")
        self.assertIsNotNone(q)
        self.assertIn('"Bangkok"', q or "")
        self.assertIn(" OR ", q or "")

    def test_fts_query_empty(self):
        self.assertIsNone(fts_query("   "))

    def test_rrf_merge_prefers_overlap(self):
        vec = [
            {
                "id": 1,
                "source": "a",
                "source_id": "1",
                "text": "alpha",
                "score": 0.9,
                "meta": {},
                "created_at": "t",
            },
            {
                "id": 2,
                "source": "b",
                "source_id": "2",
                "text": "beta",
                "score": 0.8,
                "meta": {},
                "created_at": "t",
            },
        ]
        fts = [
            {
                "id": 2,
                "source": "b",
                "source_id": "2",
                "text": "beta",
                "score": 1.2,
                "meta": {},
                "created_at": "t",
            },
            {
                "id": 3,
                "source": "c",
                "source_id": "3",
                "text": "gamma",
                "score": 1.0,
                "meta": {},
                "created_at": "t",
            },
        ]
        merged = rrf_merge(vec, fts, k=60, top_k=2)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["id"], 2)
        self.assertEqual(merged[0]["rank_source"], "hybrid_rrf")


if __name__ == "__main__":
    unittest.main()
