"""BGE cross-encoder reranker after hybrid RRF (CPU-first).

I7 — ONNX int8 quantization backend with PyTorch fallback.

Backend chain (tried in order):
  1. ONNX  — onnxruntime int8 quantized model (cold start ~5s, inference ~20ms/pair)
  2. Torch — transformers AutoModelForSequenceClassification (cold start ~60s)
  3. RRF   — no rerank, hybrid_rrf scores unchanged

Environment variables:
  RAG_RERANK=1              — enable reranking
  RAG_RERANK_MODEL          — HF model name (default: BAAI/bge-reranker-base)
  RAG_RERANK_DEVICE         — torch device (default: cpu)
  RAG_RERANK_BACKEND=onnx   — preferred backend: onnx | torch | auto
  RAG_RERANK_WARMUP=1       — warm model during _stack_warmup()
  RAG_RERANK_ONNX_DIR       — directory for ONNX model cache (default: data/models/reranker_onnx)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

_RERANK_ENABLED = os.getenv("RAG_RERANK", "0").strip().lower() in ("1", "true", "yes")
_RERANK_MODEL = os.getenv("RAG_RERANK_MODEL", "BAAI/bge-reranker-base")
_RERANK_DEVICE = os.getenv("RAG_RERANK_DEVICE", "cpu")
_RERANK_BACKEND = os.getenv("RAG_RERANK_BACKEND", "auto").strip().lower()
_RERANK_WARMUP = os.getenv("RAG_RERANK_WARMUP", "1").strip().lower() in ("1", "true", "yes")
_ONNX_DIR = Path(
    os.getenv("RAG_RERANK_ONNX_DIR", str(Path(__file__).parent / "data" / "models" / "reranker_onnx"))
)

# ---------------------------------------------------------------------------
# State — module-level singletons
# ---------------------------------------------------------------------------
_model = None          # type: object | None  (CrossEncoder | OnnxReranker | TorchReranker)
_backend_active: str | None = None   # "onnx" | "torch" | None
_warmup_status: dict = {
    "state": "idle",       # idle | warming | ready | failed
    "backend": None,       # "onnx" | "torch" | None
    "elapsed_s": 0.0,
    "error": None,
    "model": _RERANK_MODEL,
}


def rerank_enabled() -> bool:
    return _RERANK_ENABLED


def search_mode_label() -> str:
    return "hybrid_rrf_rerank" if _RERANK_ENABLED else "hybrid_rrf"


def warmup_status() -> dict:
    """Return current warmup/model status for API and UI."""
    return dict(_warmup_status)


def _set_warmup(state: str, **kw) -> None:
    _warmup_status["state"] = state
    _warmup_status.update(kw)


# ---------------------------------------------------------------------------
# Import-order fix: pyarrow must load before torch to avoid DLL conflict
# (Windows access violation in pyarrow.dataset when torch DLLs loaded first)
# ---------------------------------------------------------------------------
def _ensure_pyarrow_first() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        pass


# ---------------------------------------------------------------------------
# ONNX reranker — onnxruntime int8 quantized cross-encoder
# ---------------------------------------------------------------------------
class OnnxReranker:
    """ONNX-runtime based cross-encoder for reranking.

    Loads a quantized ONNX model from _ONNX_DIR (or exports it on first run).
    """

    def __init__(self, model_name: str, onnx_dir: Path):
        self.model_name = model_name
        self.onnx_dir = onnx_dir
        self.session = None
        self.tokenizer = None
        self._load()

    def _onnx_path(self) -> Path:
        return self.onnx_dir / "model_quantized.onnx"

    def _load(self) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        onnx_file = self._onnx_path()
        if not onnx_file.exists():
            # Export + quantize on first load
            print(f"[RAG] ONNX model not found at {onnx_file}, exporting...", flush=True)
            self._export_quantized()

        if not onnx_file.exists():
            raise FileNotFoundError(f"ONNX export failed — {onnx_file} not found")

        print(f"[RAG] Loading ONNX reranker from {onnx_file}...", flush=True)
        self.session = ort.InferenceSession(
            str(onnx_file),
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.onnx_dir))
        print("[RAG] ONNX reranker ready.", flush=True)

    def _export_quantized(self) -> None:
        """Export HF model to ONNX and apply int8 dynamic quantization."""
        from optimum.onnxruntime import ORTModelForSequenceClassification
        from onnxruntime.quantization import quantize_dynamic, QuantType

        self.onnx_dir.mkdir(parents=True, exist_ok=True)

        # Export base ONNX
        print(f"[RAG] Exporting {_RERANK_MODEL} to ONNX...", flush=True)
        model = ORTModelForSequenceClassification.from_pretrained(
            _RERANK_MODEL, export=True, provider="CPUExecutionProvider",
        )
        model.save_pretrained(str(self.onnx_dir))

        # Quantize to int8
        base_onnx = self.onnx_dir / "model.onnx"
        quant_onnx = self._onnx_path()
        if base_onnx.exists():
            print("[RAG] Applying int8 dynamic quantization...", flush=True)
            quantize_dynamic(
                str(base_onnx),
                str(quant_onnx),
                weight_type=QuantType.QUInt8,
            )
            print(f"[RAG] Quantized model saved to {quant_onnx}", flush=True)

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        import numpy as np

        texts_a = [p[0] for p in pairs]
        texts_b = [p[1] for p in pairs]
        encoded = self.tokenizer(
            texts_a, texts_b,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="np",
        )
        # onnxruntime expects numpy arrays — remove token_type_ids if present
        inputs = {k: v for k, v in encoded.items() if k in {"input_ids", "attention_mask"}}
        outputs = self.session.run(None, inputs)
        logits = outputs[0]
        # Cross-encoder: single logit per pair → relevance score
        if logits.ndim == 2 and logits.shape[1] == 1:
            scores = logits[:, 0]
        elif logits.ndim == 2 and logits.shape[1] == 2:
            # Two-class: take positive class logit
            scores = logits[:, 1]
        else:
            scores = logits.ravel()
        return scores.tolist()


# ---------------------------------------------------------------------------
# Torch reranker — transformers direct (no sentence_transformers dependency)
# ---------------------------------------------------------------------------
class TorchReranker:
    """PyTorch cross-encoder using transformers directly."""

    def __init__(self, model_name: str, device: str):
        _ensure_pyarrow_first()
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.device = device
        print(f"[RAG] Loading Torch reranker {model_name} on {device}...", flush=True)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self.model.to(device)
        self.model.eval()
        print("[RAG] Torch reranker ready.", flush=True)

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        import torch

        texts_a = [p[0] for p in pairs]
        texts_b = [p[1] for p in pairs]
        encoded = self.tokenizer(
            texts_a, texts_b,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        encoded = {k: v.to(self.device) for k, v in encoded.items()}
        with torch.no_grad():
            outputs = self.model(**encoded)
        logits = outputs.logits
        if logits.shape[1] == 1:
            scores = logits[:, 0]
        else:
            scores = logits[:, 1]
        return scores.cpu().tolist()


# ---------------------------------------------------------------------------
# Model loading — backend chain: ONNX → Torch → None
# ---------------------------------------------------------------------------
def _get_model():
    """Load reranker model with ONNX → Torch fallback chain."""
    global _model, _backend_active

    if _model is not None:
        return _model

    errors: list[str] = []

    # Try ONNX first (unless backend is explicitly "torch")
    if _RERANK_BACKEND in ("auto", "onnx"):
        try:
            _model = OnnxReranker(_RERANK_MODEL, _ONNX_DIR)
            _backend_active = "onnx"
            _set_warmup("ready", backend="onnx")
            return _model
        except Exception as e:
            errors.append(f"onnx: {e}")
            print(f"[RAG] ONNX backend failed: {e}", flush=True)

    # Fallback to Torch
    if _RERANK_BACKEND in ("auto", "torch"):
        try:
            _model = TorchReranker(_RERANK_MODEL, _RERANK_DEVICE)
            _backend_active = "torch"
            _set_warmup("ready", backend="torch")
            return _model
        except Exception as e:
            errors.append(f"torch: {e}")
            print(f"[RAG] Torch backend failed: {e}", flush=True)

    _set_warmup("failed", error="; ".join(errors))
    raise RuntimeError(
        f"RAG_RERANK=1 but no backend available — {'; '.join(errors)}"
    )


def rerank_hits(
    query: str,
    hits: list[dict],
    *,
    top_k: int,
    score_fn: Callable[[str, list[str]], list[float]] | None = None,
) -> list[dict]:
    """Re-order candidate hits by cross-encoder relevance; score_fn injectable for tests."""
    if not hits:
        return []
    if len(hits) <= 1:
        out = [dict(hits[0])]
        if score_fn is not None or _RERANK_ENABLED:
            out[0]["rank_source"] = "hybrid_rrf_rerank"
        return out[:top_k]

    texts = [h.get("text") or "" for h in hits]
    if score_fn is not None:
        scores = score_fn(query, texts)
    else:
        model = _get_model()
        pairs = [(query, t) for t in texts]
        scores = model.predict(pairs)

    scored: list[dict] = []
    for hit, sc in zip(hits, scores):
        row = dict(hit)
        row["rerank_score"] = round(float(sc), 4)
        row["score"] = row["rerank_score"]
        row["rank_source"] = "hybrid_rrf_rerank"
        scored.append(row)

    scored.sort(key=lambda h: h["rerank_score"], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Warmup — called from lifespan._stack_warmup()
# ---------------------------------------------------------------------------
async def warmup_reranker() -> dict:
    """Preload reranker model weights during startup to eliminate cold-start latency."""
    if not _RERANK_ENABLED:
        return {"state": "disabled"}
    if not _RERANK_WARMUP:
        return {"state": "skipped"}
    if _warmup_status["state"] == "ready":
        return warmup_status()

    _set_warmup("warming")
    t0 = time.monotonic()
    try:
        import asyncio

        model = await asyncio.to_thread(_get_model)

        # Fire a dummy prediction to fully warm the graph
        dummy_pairs = [("warmup query", "warmup document text")]
        await asyncio.to_thread(model.predict, dummy_pairs)

        elapsed = round(time.monotonic() - t0, 2)
        _set_warmup("ready", backend=_backend_active, elapsed_s=elapsed)
        print(
            f"[RAG] Reranker warmup complete ({_backend_active}) in {elapsed}s",
            flush=True,
        )
    except Exception as e:
        elapsed = round(time.monotonic() - t0, 2)
        _set_warmup("failed", error=str(e), elapsed_s=elapsed)
        print(f"[RAG] Reranker warmup failed: {e}", flush=True)

    return warmup_status()
