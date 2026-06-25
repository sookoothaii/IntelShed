"""Unit tests for corroboration ground-truth pilot (B-04, no network)."""

from __future__ import annotations

import unittest

import corroboration_ground_truth as cg


class CorroborationGroundTruthTests(unittest.TestCase):
    def test_all_fixtures_pass(self):
        report = cg.run_fixture_pilot()
        self.assertEqual(report["total"], len(cg.GROUND_TRUTH_CASES))
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["accuracy"], 1.0)

    def test_quake_gdacs_case(self):
        case = next(
            c for c in cg.GROUND_TRUTH_CASES if c.case_id == "gt-quake-gdacs-dual"
        )
        row = cg.evaluate_case(case)
        self.assertTrue(row["ok"])
        self.assertGreaterEqual(row["corroboration"], 0.8)


if __name__ == "__main__":
    unittest.main()
