"""Unit tests for V4-25 ReAct Agent Loop (no network)."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from react_agent import (
    ACTION_SEARCH,
    ACTION_SEARCH_ALT,
    ACTION_SYNTHESIZE,
    ReActStep,
    ReActTrace,
    _generate_thought,
    _merge_blocks,
    _synthesize,
    format_react_trace_line,
    react_agent_enabled,
    run_react_loop,
)


class ReactEnvTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_REACT_AGENT", None)
            self.assertFalse(react_agent_enabled())

    def test_enabled_when_set(self):
        with patch.dict(os.environ, {"WORLDBASE_REACT_AGENT": "1"}):
            self.assertTrue(react_agent_enabled())


class ThoughtGeneratorTests(unittest.TestCase):
    def test_step0_always_search(self):
        thought, action, _ = _generate_thought("query", 0, "", [])
        self.assertEqual(action, ACTION_SEARCH)
        self.assertIn("empty", thought.lower())

    def test_thin_block_triggers_alt_search(self):
        thought, action, _ = _generate_thought("query", 1, "thin", [ACTION_SEARCH])
        self.assertEqual(action, ACTION_SEARCH_ALT)

    def test_sufficient_content_triggers_synthesize(self):
        block = "=== RAG MEMORY ===\n[gdacs] " + "x" * 300
        thought, action, _ = _generate_thought(
            "query", 2, block, [ACTION_SEARCH, ACTION_SEARCH_ALT]
        )
        self.assertEqual(action, ACTION_SYNTHESIZE)

    def test_fallback_synthesize_when_thin_after_alt(self):
        thought, action, _ = _generate_thought(
            "query", 2, "thin", [ACTION_SEARCH, ACTION_SEARCH_ALT]
        )
        self.assertEqual(action, ACTION_SYNTHESIZE)


class MergeBlocksTests(unittest.TestCase):
    def test_empty_new_returns_base(self):
        self.assertEqual(_merge_blocks("base", ""), "base")

    def test_empty_base_returns_new(self):
        self.assertEqual(_merge_blocks("", "new"), "new")

    def test_dedup_lines(self):
        base = "line1\nline2"
        new = "line2\nline3"
        merged = _merge_blocks(base, new)
        self.assertEqual(merged.count("line2"), 1)
        self.assertIn("line3", merged)

    def test_all_new_lines_appended(self):
        base = "line1"
        new = "line2\nline3"
        merged = _merge_blocks(base, new)
        self.assertIn("line1", merged)
        self.assertIn("line2", merged)
        self.assertIn("line3", merged)


class SynthesizeTests(unittest.TestCase):
    def test_produces_header(self):
        result = _synthesize("evidence block", "test query")
        self.assertIn("REACT SYNTHESIS", result)
        self.assertIn("test query", result)
        self.assertIn("evidence block", result)

    def test_empty_block(self):
        result = _synthesize("", "query")
        self.assertIn("REACT SYNTHESIS", result)


class FormatTraceLineTests(unittest.TestCase):
    def test_disabled_returns_empty(self):
        trace = ReActTrace(query="q", enabled=False)
        self.assertEqual(format_react_trace_line(trace), "")

    def test_enabled_returns_summary(self):
        trace = ReActTrace(query="q", converged=True)
        trace.steps.append(
            ReActStep(step=0, thought="t", action=ACTION_SEARCH, action_input="q")
        )
        line = format_react_trace_line(trace)
        self.assertIn("REACT", line)
        self.assertIn("search", line)


class RunReactLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    async def test_disabled_returns_initial_block(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_REACT_AGENT", None)
            trace = await run_react_loop("query", "initial")
        self.assertFalse(trace.enabled)
        self.assertEqual(trace.final_block, "initial")
        self.assertEqual(len(trace.steps), 0)

    async def test_loop_converges_with_synthesize(self):
        mock_result = {
            "route": "vector",
            "block": "=== RAG MEMORY ===\n[gdacs] " + "x" * 300,
            "hits": [{"text": "data"}],
            "meta": {},
        }
        with patch.dict(os.environ, {"WORLDBASE_REACT_AGENT": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(return_value=mock_result),
            ):
                with patch(
                    "query_router.classify_query",
                    return_value="vector",
                ):
                    trace = await run_react_loop("what is happening?")
        self.assertTrue(trace.enabled)
        self.assertTrue(trace.converged)
        self.assertGreaterEqual(len(trace.steps), 2)  # search + synthesize
        actions = [s.action for s in trace.steps]
        self.assertIn(ACTION_SEARCH, actions)
        self.assertIn(ACTION_SYNTHESIZE, actions)
        self.assertIn("REACT SYNTHESIS", trace.final_block)

    async def test_alt_search_on_thin_result(self):
        # First search returns thin, second (alt) returns strong
        call_count = [0]

        async def mock_retrieval(query, route=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"route": "vector", "block": "thin", "hits": [], "meta": {}}
            return {
                "route": "hybrid",
                "block": "=== RAG MEMORY ===\n[gdelt] " + "x" * 300,
                "hits": [{"text": "data"}],
                "meta": {},
            }

        with patch.dict(os.environ, {"WORLDBASE_REACT_AGENT": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(side_effect=mock_retrieval),
            ):
                with patch(
                    "query_router.classify_query",
                    return_value="vector",
                ):
                    trace = await run_react_loop("query")
        actions = [s.action for s in trace.steps]
        self.assertIn(ACTION_SEARCH, actions)
        self.assertIn(ACTION_SEARCH_ALT, actions)
        self.assertIn(ACTION_SYNTHESIZE, actions)

    async def test_max_steps_respected(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_REACT_AGENT": "1", "WORLDBASE_REACT_AGENT_MAX_STEPS": "2"},
        ):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(
                    return_value={
                        "route": "vector",
                        "block": "thin",
                        "hits": [],
                        "meta": {},
                    }
                ),
            ):
                with patch(
                    "query_router.classify_query",
                    return_value="vector",
                ):
                    trace = await run_react_loop("query")
        self.assertLessEqual(len(trace.steps), 3)  # max_steps + force-synth

    async def test_search_timeout_handled(self):
        async def slow_retrieval(query, route=None):
            await asyncio.sleep(100)
            return {}

        with patch.dict(
            os.environ,
            {
                "WORLDBASE_REACT_AGENT": "1",
                "WORLDBASE_REACT_AGENT_STEP_TIMEOUT": "0.1",
            },
        ):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(side_effect=slow_retrieval),
            ):
                with patch(
                    "query_router.classify_query",
                    return_value="vector",
                ):
                    trace = await run_react_loop("query")
        # Should not crash, should have error in first step
        self.assertTrue(any(s.error for s in trace.steps))

    async def test_trace_to_dict(self):
        with patch.dict(os.environ, {"WORLDBASE_REACT_AGENT": "1"}):
            with patch(
                "query_router.route_retrieval",
                new=AsyncMock(
                    return_value={
                        "route": "vector",
                        "block": "=== RAG MEMORY ===\n[gdacs] " + "x" * 300,
                        "hits": [],
                        "meta": {},
                    }
                ),
            ):
                with patch(
                    "query_router.classify_query",
                    return_value="vector",
                ):
                    trace = await run_react_loop("query")
        d = trace.to_dict()
        self.assertIn("steps", d)
        self.assertIn("converged", d)
        self.assertIn("total_duration_ms", d)
        self.assertTrue(d["enabled"])


if __name__ == "__main__":
    unittest.main()
