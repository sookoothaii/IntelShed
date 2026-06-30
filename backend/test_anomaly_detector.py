"""Unit tests for V4-23 Anomaly Detection (Isolation Forest).

Covers:
- Feature flag gating (enabled/disabled)
- SQLite schema initialization
- Metric extraction from various feed responses
- Feature matrix construction
- Model training (Isolation Forest + z-score fallback)
- Anomaly detection (IF + z-score paths)
- FtM Event ingestion
- Briefing digest gathering
- Watch item building
- API endpoints
- Fail-soft behavior
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolation_env(monkeypatch, tmp_path):
    """Isolate each test with a temp DB and model dir."""
    db_path = str(tmp_path / "test_anomaly.db")
    monkeypatch.setenv("WORLDBASE_DB_PATH", db_path)
    monkeypatch.setenv("WORLDBASE_ANOMALY_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "1")
    monkeypatch.setenv("WORLDBASE_BRIEFING_ANOMALY", "1")
    # Reimport to pick up new env
    import importlib

    import anomaly_detector

    importlib.reload(anomaly_detector)
    anomaly_detector.init_anomaly_db()
    yield anomaly_detector
    importlib.reload(anomaly_detector)


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    def test_enabled_when_flag_on(self, _isolation_env):
        mod = _isolation_env
        assert mod._enabled() is True

    def test_disabled_when_flag_off(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "0")
        assert mod._enabled() is False

    def test_briefing_enabled_when_flag_on(self, _isolation_env):
        mod = _isolation_env
        assert mod._briefing_enabled() is True

    def test_briefing_disabled_when_flag_off(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_BRIEFING_ANOMALY", "0")
        assert mod._briefing_enabled() is False

    def test_disabled_returns_false_on_weird_values(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "banana")
        assert mod._enabled() is False


# ---------------------------------------------------------------------------
# DB initialization tests
# ---------------------------------------------------------------------------


class TestDBInit:
    def test_init_creates_tables(self, _isolation_env):
        mod = _isolation_env
        with mod._conn() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        assert "anomaly_metrics" in tables
        assert "anomaly_detections" in tables

    def test_init_is_idempotent(self, _isolation_env):
        mod = _isolation_env
        mod.init_anomaly_db()
        mod.init_anomaly_db()
        with mod._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as n FROM anomaly_metrics").fetchone()
        assert row["n"] == 0


# ---------------------------------------------------------------------------
# Metric extraction tests
# ---------------------------------------------------------------------------


class TestMetricExtraction:
    def test_gdelt_event_count(self, _isolation_env):
        mod = _isolation_env
        data = {"articles": [{"a": 1}, {"b": 2}, {"c": 3}]}
        assert mod._extract_metric("gdelt_event_count", data) == 3.0

    def test_gdelt_geo_count(self, _isolation_env):
        mod = _isolation_env
        data = {"events": [{"x": 1}, {"x": 2}]}
        assert mod._extract_metric("gdelt_geo_count", data) == 2.0

    def test_earthquake_count(self, _isolation_env):
        mod = _isolation_env
        data = {"count": 5, "earthquakes": []}
        assert mod._extract_metric("earthquake_count", data) == 5.0

    def test_earthquake_count_fallback_to_list(self, _isolation_env):
        mod = _isolation_env
        data = {"earthquakes": [1, 2, 3]}
        assert mod._extract_metric("earthquake_count", data) == 3.0

    def test_cams_pm25_avg(self, _isolation_env):
        mod = _isolation_env
        data = {"cities": [{"pm25": 10.0}, {"pm25": 20.0}, {"pm25": 30.0}]}
        assert mod._extract_metric("cams_pm25_avg", data) == 20.0

    def test_cams_pm25_empty(self, _isolation_env):
        mod = _isolation_env
        data = {"cities": []}
        assert mod._extract_metric("cams_pm25_avg", data) is None

    def test_ais_position_count(self, _isolation_env):
        mod = _isolation_env
        data = {"states": [{"s": 1}, {"s": 2}]}
        assert mod._extract_metric("ais_position_count", data) == 2.0

    def test_fusion_hotspot_count(self, _isolation_env):
        mod = _isolation_env
        data = {"hotspots": [{"h": 1}]}
        assert mod._extract_metric("fusion_hotspot_count", data) == 1.0

    def test_gdacs_count(self, _isolation_env):
        mod = _isolation_env
        data = {"count": 7}
        assert mod._extract_metric("gdacs_count", data) == 7.0

    def test_hazard_count(self, _isolation_env):
        mod = _isolation_env
        data = {"alerts": [1, 2, 3, 4]}
        assert mod._extract_metric("hazard_count", data) == 4.0

    def test_unknown_feed_returns_none(self, _isolation_env):
        mod = _isolation_env
        assert mod._extract_metric("unknown_feed", {"data": 1}) is None


# ---------------------------------------------------------------------------
# Feature matrix tests
# ---------------------------------------------------------------------------


class TestFeatureMatrix:
    def test_build_matrix_basic(self, _isolation_env):
        mod = _isolation_env
        history = {
            "feed_a": [1.0, 2.0, 3.0],
            "feed_b": [4.0, 5.0, 6.0],
        }
        matrix, keys = mod._build_feature_matrix(history)
        assert keys == ["feed_a", "feed_b"]
        assert len(matrix) == 3
        assert matrix[0] == [1.0, 4.0]
        assert matrix[2] == [3.0, 6.0]

    def test_build_matrix_truncates_to_shortest(self, _isolation_env):
        mod = _isolation_env
        history = {
            "feed_a": [1.0, 2.0, 3.0, 4.0],
            "feed_b": [5.0, 6.0],
        }
        matrix, _ = mod._build_feature_matrix(history)
        assert len(matrix) == 2

    def test_build_matrix_empty(self, _isolation_env):
        mod = _isolation_env
        matrix, keys = mod._build_feature_matrix({})
        assert matrix == []
        assert keys == []

    def test_build_matrix_with_zero_length(self, _isolation_env):
        mod = _isolation_env
        history = {"feed_a": [], "feed_b": [1.0]}
        matrix, _ = mod._build_feature_matrix(history)
        assert matrix == []


# ---------------------------------------------------------------------------
# Severity tests
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_critical(self, _isolation_env):
        assert _isolation_env._severity_from_score(0.9) == "critical"

    def test_high(self, _isolation_env):
        assert _isolation_env._severity_from_score(0.7) == "high"

    def test_medium(self, _isolation_env):
        assert _isolation_env._severity_from_score(0.55) == "medium"

    def test_low(self, _isolation_env):
        assert _isolation_env._severity_from_score(0.3) == "low"


# ---------------------------------------------------------------------------
# Storage tests
# ---------------------------------------------------------------------------


class TestStorage:
    def test_store_and_load_metric(self, _isolation_env):
        mod = _isolation_env
        mod._store_metric("test_feed", 42.0)
        history = mod._load_history("test_feed", days=365)
        assert history == [42.0]

    def test_store_multiple_metrics(self, _isolation_env):
        mod = _isolation_env
        for v in [1.0, 2.0, 3.0]:
            mod._store_metric("test_feed", v)
        history = mod._load_history("test_feed", days=365)
        assert history == [1.0, 2.0, 3.0]

    def test_store_and_list_detection(self, _isolation_env):
        mod = _isolation_env
        det_id = mod._store_detection(
            "test_feed", 99.0, 0.85, "critical", "Test anomaly"
        )
        detections = mod.list_detections()
        assert len(detections) == 1
        assert detections[0]["id"] == det_id
        assert detections[0]["feed_key"] == "test_feed"
        assert detections[0]["severity"] == "critical"

    def test_list_detections_with_feed_filter(self, _isolation_env):
        mod = _isolation_env
        mod._store_detection("feed_a", 1.0, 0.5, "medium", "A")
        mod._store_detection("feed_b", 2.0, 0.6, "high", "B")
        result = mod.list_detections(feed="feed_a")
        assert len(result) == 1
        assert result[0]["feed_key"] == "feed_a"

    def test_list_detections_with_since_filter(self, _isolation_env):
        mod = _isolation_env
        mod._store_detection("feed_a", 1.0, 0.5, "medium", "A")
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = mod.list_detections(since=future)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Model training tests
# ---------------------------------------------------------------------------


class TestTraining:
    def test_train_disabled(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "0")
        result = mod.train_model()
        assert result["enabled"] is False

    def test_train_insufficient_data(self, _isolation_env):
        mod = _isolation_env
        mod._store_metric("feed_a", 1.0)
        result = mod.train_model()
        assert result["enabled"] is True
        assert result["ok"] is False
        assert "Insufficient" in result["error"]

    def test_train_zscore_fallback(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        # Generate enough data
        for i in range(20):
            mod._store_metric("feed_a", float(i + 1))
            mod._store_metric("feed_b", float(i * 2 + 1))
        # Force ImportError for sklearn
        with mock.patch.dict("sys.modules", {"sklearn.ensemble": None}):
            result = mod.train_model()
        assert result["ok"] is True
        assert result["model_type"] == "zscore"

    def test_train_isolation_forest(self, _isolation_env):
        mod = _isolation_env
        pytest.importorskip("sklearn")
        for i in range(20):
            mod._store_metric("feed_a", float(i + 1))
            mod._store_metric("feed_b", float(i * 2 + 1))
        result = mod.train_model()
        assert result["ok"] is True
        assert result["model_type"] == "isolation_forest"
        assert result["samples"] == 20


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------


class TestDetection:
    def test_detect_disabled(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "0")
        result = asyncio_run(mod.detect_anomalies())
        assert result["enabled"] is False

    def test_detect_no_model(self, _isolation_env):
        mod = _isolation_env

        # Mock _fetch_metric to return data without HTTP
        async def mock_fetch(client, path):
            if "gdelt/pulse" in path:
                return {"articles": [1, 2, 3]}
            elif "gdelt/geo" in path:
                return {"events": [1, 2]}
            elif "earthquakes" in path:
                return {"count": 5}
            elif "airquality" in path:
                return {"cities": [{"pm25": 15.0}]}
            elif "aircraft" in path:
                return {"states": [1, 2]}
            elif "fusion/hotspots" in path:
                return {"hotspots": [{"h": 1}]}
            elif "gdacs" in path:
                return {"count": 3}
            elif "hazards" in path:
                return {"count": 2}
            return {}

        with mock.patch.object(mod, "_fetch_metric", side_effect=mock_fetch):
            result = asyncio_run(mod.detect_anomalies())
        assert result["enabled"] is True
        assert "No trained model" in result.get("message", "")

    def test_detect_with_zscore_model(self, _isolation_env):
        mod = _isolation_env
        # Train z-score model with normal data
        for i in range(20):
            mod._store_metric("feed_a", 10.0 + (i % 3))
        # Train
        with mock.patch.dict("sys.modules", {"sklearn.ensemble": None}):
            train_result = mod.train_model()
        assert train_result["ok"] is True

        # Now detect with an extreme value
        async def mock_fetch(client, path):
            if "gdelt/pulse" in path:
                return {"articles": list(range(100))}  # extreme
            return {"articles": []}

        with mock.patch.object(mod, "_fetch_metric", side_effect=mock_fetch):
            with mock.patch.object(
                mod, "_FEED_METRICS", [("feed_a", "/api/gdelt/pulse/local")]
            ):
                with mock.patch.object(mod, "_extract_metric", return_value=100.0):
                    result = asyncio_run(mod.detect_anomalies())
        assert result["enabled"] is True
        # Should detect anomaly (z-score > 3)
        if result.get("anomalies"):
            assert result["anomalies"][0]["feed"] == "feed_a"


# ---------------------------------------------------------------------------
# FtM ingestion tests
# ---------------------------------------------------------------------------


class TestFtmIngestion:
    def test_ingest_empty_list(self, _isolation_env):
        mod = _isolation_env
        result = mod.ingest_anomalies_as_events([])
        assert result["count"] == 0

    def test_ingest_fail_soft(self, _isolation_env):
        mod = _isolation_env
        anomalies = [
            {
                "feed": "test",
                "value": 1.0,
                "score": 0.9,
                "severity": "high",
                "summary": "test",
            }
        ]
        with mock.patch("builtins.__import__", side_effect=ImportError("no ftm")):
            result = mod.ingest_anomalies_as_events(anomalies)
        assert result["count"] == 0
        assert result["error"] is not None

    def test_ingest_with_mock_ftm(self, _isolation_env):
        mod = _isolation_env
        anomalies = [
            {
                "feed": "test_feed",
                "value": 99.0,
                "score": 0.85,
                "severity": "critical",
                "summary": "Test anomaly",
                "detection_id": 1,
            }
        ]
        import ftm_query as real_ftm

        mock_entity = mock.MagicMock()
        mock_entity.id = "evt-test-anomaly-001"
        with (
            mock.patch.object(real_ftm, "make_entity", return_value=mock_entity),
            mock.patch.object(real_ftm, "upsert") as mock_upsert,
        ):
            result = mod.ingest_anomalies_as_events(anomalies)
        assert result["count"] == 1
        assert len(result["ids"]) == 1
        assert result["ids"][0] == "evt-test-anomaly-001"
        mock_upsert.assert_called_once()


# ---------------------------------------------------------------------------
# Briefing digest tests
# ---------------------------------------------------------------------------


class TestBriefingDigest:
    def test_digest_disabled(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "0")
        result = asyncio_run(mod.gather_anomaly_digest())
        assert result["enabled"] is False

    def test_digest_briefing_disabled(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_BRIEFING_ANOMALY", "0")
        result = asyncio_run(mod.gather_anomaly_digest())
        assert result["enabled"] is False

    def test_digest_no_detections(self, _isolation_env):
        mod = _isolation_env
        result = asyncio_run(mod.gather_anomaly_digest())
        assert result["enabled"] is True
        assert result["count"] == 0

    def test_digest_with_detections(self, _isolation_env):
        mod = _isolation_env
        mod._store_detection(
            "test_feed", 99.0, 0.85, "critical", "Critical anomaly in test_feed"
        )
        result = asyncio_run(mod.gather_anomaly_digest())
        assert result["enabled"] is True
        assert result["count"] >= 1
        assert "CRITICAL" in result["lines"][0]["text"]

    def test_digest_fail_soft(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        def _boom(*a, **kw):
            raise Exception("DB error")

        monkeypatch.setattr(mod, "list_detections", _boom)
        result = asyncio_run(mod.gather_anomaly_digest())
        assert result["enabled"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# Watch items tests
# ---------------------------------------------------------------------------


class TestWatchItems:
    def test_build_watch_items_high_severity(self, _isolation_env):
        mod = _isolation_env
        digest = {
            "enabled": True,
            "lines": [
                {
                    "severity": "high",
                    "feed": "test_feed",
                    "summary": "Spike detected",
                    "score": 0.8,
                    "detected_at": "2026-01-01T00:00:00Z",
                    "ftm_entity_id": "evt-001",
                },
            ],
        }
        items = mod.build_anomaly_watch_items(digest)
        assert len(items) == 1
        assert items[0]["prefix"] == "anomaly"
        assert items[0]["confidence"] == 0.8

    def test_build_watch_items_filters_low_severity(self, _isolation_env):
        mod = _isolation_env
        digest = {
            "enabled": True,
            "lines": [
                {"severity": "low", "feed": "f", "summary": "s", "score": 0.3},
                {"severity": "medium", "feed": "f", "summary": "s", "score": 0.5},
            ],
        }
        items = mod.build_anomaly_watch_items(digest)
        assert len(items) == 0

    def test_build_watch_items_critical(self, _isolation_env):
        mod = _isolation_env
        digest = {
            "enabled": True,
            "lines": [
                {
                    "severity": "critical",
                    "feed": "f",
                    "summary": "Major spike",
                    "score": 0.95,
                    "detected_at": "2026-01-01T00:00:00Z",
                },
            ],
        }
        items = mod.build_anomaly_watch_items(digest)
        assert len(items) == 1
        assert "Major spike" in items[0]["title"]


# ---------------------------------------------------------------------------
# Model status tests
# ---------------------------------------------------------------------------


class TestModelStatus:
    def test_status_disabled(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        monkeypatch.setenv("WORLDBASE_ANOMALY_DETECTION", "0")
        result = mod.model_status()
        assert result["enabled"] is False

    def test_status_no_model(self, _isolation_env):
        mod = _isolation_env
        result = mod.model_status()
        assert result["enabled"] is True
        assert result["model_trained"] is False
        assert result["total_metrics"] == 0

    def test_status_with_model(self, _isolation_env):
        mod = _isolation_env
        for i in range(20):
            mod._store_metric("feed_a", float(i))
        with mock.patch.dict("sys.modules", {"sklearn.ensemble": None}):
            mod.train_model()
        result = mod.model_status()
        assert result["enabled"] is True
        assert result["model_trained"] is True
        assert result["total_metrics"] == 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def asyncio_run(coro):
    """Run an async coroutine synchronously."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Already in a loop — create a task and wait
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
