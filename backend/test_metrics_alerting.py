"""Unit tests for I4 — Metrics, Alerting, OTel setup."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._old_db = os.environ.get("WORLDBASE_DB_PATH")
        os.environ["WORLDBASE_DB_PATH"] = self._tmp.name

    def tearDown(self):
        import gc
        gc.collect()
        try:
            os.unlink(self._tmp.name)
        except PermissionError:
            pass
        if self._old_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._old_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)

    def test_render_prometheus_has_gauges(self):
        import metrics

        out = metrics.render_prometheus()
        self.assertIn("# TYPE feed_fresh_count gauge", out)
        self.assertIn("# TYPE feed_stale_count gauge", out)
        self.assertIn("# TYPE feed_error_count gauge", out)
        self.assertIn("# TYPE briefing_quality_score gauge", out)
        self.assertIn("# TYPE briefing_age_seconds gauge", out)
        self.assertIn("# TYPE duckdb_entity_count gauge", out)
        self.assertIn("# TYPE duckdb_edge_count gauge", out)
        self.assertIn("# TYPE duckdb_queue_backlog gauge", out)
        self.assertIn("# TYPE ais_stream_connected gauge", out)
        self.assertIn("# TYPE ais_vessel_count gauge", out)
        self.assertIn("# TYPE ollama_reachable gauge", out)
        self.assertIn("# TYPE pi_edge_online gauge", out)
        self.assertIn("# TYPE prediction_pending gauge", out)
        self.assertIn("# TYPE prediction_accuracy_30d gauge", out)
        self.assertIn("# TYPE rag_query_count gauge", out)
        self.assertIn("# TYPE rag_query_latency_p95 gauge", out)

    def test_render_prometheus_has_histogram(self):
        import metrics

        out = metrics.render_prometheus()
        self.assertIn("health_check_duration_seconds", out)
        self.assertIn("histogram", out)
        self.assertIn("_bucket", out)
        self.assertIn("_count", out)
        self.assertIn("_sum", out)

    def test_render_prometheus_disabled(self):
        import metrics

        old = os.environ.get("WORLDBASE_METRICS")
        os.environ["WORLDBASE_METRICS"] = "0"
        try:
            out = metrics.render_prometheus()
            self.assertIn("disabled", out)
        finally:
            if old is None:
                os.environ.pop("WORLDBASE_METRICS", None)
            else:
                os.environ["WORLDBASE_METRICS"] = old

    def test_collect_all_returns_dict(self):
        import metrics

        m = metrics.collect_all()
        self.assertIsInstance(m, dict)

    def test_record_health_check_duration(self):
        import metrics

        metrics.record_health_check_duration(0.05)
        metrics.record_health_check_duration(0.1)
        out = metrics.render_prometheus()
        self.assertIn("health_check_duration_seconds_count 2", out)

    def test_histogram_empty(self):
        import metrics

        metrics._health_check_times.clear()
        out = metrics.render_prometheus()
        self.assertIn("health_check_duration_seconds_count 0", out)


class AlertingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._old_db = os.environ.get("WORLDBASE_DB_PATH")
        os.environ["WORLDBASE_DB_PATH"] = self._tmp.name
        self._old_webhook = os.environ.get("WORLDBASE_ALERT_WEBHOOK")
        os.environ.pop("WORLDBASE_ALERT_WEBHOOK", None)

    def tearDown(self):
        import gc
        gc.collect()
        try:
            os.unlink(self._tmp.name)
        except PermissionError:
            pass
        if self._old_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._old_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)
        if self._old_webhook is not None:
            os.environ["WORLDBASE_ALERT_WEBHOOK"] = self._old_webhook

    def test_check_no_alerts_when_healthy(self):
        import alerting

        alerts = alerting.check_and_alert(
            trust_score=4, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts), 0)

    def test_check_trust_score_low(self):
        import alerting

        alerts = alerting.check_and_alert(
            trust_score=2, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert"], "trust_score_low")

    def test_check_feeds_stale_majority(self):
        import alerting

        alerts = alerting.check_and_alert(
            trust_score=4, feed_fresh=2, feed_stale=10, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert"], "feeds_stale_majority")

    def test_check_duckdb_queue_backlog_high(self):
        import alerting

        alerts = alerting.check_and_alert(
            trust_score=4, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=50
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert"], "duckdb_queue_backlog_high")
        self.assertEqual(alerts[0]["severity"], "critical")

    def test_dedup_prevents_repeat_within_window(self):
        import alerting

        # First fire
        alerts1 = alerting.check_and_alert(
            trust_score=2, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts1), 1)
        # Second fire within dedup window — should be suppressed
        alerts2 = alerting.check_and_alert(
            trust_score=2, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts2), 0)

    def test_multiple_conditions_fire(self):
        import alerting

        alerts = alerting.check_and_alert(
            trust_score=1, feed_fresh=2, feed_stale=10, duckdb_queue_backlog=50
        )
        self.assertEqual(len(alerts), 3)
        condition_keys = {a["alert"] for a in alerts}
        self.assertIn("trust_score_low", condition_keys)
        self.assertIn("feeds_stale_majority", condition_keys)
        self.assertIn("duckdb_queue_backlog_high", condition_keys)

    @patch("alerting._post_webhook")
    def test_webhook_called_when_url_set(self, mock_post):
        import alerting

        os.environ["WORLDBASE_ALERT_WEBHOOK"] = "https://example.com/webhook"
        mock_post.return_value = True
        alerts = alerting.check_and_alert(
            trust_score=2, feed_fresh=10, feed_stale=2, duckdb_queue_backlog=5
        )
        self.assertEqual(len(alerts), 1)
        mock_post.assert_called_once()
        payload = mock_post.call_args[0][0]
        self.assertEqual(payload["alert"], "trust_score_low")
        self.assertEqual(payload["source"], "worldbase-pc")


class OTelTests(unittest.TestCase):
    def test_otel_disabled_by_default(self):
        import telemetry_otel

        old_endpoint = os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        old_otel = os.environ.pop("WORLDBASE_OTEL", None)
        try:
            self.assertFalse(telemetry_otel.otel_enabled())
        finally:
            if old_endpoint:
                os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = old_endpoint
            if old_otel:
                os.environ["WORLDBASE_OTEL"] = old_otel

    def test_otel_enabled_when_configured(self):
        import telemetry_otel

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["WORLDBASE_OTEL"] = "1"
        try:
            self.assertTrue(telemetry_otel.otel_enabled())
        finally:
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            os.environ.pop("WORLDBASE_OTEL", None)

    def test_setup_otel_returns_false_without_packages(self):
        import telemetry_otel

        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["WORLDBASE_OTEL"] = "1"
        try:
            result = telemetry_otel.setup_otel(None)
            # Will fail on import or instrument — should return False
            self.assertFalse(result)
        finally:
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            os.environ.pop("WORLDBASE_OTEL", None)


class RAGQueryStatsTests(unittest.TestCase):
    def test_query_stats_empty(self):
        import rag_memory

        # Reset counters
        rag_memory._rag_query_count = 0
        rag_memory._rag_query_latencies.clear()
        stats = rag_memory.query_stats()
        self.assertEqual(stats["count"], 0)
        self.assertEqual(stats["p95_ms"], 0.0)

    def test_record_rag_query(self):
        import rag_memory

        rag_memory._rag_query_count = 0
        rag_memory._rag_query_latencies.clear()
        rag_memory.record_rag_query(0.1)
        rag_memory.record_rag_query(0.2)
        rag_memory.record_rag_query(0.3)
        stats = rag_memory.query_stats()
        self.assertEqual(stats["count"], 3)
        self.assertGreater(stats["p95_ms"], 0)


if __name__ == "__main__":
    unittest.main()
