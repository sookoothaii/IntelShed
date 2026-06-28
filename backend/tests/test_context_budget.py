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

    def test_escalation_active_in_meta(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "[usgs] Earthquake data.")],
                escalation=True,
            )
        self.assertTrue(getattr(result, "escalation_active", False))
        _, meta = context_budget.format_context_from_result(result)
        self.assertTrue(meta["context_budget"]["escalation_active"])

    def test_escalation_inactive_in_meta(self):
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "[usgs] Earthquake data.")],
                escalation=False,
            )
        self.assertFalse(getattr(result, "escalation_active", True))


class EscalationTests(unittest.TestCase):
    """Tests for the context budget escalation path (Phase 4.3)."""

    def setUp(self):
        self._orig_env = os.environ.get("WORLDBASE_CONTEXT_BUDGET")
        self._orig_esc = os.environ.get("WORLDBASE_CONTEXT_BUDGET_ESCALATION")

    def tearDown(self):
        for key, val in [
            ("WORLDBASE_CONTEXT_BUDGET", self._orig_env),
            ("WORLDBASE_CONTEXT_BUDGET_ESCALATION", self._orig_esc),
        ]:
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def test_escalation_lowers_threshold(self):
        """A quality score that would refuse at 0.35 should pass at 0.20."""
        # Quality ~0.25: no source tags → 0.25, but with a low-quality marker → <0.25
        # We need something between 0.20 and 0.35
        # Use a single low-reliability source without corroboration
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            # Without escalation → refused (quality 0.25 < 0.35)
            result_normal = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "Some text without any source tags here.")],
                escalation=False,
            )
            self.assertFalse(result_normal.ok)

            # With escalation → should pass (quality 0.25 >= 0.20)
            result_escalated = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "Some text without any source tags here.")],
                escalation=True,
            )
            self.assertTrue(result_escalated.ok)
            self.assertTrue(getattr(result_escalated, "escalation_active", False))

    def test_escalation_disabled_env(self):
        """When WORLDBASE_CONTEXT_BUDGET_ESCALATION=0, escalation flag is ignored."""
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_CONTEXT_BUDGET": "1",
                "WORLDBASE_CONTEXT_BUDGET_ESCALATION": "0",
            },
        ):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "Some text without any source tags here.")],
                escalation=True,
            )
            # Should still refuse because escalation is disabled
            self.assertFalse(result.ok)
            self.assertFalse(getattr(result, "escalation_active", True))

    def test_escalation_boosts_rag_budget(self):
        """Escalation should increase RAG budget by 50%."""
        long_text = "[usgs] " + ". ".join(f"Sentence {i}" for i in range(200))
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_CONTEXT_BUDGET": "1",
                "WORLDBASE_CONTEXT_BUDGET_RAG": "100",
            },
        ):
            # Without escalation: budget=100
            result_normal = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", long_text)],
                escalation=False,
            )
            self.assertTrue(result_normal.ok)
            normal_tokens = sum(
                s.final_tokens for s in result_normal.sections if s.category == "rag"
            )

            # With escalation: budget=150
            result_escalated = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", long_text)],
                escalation=True,
            )
            self.assertTrue(result_escalated.ok)
            escalated_tokens = sum(
                s.final_tokens for s in result_escalated.sections if s.category == "rag"
            )

            self.assertGreater(escalated_tokens, normal_tokens)

    def test_escalation_warning_in_system_prompt(self):
        """Escalation should inject a warning into the system prompt."""
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "[usgs] Earthquake data.")],
                escalation=True,
            )
        self.assertIn("EXPANDED CONTEXT MODE", result.system_prompt)

    def test_no_escalation_warning_by_default(self):
        """Default path should not have the escalation warning."""
        with patch.dict(os.environ, {"WORLDBASE_CONTEXT_BUDGET": "1"}):
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "[usgs] Earthquake data.")],
                escalation=False,
            )
        self.assertNotIn("EXPANDED CONTEXT MODE", result.system_prompt)

    def test_escalation_still_refuses_very_low_quality(self):
        """Even with escalation, quality below the escalation threshold should refuse."""
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_CONTEXT_BUDGET": "1",
                "WORLDBASE_CONTEXT_BUDGET_ESCALATION_THRESHOLD": "0.30",
            },
        ):
            # Quality 0.25 (no source tags) should refuse at 0.30 even with escalation
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "Some text without any source tags here.")],
                escalation=True,
            )
        self.assertFalse(result.ok)

    def test_escalation_threshold_env_override(self):
        """WORLDBASE_CONTEXT_BUDGET_ESCALATION_THRESHOLD can be configured."""
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_CONTEXT_BUDGET": "1",
                "WORLDBASE_CONTEXT_BUDGET_ESCALATION_THRESHOLD": "0.30",
            },
        ):
            # Quality 0.25 should refuse at 0.30 even with escalation
            result = context_budget.apply_budget(
                "system prompt" + " x" * 100,
                [("RAG MEMORY", "Some text without any source tags here.")],
                escalation=True,
            )
            self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
