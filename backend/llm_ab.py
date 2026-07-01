"""LLM A/B — side-by-side comparison of LLM providers for the same query.

Sends the same prompt to two LLM providers (e.g. Ollama vs NVIDIA NIM) and
returns both responses with timing, token estimates, and quality heuristics.

Quality heuristics (rule-based, 0 VRAM):
- Response length (chars/words)
- Source citation count ([EVIDENCE-NNN] tags)
- Section headers count
- Confidence tags (HIGH/MEDIUM/LOW)
- Hallucination indicators (assertion density without evidence)

Endpoints:
  POST /api/llm-ab/compare  — run A/B comparison
  GET /api/llm-ab/status    — module status + last comparison

WORLDBASE_LLM_AB=1 enables (default off).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

from fastapi import APIRouter, Request
from structured_log import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/llm-ab", tags=["llm-ab"])

_LAST_RUN: dict[str, Any] | None = None


def llm_ab_enabled() -> bool:
    return os.getenv("WORLDBASE_LLM_AB", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Provider call (delegates to chat_proxy)
# ---------------------------------------------------------------------------


async def _call_provider(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Call a single LLM provider and return response + metadata."""
    from chat_proxy import chat_proxy

    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            chat_proxy(
                messages=messages,
                provider=provider,
                model=model,
                stream=False,
                use_tools=False,
            ),
            timeout=timeout,
        )
        elapsed = time.perf_counter() - start
        content = ""
        if isinstance(result, dict):
            content = result.get("content") or result.get("message", "")
        elif isinstance(result, str):
            content = result

        return {
            "provider": provider,
            "model": model,
            "content": content,
            "latency_ms": round(elapsed * 1000, 2),
            "error": None,
            "token_estimate": _estimate_tokens(content),
        }
    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - start
        return {
            "provider": provider,
            "model": model,
            "content": "",
            "latency_ms": round(elapsed * 1000, 2),
            "error": "timeout",
            "token_estimate": 0,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "provider": provider,
            "model": model,
            "content": "",
            "latency_ms": round(elapsed * 1000, 2),
            "error": str(e),
            "token_estimate": 0,
        }


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Quality heuristics
# ---------------------------------------------------------------------------


_EVIDENCE_RE = re.compile(r"\[EVIDENCE-\d+\]")
_CONFIDENCE_RE = re.compile(r"\b(HIGH|MEDIUM|LOW)\b", re.IGNORECASE)
_SECTION_RE = re.compile(r"^#{1,3}\s+\S+", re.MULTILINE)
_SOURCE_RE = re.compile(r"\[source:", re.IGNORECASE)


def _quality_heuristics(content: str) -> dict[str, Any]:
    """Rule-based quality metrics (0 VRAM)."""
    if not content:
        return {
            "chars": 0,
            "words": 0,
            "evidence_refs": 0,
            "confidence_tags": 0,
            "section_headers": 0,
            "source_tags": 0,
            "assertion_density": 0.0,
            "quality_score": 0.0,
        }

    chars = len(content)
    words = len(content.split())
    evidence_refs = len(_EVIDENCE_RE.findall(content))
    confidence_tags = len(_CONFIDENCE_RE.findall(content))
    section_headers = len(_SECTION_RE.findall(content))
    source_tags = len(_SOURCE_RE.findall(content))

    # Assertion density: sentences without evidence refs
    sentences = [s.strip() for s in content.split(".") if s.strip()]
    if sentences:
        unsourced = sum(
            1
            for s in sentences
            if not _EVIDENCE_RE.search(s)
            and not _SOURCE_RE.search(s)
            and len(s.split()) > 5
        )
        assertion_density = round(unsourced / len(sentences), 3)
    else:
        assertion_density = 0.0

    # Composite quality score (0-1)
    quality = 0.0
    if evidence_refs > 0:
        quality += min(0.3, evidence_refs * 0.05)
    if source_tags > 0:
        quality += min(0.2, source_tags * 0.04)
    if section_headers > 0:
        quality += min(0.2, section_headers * 0.05)
    if confidence_tags > 0:
        quality += min(0.15, confidence_tags * 0.05)
    if words > 50:
        quality += 0.1
    if assertion_density < 0.7:
        quality += 0.05
    quality = min(1.0, quality)

    return {
        "chars": chars,
        "words": words,
        "evidence_refs": evidence_refs,
        "confidence_tags": confidence_tags,
        "section_headers": section_headers,
        "source_tags": source_tags,
        "assertion_density": assertion_density,
        "quality_score": round(quality, 3),
    }


# ---------------------------------------------------------------------------
# Comparison runner
# ---------------------------------------------------------------------------


