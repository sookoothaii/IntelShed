"""Tests for blip_bridge (V4-15 — BLIP image captioning).

All tests are offline — no network, no model loading.
HTTP calls and ONNX model loading are mocked.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("WORLDBASE_BLIP", "1")

import blip_bridge  # noqa: E402


class TestConfigHelpers(unittest.TestCase):
    """Config / env helpers."""

    def test_enabled_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_BLIP", None)
            self.assertFalse(blip_bridge._enabled())

    def test_enabled_on(self):
        with patch.dict(os.environ, {"WORLDBASE_BLIP": "1"}):
            self.assertTrue(blip_bridge._enabled())

    def test_resolve_device_auto(self):
        with patch.dict(os.environ, {"WORLDBASE_BLIP_DEVICE": "auto"}):
            # Should return cpu or cuda, not auto
            device = blip_bridge._resolve_device()
            self.assertIn(device, ("cpu", "cuda"))

    def test_resolve_device_explicit(self):
        with patch.object(blip_bridge, "_DEVICE_PREF", "cpu"):
            self.assertEqual(blip_bridge._resolve_device(), "cpu")

    def test_resolve_backend_auto_with_nvidia_key(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_BLIP_BACKEND": "auto", "NVIDIA_API_KEY": "fake-key"},
        ):
            self.assertEqual(blip_bridge._resolve_backend(), "nvidia")

    def test_resolve_backend_auto_without_nvidia_key(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_BLIP_BACKEND": "auto", "NVIDIA_API_KEY": ""},
        ):
            self.assertEqual(blip_bridge._resolve_backend(), "onnx")

    def test_resolve_backend_explicit_onnx(self):
        with patch.dict(os.environ, {"WORLDBASE_BLIP_BACKEND": "onnx"}):
            self.assertEqual(blip_bridge._resolve_backend(), "onnx")

    def test_warmup_status_initial(self):
        status = blip_bridge.warmup_status()
        self.assertEqual(status["state"], "idle")
        self.assertIsNone(status["backend"])


class TestCaptionDisabled(unittest.IsolatedAsyncioTestCase):
    """When bridge is disabled."""

    async def test_caption_image_disabled(self):
        with patch.object(blip_bridge, "_enabled", return_value=False):
            result = await blip_bridge.caption_image(b"fake-image")
            self.assertEqual(result["caption"], "")
            self.assertIn("disabled", result["error"])

    async def test_caption_from_url_disabled(self):
        # caption_from_url downloads first, then calls caption_image which checks _enabled.
        # Mock caption_image to avoid network call and verify disabled behavior.
        with patch.object(
            blip_bridge, "caption_image", new_callable=AsyncMock
        ) as mock_cap:
            mock_cap.return_value = {
                "caption": "",
                "backend": None,
                "error": "BLIP bridge disabled",
            }
            with patch.object(blip_bridge, "_enabled", return_value=False):
                # Mock the HTTP download too
                mock_response = MagicMock()
                mock_response.raise_for_status = MagicMock()
                mock_response.content = b"fake"
                mock_response.headers = {"content-type": "image/jpeg"}
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=mock_response)
                with patch("httpx.AsyncClient", return_value=mock_client):
                    result = await blip_bridge.caption_from_url(
                        "http://example.com/img.jpg"
                    )
        self.assertEqual(result["caption"], "")
        self.assertIn("disabled", result["error"])


class TestNvidiaCaption(unittest.IsolatedAsyncioTestCase):
    """NVIDIA VLM API captioning (mocked HTTP)."""

    async def test_nvidia_caption_success(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "A military vehicle crossing a bridge at dawn."
                        }
                    }
                ]
            }
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict(
                os.environ,
                {"NVIDIA_API_KEY": "fake-key", "WORLDBASE_BLIP_BACKEND": "nvidia"},
            ):
                result = await blip_bridge._nvidia_caption(b"fake-image-bytes")

        self.assertEqual(result["backend"], "nvidia")
        self.assertIn("military vehicle", result["caption"])
        self.assertNotIn("error", result)

    async def test_nvidia_caption_no_key(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
            result = await blip_bridge._nvidia_caption(b"fake-image")
        self.assertEqual(result["caption"], "")
        self.assertIn("NVIDIA_API_KEY", result["error"])

    async def test_nvidia_caption_api_error(self):
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        httpx_exc = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=mock_response
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx_exc)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict(
                os.environ,
                {"NVIDIA_API_KEY": "fake-key", "WORLDBASE_BLIP_BACKEND": "nvidia"},
            ):
                result = await blip_bridge._nvidia_caption(b"fake-image")

        self.assertEqual(result["caption"], "")
        self.assertIn("HTTP 500", result["error"])

    async def test_nvidia_caption_network_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.dict(
                os.environ,
                {"NVIDIA_API_KEY": "fake-key", "WORLDBASE_BLIP_BACKEND": "nvidia"},
            ):
                result = await blip_bridge._nvidia_caption(b"fake-image")

        self.assertEqual(result["caption"], "")
        self.assertIn("connection refused", result["error"])


class TestCaptionImageRouting(unittest.IsolatedAsyncioTestCase):
    """Test that caption_image routes to the correct backend."""

    async def test_routes_to_nvidia_when_backend_nvidia(self):
        expected = {"caption": "test caption", "backend": "nvidia"}

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="nvidia"):
                with patch.object(
                    blip_bridge, "_nvidia_caption", new_callable=AsyncMock
                ) as mock_nvidia:
                    mock_nvidia.return_value = expected
                    result = await blip_bridge.caption_image(b"fake-image")

        self.assertEqual(result["backend"], "nvidia")
        mock_nvidia.assert_called_once()

    async def test_routes_to_onnx_when_backend_onnx(self):
        expected = {
            "caption": "onnx caption",
            "backend": "onnx",
            "provider": "CPUExecutionProvider",
            "tokens_generated": 10,
        }

        mock_model = MagicMock()
        mock_model.caption = MagicMock(return_value=expected)

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="onnx"):
                with patch.object(
                    blip_bridge, "get_model", new_callable=AsyncMock
                ) as mock_get:
                    mock_get.return_value = mock_model
                    result = await blip_bridge.caption_image(b"fake-image")

        self.assertEqual(result["backend"], "onnx")
        self.assertIn("caption", result)

    async def test_onnx_fallback_to_nvidia_on_error(self):
        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="onnx"):
                with patch.object(
                    blip_bridge, "get_model", new_callable=AsyncMock
                ) as mock_get:
                    mock_get.side_effect = RuntimeError("ONNX load failed")
                    with patch.object(
                        blip_bridge, "_nvidia_caption", new_callable=AsyncMock
                    ) as mock_nvidia:
                        mock_nvidia.return_value = {
                            "caption": "fallback",
                            "backend": "nvidia",
                        }
                        with patch.dict(os.environ, {"NVIDIA_API_KEY": "fake-key"}):
                            result = await blip_bridge.caption_image(b"fake-image")

        self.assertEqual(result["backend"], "nvidia")
        self.assertEqual(result["caption"], "fallback")


class TestCaptionFromUrl(unittest.IsolatedAsyncioTestCase):
    """caption_from_url HTTP fetching."""

    async def test_caption_from_url_success(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b"fake-image-bytes"
        mock_response.headers = {"content-type": "image/png"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            with patch.object(blip_bridge, "_enabled", return_value=True):
                with patch.object(
                    blip_bridge, "caption_image", new_callable=AsyncMock
                ) as mock_caption:
                    mock_caption.return_value = {"caption": "test", "backend": "onnx"}
                    result = await blip_bridge.caption_from_url(
                        "http://example.com/img.png"
                    )

        mock_caption.assert_called_once_with(b"fake-image-bytes", "image/png")
        self.assertEqual(result["caption"], "test")

    async def test_caption_from_url_network_error(self):
        with patch("httpx.AsyncClient") as mock_client_cls:
            instance = mock_client_cls.return_value.__aenter__.return_value
            instance.get = AsyncMock(side_effect=Exception("DNS resolution failed"))

            result = await blip_bridge.caption_from_url(
                "http://nonexistent.invalid/x.jpg"
            )

        self.assertEqual(result["caption"], "")
        self.assertIn("DNS", result["error"])


class TestWarmup(unittest.IsolatedAsyncioTestCase):
    """Warmup behavior."""

    async def test_warmup_disabled(self):
        with patch.object(blip_bridge, "_enabled", return_value=False):
            result = await blip_bridge.warmup_blip()
        self.assertFalse(result["enabled"])

    async def test_warmup_nvidia_backend(self):
        blip_bridge._set_warmup("idle")
        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="nvidia"):
                result = await blip_bridge.warmup_blip()
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["backend"], "nvidia")

    async def test_warmup_onnx_success(self):
        mock_model = MagicMock()
        mock_model.active_provider = "CPUExecutionProvider"

        # Reset warmup state and model singleton
        blip_bridge._set_warmup("idle")
        blip_bridge._model = None

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="onnx"):
                with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
                    with patch.object(
                        blip_bridge, "OnnxBlipCaptioner", return_value=mock_model
                    ):
                        result = await blip_bridge.warmup_blip()

        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["backend"], "onnx")

    async def test_warmup_onnx_failure(self):
        blip_bridge._set_warmup("idle")
        blip_bridge._model = None

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="onnx"):
                with patch.dict(os.environ, {"NVIDIA_API_KEY": ""}):
                    with patch.object(
                        blip_bridge,
                        "OnnxBlipCaptioner",
                        side_effect=RuntimeError("model not found"),
                    ):
                        result = await blip_bridge.warmup_blip()

        self.assertEqual(result["state"], "failed")
        self.assertIsNotNone(result["error"])


class TestFastApiRoutes(unittest.IsolatedAsyncioTestCase):
    """FastAPI route tests via TestClient."""

    def test_status_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(blip_bridge.router)
        client = TestClient(app)

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(blip_bridge, "_resolve_backend", return_value="onnx"):
                r = client.get("/api/vision/blip/status")

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["backend"], "onnx")

    def test_status_route_disabled(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(blip_bridge.router)
        client = TestClient(app)

        with patch.object(blip_bridge, "_enabled", return_value=False):
            r = client.get("/api/vision/blip/status")

        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])

    def test_caption_route_disabled(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(blip_bridge.router)
        client = TestClient(app)

        with patch.object(blip_bridge, "_enabled", return_value=False):
            r = client.post(
                "/api/vision/blip/caption",
                files={"file": ("test.jpg", b"fake", "image/jpeg")},
            )

        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])

    def test_caption_url_route(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(blip_bridge.router)
        client = TestClient(app)

        with patch.object(blip_bridge, "_enabled", return_value=True):
            with patch.object(
                blip_bridge, "caption_from_url", new_callable=AsyncMock
            ) as mock_cap:
                mock_cap.return_value = {"caption": "test caption", "backend": "onnx"}
                r = client.post(
                    "/api/vision/blip/caption-url",
                    json={"url": "http://example.com/img.jpg"},
                )

        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["caption"], "test caption")
        self.assertEqual(data["url"], "http://example.com/img.jpg")


if __name__ == "__main__":
    unittest.main()
