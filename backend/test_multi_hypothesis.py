"""Unit tests for V4-20 Multi-Hypothesis Synthesis (no network)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import multi_hypothesis as mh_mod
from multi_hypothesis import (
    HypothesisDraft,
    MultiHypothesisResult,
    STANCES,
    _build_draft_prompt,
    _compare_drafts,
    _merge_drafts,
    _rule_based_draft,
    format_hypothesis_trace_line,
    multi_hypothesis_enabled,
    run_multi_hypothesis,
)


class MultiHypothesisEnvTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_MULTI_HYPOTHESIS", None)
            self.assertFalse(multi_hypothesis_enabled())

    def test_enabled_when_set(self):
        with patch.dict(os.environ, {"WORLDBASE_MULTI_HYPOTHESIS": "1"}):
            self.assertTrue(multi_hypothesis_enabled())


class StancesTests(unittest.TestCase):
    def test_three_stances_defined(self):
        self.assertEqual(len(STANCES), 3)
        ids = [s["id"] for s in STANCES]
        self.assertEqual(ids, ["A", "B", "C"])

    def test_stance_labels(self):
        labels = [s["label"] for s in STANCES]
        self.assertIn("baseline", labels)
        self.assertIn("adversarial", labels)
        self.assertIn("forecast", labels)

    def test_each_stance_has_prompt(self):
        for s in STANCES:
            self.assertTrue(s["prompt"].strip())


class BuildDraftPromptTests(unittest.TestCase):
    def test_returns_messages_list(self):
        msgs = _build_draft_prompt("query", "context", "stance prompt")
        self.assertIsInstance(msgs, list)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[1]["role"], "user")

    def test_stance_prompt_included(self):
        msgs = _build_draft_prompt("q", "ctx", "Be skeptical.")
        self.assertIn("Be skeptical.", msgs[0]["content"])

    def test_context_included(self):
        msgs = _build_draft_prompt("q", "SPECIAL_EVIDENCE_123", "stance")
        self.assertIn("SPECIAL_EVIDENCE_123", msgs[0]["content"])

    def test_query_included(self):
        msgs = _build_draft_prompt("SPECIAL_QUERY_456", "ctx", "stance")
        self.assertIn("SPECIAL_QUERY_456", msgs[0]["content"])


class RuleBasedDraftTests(unittest.TestCase):
    def test_baseline_draft(self):
        stance = STANCES[0]
        draft = _rule_based_draft("query", "[gdacs] Flood in Bangkok", stance)
        self.assertEqual(draft.stance_id, "A")
        self.assertEqual(draft.stance_label, "baseline")
        self.assertEqual(draft.source, "rule_based")
        self.assertIn("Baseline", draft.content)
        self.assertIn("Flood", draft.content)

    def test_adversarial_draft(self):
        stance = STANCES[1]
        draft = _rule_based_draft("query", "[gdacs] Event data", stance)
        self.assertEqual(draft.stance_id, "B")
        self.assertIn("CHALLENGE", draft.content)
        self.assertIn("Alternative", draft.content)

    def test_forecast_draft(self):
        stance = STANCES[2]
        draft = _rule_based_draft("query", "[gdelt] Protest data", stance)
        self.assertEqual(draft.stance_id, "C")
        self.assertIn("Scenario", draft.content)
        self.assertIn("24-72h", draft.content)

    def test_empty_context_handled(self):
        draft = _rule_based_draft("query", "", STANCES[0])
        self.assertTrue(draft.content)


class CompareDraftsTests(unittest.TestCase):
    def test_empty_drafts(self):
        best, notes = _compare_drafts([])
        self.assertEqual(best, "")
        self.assertIn("No drafts", notes)

    def test_llm_draft_preferred_over_rule_based(self):
        d1 = HypothesisDraft(
            stance_id="A",
            stance_label="baseline",
            content="x" * 500,
            source="rule_based",
        )
        d2 = HypothesisDraft(
            stance_id="B",
            stance_label="adversarial",
            content="x" * 500,
            source="cloud:nvidia",
        )
        best, notes = _compare_drafts([d1, d2])
        self.assertEqual(best, "B")
        self.assertIn("LLM-generated", notes)

    def test_adversarial_bonus(self):
        d1 = HypothesisDraft(
            stance_id="A", stance_label="baseline", content="x" * 500, source="ollama"
        )
        d2 = HypothesisDraft(
            stance_id="B",
            stance_label="adversarial",
            content="x" * 500,
            source="ollama",
        )
        best, _ = _compare_drafts([d1, d2])
        self.assertEqual(best, "B")

    def test_error_penalty(self):
        d1 = HypothesisDraft(
            stance_id="A", stance_label="baseline", content="x" * 500, source="ollama"
        )
        d2 = HypothesisDraft(
            stance_id="B",
            stance_label="adversarial",
            content="x" * 500,
            source="ollama",
            error="timeout",
        )
        best, _ = _compare_drafts([d1, d2])
        # d1 should win because d2 has error penalty
        self.assertEqual(best, "A")

    def test_notes_contain_all_drafts(self):
        drafts = [
            HypothesisDraft(
                stance_id="A",
                stance_label="baseline",
                content="short",
                source="rule_based",
            ),
            HypothesisDraft(
                stance_id="B",
                stance_label="adversarial",
                content="longer text" * 10,
                source="ollama",
            ),
        ]
        _, notes = _compare_drafts(drafts)
        self.assertIn("A", notes)
        self.assertIn("B", notes)


class MergeDraftsTests(unittest.TestCase):
    def test_empty_drafts(self):
        self.assertEqual(_merge_drafts([], "A"), "")

    def test_best_first(self):
        drafts = [
            HypothesisDraft(
                stance_id="A",
                stance_label="baseline",
                content="AAA",
                source="rule_based",
            ),
            HypothesisDraft(
                stance_id="B",
                stance_label="adversarial",
                content="BBB",
                source="rule_based",
            ),
        ]
        merged = _merge_drafts(drafts, "B")
        # B should appear first
        self.assertLess(merged.index("BBB"), merged.index("AAA"))
        self.assertIn("[SELECTED]", merged)

    def test_header_present(self):
        drafts = [
            HypothesisDraft(
                stance_id="A",
                stance_label="baseline",
                content="content",
                source="ollama",
            ),
        ]
        merged = _merge_drafts(drafts, "A")
        self.assertIn("MULTI-HYPOTHESIS SYNTHESIS", merged)


class FormatTraceLineTests(unittest.TestCase):
    def test_disabled_returns_empty(self):
        result = MultiHypothesisResult(enabled=False)
        self.assertEqual(format_hypothesis_trace_line(result), "")

    def test_enabled_returns_summary(self):
        result = MultiHypothesisResult(
            drafts=[
                HypothesisDraft(
                    stance_id="A", stance_label="baseline", content="x", source="ollama"
                ),
            ],
            best_stance="A",
            llm_used=True,
        )
        line = format_hypothesis_trace_line(result)
        self.assertIn("MULTI-HYPOTHESIS", line)
        self.assertIn("Best: A", line)


class RunMultiHypothesisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    async def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_MULTI_HYPOTHESIS", None)
            result = await run_multi_hypothesis("query", "context")
        self.assertFalse(result.enabled)
        self.assertEqual(len(result.drafts), 0)

    async def test_rule_based_fallback_when_no_llm(self):
        with patch.dict(os.environ, {"WORLDBASE_MULTI_HYPOTHESIS": "1"}):
            with patch.object(
                mh_mod,
                "_try_llm_draft",
                new=AsyncMock(return_value=None),
            ):
                result = await run_multi_hypothesis("query", "[gdacs] evidence")
        self.assertTrue(result.enabled)
        self.assertGreaterEqual(len(result.drafts), 2)
        self.assertFalse(result.llm_used)
        for d in result.drafts:
            self.assertEqual(d.source, "rule_based")
        self.assertTrue(result.merged_block)
        self.assertTrue(result.best_stance)

    async def test_llm_drafts_used_when_available(self):
        async def mock_try_llm(query, context, stance):
            return HypothesisDraft(
                stance_id=stance["id"],
                stance_label=stance["label"],
                content=f"LLM draft for {stance['label']}",
                source="cloud:nvidia",
            )

        with patch.dict(os.environ, {"WORLDBASE_MULTI_HYPOTHESIS": "1"}):
            with patch.object(
                mh_mod,
                "_try_llm_draft",
                new=AsyncMock(side_effect=mock_try_llm),
            ):
                result = await run_multi_hypothesis("query", "context")
        self.assertTrue(result.llm_used)
        self.assertEqual(len(result.drafts), 3)
        for d in result.drafts:
            self.assertTrue(d.source.startswith("cloud:"))

    async def test_mixed_llm_and_rule_based(self):
        async def mock_try_llm(query, context, stance):
            if stance["id"] == "A":
                return HypothesisDraft(
                    stance_id="A",
                    stance_label="baseline",
                    content="LLM content A",
                    source="ollama",
                )
            return None  # B and C fall back to rule-based

        with patch.dict(os.environ, {"WORLDBASE_MULTI_HYPOTHESIS": "1"}):
            with patch.object(
                mh_mod,
                "_try_llm_draft",
                new=AsyncMock(side_effect=mock_try_llm),
            ):
                result = await run_multi_hypothesis("query", "context")
        sources = [d.source for d in result.drafts]
        self.assertIn("ollama", sources)
        self.assertIn("rule_based", sources)

    async def test_result_to_dict(self):
        with patch.dict(os.environ, {"WORLDBASE_MULTI_HYPOTHESIS": "1"}):
            with patch.object(
                mh_mod,
                "_try_llm_draft",
                new=AsyncMock(return_value=None),
            ):
                result = await run_multi_hypothesis("query", "context")
        d = result.to_dict()
        self.assertIn("drafts", d)
        self.assertIn("best_stance", d)
        self.assertTrue(d["enabled"])


if __name__ == "__main__":
    unittest.main()
