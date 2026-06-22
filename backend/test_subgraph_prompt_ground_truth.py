"""Unit tests for subgraph prompt A/B pilot (B-05, no network)."""

from __future__ import annotations

import unittest

from subgraph_prompt_ground_truth import (
    _caption_overlap,
    compare_prompt_ab,
    run_fixture_pilot,
)


class SubgraphPromptGroundTruthTests(unittest.TestCase):
    def test_caption_overlap_partial(self):
        items = [{"text": "Event: Bangkok flooding alert (gdacs)"}]
        nodes = [{"caption": "Bangkok flooding alert"}]
        overlap = _caption_overlap(items, nodes)
        self.assertGreaterEqual(overlap, 0.99)

    def test_compare_prompt_ab_empty_intel(self):
        ab = compare_prompt_ab({"enabled": True, "items": [], "window_hours": 48})
        self.assertIn("flat_chars", ab)
        self.assertIn("active_mode", ab)

    def test_fixture_pilot_all_pass(self):
        report = run_fixture_pilot()
        self.assertEqual(report["passed"], report["total"])
        self.assertGreater(report["total"], 0)


if __name__ == "__main__":
    unittest.main()