async def run_llm_comparison(
    prompt: str,
    provider_a: str,
    model_a: str,
    provider_b: str,
    model_b: str,
    *,
    system_prompt: str = "",
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run A/B comparison between two LLM providers."""
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Run both providers in parallel
    result_a, result_b = await asyncio.gather(
        _call_provider(provider_a, model_a, messages, timeout=timeout),
        _call_provider(provider_b, model_b, messages, timeout=timeout),
    )

    # Compute quality heuristics
    quality_a = _quality_heuristics(result_a["content"])
    quality_b = _quality_heuristics(result_b["content"])

    comparison = {
        "available": True,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt": prompt[:500],  # truncate for storage
        "provider_a": result_a,
        "provider_b": result_b,
        "quality_a": quality_a,
        "quality_b": quality_b,
        "winner": _determine_winner(result_a, result_b, quality_a, quality_b),
    }

    global _LAST_RUN
    _LAST_RUN = {
        "run_at": comparison["run_at"],
        "provider_a": provider_a,
        "provider_b": provider_b,
        "latency_a_ms": result_a["latency_ms"],
        "latency_b_ms": result_b["latency_ms"],
        "quality_a": quality_a["quality_score"],
        "quality_b": quality_b["quality_score"],
        "winner": comparison["winner"],
    }

    return comparison


def _determine_winner(
    result_a: dict[str, Any],
    result_b: dict[str, Any],
    quality_a: dict[str, Any],
    quality_b: dict[str, Any],
) -> dict[str, Any]:
    """Determine the winner based on quality + latency."""
    if result_a["error"] and result_b["error"]:
        return {"winner": "none", "reason": "both_failed"}
    if result_a["error"]:
        return {"winner": "b", "reason": "a_failed"}
    if result_b["error"]:
        return {"winner": "a", "reason": "b_failed"}

    qa = quality_a["quality_score"]
    qb = quality_b["quality_score"]
    la = result_a["latency_ms"]
    lb = result_b["latency_ms"]

    # Quality is primary, latency is tiebreaker
    if abs(qa - qb) < 0.05:
        # Near-tie on quality — pick faster
        if la < lb:
            return {
                "winner": "a",
                "reason": "quality_tie_faster",
                "quality_a": qa,
                "quality_b": qb,
                "latency_a_ms": la,
                "latency_b_ms": lb,
            }
        else:
            return {
                "winner": "b",
                "reason": "quality_tie_faster",
                "quality_a": qa,
                "quality_b": qb,
                "latency_a_ms": la,
                "latency_b_ms": lb,
            }
    elif qa > qb:
        return {
            "winner": "a",
            "reason": "higher_quality",
            "quality_a": qa,
            "quality_b": qb,
            "latency_a_ms": la,
            "latency_b_ms": lb,
        }
    else:
        return {
            "winner": "b",
            "reason": "higher_quality",
            "quality_a": qa,
            "quality_b": qb,
            "latency_a_ms": la,
            "latency_b_ms": lb,
        }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def llm_ab_status() -> dict[str, Any]:
    return {"enabled": llm_ab_enabled(), "last_run": _LAST_RUN}


@router.post("/compare")
async def compare_providers(request: Request) -> dict[str, Any]:
    """Run A/B comparison between two LLM providers.

    Body:
    {
        "prompt": "Analyze maritime activity in the Gulf of Thailand",
        "provider_a": "ollama",
        "model_a": "qwen3:8b",
        "provider_b": "nvidia",
        "model_b": "stepfun-ai/step-3.7-flash",
        "system_prompt": "You are an intelligence analyst...",
        "timeout": 60
    }
    """
    if not llm_ab_enabled():
        return {
            "available": False,
            "reason": "LLM A/B disabled — set WORLDBASE_LLM_AB=1",
        }

    body = await request.json()
    prompt = body.get("prompt", "")
    if not prompt:
        return {"available": False, "error": "prompt required"}

    provider_a = body.get("provider_a", "ollama")
    model_a = body.get("model_a", "qwen3:8b")
    provider_b = body.get("provider_b", "nvidia")
    model_b = body.get("model_b", "stepfun-ai/step-3.7-flash")
    system_prompt = body.get("system_prompt", "")
    timeout = float(body.get("timeout", 60))

    try:
        return await run_llm_comparison(
            prompt,
            provider_a,
            model_a,
            provider_b,
            model_b,
            system_prompt=system_prompt,
            timeout=timeout,
        )
    except Exception as e:
        log.error("llm_ab_failed", error=repr(e))
        return {"available": False, "error": str(e)}
