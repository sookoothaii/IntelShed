"""Phase 2 — FeedConnector runner unit tests (no network)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from feeds.envelope import FeedEnvelope, build_feed_envelope, validate_feed_payload
from feeds.runner import FeedConnector


class FeedEnvelopeBuilderTests(unittest.TestCase):
    def test_build_feed_envelope_cve_shape(self):
        payload = build_feed_envelope(
            FeedEnvelope(count=2, source="cisa.gov/kev", stale=False, error=None),
            vulnerabilities=[],
        )
        self.assertEqual(validate_feed_payload(payload, endpoint="cve"), [])

    def test_merge_includes_extra_fields(self):
        payload = FeedEnvelope(count=5, sources=["ioda"]).merge(items=[{"lat": 1.0}])
        self.assertEqual(payload["count"], 5)
        self.assertEqual(payload["sources"], ["ioda"])
        self.assertEqual(len(payload["items"]), 1)


class FeedConnectorTests(unittest.TestCase):
    def setUp(self):
        self.connector = FeedConnector(
            "test_feed", ttl_sec=60, default_source="test-src"
        )

    def test_get_cached_miss(self):
        self.assertIsNone(self.connector.get_cached())

    def test_set_and_get_cached(self):
        payload = {
            "count": 1,
            "source": "test-src",
            "updated": "2026-06-21T00:00:00+00:00",
        }
        self.connector.set_cached(payload)
        self.assertEqual(self.connector.get_cached(), payload)

    def test_build_persists_when_fresh(self):
        with patch("feeds.runner.feed_registry.write_auto") as mock_write:
            out = self.connector.build(
                FeedEnvelope(count=3, source="test-src"),
                persist=True,
                items=[],
            )
            mock_write.assert_called_once_with("test_feed", out)
            self.assertEqual(out["count"], 3)

    def test_build_skips_persist_on_error(self):
        with patch("feeds.runner.feed_registry.write_auto") as mock_write:
            self.connector.build(
                FeedEnvelope(count=0, source="test-src", error="upstream down"),
                persist=True,
            )
            mock_write.assert_not_called()

    def test_empty_payload_contract(self):
        out = self.connector.empty_payload("timeout", source="test-src", items=[])
        self.assertEqual(validate_feed_payload(out), [])


class FeedConnectorRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_applies_default_source(self):
        connector = FeedConnector(
            "pegel", ttl_sec=60, default_source="pegelonline.wsv.de"
        )

        async def _fetch():
            return FeedEnvelope(count=2, updated="2026-06-21T00:00:00+00:00").merge(
                gauges=[]
            )

        with patch("feeds.runner.feed_registry.write_auto"):
            out = await connector.run(_fetch, persist=False)
        self.assertEqual(out.get("source"), "pegelonline.wsv.de")
        self.assertEqual(validate_feed_payload(out, endpoint="pegel"), [])


if __name__ == "__main__":
    unittest.main()
