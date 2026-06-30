"""ColQwen2 visual document understanding — on-demand microservice process manager.

V4-22 — Manages a separate ColQwen2 process for visual document QA and
multi-image understanding. The process is started on-demand and stopped
after an idle timeout to conserve VRAM (depends on V4-51 VRAM scheduling).

The microservice runs as a subprocess with its own FastAPI app on a
configurable port. This module manages the lifecycle (start/stop/health)
and proxies requests to it.

Env vars:
  WORLDBASE_COLQWEN2=1              enable service (default off)
  WORLDBASE_COLQWEN2_MODEL          HF model name (default: vidore/colqwen2-v0.1)
  WORLDBASE_COLQWEN2_PORT           port for the microservice (default: 8009)
  WORLDBASE_COLQWEN2_DEVICE=auto    auto | cuda | cpu
  WORLDBASE_COLQWEN2_IDLE_TIMEOUT   auto-stop after N seconds idle (default: 300)
  WORLDBASE_COLQWEN2_START_TIMEOUT  max seconds to wait for startup (default: 120)
  WORLDBASE_COLQWEN2_MAX_CONCURRENT max concurrent requests (default: 4)

Endpoints:
  GET  /api/vision/colqwen2/status
  POST /api/vision/colqwen2/start
  POST /api/vision/colqwen2/stop
  POST /api/vision/colqwen2/query   (body: {"images": ["base64..."], "query": "text"})
  POST /api/vision/colqwen2/ingest  (body: {"images": ["base64..."], "doc_id": "..."})
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vision/colqwen2", tags=["vision-colqwen2"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_MODEL_NAME = os.getenv("WORLDBASE_COLQWEN2_MODEL", "vidore/colqwen2-v0.1")
_PORT = int(os.getenv("WORLDBASE_COLQWEN2_PORT", "8009"))
_DEVICE_PREF = os.getenv("WORLDBASE_COLQWEN2_DEVICE", "auto").strip().lower()
_IDLE_TIMEOUT = float(os.getenv("WORLDBASE_COLQWEN2_IDLE_TIMEOUT", "300"))
_START_TIMEOUT = float(os.getenv("WORLDBASE_COLQWEN2_START_TIMEOUT", "120"))
_MAX_CONCURRENT = int(os.getenv("WORLDBASE_COLQWEN2_MAX_CONCURRENT", "4"))

# ---------------------------------------------------------------------------
# Process state
# ---------------------------------------------------------------------------

_process: subprocess.Popen | None = None
_process_lock = asyncio.Lock()
_last_activity: float = 0.0
_start_time: float = 0.0
_request_semaphore: asyncio.Semaphore | None = None
_idle_monitor_task: asyncio.Task | None = None


def _enabled() -> bool:
    return os.getenv("WORLDBASE_COLQWEN2", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _resolve_device() -> str:
    if _DEVICE_PREF != "auto":
        return _DEVICE_PREF
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _service_url(path: str = "") -> str:
    return f"http://127.0.0.1:{_PORT}{path}"


# ---------------------------------------------------------------------------
# Inline microservice script
# ---------------------------------------------------------------------------

_MICROSERVICE_SCRIPT = '''
"""ColQwen2 microservice — spawned by colqwen2_service.py on demand."""
import sys, os, json, base64, io, time, logging
from typing import Any

logging.basicConfig(level=logging.INFO, format="[colqwen2] %(message)s")
log = logging.getLogger(__name__)

PORT = int(os.getenv("COLQWEN2_PORT", "8009"))
MODEL_NAME = os.getenv("COLQWEN2_MODEL", "vidore/colqwen2-v0.1")
DEVICE = os.getenv("COLQWEN2_DEVICE", "auto")

_model = None
_processor = None

def _resolve_device():
    if DEVICE != "auto":
        return DEVICE
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"

def load_model():
    global _model, _processor
    if _model is not None:
        return _model, _processor
    log.info("loading model=%s device=%s", MODEL_NAME, _resolve_device())
    try:
        import torch
        from transformers import AutoModelForVision2Seq, AutoProcessor
        device = _resolve_device()
        _processor = AutoProcessor.from_pretrained(MODEL_NAME)
        _model = AutoModelForVision2Seq.from_pretrained(
            MODEL_NAME, torch_dtype=torch.float16 if device == "cuda" else torch.float32
        ).to(device).eval()
        log.info("model_loaded device=%s", device)
    except Exception as exc:
        log.error("model_load_error: %s", exc)
        raise
    return _model, _processor

def _decode_images(b64_list):
    from PIL import Image
    images = []
    for b64 in b64_list:
        raw = base64.b64decode(b64)
        images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
    return images

def run_query(images_b64, query):
    import torch
    model, processor = load_model()
    device = next(model.parameters()).device
    images = _decode_images(images_b64)
    inputs = processor(images=images, text=[query], return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model(**inputs)
    # Return raw embeddings for similarity scoring
    embeddings = outputs.logits_per_query.cpu().tolist() if hasattr(outputs, "logits_per_query") else []
    return {"scores": embeddings, "query": query, "num_images": len(images)}

def run_ingest(images_b64, doc_id):
    import torch
    model, processor = load_model()
    device = next(model.parameters()).device
    images = _decode_images(images_b64)
    inputs = processor(images=images, return_tensors="pt").to(device)
    with torch.no_grad():
        outputs = model.get_image_features(**inputs) if hasattr(model, "get_image_features") else model(**inputs)
    embeddings = outputs.cpu().tolist() if hasattr(outputs, "cpu") else []
    return {"doc_id": doc_id, "num_images": len(images), "embedding_dim": len(embeddings[0]) if embeddings else 0}

# --- Minimal HTTP server (no FastAPI dependency in subprocess) ---
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            loaded = _model is not None
            self._send_json(200, {"status": "ok", "model_loaded": loaded, "model": MODEL_NAME, "device": _resolve_device()})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return
        try:
            if self.path == "/query":
                result = run_query(data.get("images", []), data.get("query", ""))
                self._send_json(200, result)
            elif self.path == "/ingest":
                result = run_ingest(data.get("images", []), data.get("doc_id", ""))
                self._send_json(200, result)
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as exc:
            log.error("request_error: %s", exc)
            self._send_json(500, {"error": str(exc)[:300]})

    def log_message(self, fmt, *args):
        pass  # suppress default logging

def main():
    log.info("starting ColQwen2 microservice on port %d", PORT)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    # Preload model in background
    import threading
    t = threading.Thread(target=load_model, daemon=True)
    t.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
        server.shutdown()

if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def _write_script() -> str:
    """Write the microservice script to a temp file."""
    import tempfile

    fd, path = tempfile.mkstemp(suffix="_colqwen2_srv.py", prefix="wb_")
    with os.fdopen(fd, "w") as f:
        f.write(_MICROSERVICE_SCRIPT)
    return path


async def start_service() -> dict[str, Any]:
    """Start the ColQwen2 microservice subprocess."""
    global _process, _start_time, _last_activity, _request_semaphore, _idle_monitor_task

    if not _enabled():
        return {"started": False, "error": "ColQwen2 service disabled"}

    async with _process_lock:
        if _process is not None and _process.poll() is None:
            return {"started": False, "already_running": True, "port": _PORT}

        script_path = _write_script()
        env = os.environ.copy()
        env["COLQWEN2_PORT"] = str(_PORT)
        env["COLQWEN2_MODEL"] = _MODEL_NAME
        env["COLQWEN2_DEVICE"] = _resolve_device()

        logger.info(
            "colqwen2_starting port=%d model=%s device=%s",
            _PORT,
            _MODEL_NAME,
            _resolve_device(),
        )
        try:
            _process = subprocess.Popen(
                [sys.executable, script_path],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
        except Exception as exc:
            return {"started": False, "error": str(exc)[:300]}

        _start_time = time.time()
        _last_activity = time.time()
        _request_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

        # Wait for health endpoint
        healthy = await _wait_for_health()
        if not healthy:
            await _kill_process()
            return {
                "started": False,
                "error": "Service failed to become healthy within timeout",
            }

        # Start idle monitor
        if _idle_monitor_task is None or _idle_monitor_task.done():
            _idle_monitor_task = asyncio.create_task(_idle_monitor())

        return {
            "started": True,
            "port": _PORT,
            "pid": _process.pid,
            "model": _MODEL_NAME,
            "device": _resolve_device(),
        }


async def _wait_for_health() -> bool:
    """Poll the microservice health endpoint until it responds."""
    deadline = time.time() + _START_TIMEOUT
    while time.time() < deadline:
        if _process is None or _process.poll() is not None:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(_service_url("/health"))
                if resp.status_code == 200:
                    logger.info(
                        "colqwen2_healthy pid=%d", _process.pid if _process else 0
                    )
                    return True
        except (httpx.ConnectError, httpx.ReadTimeout, OSError, Exception):
            pass
        await asyncio.sleep(2.0)
    return False


async def _kill_process() -> None:
    """Terminate the subprocess."""
    global _process
    if _process is None:
        return
    try:
        _process.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(_process.wait), timeout=10.0)
        except asyncio.TimeoutError:
            _process.kill()
            await asyncio.to_thread(_process.wait)
    except Exception as exc:
        logger.warning("colqwen2_kill_error: %s", exc)
    finally:
        _process = None


async def stop_service() -> dict[str, Any]:
    """Stop the ColQwen2 microservice."""
    global _idle_monitor_task, _process

    async with _process_lock:
        if _process is None or _process.poll() is not None:
            _process = None
            return {"stopped": True, "was_running": False}

        await _kill_process()

    if _idle_monitor_task and not _idle_monitor_task.done():
        _idle_monitor_task.cancel()
        try:
            await _idle_monitor_task
        except asyncio.CancelledError:
            pass
        _idle_monitor_task = None

    return {"stopped": True, "was_running": True}


async def _idle_monitor() -> None:
    """Background task: auto-stop after idle timeout."""
    global _process
    while True:
        await asyncio.sleep(10.0)
        if _process is None or _process.poll() is not None:
            return
        idle = time.time() - _last_activity
        if idle > _IDLE_TIMEOUT:
            logger.info("colqwen2_idle_stop idle=%.0fs", idle)
            async with _process_lock:
                await _kill_process()
            return


def is_running() -> bool:
    return _process is not None and _process.poll() is None


def get_status() -> dict[str, Any]:
    return {
        "enabled": _enabled(),
        "running": is_running(),
        "port": _PORT,
        "model": _MODEL_NAME,
        "device": _resolve_device(),
        "pid": _process.pid if _process else None,
        "uptime_s": round(time.time() - _start_time, 1) if is_running() else 0,
        "idle_s": round(time.time() - _last_activity, 1) if is_running() else 0,
        "idle_timeout_s": _IDLE_TIMEOUT,
        "max_concurrent": _MAX_CONCURRENT,
    }


# ---------------------------------------------------------------------------
# Request proxying
# ---------------------------------------------------------------------------


async def _proxy_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """Proxy a request to the microservice, starting it if needed."""
    global _last_activity

    if not _enabled():
        return {"error": "ColQwen2 service disabled"}

    if not is_running():
        result = await start_service()
        if not result.get("started"):
            return {"error": "Failed to start ColQwen2 service", "detail": result}

    _last_activity = time.time()

    if _request_semaphore is None:
        return {"error": "Service not initialized"}

    async with _request_semaphore:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(_service_url(path), json=body)
                resp.raise_for_status()
                _last_activity = time.time()
                return resp.json()
        except httpx.ConnectError:
            return {"error": "ColQwen2 service unreachable"}
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}",
                "detail": exc.response.text[:200],
            }
        except Exception as exc:
            return {"error": str(exc)[:300]}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def query_documents(images_b64: list[str], query: str) -> dict[str, Any]:
    """Query ColQwen2 with images and a text query."""
    return await _proxy_post("/query", {"images": images_b64, "query": query})


async def ingest_documents(images_b64: list[str], doc_id: str) -> dict[str, Any]:
    """Ingest document images into ColQwen2 for later retrieval."""
    return await _proxy_post("/ingest", {"images": images_b64, "doc_id": doc_id})


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    images: list[str]  # base64-encoded images
    query: str


class IngestRequest(BaseModel):
    images: list[str]  # base64-encoded images
    doc_id: str


@router.get("/status")
async def colqwen2_status():
    return get_status()


@router.post("/start")
async def colqwen2_start():
    if not _enabled():
        return {"enabled": False, "error": "ColQwen2 service disabled"}
    return await start_service()


@router.post("/stop")
async def colqwen2_stop():
    return await stop_service()


@router.post("/query")
async def colqwen2_query(body: QueryRequest):
    if not _enabled():
        return {"enabled": False, "error": "ColQwen2 service disabled"}
    if not body.images:
        return {"error": "No images provided"}
    if not body.query:
        return {"error": "No query provided"}
    return await query_documents(body.images, body.query)


@router.post("/ingest")
async def colqwen2_ingest(body: IngestRequest):
    if not _enabled():
        return {"enabled": False, "error": "ColQwen2 service disabled"}
    if not body.images:
        return {"error": "No images provided"}
    return await ingest_documents(body.images, body.doc_id)
