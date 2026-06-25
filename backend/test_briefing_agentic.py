"""Unit tests for briefing agentic loop (Track R1.4, no network)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import briefing_agentic as briefing_agentic_mod
from briefing_agentic import (
    AgenticPhase,
    apply_corroboration_pass,
    assess_coverage,
    format_rag_recall_block,
    run_briefing_agentic_loop,
)


class BriefingAgenticTests(unittest.TestCase):
    def test_coverage_detects_thin_buckets(self):
        digest = {
            "local": ["- Bangkok flood warning"],
            "regional": ["- No regional signals highlighted."],
            "global": ["- No global priorities beyond baseline."],
            "region_label": "Thailand",
        }
        cov = assess_coverage(digest)
        self.assertIn("local", cov["gaps"])
        self.assertIn("regional", cov["gaps"])
        self.assertEqual(cov["phase"], AgenticPhase.COVERAGE.value)

    def test_corroboration_pass_scores_digest(self):
        digest = {
            "local": [
                "- Local news: Bangkok flood",
                "- Air quality: Bangkok PM2.5 elevated",
            ],
            "regional": ["- Humanitarian data: Myanmar border"],
            "global": ["- Media heat: Middle East tensions"],
            "rag_recall": [],
        }
        meta = apply_corroboration_pass(digest)
        self.assertEqual(meta["phase"], AgenticPhase.CORROBORATION.value)
        self.assertGreaterEqual(meta["digest_lines_scored"], 3)
        self.assertIn("digest_line_meta", digest)

    def test_format_rag_recall_block(self):
        block = format_rag_recall_block(
            [
                {
                    "text": "RAG recall (situations): Flood near Bangkok",
                    "corroborated": True,
                }
            ],
            lang="en",
        )
        self.assertIn("SUPPLEMENTAL RAG RECALL", block)
        self.assertIn("corroborated", block)

    def test_prompt_includes_rag_block_when_present(self):
        from operator_briefing import build_security_advisor_prompt

        digest = {
            "region_label": "Thailand",
            "window": "24h",
            "local": ["- Local news: test"],
            "regional": ["- Regional item"],
            "global": ["- Global item"],
            "fusion": "none",
            "cyber": ["- none"],
            "infra": ["test"],
            "nodes": ["- none"],
            "intel": {"enabled": False, "count": 0, "entities": [], "items": []},
            "watch_items": [],
            "rag_recall": [
                {
                    "text": "RAG recall (gdelt_pulse_local): Thailand weather",
                    "corroborated": False,
                }
            ],
        }
        prompt = build_security_advisor_prompt(digest)
        self.assertIn("SUPPLEMENTAL RAG RECALL", prompt)


class BriefingAgenticAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_disabled_returns_unchanged(self):
        with patch.dict(os.environ, {"BRIEFING_AGENTIC_LOOP": "0"}):
            digest = {"local": ["- only line"], "regional": [], "global": []}
            out, trace = await run_briefing_agentic_loop(digest)
            self.assertFalse(trace.get("enabled"))
            self.assertEqual(out["local"], digest["local"])

    async def test_loop_retrieve_augmented_digest(self):
        digest = {
            "local": ["- No local signals in feeds (last 24h)."],
            "regional": ["- No regional signals highlighted."],
            "global": ["- No global priorities beyond baseline."],
            "region_label": "Thailand",
        }

        recalls = [
            {
                "bucket": "local",
                "text": "RAG recall (gdelt_pulse_local): Bangkok haze worsens",
                "score": 0.8,
                "source": "gdelt_pulse_local",
                "corroborated": False,
            }
        ]
        retrieve_meta = {
            "phase": AgenticPhase.RETRIEVE.value,
            "retrieved": 1,
            "per_bucket": {"local": 1},
            "errors": [],
        }

        with patch.dict(os.environ, {"BRIEFING_AGENTIC_LOOP": "1"}):
            with patch.object(
                briefing_agentic_mod,
                "_retrieve_for_gaps",
                new=AsyncMock(return_value=(recalls, retrieve_meta)),
            ):
                out, trace = await run_briefing_agentic_loop(digest)
        self.assertTrue(trace.get("enabled"))
        self.assertGreaterEqual(trace.get("rounds"), 2)
        self.assertTrue(any("RAG " in ln for ln in out.get("local") or []))

    async def test_loop_max_three_phases(self):
        digest = {
            "local": ["- No local signals in feeds (last 24h)."],
            "regional": ["- No regional signals highlighted."],
            "global": ["- No global priorities beyond baseline."],
            "region_label": "Thailand",
        }
        with patch.dict(os.environ, {"BRIEFING_AGENTIC_LOOP": "1"}):
            with patch.object(
                briefing_agentic_mod,
                "_retrieve_for_gaps",
                new=AsyncMock(
                    return_value=(
                        [],
                        {
                            "phase": AgenticPhase.RETRIEVE.value,
                            "retrieved": 0,
                            "errors": [],
                        },
                    )
                ),
            ):
                _, trace = await run_briefing_agentic_loop(digest)
        self.assertLessEqual(trace.get("rounds"), 3)
        phases = [p.get("phase") for p in trace.get("phases") or []]
        self.assertEqual(phases[0], AgenticPhase.COVERAGE.value)
        self.assertIn(AgenticPhase.CORROBORATION.value, phases)


if __name__ == "__main__":
    unittest.main()
