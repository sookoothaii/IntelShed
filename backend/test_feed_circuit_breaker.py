"""Tests for V4-64 Feed Circuit Breaker + ETag Polling.

Tests:
- Circuit breaker state transitions (closed → open → half-open → closed)
- Consecutive failure threshold
- Cooldown timing
- ETag / Last-Modified conditional header tracking
- can_request gating
- get_all_circuits status
- reset_circuit
- FeedEnvelope etag/last_modified fields
"""

import os
import sys
import time
from unittest.mock import patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestCircuitBreakerConfig:
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_FEED_CIRCUIT_BREAKER", None)
            import feed_circuit_breaker

            assert feed_circuit_breaker.circuit_breaker_enabled() is True

    def test_disabled(self):
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "0"}):
            import feed_circuit_breaker

            assert feed_circuit_breaker.circuit_breaker_enabled() is False


class TestCircuitBreakerStates:
    def test_initial_state_is_closed(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        circuit = fcb.get_circuit("test_feed_1")
        assert circuit.state == fcb.CircuitState.CLOSED
        assert circuit.consecutive_failures == 0

    def test_can_request_when_closed(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        assert fcb.can_request("test_feed_2") is True

    def test_can_request_when_disabled(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "0"}):
            assert fcb.can_request("test_feed_3") is True

    def test_circuit_opens_after_threshold(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 3):
                feed_id = "test_threshold"
                for i in range(3):
                    fcb.record_failure(feed_id, f"error_{i}")

                circuit = fcb.get_circuit(feed_id)
                assert circuit.state == fcb.CircuitState.OPEN
                assert circuit.consecutive_failures == 3
                assert fcb.can_request(feed_id) is False

    def test_circuit_does_not_open_below_threshold(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 5):
                feed_id = "test_below_threshold"
                for i in range(4):
                    fcb.record_failure(feed_id, f"error_{i}")

                circuit = fcb.get_circuit(feed_id)
                assert circuit.state == fcb.CircuitState.CLOSED
                assert fcb.can_request(feed_id) is True

    def test_success_resets_failures(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 5):
                feed_id = "test_success_reset"
                fcb.record_failure(feed_id, "error_1")
                fcb.record_failure(feed_id, "error_2")
                fcb.record_success(feed_id)

                circuit = fcb.get_circuit(feed_id)
                assert circuit.state == fcb.CircuitState.CLOSED
                assert circuit.consecutive_failures == 0
                assert circuit.total_successes == 1

    def test_half_open_after_cooldown(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 2):
                with patch.object(fcb, "_COOLDOWN", 0.1):
                    feed_id = "test_half_open"
                    fcb.record_failure(feed_id, "error_1")
                    fcb.record_failure(feed_id, "error_2")

                    circuit = fcb.get_circuit(feed_id)
                    assert circuit.state == fcb.CircuitState.OPEN

                    # Wait for cooldown
                    time.sleep(0.15)

                    # Should allow request (half-open)
                    assert fcb.can_request(feed_id) is True
                    assert circuit.state == fcb.CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 2):
                with patch.object(fcb, "_COOLDOWN", 0.1):
                    feed_id = "test_half_open_success"
                    fcb.record_failure(feed_id, "error_1")
                    fcb.record_failure(feed_id, "error_2")
                    assert circuit_state(fcb, feed_id) == fcb.CircuitState.OPEN

                    time.sleep(0.15)
                    fcb.can_request(feed_id)  # triggers half-open
                    fcb.record_success(feed_id)

                    circuit = fcb.get_circuit(feed_id)
                    assert circuit.state == fcb.CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 2):
                with patch.object(fcb, "_COOLDOWN", 0.1):
                    feed_id = "test_half_open_failure"
                    fcb.record_failure(feed_id, "error_1")
                    fcb.record_failure(feed_id, "error_2")
                    assert circuit_state(fcb, feed_id) == fcb.CircuitState.OPEN

                    time.sleep(0.15)
                    fcb.can_request(feed_id)  # triggers half-open
                    fcb.record_failure(feed_id, "error_3")

                    circuit = fcb.get_circuit(feed_id)
                    assert circuit.state == fcb.CircuitState.OPEN


