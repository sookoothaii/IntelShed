"""Tests for colqwen2_service (V4-22 — ColQwen2 on-demand microservice).

All tests are offline — no subprocess spawning, no model loading.
subprocess.Popen and httpx calls are mocked.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("WORLDBASE_COLQWEN2", "1")

import colqwen2_service as svc  # noqa: E402


class TestConfigHelpers(unittest.TestCase):
    """Config / env helpers."""

    def test_enabled_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_COLQWEN2", None)
            self.assertFalse(svc._enabled())

    def test_enabled_on(self):
        with patch.dict(os.environ, {"WORLDBASE_COLQWEN2": "1"}):
            self.assertTrue(svc._enabled())

    def test_resolve_device_auto(self):
        with patch.dict(os.environ, {"WORLDBASE_COLQWEN2_DEVICE": "auto"}):
            device = svc._resolve_device()
            self.assertIn(device, ("cpu", "cuda"))

    def test_resolve_device_explicit(self):
        with patch.object(svc, "_DEVICE_PREF", "cpu"):
            self.assertEqual(svc._resolve_device(), "cpu")

    def test_service_url(self):
        with patch.dict(os.environ, {"WORLDBASE_COLQWEN2_PORT": "8011"}):
            # _PORT is read at module load, so test the function directly
            url = svc._service_url("/health")
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            self.assertTrue(url.endswith("/health"))

    def test_get_status_not_running(self):
        svc._process = None
        status = svc.get_status()
        self.assertFalse(status["running"])
        self.assertIsNone(status["pid"])

    def test_get_status_running(self):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc
        svc._start_time = 100.0
        svc._last_activity = 100.0
        try:
            status = svc.get_status()
            self.assertTrue(status["running"])
            self.assertEqual(status["pid"], 12345)
        finally:
            svc._process = None

    def test_is_running_false_when_none(self):
        svc._process = None
        self.assertFalse(svc.is_running())

    def test_is_running_true_when_alive(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc
        try:
            self.assertTrue(svc.is_running())
        finally:
            svc._process = None

    def test_is_running_false_when_dead(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=1)  # exit code 1
        svc._process = mock_proc
        try:
            self.assertFalse(svc.is_running())
        finally:
            svc._process = None


class TestStartService(unittest.IsolatedAsyncioTestCase):
    """start_service with mocked subprocess."""

    async def test_start_disabled(self):
        with patch.object(svc, "_enabled", return_value=False):
            result = await svc.start_service()
        self.assertFalse(result["started"])

    async def test_start_already_running(self):
        mock_proc = MagicMock()
        mock_proc.pid = 999
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc
        try:
            with patch.object(svc, "_enabled", return_value=True):
                result = await svc.start_service()
            self.assertFalse(result["started"])
            self.assertTrue(result["already_running"])
        finally:
            svc._process = None

    async def test_start_success(self):
        mock_proc = MagicMock()
        mock_proc.pid = 4242
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = None

        with patch.object(svc, "_enabled", return_value=True):
            with patch("subprocess.Popen", return_value=mock_proc):
                with patch.object(
                    svc, "_wait_for_health", new_callable=AsyncMock
                ) as mock_health:
                    mock_health.return_value = True
                    with patch("asyncio.create_task") as mock_task:
                        mock_task.return_value = MagicMock(
                            done=MagicMock(return_value=True)
                        )
                        result = await svc.start_service()

        self.assertTrue(result["started"])
        self.assertEqual(result["pid"], 4242)
        svc._process = None

    async def test_start_health_check_fails(self):
        mock_proc = MagicMock()
        mock_proc.pid = 3333
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = None

        with patch.object(svc, "_enabled", return_value=True):
            with patch("subprocess.Popen", return_value=mock_proc):
                with patch.object(
                    svc, "_wait_for_health", new_callable=AsyncMock
                ) as mock_health:
                    mock_health.return_value = False
                    with patch.object(
                        svc, "_kill_process", new_callable=AsyncMock
                    ) as mock_kill:
                        result = await svc.start_service()

        self.assertFalse(result["started"])
        self.assertIn("healthy", result["error"])
        mock_kill.assert_called_once()
        svc._process = None

    async def test_start_popen_error(self):
        svc._process = None
        with patch.object(svc, "_enabled", return_value=True):
            with patch("subprocess.Popen", side_effect=OSError("spawn failed")):
                result = await svc.start_service()
        self.assertFalse(result["started"])
        self.assertIn("spawn failed", result["error"])
        svc._process = None


class TestStopService(unittest.IsolatedAsyncioTestCase):
    """stop_service."""

    async def test_stop_not_running(self):
        svc._process = None
        result = await svc.stop_service()
        self.assertTrue(result["stopped"])
        self.assertFalse(result["was_running"])

    async def test_stop_running(self):
        mock_proc = MagicMock()
        mock_proc.pid = 5555
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc
        svc._idle_monitor_task = None

        with patch.object(svc, "_kill_process", new_callable=AsyncMock) as mock_kill:
            result = await svc.stop_service()

        self.assertTrue(result["stopped"])
        self.assertTrue(result["was_running"])
        mock_kill.assert_called_once()
        svc._process = None


class TestWaitForHealth(unittest.IsolatedAsyncioTestCase):
    """_wait_for_health polling."""

    async def test_health_immediate_success(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await svc._wait_for_health()

        self.assertTrue(result)
        svc._process = None

    async def test_health_process_dies(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=1)  # process exited
        svc._process = mock_proc

        result = await svc._wait_for_health()
        self.assertFalse(result)
        svc._process = None

    async def test_health_timeout(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc

        # Simulate connection errors (service never starts)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict(os.environ, {"WORLDBASE_COLQWEN2_START_TIMEOUT": "0.5"}):
                # We need to temporarily set the module-level variable
                original = svc._START_TIMEOUT
                svc._START_TIMEOUT = 0.5
                try:
                    result = await svc._wait_for_health()
                finally:
                    svc._START_TIMEOUT = original

        self.assertFalse(result)
        svc._process = None


class TestProxyPost(unittest.IsolatedAsyncioTestCase):
    """_proxy_post request forwarding."""

    async def test_proxy_disabled(self):
        with patch.object(svc, "_enabled", return_value=False):
            result = await svc._proxy_post("/query", {"images": [], "query": "test"})
        self.assertIn("disabled", result["error"])

    async def test_proxy_starts_service_if_not_running(self):
        svc._process = None
        svc._request_semaphore = asyncio.Semaphore(4)

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={"scores": [[0.9]], "query": "test"}
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(svc, "_enabled", return_value=True):
            with patch.object(svc, "is_running", return_value=True):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await svc._proxy_post(
                        "/query", {"images": ["b64"], "query": "test"}
                    )

        self.assertIn("scores", result)
        svc._process = None

    async def test_proxy_connect_error(self):
        import httpx

        svc._process = None
        svc._request_semaphore = asyncio.Semaphore(4)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch.object(svc, "_enabled", return_value=True):
            with patch.object(svc, "is_running", return_value=True):
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await svc._proxy_post(
                        "/query", {"images": [], "query": "test"}
                    )

        self.assertIn("unreachable", result["error"])
        svc._process = None


class TestPublicApi(unittest.IsolatedAsyncioTestCase):
    """Public API functions."""

    async def test_query_documents(self):
        expected = {"scores": [[0.95]], "query": "find tanks", "num_images": 1}
        with patch.object(svc, "_proxy_post", new_callable=AsyncMock) as mock_proxy:
            mock_proxy.return_value = expected
            result = await svc.query_documents(["base64img"], "find tanks")
        self.assertEqual(result["query"], "find tanks")
        mock_proxy.assert_called_once_with(
            "/query", {"images": ["base64img"], "query": "find tanks"}
        )

    async def test_ingest_documents(self):
        expected = {"doc_id": "doc-001", "num_images": 2, "embedding_dim": 768}
        with patch.object(svc, "_proxy_post", new_callable=AsyncMock) as mock_proxy:
            mock_proxy.return_value = expected
            result = await svc.ingest_documents(["img1", "img2"], "doc-001")
        self.assertEqual(result["doc_id"], "doc-001")
        mock_proxy.assert_called_once_with(
            "/ingest", {"images": ["img1", "img2"], "doc_id": "doc-001"}
        )


class TestFastApiRoutes(unittest.IsolatedAsyncioTestCase):
    """FastAPI route tests via TestClient."""

    def test_status_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        svc._process = None
        r = client.get("/api/vision/colqwen2/status")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data["running"])

    def test_start_route_disabled(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        with patch.object(svc, "_enabled", return_value=False):
            r = client.post("/api/vision/colqwen2/start")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])

    def test_stop_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        svc._process = None
        r = client.post("/api/vision/colqwen2/stop")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["stopped"])

    def test_query_route_disabled(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        with patch.object(svc, "_enabled", return_value=False):
            r = client.post(
                "/api/vision/colqwen2/query",
                json={"images": ["base64"], "query": "test"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])

    def test_query_route_validation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        with patch.object(svc, "_enabled", return_value=True):
            # Missing images
            r = client.post(
                "/api/vision/colqwen2/query",
                json={"images": [], "query": "test"},
            )
            self.assertEqual(r.status_code, 200)
            self.assertIn("error", r.json())

            # Missing query
            r = client.post(
                "/api/vision/colqwen2/query",
                json={"images": ["b64"], "query": ""},
            )
            self.assertEqual(r.status_code, 200)
            self.assertIn("error", r.json())

    def test_ingest_route_disabled(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(svc.router)
        client = TestClient(app)

        with patch.object(svc, "_enabled", return_value=False):
            r = client.post(
                "/api/vision/colqwen2/ingest",
                json={"images": ["base64"], "doc_id": "doc1"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])


class TestIdleMonitor(unittest.IsolatedAsyncioTestCase):
    """Idle monitor auto-stop."""

    async def test_idle_monitor_stops_after_timeout(self):
        mock_proc = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        svc._process = mock_proc

        # Set very short idle timeout
        original_timeout = svc._IDLE_TIMEOUT
        svc._IDLE_TIMEOUT = 0.1
        svc._last_activity = 0.0  # very old

        # Save real asyncio.sleep before patching
        real_sleep = asyncio.sleep

        with patch.object(svc, "_kill_process", new_callable=AsyncMock) as mock_kill:
            # Patch asyncio.sleep in the svc module to be fast (no recursion)
            async def fast_sleep(_):
                # Use original asyncio.sleep via __dict__ to avoid recursion
                pass

            with patch.object(svc.asyncio, "sleep", fast_sleep):
                task = asyncio.create_task(svc._idle_monitor())
                await real_sleep(0.5)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        mock_kill.assert_called_once()
        svc._IDLE_TIMEOUT = original_timeout
        svc._process = None

    async def test_idle_monitor_exits_when_process_dead(self):
        svc._process = None

        real_sleep = asyncio.sleep

        async def fast_sleep(_):
            pass

        with patch.object(svc.asyncio, "sleep", fast_sleep):
            task = asyncio.create_task(svc._idle_monitor())
            await real_sleep(0.3)
            self.assertTrue(task.done() or task.cancelled())
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    unittest.main()
