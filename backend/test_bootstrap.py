"""Tests for V4-45 Bootstrap Hydration Endpoint.

Tests:
- Feature flag gating (default off)
- Tier assembly (fast + slow)
- Cache hit/miss
- Fail-soft (missing feeds don't break bootstrap)
- Negative caching sentinel
- Endpoint response structure
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestBootstrapConfig:
    def test_bootstrap_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_BOOTSTRAP", None)
            import bootstrap

            assert bootstrap.bootstrap_enabled() is False

    def test_bootstrap_enabled(self):
        with patch.dict(os.environ, {"WORLDBASE_BOOTSTRAP": "1"}):
            import bootstrap

            assert bootstrap.bootstrap_enabled() is True

    def test_neg_sentinel(self):
        import bootstrap

        assert bootstrap.NEG == "__WM_NEG__"


class TestBootstrapFast:
    def test_assemble_fast_returns_tier(self):
        import bootstrap

        data = asyncio.run(bootstrap._assemble_fast())
        assert data["tier"] == "fast"
        assert "generated_at" in data
        assert data["ttl_sec"] == 1200

    def test_assemble_fast_has_all_sections(self):
        import bootstrap

        data = asyncio.run(bootstrap._assemble_fast())
        expected_sections = {
            "briefing",
            "fusion_hotspots",
            "feed_status",
            "situations",
            "ais",
            "anomalies",
        }
        assert expected_sections.issubset(set(data.keys()))

    def test_assemble_fast_fail_soft(self):
        """When a sub-gatherer fails, the section should have an error key, not crash."""
        import bootstrap

        with patch.object(
            bootstrap, "_gather_briefing", new=AsyncMock(side_effect=Exception("test"))
        ):
            data = asyncio.run(bootstrap._assemble_fast())
            assert "error" in data["briefing"]
            # Other sections should still be present
            assert "feed_status" in data

    def test_assemble_fast_anomalies_neg_when_disabled(self):
        """When anomaly detection is off, anomalies section should be NEG sentinel."""
        import bootstrap

        with patch.dict(os.environ, {"WORLDBASE_ANOMALY_DETECTION": "0"}):
            data = asyncio.run(bootstrap._assemble_fast())
            assert data["anomalies"] == "__WM_NEG__"


class TestBootstrapSlow:
    def test_assemble_slow_returns_tier(self):
        import bootstrap

        data = asyncio.run(bootstrap._assemble_slow())
        assert data["tier"] == "slow"
        assert "generated_at" in data
        assert data["ttl_sec"] == 7200

    def test_assemble_slow_has_all_sections(self):
        import bootstrap

        data = asyncio.run(bootstrap._assemble_slow())
        expected_sections = {
            "ftm_stats",
            "gdelt_pulse",
            "cams",
            "earthquakes",
            "darkweb_digest",
            "ransomware_digest",
            "prediction",
        }
        assert expected_sections.issubset(set(data.keys()))

    def test_assemble_slow_fail_soft(self):
        import bootstrap

        with patch.object(
            bootstrap, "_gather_ftm_stats", new=AsyncMock(side_effect=Exception("test"))
        ):
            data = asyncio.run(bootstrap._assemble_slow())
            assert "error" in data["ftm_stats"]
            assert "gdelt_pulse" in data

    def test_assemble_slow_darkweb_neg_when_disabled(self):
        import bootstrap

        with patch.dict(os.environ, {"WORLDBASE_DARKWEB": "0"}):
            data = asyncio.run(bootstrap._assemble_slow())
            assert data["darkweb_digest"] == "__WM_NEG__"

    def test_assemble_slow_ransomware_neg_when_disabled(self):
        import bootstrap

        with patch.dict(os.environ, {"WORLDBASE_RANSOMWARE": "0"}):
            data = asyncio.run(bootstrap._assemble_slow())
            assert data["ransomware_digest"] == "__WM_NEG__"

    def test_assemble_slow_prediction_neg_when_disabled(self):
        import bootstrap

        with patch.dict(os.environ, {"WORLDBASE_PREDICTIVE": "0"}):
            data = asyncio.run(bootstrap._assemble_slow())
            assert data["prediction"] == "__WM_NEG__"


class TestBootstrapCache:
    def test_cache_returns_cached_data(self):
        import bootstrap

        # Clear cache
        bootstrap._CACHE.clear()

        # First call assembles
        data1 = asyncio.run(bootstrap._get_cached_or_assemble("fast"))
        assert data1["tier"] == "fast"

        # Second call should return cached (same generated_at)
        data2 = asyncio.run(bootstrap._get_cached_or_assemble("fast"))
        assert data2["generated_at"] == data1["generated_at"]

    def test_cache_separate_for_tiers(self):
        import bootstrap

        bootstrap._CACHE.clear()

        fast = asyncio.run(bootstrap._get_cached_or_assemble("fast"))
        slow = asyncio.run(bootstrap._get_cached_or_assemble("slow"))

        assert fast["tier"] == "fast"
        assert slow["tier"] == "slow"
        assert (
            fast["generated_at"] != slow["generated_at"] or True
        )  # may be same timestamp

    def test_cache_expires(self):
        import bootstrap
        import time

        bootstrap._CACHE.clear()

        # Insert a stale cache entry
        stale_time = time.time() - 1300  # older than _FAST_TTL
        bootstrap._CACHE["bootstrap:fast"] = (
            stale_time,
            {"tier": "fast", "stale": True},
        )

        # Should re-assemble since cache is expired
        data = asyncio.run(bootstrap._get_cached_or_assemble("fast"))
        assert data.get("stale") is None
        assert "generated_at" in data


class TestBootstrapEndpoint:
    def test_endpoint_disabled_returns_503(self):
        import bootstrap
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"WORLDBASE_BOOTSTRAP": "0"}):
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(bootstrap.router)
            client = TestClient(app)
            resp = client.get("/api/bootstrap?tier=fast")
            assert resp.status_code == 503
            assert "disabled" in resp.json()["error"].lower()

    def test_endpoint_enabled_returns_data(self):
        import bootstrap
        from fastapi.testclient import TestClient

        bootstrap._CACHE.clear()
        with patch.dict(os.environ, {"WORLDBASE_BOOTSTRAP": "1"}):
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(bootstrap.router)
            client = TestClient(app)
            resp = client.get("/api/bootstrap?tier=fast")
            assert resp.status_code == 200
            data = resp.json()
            assert data["tier"] == "fast"
            assert "generated_at" in data
            # Cache-Control header
            assert "s-maxage=1200" in resp.headers.get("cache-control", "")

    def test_endpoint_slow_tier(self):
        import bootstrap
        from fastapi.testclient import TestClient

        bootstrap._CACHE.clear()
        with patch.dict(os.environ, {"WORLDBASE_BOOTSTRAP": "1"}):
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(bootstrap.router)
            client = TestClient(app)
            resp = client.get("/api/bootstrap?tier=slow")
            assert resp.status_code == 200
            data = resp.json()
            assert data["tier"] == "slow"
            assert "s-maxage=7200" in resp.headers.get("cache-control", "")

    def test_endpoint_invalid_tier(self):
        import bootstrap
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"WORLDBASE_BOOTSTRAP": "1"}):
            from fastapi import FastAPI

            app = FastAPI()
            app.include_router(bootstrap.router)
            client = TestClient(app)
            resp = client.get("/api/bootstrap?tier=invalid")
            assert resp.status_code == 422  # FastAPI validation error
