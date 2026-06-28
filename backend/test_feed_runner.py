"""Phase 2 — FeedConnector runner unit tests (no network)."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from feeds.envelope import FeedEnvelope, build_feed_envelope, validate_feed_payload
from feeds.runner import CircuitBreaker, CircuitState, FeedConnector


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


class CircuitBreakerTests(unittest.TestCase):
    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_sec=60)
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertTrue(cb.can_attempt())

    def test_trips_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout_sec=60)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertFalse(cb.can_attempt())
        self.assertIsNotNone(cb.open_until)

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_sec=0.05)
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        self.assertTrue(cb.can_attempt())

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_sec=0.05)
        cb.record_failure()
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        cb.record_success()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout_sec=0.05)
        cb.record_failure()
        time.sleep(0.06)
        self.assertEqual(cb.state, CircuitState.HALF_OPEN)
        cb.record_failure()
        self.assertEqual(cb.state, CircuitState.OPEN)

    def test_exponential_backoff(self):
        cb = CircuitBreaker(
            failure_threshold=1, reset_timeout_sec=60, max_backoff_sec=900
        )
        cb.record_failure()
        self.assertEqual(cb._current_timeout, 60)
        # Simulate open → half-open → failure cycle
        cb._state = CircuitState.HALF_OPEN
        cb.record_failure()
        self.assertEqual(cb._current_timeout, 120)
        cb._state = CircuitState.HALF_OPEN
        cb.record_failure()
        self.assertEqual(cb._current_timeout, 240)

    def test_backoff_capped(self):
        cb = CircuitBreaker(
            failure_threshold=1, reset_timeout_sec=60, max_backoff_sec=200
        )
        for _ in range(10):
            cb._state = CircuitState.HALF_OPEN
            cb.record_failure()
        self.assertLessEqual(cb._current_timeout, 200)

    def test_success_resets_backoff(self):
        cb = CircuitBreaker(
            failure_threshold=1, reset_timeout_sec=60, max_backoff_sec=900
        )
        cb.record_failure()
        cb._state = CircuitState.HALF_OPEN
        cb.record_failure()
        self.assertEqual(cb._current_timeout, 120)
        cb.record_success()
        self.assertEqual(cb._current_timeout, 60)


class FeedConnectorCircuitBreakerTests(unittest.IsolatedAsyncioTestCase):
    async def test_circuit_open_serves_stale(self):
        """When circuit is OPEN, run() skips fetch and serves stale from memory."""
        connector = FeedConnector("failing_feed", ttl_sec=0.01, default_source="test")

        # Pre-seed memory with a payload
        connector.set_cached({"count": 1, "source": "test", "updated": "2026-01-01"})

        # Force the breaker into OPEN state
        cb = connector._ensure_breaker()
        if cb:
            for _ in range(cb.failure_threshold):
                cb.record_failure()

        call_count = 0

        async def _fetch():
            nonlocal call_count
            call_count += 1
            return {"count": 99, "source": "test"}

        # Wait for TTL to expire so cached is stale
        await asyncio.sleep(0.02)
        out = await connector.run(_fetch, persist=False)
        self.assertEqual(call_count, 0, "fetch should not be called when circuit open")
        self.assertTrue(out.get("stale"))

    async def test_circuit_closed_allows_fetch(self):
        """When circuit is CLOSED, run() calls fetch normally."""
        connector = FeedConnector("ok_feed", ttl_sec=0.01, default_source="test")

        call_count = 0

        async def _fetch():
            nonlocal call_count
            call_count += 1
            return {"count": 5, "source": "test"}

        await asyncio.sleep(0.02)
        out = await connector.run(_fetch, persist=False)
        self.assertEqual(call_count, 1)
        self.assertEqual(out["count"], 5)

    async def test_repeated_failures_open_circuit(self):
        """N consecutive failures trip the breaker to OPEN."""
        connector = FeedConnector("flaky_feed", ttl_sec=0.01, default_source="test")

        async def _fail():
            raise ConnectionError("upstream gone")

        with patch("feeds.runner.feed_registry.write_auto"):
            for _ in range(10):
                await connector.run(_fail, persist=False)

        cb = connector._ensure_breaker()
        if cb:
            self.assertEqual(cb.state, CircuitState.OPEN)


if __name__ == "__main__":
    unittest.main()
