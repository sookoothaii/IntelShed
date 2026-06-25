"""Unit tests for operator-first fusion hotspot ranking (no network)."""

import unittest

import fusion_heatmap as fh


class TestFusionOperatorRank(unittest.TestCase):
    def test_rank_cells_for_operator_prefers_thailand_over_us(self):
        cells = [
            {
                "lat": 33.0,
                "lon": -89.0,
                "score": 0.9,
                "intensity": 9.0,
                "sources": ["quakes"],
            },
            {
                "lat": 13.75,
                "lon": 100.5,
                "score": 0.55,
                "intensity": 5.0,
                "sources": ["gdacs"],
            },
            {
                "lat": 3.5,
                "lon": 104.0,
                "score": 0.7,
                "intensity": 7.0,
                "sources": ["gdacs"],
            },
        ]
        ranked = fh.rank_cells_for_operator(cells, top=2)
        self.assertEqual(len(ranked), 2)
        lats = [c["lat"] for c in ranked]
        self.assertIn(13.75, lats)
        self.assertNotIn(33.0, lats)


if __name__ == "__main__":
    unittest.main()
