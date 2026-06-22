"""Unit tests for prediction ground-truth pilot (B-03, no network)."""

from __future__ import annotations

import unittest

import prediction_ground_truth as gt


class PredictionGroundTruthTests(unittest.TestCase):
    def test_all_fixtures_pass(self):
        report = gt.run_fixture_pilot()
        self.assertEqual(report["total"], 10)
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["accuracy"], 1.0)

    def test_evaluate_case_returns_outcome(self):
        case = gt.GROUND_TRUTH_CASES[0]
        row = gt.evaluate_case(case)
        self.assertTrue(row["ok"])
        self.assertTrue(row["actual_hit"])
        self.assertIn("media", row["outcome"].lower())


if __name__ == "__main__":
    unittest.main()
