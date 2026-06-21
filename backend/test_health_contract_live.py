"""Phase 0 — live feed-envelope contract (opt-in, network).

Skips when the API is unreachable, so it is safe in the offline unit suite.
The smoke test runs it against the live backend to catch real bridge drift.

Two layers:
  * every /api/health feeds[...] row → structural contract (lenient on count).
  * curated endpoints that guarantee count + provenance → full envelope.
"""

from __future__ import annotations

import json
import os
import unittest
import urllib.error
import urllib.request

from feeds.envelope import validate_feed_payload, validate_health_feeds

BASE_URL = os.getenv("WORLDBASE_SMOKE_BASE", "http://127.0.0.1:8002").rstrip("/")

# Endpoints whose payloads always carry count + source (full envelope check).
CURATED_ENDPOINTS = (
    "/api/cve",
    "/api/wildfires",
    "/api/gdacs",
)


def _get_json(path: str, timeout: float = 30.0):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "WorldBase-contract-test"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted localhost)
        return json.loads(resp.read().decode("utf-8"))


def _api_reachable() -> bool:
    try:
        _get_json("/api/health/ping", timeout=4.0)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


@unittest.skipUnless(_api_reachable(), f"API not reachable at {BASE_URL}")
class HealthContractLiveTests(unittest.TestCase):
    def test_health_feed_rows_satisfy_contract(self):
        health = _get_json("/api/health", timeout=120.0)
        feeds = health.get("feeds", {})
        self.assertTrue(feeds, "no feeds in /api/health")
        violations = validate_health_feeds(feeds)
        self.assertEqual(violations, [], msg=f"health row drift: {violations}")

    def test_curated_endpoints_full_envelope(self):
        for path in CURATED_ENDPOINTS:
            with self.subTest(endpoint=path):
                try:
                    payload = _get_json(path, timeout=60.0)
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    self.skipTest(f"{path} unreachable: {exc}")
                # Upstream-down responses are fail-soft (count:0 + error) and
                # still satisfy the envelope; only assert when not errored out.
                violations = validate_feed_payload(payload, endpoint=path)
                self.assertEqual(violations, [], msg=f"{path} envelope drift: {violations}")


if __name__ == "__main__":
    unittest.main()
