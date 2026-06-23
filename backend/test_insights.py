"""Track A insight synthesis — deterministic ranking, confidence, dedup, fail-soft."""

import asyncio
import unittest
from unittest.mock import patch

import insights


def _cell(cell_id, lat, lon, score, *, delta=0.0, sources=None, sample=None):
    return {
        "cell_id": cell_id,
        "lat": lat,
        "lon": lon,
        "score": score,
        "delta_score": delta,
        "sources": sources or [],
        "samples": ([{"source": "x", "label": sample}] if sample else []),
    }


class InsightSynthesisTests(unittest.TestCase):
    def test_rising_cells_rank_first(self):
        hotspots = [
            _cell("a", 13.0, 101.0, 0.9, delta=0.0, sources=["hazard"]),
            _cell("b", 14.0, 100.0, 0.5, delta=0.30, sources=["gdacs", "anomaly"]),
        ]
        out = insights.synthesize_insights(hotspots, [], top=10, with_entities=False)
        self.assertEqual(out[0]["cell_id"], "b")  # rising beats higher score
        self.assertTrue(out[0]["rising"])
        self.assertEqual(out[0]["rank"], 1)
        self.assertFalse(out[1]["rising"])

    def test_confidence_increases_with_families_and_delta(self):
        single = insights.synthesize_insights(
            [_cell("a", 13.0, 101.0, 0.4, sources=["hazard"])], [], with_entities=False
        )[0]
        multi = insights.synthesize_insights(
            [_cell("b", 13.0, 101.0, 0.4, delta=0.2, sources=["hazard", "gdacs", "quake"])],
            [],
            with_entities=False,
        )[0]
        self.assertLess(single["confidence"], multi["confidence"])
        self.assertIn("source famil", single["confidence_basis"])

    def test_dedup_by_cell_id(self):
        hotspots = [
            _cell("dup", 1.0, 2.0, 0.6, sources=["a"]),
            _cell("dup", 1.0, 2.0, 0.6, sources=["a"]),
        ]
        out = insights.synthesize_insights(hotspots, [], with_entities=False)
        self.assertEqual(len(out), 1)

    def test_top_cap_and_rank(self):
        hotspots = [_cell(f"c{i}", float(i), 100.0, 0.9 - i * 0.05, sources=["x"]) for i in range(15)]
        out = insights.synthesize_insights(hotspots, [], top=10, with_entities=False)
        self.assertEqual(len(out), 10)
        self.assertEqual([i["rank"] for i in out], list(range(1, 11)))

    def test_delta_from_delta_map(self):
        hotspots = [_cell("a", 13.0, 101.0, 0.5, delta=0.0, sources=["x"])]
        deltas = [{"cell_id": "a", "delta_score": 0.25}]
        out = insights.synthesize_insights(hotspots, deltas, with_entities=False)
        self.assertTrue(out[0]["rising"])
        self.assertEqual(out[0]["delta_score"], 0.25)

    def test_skips_cells_without_coords(self):
        hotspots = [{"cell_id": "x", "lat": None, "lon": None, "score": 0.9, "sources": []}]
        out = insights.synthesize_insights(hotspots, [], with_entities=False)
        self.assertEqual(out, [])


class InsightBuildTests(unittest.TestCase):
    def test_build_insights_empty_when_no_hotspots(self):
        async def fake(*a, **k):
            return ([], "- none", [])

        with patch.object(insights.fusion_heatmap, "top_hotspots_for_llm", fake):
            payload = asyncio.run(insights.build_insights(top=10))
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["insights"], [])

    def test_build_insights_failsoft_on_error(self):
        async def boom(*a, **k):
            raise RuntimeError("fusion down")

        with patch.object(insights.fusion_heatmap, "top_hotspots_for_llm", boom):
            payload = asyncio.run(insights.build_insights(top=10))
        self.assertEqual(payload["count"], 0)
        self.assertIn("error", payload)

    def test_build_insights_synthesizes(self):
        async def fake(*a, **k):
            return (
                [_cell("a", 13.0, 101.0, 0.8, delta=0.2, sources=["gdacs", "anomaly"], sample="Flood")],
                "- text",
                [{"cell_id": "a", "delta_score": 0.2}],
            )

        with patch.object(insights.fusion_heatmap, "top_hotspots_for_llm", fake), patch.object(
            insights, "_entities_for", lambda bbox: []
        ), patch.object(insights, "_LLM_ENABLED", False):
            payload = asyncio.run(insights.build_insights(top=10))
        self.assertEqual(payload["count"], 1)
        ins = payload["insights"][0]
        self.assertEqual(ins["rank"], 1)
        self.assertTrue(ins["rising"])
        self.assertEqual(ins["narrative_source"], "template")
        self.assertIn("Flood", ins["headline"])


