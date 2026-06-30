"""BLIP image captioning bridge — ONNX GPU/CPU + optional NVIDIA VLM API.

V4-15 — Provides image captioning for the OSINT workflow. Supports two backends:

1. **ONNX** — Salesforce/blip-image-captioning-base via ONNX Runtime.
   CUDA EP when available, CPU fallback. Lazy-loaded singleton.
2. **NVIDIA VLM API** — NVIDIA NIM vision-language model (e.g. meta/llama-3.2-90b-vision-instruct).
   Used when WORLDBASE_BLIP_BACKEND=nvidia and NVIDIA_API_KEY is set.

Env vars:
  WORLDBASE_BLIP=1              enable bridge (default off)
  WORLDBASE_BLIP_BACKEND=auto   auto | onnx | nvidia
  WORLDBASE_BLIP_MODEL          HF model name (default: Salesforce/blip-image-captioning-base)
  WORLDBASE_BLIP_DEVICE=auto    auto | cuda | cpu (ONNX only)
  WORLDBASE_BLIP_ONNX_DIR       ONNX model cache dir (default: data/models/blip_onnx)
  WORLDBASE_BLIP_NVIDIA_MODEL   NVIDIA VLM model (default: meta/llama-3.2-90b-vision-instruct)
  WORLDBASE_BLIP_MAX_IMAGES     max images per batch (default: 8)
  WORLDBASE_BLIP_TIMEOUT        NVIDIA API timeout in seconds (default: 30)

Endpoints:
  GET  /api/vision/blip/status
  POST /api/vision/blip/caption   (upload image file)
  POST /api/vision/blip/caption-url  (body: {"url": "https://..."})
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vision/blip", tags=["vision-blip"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BACKEND = os.getenv("WORLDBASE_BLIP_BACKEND", "auto").strip().lower()
_MODEL_NAME = os.getenv("WORLDBASE_BLIP_MODEL", "Salesforce/blip-image-captioning-base")
_DEVICE_PREF = os.getenv("WORLDBASE_BLIP_DEVICE", "auto").strip().lower()
_ONNX_DIR = os.getenv(
    "WORLDBASE_BLIP_ONNX_DIR",
    str(os.path.join(os.path.dirname(__file__), "data", "models", "blip_onnx")),
)
_NVIDIA_MODEL = os.getenv(
    "WORLDBASE_BLIP_NVIDIA_MODEL", "meta/llama-3.2-90b-vision-instruct"
)
_MAX_IMAGES = int(os.getenv("WORLDBASE_BLIP_MAX_IMAGES", "8"))
_NVIDIA_TIMEOUT = float(os.getenv("WORLDBASE_BLIP_TIMEOUT", "30"))

_NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Lazy-loaded model singleton
_model: Any = None
_model_lock = asyncio.Lock()
_warmup_status: dict[str, Any] = {
    "state": "idle",
    "backend": None,
    "provider": None,
    "elapsed_s": 0.0,
    "error": None,
    "model": _MODEL_NAME,
}


def _enabled() -> bool:
    return os.getenv("WORLDBASE_BLIP", "0").strip().lower() in ("1", "true", "yes")


def warmup_status() -> dict[str, Any]:
    return dict(_warmup_status)


def _set_warmup(state: str, **kw: Any) -> None:
    _warmup_status["state"] = state
    _warmup_status.update(kw)


def _resolve_device() -> str:
    if _DEVICE_PREF != "auto":
        return _DEVICE_PREF
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _resolve_backend() -> str:
    """Decide which backend to use."""
    if _BACKEND != "auto":
        return _BACKEND
    # Prefer NVIDIA if API key is set, fall back to ONNX
    if os.getenv("NVIDIA_API_KEY"):
        return "nvidia"
    return "onnx"


# ---------------------------------------------------------------------------
# ONNX BLIP captioner
# ---------------------------------------------------------------------------


class OnnxBlipCaptioner:
    """ONNX Runtime BLIP image captioning model.

    Loads a quantized ONNX model from _ONNX_DIR (or exports on first run).
    Uses the HuggingFace transformers processor for preprocessing.
    """

    def __init__(self, model_name: str, onnx_dir: str):
        self.model_name = model_name
        self.onnx_dir = onnx_dir
        self.session = None
        self.processor = None
        self.active_provider: str | None = None
        self._load()

    def _onnx_path(self) -> str:
        return os.path.join(self.onnx_dir, "model.onnx")

    def _load(self) -> None:
        import onnxruntime as ort
        from transformers import AutoProcessor

        onnx_file = self._onnx_path()
        if not os.path.exists(onnx_file):
            self._export_onnx()

        if not os.path.exists(onnx_file):
            raise FileNotFoundError(f"ONNX export failed — {onnx_file} not found")

        providers: list[str] = []
        if _resolve_device() == "cuda":
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")

        logger.info("blip_onnx_loading path=%s providers=%s", onnx_file, providers)
        self.session = ort.InferenceSession(onnx_file, providers=providers)
        actual = self.session.get_providers()
        self.active_provider = actual[0] if actual else "unknown"
        logger.info("blip_onnx_ready provider=%s", self.active_provider)

        self.processor = AutoProcessor.from_pretrained(self.onnx_dir)

    def _export_onnx(self) -> None:
        """Export HF BLIP model to ONNX on first run."""
        from transformers import BlipForConditionalGeneration, AutoProcessor
        import torch

        os.makedirs(self.onnx_dir, exist_ok=True)

        logger.info("blip_onnx_exporting model=%s", self.model_name)
        model = BlipForConditionalGeneration.from_pretrained(self.model_name)
        model.eval()

        processor = AutoProcessor.from_pretrained(self.model_name)
        processor.save_pretrained(self.onnx_dir)

        # Create dummy inputs for trace
        dummy_pixel = torch.randn(1, 3, 384, 384)
        dummy_input_ids = torch.tensor([[30522]])  # BOS token for blip

        onnx_file = self._onnx_path()
        torch.onnx.export(
            model,
            (dummy_pixel, dummy_input_ids),
            onnx_file,
            input_names=["pixel_values", "input_ids"],
            output_names=["logits"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "input_ids": {0: "batch", 1: "seq"},
                "logits": {0: "batch", 1: "seq"},
            },
            opset_version=17,
        )
        logger.info("blip_onnx_exported path=%s", onnx_file)

        # Save model weights too for text generation
        model.save_pretrained(self.onnx_dir)

    def caption(self, image_bytes: bytes, max_tokens: int = 50) -> dict[str, Any]:
        """Generate a caption for the given image bytes."""
        from PIL import Image
        import numpy as np

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt")

        # Run vision encoder via ONNX
        pixel_values = inputs["pixel_values"].numpy()
        # Start with BOS token
        input_ids = np.array([[30522]], dtype=np.int64)

        # Simple greedy decode using ONNX session
        generated: list[int] = []
        for _ in range(max_tokens):
            try:
                outputs = self.session.run(
                    None,
                    {"pixel_values": pixel_values, "input_ids": input_ids},
                )
                logits = outputs[0]
                next_token = int(np.argmax(logits[0, -1, :]))
                if next_token == 30523:  # EOS token for BLIP
                    break
                generated.append(next_token)
                input_ids = np.concatenate(
                    [input_ids, np.array([[next_token]], dtype=np.int64)], axis=1
                )
            except Exception as exc:
                logger.warning("blip_onnx_decode_step_error: %s", exc)
                break

        text = self.processor.tokenizer.decode(generated, skip_special_tokens=True)
        return {
            "caption": text.strip(),
            "backend": "onnx",
            "provider": self.active_provider,
            "tokens_generated": len(generated),
        }


# ---------------------------------------------------------------------------
# NVIDIA VLM API captioner
# ---------------------------------------------------------------------------


async def _nvidia_caption(
    image_bytes: bytes, mime_type: str = "image/jpeg"
) -> dict[str, Any]:
    """Caption an image via NVIDIA NIM VLM API."""
    api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        return {"caption": "", "backend": "nvidia", "error": "NVIDIA_API_KEY not set"}

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"

    payload = {
        "model": _NVIDIA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {
                        "type": "text",
                        "text": "Describe this image concisely for intelligence analysis. Focus on: objects, people, locations, text visible, and any notable details.",
                    },
                ],
            }
        ],
        "max_tokens": 200,
        "temperature": 0.3,
        "stream": False,
    }

    url = f"{_NVIDIA_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_NVIDIA_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            caption = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "caption": caption.strip(),
                "backend": "nvidia",
                "model": _NVIDIA_MODEL,
                "tokens_generated": len(caption.split()),
            }
    except httpx.HTTPStatusError as exc:
        return {
            "caption": "",
            "backend": "nvidia",
            "error": f"HTTP {exc.response.status_code}: {exc.response.text[:200]}",
        }
    except Exception as exc:
        return {
            "caption": "",
            "backend": "nvidia",
            "error": str(exc)[:300],
        }


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


async def get_model() -> OnnxBlipCaptioner:
    """Lazy-load the ONNX BLIP model (thread-safe)."""
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        try:
            _set_warmup("warming")
            t0 = time.perf_counter()
            _model = OnnxBlipCaptioner(_MODEL_NAME, _ONNX_DIR)
            elapsed = time.perf_counter() - t0
            _set_warmup(
                "ready",
                backend="onnx",
                provider=_model.active_provider,
                elapsed_s=round(elapsed, 2),
            )
            logger.info("blip_model_loaded elapsed=%.1fs", elapsed)
        except Exception as exc:
            _set_warmup("failed", error=str(exc)[:300])
            logger.warning("blip_model_load_error: %s", exc)
            raise
    return _model


async def warmup_blip() -> dict[str, Any]:
    """Preload the BLIP model during startup (ONNX backend only)."""
    if not _enabled():
        return {"state": "idle", "enabled": False}
    backend = _resolve_backend()
    if backend == "nvidia":
        _set_warmup("ready", backend="nvidia", provider="api")
        return warmup_status()
    try:
        await get_model()
    except Exception:
        pass
    return warmup_status()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def caption_image(
    image_bytes: bytes, mime_type: str = "image/jpeg"
) -> dict[str, Any]:
    """Caption an image using the configured backend.

    Returns dict with:
      - caption: str
      - backend: str (onnx | nvidia)
      - provider: str (for ONNX)
      - error: str | None
    """
    if not _enabled():
        return {"caption": "", "backend": None, "error": "BLIP bridge disabled"}

    backend = _resolve_backend()

    if backend == "nvidia":
        return await _nvidia_caption(image_bytes, mime_type)

    # ONNX path
    try:
        model = await get_model()
        result = await asyncio.to_thread(model.caption, image_bytes)
        return result
    except Exception as exc:
        # Fail-soft: try NVIDIA if ONNX fails and key is available
        if os.getenv("NVIDIA_API_KEY"):
            logger.warning("blip_onnx_failed_fallback_nvidia: %s", exc)
            return await _nvidia_caption(image_bytes, mime_type)
        return {"caption": "", "backend": "onnx", "error": str(exc)[:300]}


async def caption_from_url(url: str) -> dict[str, Any]:
    """Download an image from URL and caption it."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            mime_type = resp.headers.get("content-type", "image/jpeg")
            image_bytes = resp.content
            if len(image_bytes) > 20 * 1024 * 1024:
                return {"caption": "", "error": "Image too large (max 20 MB)"}
            return await caption_image(image_bytes, mime_type)
    except Exception as exc:
        return {"caption": "", "error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class CaptionUrlRequest(BaseModel):
    url: str


@router.get("/status")
async def blip_status():
    backend = _resolve_backend()
    return {
        "enabled": _enabled(),
        "backend": backend,
        "model": _MODEL_NAME if backend == "onnx" else _NVIDIA_MODEL,
        "device": _resolve_device() if backend == "onnx" else None,
        "onnx_dir": _ONNX_DIR,
        "max_images": _MAX_IMAGES,
        "warmup": warmup_status(),
    }


@router.post("/caption")
async def blip_caption_upload(file: UploadFile = File(...)):
    """Caption an uploaded image file."""
    if not _enabled():
        return {"enabled": False, "error": "BLIP bridge disabled"}
    image_bytes = await file.read()
    if not image_bytes:
        return {"error": "Empty image file"}
    mime_type = file.content_type or "image/jpeg"
    result = await caption_image(image_bytes, mime_type)
    result["filename"] = file.filename
    result["size_bytes"] = len(image_bytes)
    return result


@router.post("/caption-url")
async def blip_caption_url(body: CaptionUrlRequest):
    """Caption an image from a URL."""
    if not _enabled():
        return {"enabled": False, "error": "BLIP bridge disabled"}
    if not body.url:
        return {"error": "No URL provided"}
    result = await caption_from_url(body.url)
    result["url"] = body.url
    return result
