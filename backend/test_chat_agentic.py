"""Unit tests for P3 chat agentic loop (no network)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import chat_agentic as chat_agentic_mod
from chat_agentic import (
    apply_corroboration_tags,
    assess_coverage,
    chat_agentic_enabled,
    format_agentic_trace_line,
    max_rounds,
    run_chat_agentic_loop,
)


class ChatAgenticEnvTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_CHAT_AGENTIC", None)
            self.assertFalse(chat_agentic_enabled())

    def test_enabled_when_set(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC": "1"}):
            self.assertTrue(chat_agentic_enabled())

    def test_max_rounds_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS", None)
            self.assertEqual(max_rounds(), 3)

    def test_max_rounds_custom(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS": "2"}):
            self.assertEqual(max_rounds(), 2)


class CoverageTests(unittest.TestCase):
    def test_empty_block_detected(self):
        cov = assess_coverage("what is happening in Bangkok?", "")
        self.assertIn("empty_block", cov["gaps"])
        self.assertTrue(cov["needs_retrieve"])

    def test_short_block_detected(self):
        cov = assess_coverage("test query", "short block")
        self.assertIn("block_too_short", cov["gaps"])

    def test_strong_block_no_gaps(self):
        block = "=== RAG MEMORY (high confidence) ===\n" + "[gdacs] " + "x" * 300
        cov = assess_coverage("query", block)
        self.assertFalse(cov["needs_retrieve"])

    def test_low_confidence_block_detected(self):
        block = "=== CRAG fallback (low confidence) ===\n" + "x" * 300
        cov = assess_coverage("query", block)
        self.assertIn("low_confidence", cov["gaps"])

    def test_no_source_tags_detected(self):
        block = "x" * 300
        cov = assess_coverage("query", block)
        self.assertIn("no_source_tags", cov["gaps"])

    def test_source_tags_counted(self):
        block = "=== RAG MEMORY (high confidence) ===\n[gdacs] " + "x" * 300
        cov = assess_coverage("query", block)
        self.assertGreaterEqual(cov["unique_sources"], 1)


class CorroborationTests(unittest.TestCase):
    def test_empty_block_no_tags(self):
        block, meta = apply_corroboration_tags("")
        self.assertEqual(meta["tagged_lines"], 0)
        self.assertEqual(block, "")

    def test_single_source_uncorroborated(self):
        block = "=== RAG MEMORY ===\n[gdacs] Flood warning in Thailand"
        tagged, meta = apply_corroboration_tags(block)
        self.assertEqual(meta["tagged_lines"], 1)
        self.assertEqual(meta["uncorroborated"], 1)
        self.assertEqual(meta["corroborated"], 0)
        self.assertIn("[uncorroborated]", tagged)

    def test_two_sources_same_topic_corroborated(self):
        block = (
            "=== RAG MEMORY ===\n"
            "[gdacs] Flood warning in Thailand Bangkok area\n"
            "[gdelt] Thailand Bangkok flooding situation report"
        )
        tagged, meta = apply_corroboration_tags(block)
        self.assertEqual(meta["tagged_lines"], 2)
        self.assertGreaterEqual(meta["corroborated"], 1)
        self.assertIn("[corroborated]", tagged)

    def test_different_sources_no_overlap(self):
        block = (
            "=== RAG MEMORY ===\n"
            "[gdacs] Earthquake in Japan Tokyo region\n"
            "[ais] Vessel MV NORDIC passing through Suez Canal"
        )
        tagged, meta = apply_corroboration_tags(block)
        self.assertEqual(meta["corroborated"], 0)
        self.assertEqual(meta["uncorroborated"], 2)

    def test_numeric_brackets_not_sources(self):
        block = "=== RAG MEMORY ===\n[0.85] Some content here that is long enough"
        tagged, meta = apply_corroboration_tags(block)
        self.assertEqual(meta["tagged_lines"], 0)

    def test_existing_tags_not_duplicated(self):
        block = "[gdacs] Flood warning [corroborated]"
        tagged, _ = apply_corroboration_tags(block)
        self.assertEqual(tagged.count("[corroborated]"), 1)


class TraceLineTests(unittest.TestCase):
    def test_disabled_returns_empty(self):
        line = format_agentic_trace_line({"enabled": False})
        self.assertEqual(line, "")

    def test_enabled_returns_phases(self):
        trace = {
            "enabled": True,
            "phases": [
                {"phase": "coverage"},
                {"phase": "retrieve"},
                {"phase": "corroboration"},
            ],
        }
        line = format_agentic_trace_line(trace)
        self.assertIn("AGENTIC", line)
        self.assertIn("coverage", line)
        self.assertIn("retrieve", line)
        self.assertIn("corroboration", line)


class RunChatAgenticLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    async def test_disabled_returns_unchanged(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC": "0"}):
            block, trace = await run_chat_agentic_loop("query", "original block")
            self.assertFalse(trace.get("enabled"))
            self.assertEqual(block, "original block")

    async def test_enabled_runs_all_phases(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC": "1"}):
            with patch.object(
                chat_agentic_mod,
                "_retrieve_augmented",
                new=AsyncMock(
                    return_value=(
                        "augmented block",
                        {
                            "phase": "retrieve",
                            "route": "vector",
                            "retrieved": 2,
                            "errors": [],
                        },
                    )
                ),
            ):
                block, trace = await run_chat_agentic_loop(
                    "what is happening in Bangkok?",
                    "short",
                )
        self.assertTrue(trace.get("enabled"))
        self.assertEqual(trace.get("status"), "done")
        phases = [p.get("phase") for p in trace.get("phases") or []]
        self.assertIn("coverage", phases)
        self.assertIn("retrieve", phases)
        self.assertIn("corroboration", phases)
        self.assertGreaterEqual(trace.get("rounds"), 2)

    async def test_no_gaps_skips_retrieve(self):
        strong_block = "=== RAG MEMORY (high confidence) ===\n[gdacs] " + "x" * 300
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC": "1"}):
            block, trace = await run_chat_agentic_loop("query", strong_block)
        phases = [p.get("phase") for p in trace.get("phases") or []]
        self.assertIn("coverage", phases)
        self.assertNotIn("retrieve", phases)
        self.assertIn("corroboration", phases)

    async def test_max_rounds_respected(self):
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_CHAT_AGENTIC": "1",
                "WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS": "1",
            },
        ):
            block, trace = await run_chat_agentic_loop("query", "short")
        self.assertLessEqual(trace.get("rounds"), 1)
        phases = [p.get("phase") for p in trace.get("phases") or []]
        self.assertEqual(len(phases), 1)

    async def test_retrieve_augmentation_adds_content(self):
        with patch.dict(os.environ, {"WORLDBASE_CHAT_AGENTIC": "1"}):
            with patch.object(
                chat_agentic_mod,
                "_retrieve_augmented",
                new=AsyncMock(
                    return_value=(
                        "original\n\n=== AGENTIC RETRIEVAL (coverage gap fill) ===\n[gdelt] New finding",
                        {
                            "phase": "retrieve",
                            "route": "vector",
                            "retrieved": 1,
                            "errors": [],
                        },
                    )
                ),
            ):
                block, trace = await run_chat_agentic_loop("query", "short")
        self.assertIn("AGENTIC RETRIEVAL", block)
        self.assertIn("[gdelt]", block)


class RetrieveAugmentedTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieve_calls_route_retrieval(self):
        from chat_agentic import _retrieve_augmented

        mock_result = {
            "route": "vector",
            "block": "=== RAG MEMORY (vector search) ===\n[gdacs] New data found",
            "hits": [{"text": "New data found", "score": 0.8}],
            "meta": {"route": "vector"},
        }
        with patch.dict(os.environ, {"WORLDBASE_QUERY_ROUTER": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(return_value=mock_result),
            ):
                block, meta = await _retrieve_augmented(
                    "what is happening",
                    "original",
                    ["block_too_short"],
                )
        self.assertIn("New data found", block)
        self.assertEqual(meta["retrieved"], 1)
        self.assertEqual(meta["route"], "vector")

    async def test_retrieve_handles_errors(self):
        from chat_agentic import _retrieve_augmented

        with patch.dict(os.environ, {"WORLDBASE_QUERY_ROUTER": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(side_effect=Exception("network error")),
            ):
                block, meta = await _retrieve_augmented(
                    "query",
                    "original",
                    ["empty_block"],
                )
        self.assertEqual(block, "original")
        self.assertTrue(len(meta["errors"]) > 0)

    async def test_retrieve_dedupes_existing_lines(self):
        from chat_agentic import _retrieve_augmented

        existing = "=== RAG MEMORY ===\n[gdacs] Already here"
        mock_result = {
            "route": "vector",
            "block": "=== RAG MEMORY ===\n[gdacs] Already here\n[gdelt] New finding",
            "hits": [{"text": "New finding"}],
            "meta": {},
        }
        with patch.dict(os.environ, {"WORLDBASE_QUERY_ROUTER": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(return_value=mock_result),
            ):
                block, meta = await _retrieve_augmented(
                    "query",
                    existing,
                    ["block_too_short"],
                )
        self.assertIn("New finding", block)
        # Should not duplicate the existing line
        self.assertEqual(block.count("Already here"), 1)


if __name__ == "__main__":
    unittest.main()
