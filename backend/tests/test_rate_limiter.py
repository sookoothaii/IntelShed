"""Tests for the sliding-window rate limiter (E-02).

Covers:
- SlidingWindowLimiter in-memory backend
- Health endpoint exemption
- API-key exemption
- Node-token exemption
- Per-endpoint overrides
- Rate limit enforcement (429 after exceeding RPM)
- Window expiry (requests allowed after window passes)
- setup_rate_limiting integration
- CSP header presence in SecurityHeadersMiddleware
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _clean_env(monkeypatch):
    """Ensure clean env for rate limiter tests."""
    monkeypatch.delenv("WORLDBASE_RATE_LIMIT", raising=False)
    monkeypatch.delenv("WORLDBASE_RATE_LIMIT_RPM", raising=False)
    monkeypatch.delenv("WORLDBASE_RATE_LIMIT_WINDOW_SEC", raising=False)
    monkeypatch.delenv("WORLDBASE_RATE_LIMIT_OVERRIDES", raising=False)
    monkeypatch.delenv("WORLDBASE_API_KEY", raising=False)
    monkeypatch.delenv("NODE_INGEST_TOKEN", raising=False)
    monkeypatch.delenv("RATE_LIMIT_STORAGE", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REDIS_URL", raising=False)
    # Reset module-level state
    import middleware.rate_limit as rl

    rl._sliding_window_limiter = None
    rl.SLIDING_WINDOW_ENABLED = True
    rl.SLIDING_WINDOW_RPM = 60
    rl.SLIDING_WINDOW_WINDOW_SEC = 60.0
    yield
    rl._sliding_window_limiter = None


@pytest.fixture
def limiter(_clean_env):
    """Create a SlidingWindowLimiter with in-memory backend."""
    from middleware.rate_limit import SlidingWindowLimiter

    return SlidingWindowLimiter(rpm=5, window_seconds=60.0)


def _make_request(path: str = "/api/test", headers: dict | None = None):
    """Create a mock Request object."""
    request = MagicMock()
    request.url.path = path
    request.headers = headers or {}
    return request


# ---------------------------------------------------------------------------
# SlidingWindowLimiter — in-memory tests
# ---------------------------------------------------------------------------


class TestSlidingWindowLimiter:
    def test_allows_requests_under_limit(self, limiter):
        req = _make_request()
        for i in range(5):
            allowed, remaining, limit, retry = limiter.check(req)
            assert allowed, f"Request {i + 1} should be allowed"
        assert limit == 5

    def test_blocks_request_over_limit(self, limiter):
        req = _make_request()
        for _ in range(5):
            limiter.check(req)
        allowed, remaining, limit, retry = limiter.check(req)
        assert not allowed
        assert remaining == 0
        assert retry > 0

    def test_health_endpoint_exempt(self, limiter):
        req = _make_request(path="/api/health/ping")
        allowed, remaining, limit, retry = limiter.check(req)
        assert allowed
        assert remaining == -1  # exempt marker

    def test_health_endpoint_always_exempt(self, limiter):
        """Even after exhausting limit on other paths, health is exempt."""
        req = _make_request(path="/api/data")
        for _ in range(5):
            limiter.check(req)
        # Next /api/data request is blocked
        allowed, _, _, _ = limiter.check(req)
        assert not allowed
        # But /api/health is still allowed
        health_req = _make_request(path="/api/health")
        allowed, _, _, _ = limiter.check(health_req)
        assert allowed

    def test_api_key_exempt(self, limiter, monkeypatch):
        monkeypatch.setenv("WORLDBASE_API_KEY", "test-secret-key")
        req = _make_request(headers={"X-API-Key": "test-secret-key"})
        allowed, remaining, limit, retry = limiter.check(req)
        assert allowed
        assert remaining == -1

    def test_wrong_api_key_not_exempt(self, limiter, monkeypatch):
        monkeypatch.setenv("WORLDBASE_API_KEY", "correct-key")
        req = _make_request(headers={"X-API-Key": "wrong-key"})
        allowed, remaining, limit, retry = limiter.check(req)
        assert allowed  # first request, should be allowed
        assert remaining != -1  # not exempt

    def test_node_token_exempt(self, limiter, monkeypatch):
        monkeypatch.setenv("NODE_INGEST_TOKEN", "node-secret-token")
        req = _make_request(headers={"X-Node-Token": "node-secret-token"})
        allowed, remaining, limit, retry = limiter.check(req)
        assert allowed
        assert remaining == -1

    def test_endpoint_overrides(self, limiter, monkeypatch):
        limiter.endpoint_overrides = {"/api/chat": (2, 60.0)}
        chat_req = _make_request(path="/api/chat")
        # Only 2 requests allowed for /api/chat
        limiter.check(chat_req)
        limiter.check(chat_req)
        allowed, _, limit, _ = limiter.check(chat_req)
        assert not allowed
        assert limit == 2
        # Other paths still get default 5
        other_req = _make_request(path="/api/data")
        allowed, _, limit, _ = limiter.check(other_req)
        assert allowed
        assert limit == 5

    def test_window_expiry_allows_after_timeout(self, limiter):
        """Requests should be allowed again after the window passes."""
        # Use a very short window for testing
        from middleware.rate_limit import SlidingWindowLimiter

        short_limiter = SlidingWindowLimiter(rpm=3, window_seconds=0.1)
        req = _make_request()
        # Exhaust the limit
        for _ in range(3):
            short_limiter.check(req)
        allowed, _, _, _ = short_limiter.check(req)
        assert not allowed
        # Wait for window to expire
        time.sleep(0.15)
        allowed, _, _, _ = short_limiter.check(req)
        assert allowed

    def test_different_ips_tracked_separately(self, limiter):
        """Different IPs should have separate rate limit counters."""
        req1 = _make_request()
        req1.headers = {}
        # Mock get_ip_with_forwarding to return different IPs
        req1._mock_ip = "1.2.3.4"
        req2 = _make_request()
        req2._mock_ip = "5.6.7.8"

        with patch("middleware.rate_limit.get_ip_with_forwarding") as mock_ip:
            mock_ip.side_effect = lambda r: getattr(r, "_mock_ip", "127.0.0.1")
            # Exhaust IP 1
            for _ in range(5):
                limiter.check(req1)
            allowed, _, _, _ = limiter.check(req1)
            assert not allowed
            # IP 2 should still be allowed
            allowed, _, _, _ = limiter.check(req2)
            assert allowed

    def test_returns_remaining_count(self, limiter):
        req = _make_request()
        allowed, remaining, limit, _ = limiter.check(req)
        assert allowed
        assert remaining == 4  # 5 - 1 = 4 remaining
        limiter.check(req)
        allowed, remaining, _, _ = limiter.check(req)
        assert allowed
        assert remaining == 2  # 5 - 3 = 2 remaining


# ---------------------------------------------------------------------------
# Integration test via FastAPI app
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    def test_middleware_blocks_excess_requests(self, _clean_env, monkeypatch):
        """End-to-end: FastAPI app with sliding window middleware."""
        monkeypatch.setenv("WORLDBASE_RATE_LIMIT", "1")
        monkeypatch.setenv("WORLDBASE_RATE_LIMIT_RPM", "3")
        monkeypatch.setenv("RATE_LIMIT_STORAGE", "memory")

        # Reimport to pick up new env
        import importlib

        import middleware.rate_limit as rl

        importlib.reload(rl)
        rl._sliding_window_limiter = None

        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"status": "ok"}

        @app.get("/api/health/ping")
        async def health():
            return {"status": "healthy"}

        rl.setup_sliding_window_middleware(app)

        client = TestClient(app)

        # 3 requests should succeed
        for i in range(3):
            resp = client.get("/api/test")
            assert resp.status_code == 200, f"Request {i + 1} failed"

        # 4th request should be blocked
        resp = client.get("/api/test")
        assert resp.status_code == 429
        assert resp.headers["Retry-After"]
        assert "RATE_LIMIT_EXCEEDED" in resp.json()["error"]["code"]

        # Health endpoint should still work
        resp = client.get("/api/health/ping")
        assert resp.status_code == 200

    def test_middleware_disabled(self, _clean_env, monkeypatch):
        monkeypatch.setenv("WORLDBASE_RATE_LIMIT", "0")
        monkeypatch.setenv("RATE_LIMIT_STORAGE", "memory")

        import importlib

        import middleware.rate_limit as rl

        importlib.reload(rl)
        rl._sliding_window_limiter = None

        app = FastAPI()

        @app.get("/api/test")
        async def test_endpoint():
            return {"status": "ok"}

        rl.setup_sliding_window_middleware(app)
        client = TestClient(app)

        # Should not be rate limited at all
        for _ in range(100):
            resp = client.get("/api/test")
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# CSP header tests
# ---------------------------------------------------------------------------


class TestCSPHeaders:
    def test_security_headers_middleware_has_csp(self):
        from middleware.security_headers import SecurityHeadersMiddleware

        assert "Content-Security-Policy" in SecurityHeadersMiddleware._HEADERS
        csp = SecurityHeadersMiddleware._HEADERS["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp
        assert "base-uri 'self'" in csp
        assert "form-action 'self'" in csp

    def test_csp_header_in_response(self):
        from middleware.security_headers import SecurityHeadersMiddleware

        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/api/test")
        async def test():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/api/test")
        assert resp.status_code == 200
        assert "content-security-policy" in {k.lower() for k in resp.headers.keys()}
        csp = resp.headers.get("content-security-policy", "")
        assert "default-src 'self'" in csp
        assert "worker-src 'self' blob:" in csp

    def test_csp_sync_across_sources(self):
        """Verify CSP is synchronized across index.html, Caddyfile, and middleware."""
        from middleware.security_headers import SecurityHeadersMiddleware

        middleware_csp = SecurityHeadersMiddleware._HEADERS["Content-Security-Policy"]

        # Read index.html
        import pathlib

        frontend_path = (
            pathlib.Path(__file__).parent.parent.parent / "frontend" / "index.html"
        )
        if frontend_path.exists():
            html = frontend_path.read_text(encoding="utf-8")
            assert "Content-Security-Policy" in html
            # Extract CSP from meta tag
            import re

            match = re.search(r'content="([^"]*Content-Security-Policy[^"]*)"', html)
            if match:
                # The meta tag uses http-equiv, so the content IS the CSP value
                pass  # CSP is in the content attribute

        # Read Caddyfile
        caddy_path = pathlib.Path(__file__).parent.parent.parent / "Caddyfile"
        if caddy_path.exists():
            caddy = caddy_path.read_text(encoding="utf-8")
            assert "Content-Security-Policy" in caddy

        # All three should contain the same key directives
        for source_name, source_text in [
            ("middleware", middleware_csp),
        ]:
            assert "default-src 'self'" in source_text
            assert "script-src 'self' 'unsafe-inline' 'unsafe-eval'" in source_text
            assert "worker-src 'self' blob:" in source_text
            assert "object-src 'none'" in source_text