class TestETagConditionalHeaders:
    def test_get_conditional_headers_empty(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        headers = fcb.get_conditional_headers("test_etag_1")
        assert headers == {}

    def test_update_and_get_etag(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        fcb.update_conditional_headers("test_etag_2", {"ETag": '"abc123"'})
        headers = fcb.get_conditional_headers("test_etag_2")
        assert headers.get("If-None-Match") == '"abc123"'

    def test_update_and_get_last_modified(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        fcb.update_conditional_headers(
            "test_etag_3", {"Last-Modified": "Wed, 21 Oct 2026 07:28:00 GMT"}
        )
        headers = fcb.get_conditional_headers("test_etag_3")
        assert headers.get("If-Modified-Since") == "Wed, 21 Oct 2026 07:28:00 GMT"

    def test_record_success_updates_etag(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        fcb.record_success(
            "test_etag_4",
            etag='"xyz789"',
            last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
        )
        headers = fcb.get_conditional_headers("test_etag_4")
        assert headers.get("If-None-Match") == '"xyz789"'
        assert headers.get("If-Modified-Since") == "Mon, 01 Jan 2026 00:00:00 GMT"

    def test_conditional_headers_disabled(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "0"}):
            fcb.update_conditional_headers("test_etag_5", {"ETag": '"abc"'})
            headers = fcb.get_conditional_headers("test_etag_5")
            assert headers == {}


class TestCircuitBreakerStatus:
    def test_get_all_circuits(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            fcb.record_success("feed_a")
            fcb.record_failure("feed_b", "timeout")
            status = fcb.get_all_circuits()

            assert "feed_a" in status
            assert "feed_b" in status
            assert status["feed_a"]["state"] == "closed"
            assert status["feed_b"]["state"] == "closed"
            assert status["feed_b"]["consecutive_failures"] == 1
            assert status["feed_a"]["stats"]["total_successes"] == 1

    def test_reset_circuit(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        with patch.dict(os.environ, {"WORLDBASE_FEED_CIRCUIT_BREAKER": "1"}):
            with patch.object(fcb, "_THRESHOLD", 2):
                feed_id = "test_reset"
                fcb.record_failure(feed_id, "e1")
                fcb.record_failure(feed_id, "e2")
                assert circuit_state(fcb, feed_id) == fcb.CircuitState.OPEN

                assert fcb.reset_circuit(feed_id) is True
                assert circuit_state(fcb, feed_id) == fcb.CircuitState.CLOSED

    def test_reset_nonexistent_circuit(self):
        import feed_circuit_breaker as fcb

        fcb._CIRCUITS.clear()
        assert fcb.reset_circuit("nonexistent") is False


class TestFeedEnvelopeETag:
    def test_envelope_has_etag_field(self):
        from feeds.envelope import FeedEnvelope

        env = FeedEnvelope(count=5, etag='"abc123"')
        assert env.etag == '"abc123"'

    def test_envelope_has_last_modified_field(self):
        from feeds.envelope import FeedEnvelope

        env = FeedEnvelope(count=5, last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
        assert env.last_modified == "Mon, 01 Jan 2026 00:00:00 GMT"

    def test_build_envelope_includes_etag(self):
        from feeds.envelope import FeedEnvelope, build_feed_envelope

        env = FeedEnvelope(count=5, etag='"abc123"')
        out = build_feed_envelope(env)
        assert out["etag"] == '"abc123"'

    def test_build_envelope_includes_last_modified(self):
        from feeds.envelope import FeedEnvelope, build_feed_envelope

        env = FeedEnvelope(count=5, last_modified="Mon, 01 Jan 2026 00:00:00 GMT")
        out = build_feed_envelope(env)
        assert out["last_modified"] == "Mon, 01 Jan 2026 00:00:00 GMT"

    def test_build_envelope_without_etag(self):
        from feeds.envelope import FeedEnvelope, build_feed_envelope

        env = FeedEnvelope(count=5)
        out = build_feed_envelope(env)
        assert "etag" not in out
        assert "last_modified" not in out

    def test_health_meta_keys_includes_etag(self):
        from feeds.envelope import HEALTH_META_KEYS

        assert "etag" in HEALTH_META_KEYS
        assert "last_modified" in HEALTH_META_KEYS

    def test_extract_health_feed_meta_includes_etag(self):
        from feeds.envelope import extract_health_feed_meta

        val = {
            "count": 5,
            "etag": '"abc"',
            "last_modified": "Mon, 01 Jan 2026 00:00:00 GMT",
        }
        meta = extract_health_feed_meta(val)
        assert meta.get("etag") == '"abc"'
        assert meta.get("last_modified") == "Mon, 01 Jan 2026 00:00:00 GMT"


class TestCircuitBreakerEndpoint:
    def test_endpoint_returns_status(self):
        import feed_circuit_breaker as fcb
        from fastapi.testclient import TestClient

        fcb._CIRCUITS.clear()
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(fcb.router)
        client = TestClient(app)
        resp = client.get("/api/feeds/circuit-breaker")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "threshold" in data
        assert "cooldown_sec" in data
        assert "feeds" in data


# Helper
def circuit_state(fcb, feed_id: str):
    return fcb.get_circuit(feed_id).state
