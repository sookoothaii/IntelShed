"""Hardware-aware model cookbook — scans VRAM and recommends model + num_ctx.

Scans nvidia-smi for free VRAM, checks Ollama for available models, and
recommends the best model + context window for the current hardware.

Env vars:
    OLLAMA_HOST — Ollama API host (default 127.0.0.1:11434)
    OLLAMA_MODEL — current default model (default qwen3:8b)
    WORLDBASE_MODEL_COOKBOOK — set "1" to enable (default on)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/models", tags=["model-cookbook"])

# Model registry: (name, min_vram_gb, recommended_ctx, file_size_gb, notes)
_MODEL_REGISTRY: list[dict[str, Any]] = [
    {
        "model": "qwen3:1.7b",
        "min_vram_gb": 3.0,
        "recommended_ctx": 8192,
        "file_size_gb": 1.0,
        "tier": "edge",
        "notes": "Fast, low quality. Pi or very tight VRAM.",
    },
    {
        "model": "qwen3:8b",
        "min_vram_gb": 6.5,
        "recommended_ctx": 8192,
        "file_size_gb": 4.9,
        "tier": "standard",
        "notes": "Balanced default. Good for briefing + chat.",
    },
    {
        "model": "qwen3:14b",
        "min_vram_gb": 10.0,
        "recommended_ctx": 8192,
        "file_size_gb": 8.6,
        "tier": "quality",
        "notes": "Better reasoning. ~2x slower than 8b. Thinking mode may OOM at 16k ctx.",
    },
    {
        "model": "qwen3:32b",
        "min_vram_gb": 20.0,
        "recommended_ctx": 4096,
        "file_size_gb": 19.0,
        "tier": "max",
        "notes": "Best quality. Needs 24GB+ VRAM. Reduced ctx to fit.",
    },
]

# Embedding models (always loaded alongside chat model)
_EMBED_VRAM_GB = 0.5
# OS + overhead reserve
_OVERHEAD_GB = 1.5


def _run_nvidia_smi() -> dict[str, Any] | None:
    """Query nvidia-smi for GPU info. Returns None if unavailable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        parts = [p.strip() for p in result.stdout.strip().splitlines()[0].split(",")]
        if len(parts) < 4:
            return None
        return {
            "gpu_name": parts[0],
            "vram_total_mb": int(parts[1]),
            "vram_used_mb": int(parts[2]),
            "vram_free_mb": int(parts[3]),
            "vram_total_gb": round(int(parts[1]) / 1024, 1),
            "vram_free_gb": round(int(parts[3]) / 1024, 1),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _query_ollama_models(host: str) -> list[dict[str, Any]]:
    """Get installed models from Ollama API."""
    import urllib.request
    import urllib.error

    url = f"http://{host}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        return data.get("models", [])
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []


def _estimate_vram_for_ctx(model_file_gb: float, num_ctx: int) -> float:
    """Estimate VRAM usage for a model at a given context length.

    KV cache grows roughly linearly with context length.
    Approximation: weights + 0.06GB per 1k ctx + overhead.
    """
    kv_cache_gb = (num_ctx / 1024) * 0.06
    return model_file_gb + kv_cache_gb + _OVERHEAD_GB + _EMBED_VRAM_GB


def _fits_in_vram(model: dict[str, Any], num_ctx: int, free_vram_gb: float) -> bool:
    """Check if a model + ctx fits in available VRAM."""
    estimated = _estimate_vram_for_ctx(model["file_size_gb"], num_ctx)
    return estimated <= free_vram_gb


def _best_ctx_for_model(model: dict[str, Any], free_vram_gb: float) -> int:
    """Find the best context window that fits in VRAM."""
    ctx_options = [16384, 12288, 8192, 6144, 4096]
    for ctx in ctx_options:
        if _fits_in_vram(model, ctx, free_vram_gb):
            return ctx
    return 2048  # Ollama default fallback


def recommend(
    *,
    host: str | None = None,
    available_models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate hardware-aware model recommendation.

    Returns dict with:
        - gpu: GPU info or None
        - available_models: list of installed model names
        - recommended_model: best model name for this hardware
        - recommended_ctx: best num_ctx for recommended model
        - current_model: OLLAMA_MODEL env var
        - reasoning: explanation string
        - alternatives: list of other viable models with ctx
    """
    ollama_host = (host or os.getenv("OLLAMA_HOST", "127.0.0.1:11434")).split(",")[0].strip()
    current_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    gpu = _run_nvidia_smi()

    if available_models is None:
        available_models = _query_ollama_models(ollama_host)

    installed_names = [m.get("name", "") for m in available_models]

    # Filter registry to installed models
    candidates = [m for m in _MODEL_REGISTRY if m["model"] in installed_names]

    if not candidates:
        # Fall back to registry without install check
        candidates = list(_MODEL_REGISTRY)

    if not gpu:
        return {
            "gpu": None,
            "available_models": installed_names,
            "recommended_model": current_model,
            "recommended_ctx": 4096,
            "current_model": current_model,
            "reasoning": "No NVIDIA GPU detected (nvidia-smi unavailable). Using current model with safe ctx=4096.",
            "alternatives": [],
        }

    free_gb = gpu["vram_free_gb"]

    # Sort by tier priority: quality > standard > edge > max
    tier_order = {"quality": 3, "standard": 2, "edge": 1, "max": 4}
    candidates.sort(key=lambda m: tier_order.get(m["tier"], 0), reverse=True)

    best = None
    best_ctx = 4096
    alternatives: list[dict[str, Any]] = []

    for model in candidates:
        ctx = _best_ctx_for_model(model, free_gb)
        if ctx >= 4096:
            entry = {
                "model": model["model"],
                "num_ctx": ctx,
                "tier": model["tier"],
                "estimated_vram_gb": round(_estimate_vram_for_ctx(model["file_size_gb"], ctx), 1),
                "notes": model["notes"],
            }
            if best is None:
                best = model
                best_ctx = ctx
            else:
                alternatives.append(entry)

    if best is None:
        # Nothing fits — recommend smallest
        smallest = min(candidates, key=lambda m: m["file_size_gb"])
        return {
            "gpu": gpu,
            "available_models": installed_names,
            "recommended_model": smallest["model"],
            "recommended_ctx": 2048,
            "current_model": current_model,
            "reasoning": f"VRAM very tight ({free_gb} GB free). Smallest model with ctx=2048. Consider closing other GPU apps.",
            "alternatives": [],
        }

    reasoning_parts = [
        f"GPU: {gpu['gpu_name']} ({gpu['vram_free_gb']} GB free of {gpu['vram_total_gb']} GB)",
        f"Best fit: {best['model']} at ctx={best_ctx} (~{_estimate_vram_for_ctx(best['file_size_gb'], best_ctx):.1f} GB estimated)",
    ]
    if best["model"] != current_model:
        reasoning_parts.append(f"Current model is {current_model} — upgrade recommended")
    else:
        reasoning_parts.append("Current model matches recommendation")

    return {
        "gpu": gpu,
        "available_models": installed_names,
        "recommended_model": best["model"],
        "recommended_ctx": best_ctx,
        "current_model": current_model,
        "reasoning": ". ".join(reasoning_parts),
        "alternatives": alternatives,
    }


def get_recommendation() -> dict[str, Any]:
    """Public API — returns recommendation dict for /api/models/cookbook."""
    return recommend()


@router.get("/cookbook")
async def model_cookbook() -> dict[str, Any]:
    """Hardware-aware model recommendation. Scans VRAM + Ollama models."""
    return get_recommendation()
