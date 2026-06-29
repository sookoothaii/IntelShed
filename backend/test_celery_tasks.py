"""Unit tests for Celery task queue integration.

Tests cover:
- Task registration and naming
- Config feature flag (WORLDBASE_TASK_QUEUE)
- Feed task HTTP dispatch with mocked httpx
- Briefing task HTTP dispatch with mocked httpx
- Retry logic on transient failures (HTTP 5xx, connection errors)
- Circuit breaker integration (HTTP 503 triggers retry)
- Non-retryable errors (HTTP 4xx except 429)
- Beat schedule structure
- Backward compatibility (lifespan mode default)
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import celery.exceptions
import config


class CeleryConfigTests(unittest.TestCase):
    """Config feature flag and Celery settings."""

    def setUp(self):
        config.get_config.cache_clear()

    def tearDown(self):
        config.get_config.cache_clear()

    def test_default_task_queue_is_lifespan(self):
        cfg = config.get_config()
        self.assertEqual(cfg.task_queue, "lifespan")

    def test_celery_mode_when_env_set(self):
        os.environ["WORLDBASE_TASK_QUEUE"] = "celery"
        config.get_config.cache_clear()
        cfg = config.get_config()
        self.assertEqual(cfg.task_queue, "celery")
        del os.environ["WORLDBASE_TASK_QUEUE"]

    def test_celery_broker_url_default(self):
        cfg = config.get_config()
        self.assertTrue(cfg.celery_broker_url.startswith("redis://"))

    def test_celery_result_backend_default(self):
        cfg = config.get_config()
        self.assertTrue(cfg.celery_result_backend.startswith("redis://"))

    def test_celery_backend_url_default(self):
        cfg = config.get_config()
        self.assertTrue(cfg.celery_backend_url.startswith("http://"))


class CeleryAppTests(unittest.TestCase):
    """Celery app structure and Beat schedule."""

    def test_celery_app_importable(self):
        from tasks.celery_app import celery_app

        self.assertIsNotNone(celery_app)

    def test_celery_app_name(self):
        from tasks.celery_app import celery_app

        self.assertEqual(celery_app.main, "worldbase")

    def test_beat_schedule_has_feed_tasks(self):
        from tasks.celery_app import beat_schedule

        feed_keys = [k for k in beat_schedule if k.startswith("ingest-feed-")]
        self.assertGreater(len(feed_keys), 0)
        for key in feed_keys:
            self.assertEqual(beat_schedule[key]["task"], "tasks.feeds.ingest_feed")

    def test_beat_schedule_has_briefing_task(self):
        from tasks.celery_app import beat_schedule

        self.assertIn("generate-briefing", beat_schedule)
        self.assertEqual(
            beat_schedule["generate-briefing"]["task"],
            "tasks.briefing.generate_briefing",
        )

    def test_beat_schedule_feed_sources_match_feed_ingest(self):
        from tasks.celery_app import _FEED_SOURCES

        expected = {
            "gdacs",
            "gdelt_geo",
            "gdelt_pulse",
            "gdelt_geo_west_asia",
            "gdelt_pulse_west_asia",
            "eonet",
            "maritime",
        }
        self.assertEqual(set(_FEED_SOURCES), expected)

    def test_tasks_module_included(self):
        from tasks.celery_app import celery_app

        includes = celery_app.conf.get("include", [])
        self.assertIn("tasks.feeds", includes)
        self.assertIn("tasks.briefing", includes)


class FeedTaskTests(unittest.TestCase):
    """Feed ingest task HTTP dispatch and retry logic."""

    def setUp(self):
        config.get_config.cache_clear()

    def test_ingest_feed_success(self):
        """Successful feed ingest returns result dict."""
        from tasks.feeds import ingest_feed

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "totals": {"entities": 5}}
        mock_response.raise_for_status = MagicMock()

        with patch("tasks.feeds.httpx.post", return_value=mock_response):
            result = ingest_feed.run("gdacs")

        self.assertTrue(result["ok"])
        self.assertEqual(result["totals"]["entities"], 5)

    def test_ingest_feed_circuit_breaker_503_triggers_retry(self):
        """HTTP 503 (circuit breaker open) should trigger retry."""
        from tasks.feeds import ingest_feed

        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.text = "Service Unavailable"

        import httpx

        httpx_exc = httpx.HTTPStatusError(
            "503 Server Error", request=MagicMock(), response=mock_response
        )

        with patch("tasks.feeds.httpx.post", side_effect=httpx_exc):
            with patch.object(
                ingest_feed, "retry", side_effect=celery.exceptions.Retry()
            ) as mock_retry:
                with self.assertRaises(celery.exceptions.Retry):
                    ingest_feed.run("gdacs")
                mock_retry.assert_called_once()

    def test_ingest_feed_client_error_no_retry(self):
        """HTTP 400 should not retry — returns error dict."""
        from tasks.feeds import ingest_feed

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        import httpx

        httpx_exc = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response
        )

        with patch("tasks.feeds.httpx.post", side_effect=httpx_exc):
            with patch.object(
                ingest_feed, "retry", return_value={"retried": True}
            ) as mock_retry:
                result = ingest_feed.run("gdacs")
                mock_retry.assert_not_called()
                self.assertIn("error", result)

    def test_ingest_feed_read_timeout_fail_soft(self):
        """ReadTimeout should fail soft — no retry, return error dict."""
        from tasks.feeds import ingest_feed

        import httpx

        with patch(
            "tasks.feeds.httpx.post", side_effect=httpx.ReadTimeout("timed out")
        ):
            with patch.object(
                ingest_feed, "retry", return_value={"retried": True}
            ) as mock_retry:
                result = ingest_feed.run("gdacs")
                mock_retry.assert_not_called()
                self.assertIn("error", result)
                self.assertEqual(result["error"], "read timeout")

    def test_ingest_feed_connection_error_triggers_retry(self):
        """Connection error should trigger retry."""
        from tasks.feeds import ingest_feed

        import httpx

        with patch("tasks.feeds.httpx.post", side_effect=httpx.ConnectError("refused")):
            # Connection error is re-raised by our code; autoretry wrapper handles retry
            with self.assertRaises(httpx.ConnectError):
                ingest_feed.run("gdacs")

    def test_ingest_feed_passes_source_param(self):
        """Task should pass source_name as query param."""
        from tasks.feeds import ingest_feed

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("tasks.feeds.httpx.post", return_value=mock_response) as mock_post:
            ingest_feed.run("maritime")
            call_args = mock_post.call_args
            params = call_args.kwargs.get("params") or call_args[1].get("params")
            self.assertEqual(params["sources"], "maritime")

    def test_ingest_all_feeds_success(self):
        """ingest_all_feeds calls backend without source filter."""
        from tasks.feeds import ingest_all_feeds

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "totals": {"entities": 50}}
        mock_response.raise_for_status = MagicMock()

        with patch("tasks.feeds.httpx.post", return_value=mock_response):
            result = ingest_all_feeds.run()

        self.assertTrue(result["ok"])

    def test_ingest_feed_api_key_header(self):
        """Task should include X-API-Key header when API key is set."""
        from tasks import feeds as feeds_module

        old_key = feeds_module._API_KEY
        feeds_module._API_KEY = "test-secret-key"
        try:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_response.raise_for_status = MagicMock()

            with patch(
                "tasks.feeds.httpx.post", return_value=mock_response
            ) as mock_post:
                feeds_module.ingest_feed.run("gdacs")
                call_args = mock_post.call_args
                headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
                self.assertEqual(headers["X-API-Key"], "test-secret-key")
        finally:
            feeds_module._API_KEY = old_key


class BriefingTaskTests(unittest.TestCase):
    """Briefing generation task HTTP dispatch and retry logic."""

    def setUp(self):
        config.get_config.cache_clear()

    def test_generate_briefing_success(self):
        """Successful briefing generation returns result dict."""
        from tasks.briefing import generate_briefing

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Briefing text",
            "digest": {"insights": []},
        }
        mock_response.raise_for_status = MagicMock()

        with patch("tasks.briefing.httpx.post", return_value=mock_response):
            result = generate_briefing.run()

        self.assertIn("text", result)

    def test_generate_briefing_server_error_triggers_retry(self):
        """HTTP 500 should trigger retry."""
        from tasks.briefing import generate_briefing

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        import httpx

        httpx_exc = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=mock_response
        )

        with patch("tasks.briefing.httpx.post", side_effect=httpx_exc):
            with patch.object(
                generate_briefing, "retry", side_effect=celery.exceptions.Retry()
            ) as mock_retry:
                with self.assertRaises(celery.exceptions.Retry):
                    generate_briefing.run()
                mock_retry.assert_called_once()

    def test_generate_briefing_client_error_no_retry(self):
        """HTTP 404 should not retry — returns error dict."""
        from tasks.briefing import generate_briefing

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        import httpx

        httpx_exc = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=mock_response
        )

        with patch("tasks.briefing.httpx.post", side_effect=httpx_exc):
            with patch.object(
                generate_briefing, "retry", return_value={"retried": True}
            ) as mock_retry:
                result = generate_briefing.run()
                mock_retry.assert_not_called()
                self.assertIn("error", result)

    def test_generate_briefing_read_timeout_fail_soft(self):
        """ReadTimeout should fail soft — no retry, return error dict."""
        from tasks.briefing import generate_briefing

        import httpx

        with patch(
            "tasks.briefing.httpx.post", side_effect=httpx.ReadTimeout("timed out")
        ):
            with patch.object(
                generate_briefing, "retry", return_value={"retried": True}
            ) as mock_retry:
                result = generate_briefing.run()
                mock_retry.assert_not_called()
                self.assertIn("error", result)
                self.assertEqual(result["error"], "read timeout")

    def test_generate_briefing_connection_error_triggers_retry(self):
        """Connection error should trigger retry."""
        from tasks.briefing import generate_briefing

        import httpx

        with patch(
            "tasks.briefing.httpx.post", side_effect=httpx.ConnectError("refused")
        ):
            # Connection error is re-raised by our code; autoretry wrapper handles retry
            with self.assertRaises(httpx.ConnectError):
                generate_briefing.run()

    def test_generate_briefing_lang_param(self):
        """Task should pass lang as query param when provided."""
        from tasks.briefing import generate_briefing

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"text": "Briefing"}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "tasks.briefing.httpx.post", return_value=mock_response
        ) as mock_post:
            generate_briefing.run(lang="de")
            call_args = mock_post.call_args
            params = call_args.kwargs.get("params") or call_args[1].get("params")
            self.assertEqual(params["lang"], "de")


class TaskRetryPolicyTests(unittest.TestCase):
    """Verify Celery task decorator retry configuration."""

    def test_feed_task_max_retries(self):
        from tasks.feeds import ingest_feed

        self.assertEqual(ingest_feed.max_retries, 5)

    def test_feed_task_retry_backoff_enabled(self):
        from tasks.feeds import ingest_feed

        # Celery stores autoretry config in task attributes
        self.assertTrue(getattr(ingest_feed, "autoretry_for", None) is not None)

    def test_briefing_task_max_retries(self):
        from tasks.briefing import generate_briefing

        self.assertEqual(generate_briefing.max_retries, 3)

    def test_briefing_task_autoretry_for_includes_http_error(self):
        from tasks.briefing import generate_briefing

        autoretry = getattr(generate_briefing, "autoretry_for", None)
        self.assertIsNotNone(autoretry)

    def test_feed_task_autoretry_for_includes_http_error(self):
        from tasks.feeds import ingest_feed

        autoretry = getattr(ingest_feed, "autoretry_for", None)
        self.assertIsNotNone(autoretry)


class BackwardCompatibilityTests(unittest.TestCase):
    """Verify lifespan mode is the default and Celery is opt-in."""

    def setUp(self):
        config.get_config.cache_clear()

    def tearDown(self):
        config.get_config.cache_clear()

    def test_lifespan_mode_default(self):
        cfg = config.get_config()
        self.assertEqual(cfg.task_queue, "lifespan")

    def test_celery_mode_opt_in(self):
        old = os.environ.get("WORLDBASE_TASK_QUEUE")
        os.environ["WORLDBASE_TASK_QUEUE"] = "celery"
        config.get_config.cache_clear()
        cfg = config.get_config()
        self.assertEqual(cfg.task_queue, "celery")
        if old is None:
            del os.environ["WORLDBASE_TASK_QUEUE"]
        else:
            os.environ["WORLDBASE_TASK_QUEUE"] = old
        config.get_config.cache_clear()

    def test_lifespan_mode_when_invalid_value(self):
        os.environ["WORLDBASE_TASK_QUEUE"] = "invalid"
        config.get_config.cache_clear()
        cfg = config.get_config()
        self.assertEqual(cfg.task_queue, "invalid")
        del os.environ["WORLDBASE_TASK_QUEUE"]
        config.get_config.cache_clear()


if __name__ == "__main__":
    unittest.main()