class NarrationTests(unittest.TestCase):
    def setUp(self):
        insights._NARRATIVE_CACHE.clear()

    def test_parse_narration_strict_format(self):
        text = (
            "1| Flood escalating in Texas :: Two feeds converge; check before briefing.\n"
            "garbage line that should be ignored\n"
            "2| Quiet cell :: Single source only; monitor.\n"
        )
        parsed = insights._parse_narration(text)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[1][0], "Flood escalating in Texas")
        self.assertIn("converge", parsed[1][1])

    def test_narrate_applies_llm_text(self):
        ins = insights.synthesize_insights(
            [_cell("a", 13.0, 101.0, 0.8, delta=0.2, sources=["gdacs", "anomaly"], sample="Flood")],
            [],
            with_entities=False,
        )

        async def fake_complete(prompt):
            return "1| LLM headline :: LLM so what sentence."

        with patch.object(insights, "_ollama_complete", fake_complete), patch.object(
            insights, "_LLM_ENABLED", True
        ):
            out = asyncio.run(insights.narrate_insights(ins))
        self.assertEqual(out[0]["headline"], "LLM headline")
        self.assertEqual(out[0]["narrative_source"], "ollama")

    def test_narrate_failsoft_keeps_template(self):
        ins = insights.synthesize_insights(
            [_cell("a", 13.0, 101.0, 0.8, sources=["x"])], [], with_entities=False
        )
        template_headline = ins[0]["headline"]

        async def empty(prompt):
            return ""

        with patch.object(insights, "_ollama_complete", empty), patch.object(
            insights, "_LLM_ENABLED", True
        ):
            out = asyncio.run(insights.narrate_insights(ins))
        self.assertEqual(out[0]["headline"], template_headline)
        self.assertEqual(out[0]["narrative_source"], "template")

    def test_narrate_disabled_noop(self):
        ins = insights.synthesize_insights(
            [_cell("a", 13.0, 101.0, 0.8, sources=["x"])], [], with_entities=False
        )

        async def boom(prompt):
            raise AssertionError("should not be called when disabled")

        with patch.object(insights, "_ollama_complete", boom), patch.object(
            insights, "_LLM_ENABLED", False
        ):
            out = asyncio.run(insights.narrate_insights(ins))
        self.assertEqual(out[0]["narrative_source"], "template")

    def test_narrate_uses_cache_second_call(self):
        ins = insights.synthesize_insights(
            [_cell("a", 13.0, 101.0, 0.8, sources=["x"])], [], with_entities=False
        )
        calls = {"n": 0}

        async def once(prompt):
            calls["n"] += 1
            return "1| Cached headline :: Cached so what."

        with patch.object(insights, "_ollama_complete", once), patch.object(
            insights, "_LLM_ENABLED", True
        ):
            asyncio.run(insights.narrate_insights(ins))
            # rebuild identical insight → should hit cache, not call LLM again
            ins2 = insights.synthesize_insights(
                [_cell("a", 13.0, 101.0, 0.8, sources=["x"])], [], with_entities=False
            )
            out2 = asyncio.run(insights.narrate_insights(ins2))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(out2[0]["headline"], "Cached headline")
        self.assertEqual(out2[0]["narrative_source"], "ollama")


class SlimAndPromptTests(unittest.TestCase):
    def _sample(self):
        return insights.synthesize_insights(
            [
                _cell("a", 13.0, 101.0, 0.8, delta=0.2, sources=["gdacs", "anomaly"], sample="Flood"),
                _cell("b", 14.0, 100.0, 0.6, sources=["hazard"]),
            ],
            [],
            with_entities=False,
        )

    def test_slim_insights_shape_and_cap(self):
        slim = insights.slim_insights(self._sample(), top=1)
        self.assertEqual(len(slim), 1)
        self.assertIn("headline", slim[0])
        self.assertIn("center", slim[0])
        self.assertNotIn("bbox", slim[0])
        self.assertNotIn("entities", slim[0])

    def test_prompt_block_lists_ranked_insights(self):
        block = insights.format_insights_prompt_block(self._sample(), top=2)
        self.assertIn("INSIGHTS", block)
        self.assertIn("#1", block)
        self.assertIn("conf", block)

    def test_prompt_block_empty_when_no_insights(self):
        self.assertEqual(insights.format_insights_prompt_block([], top=5), "")


if __name__ == "__main__":
    unittest.main()
