"""Unit tests for context_budget.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import context_budget


class EstimateTokensTests(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(context_budget._estimate_tokens(""), 0)

    def test_short_text(self):
        text = "The quick brown fox jumps over the lazy dog."
        n = context_budget._estimate_tokens(text)
        self.assertGreater(n, 0)
        self.assertLess(n, 50)


class CategoryDetectionTests(unittest.TestCase):
    def test_internal_telemetry(self):
        self.assertEqual(
            context_budget._detect_category("INTERNAL TELEMETRY"), "evidence"
        )

    def test_rag_memory(self):
        self.assertEqual(context_budget._detect_category("RAG MEMORY"), "rag")

    def test_selected_target(self):
        self.assertEqual(context_budget._detect_category("SELECTED TARGET"), "evidence")

    def test_web_search(self):
        self.assertEqual(context_budget._detect_category("WEB SEARCH RESULTS"), "rag")

    def test_unknown_is_aux(self):
        self.assertEqual(context_budget._detect_category("Something else"), "aux")


class ProvenanceScoreTests(unittest.TestCase):
    def test_no_sources_low_score(self):
        score = context_budget._section_provenance_score("Some text without tags")
        self.assertLess(score, 0.5)

    def test_high_reliability_source(self):
        score = context_budget._section_provenance_score(
            "[usgs] Earthquake M6.5 in Japan"
        )
        self.assertGreaterEqual(score, 0.7)

    def test_low_quality_marker_penalty(self):
        score = context_budget._section_provenance_score(
            "[usgs] CRAG fallback (low confidence)."
        )
        self.assertLess(score, 0.7)


class ApplyBudgetTests(unittest.TestCase):
    def setUp(self):
        self._orig_env = os.environ.get("WORLDBASE_CONTEXT_BUDGET")

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("WORLDBASE_CONTEXT_BUDGET", None)
        else:
            os.environ["WORLDBASE_CONTEXT_BUDGET"] = self._orig_env

    def test_disabled_returns_ok(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "0"}):
            result = context_budget.apply_budget(
                "system prompt",
                [("RAG MEMORY", "[usgs] Earthquake data")],
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.refusal_reason, None)

    def test_high_quality_ok(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [
                    ("RAG MEMORY", "[usgs] Earthquake M6.5 in Japan."),
                    ("INTERNAL TELEMETRY", "[gdelt] Political context."),
                ],
            )
        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.quality_score, 0.5)

    def test_low_quality_refuses(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [
                    ("RAG MEMORY", "No data available."),
                ],
            )
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.refusal_reason)

    def test_system_prompt_too_long_refuses(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET_SYSTEM": "10"}):
                result = context_budget.apply_budget(
                    "system prompt" + " x" * 5000,
                    [],
                )
        self.assertFalse(result.ok)
        self.assertIn("System prompt", result.refusal_reason)

    def test_truncation_happens(self):
        # Many short sentences so truncation can cut some
        long_text = "[usgs] " + ". ".join(f"Sentence {i}" for i in range(200))
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET_RAG": "50"}):
                result = context_budget.apply_budget(
                    "system prompt" + " x" * 100,
                    [("RAG MEMORY", long_text)],
                )
        self.assertTrue(result.ok)
        section = result.sections[0]
        self.assertTrue(section.truncated)
        self.assertLess(section.final_tokens, section.original_tokens)


class FormatResultTests(unittest.TestCase):
    def test_renders_sections(self):
        result = context_budget.apply_budget(
            "system prompt" + " x" * 100,
            [("RAG MEMORY", "[usgs] Earthquake data.")],
        )
        text, meta = context_budget.format_context_from_result(result)
        self.assertIn("RAG MEMORY", text)
        self.assertIn("context_budget", meta)
        self.assertTrue(meta["context_budget"]["ok"])


if __name__ == "__main__":
    unittest.main()
