"""Unit tests for the shared freshness classifier."""

from __future__ import annotations

import unittest

from freshness import classify_freshness


class ClassifyFreshnessDriftTests(unittest.TestCase):
    """Vocab='drift' → fresh | aging | stale | error | missing."""

    def test_fresh(self):
        self.assertEqual(classify_freshness(10, 300, vocab="drift"), "fresh")

    def test_aging(self):
        self.assertEqual(classify_freshness(350, 300, vocab="drift"), "aging")

    def test_stale_by_age(self):
        self.assertEqual(classify_freshness(700, 300, vocab="drift"), "stale")

    def test_error_overrides_age(self):
        self.assertEqual(
            classify_freshness(10, 300, error="timeout", vocab="drift"), "error"
        )

    def test_stale_flag_overrides_age(self):
        self.assertEqual(
            classify_freshness(10, 300, stale_flag=True, vocab="drift"), "stale"
        )

    def test_error_overrides_stale_flag(self):
        self.assertEqual(
            classify_freshness(10, 300, error="timeout", stale_flag=True, vocab="drift"),
            "error",
        )

    def test_missing_no_payload(self):
        self.assertEqual(
            classify_freshness(None, 300, has_payload=False, vocab="drift"), "missing"
        )

    def test_age_none_with_payload(self):
        self.assertEqual(classify_freshness(None, 300, vocab="drift"), "missing")


class ClassifyFreshnessHealthTests(unittest.TestCase):
    """Vocab='health' → fresh | warn | stale | unknown."""

    def test_fresh(self):
        self.assertEqual(classify_freshness(10, 300, vocab="health"), "fresh")

    def test_warn(self):
        self.assertEqual(classify_freshness(350, 300, vocab="health"), "warn")

    def test_stale_by_age(self):
        self.assertEqual(classify_freshness(700, 300, vocab="health"), "stale")

    def test_error_maps_to_stale(self):
        """Health vocab has no 'error' status — errors map to 'stale'."""
        self.assertEqual(
            classify_freshness(10, 300, error="timeout", vocab="health"), "stale"
        )

    def test_stale_flag(self):
        self.assertEqual(
            classify_freshness(10, 300, stale_flag=True, vocab="health"), "stale"
        )

    def test_no_payload_unknown(self):
        self.assertEqual(
            classify_freshness(None, 300, has_payload=False, vocab="health"), "unknown"
        )

    def test_age_none_unknown(self):
        self.assertEqual(classify_freshness(None, 300, vocab="health"), "unknown")


class FreshnessConsistencyTests(unittest.TestCase):
    """Verify the two vocabularies agree where they overlap."""

    def test_fresh_agrees(self):
        self.assertEqual(
            classify_freshness(10, 300, vocab="drift"),
            classify_freshness(10, 300, vocab="health"),
        )

    def test_stale_by_age_agrees(self):
        self.assertEqual(
            classify_freshness(700, 300, vocab="drift"),
            classify_freshness(700, 300, vocab="health"),
        )

    def test_stale_flag_agrees(self):
        self.assertEqual(
            classify_freshness(10, 300, stale_flag=True, vocab="drift"),
            classify_freshness(10, 300, stale_flag=True, vocab="health"),
        )

    def test_aging_vs_warn_same_boundary(self):
        """Both use ttl*2 as the fresh→aging/warn→stale boundary."""
        self.assertEqual(classify_freshness(350, 300, vocab="drift"), "aging")
        self.assertEqual(classify_freshness(350, 300, vocab="health"), "warn")
        self.assertEqual(classify_freshness(599, 300, vocab="drift"), "aging")
        self.assertEqual(classify_freshness(599, 300, vocab="health"), "warn")
        self.assertEqual(classify_freshness(601, 300, vocab="drift"), "stale")
        self.assertEqual(classify_freshness(601, 300, vocab="health"), "stale")


if __name__ == "__main__":
    unittest.main()
