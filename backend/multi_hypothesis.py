"""V4-20 — Multi-Hypothesis Synthesis (3 Drafts + Comparison).

Generates multiple independent analytical drafts from the same evidence,
each with a different analytical stance, then compares and selects the best
(or merges them into a single synthesis).

Drafts are produced via LLM calls when available:
  - Cloud LLM (NVIDIA NIM / Groq / OpenRouter) preferred
  - Ollama fallback when cloud is unavailable

When no LLM is reachable, falls back to a rule-based draft generator that
produces structurally different summaries from the same context block.

Env:
  WORLDBASE_MULTI_HYPOTHESIS=1 (default off, opt-in)
  WORLDBASE_MULTI_HYPOTHESIS_DRAFTS=3 (number of drafts, min 2)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from config import get_config

# Analytical stances for each draft
STANCES = (
    {
        "id": "A",
        "label": "baseline",
        "prompt": (
            "Provide a balanced, factual assessment based solely on the evidence. "
            "State what is known, what is uncertain, and what is not covered."
        ),
    },
    {
        "id": "B",
        "label": "adversarial",
        "prompt": (
            "Adopt a red-team / devil's advocate stance. Challenge the strongest "
            "claims in the evidence. Identify assumptions, blind spots, and "
            "alternative explanations. Be skeptical but fair."
        ),
    },
    {
        "id": "C",
        "label": "forecast",
        "prompt": (
            "Focus on implications and forward-looking analysis. Based on the "
            "evidence, project likely developments, risk indicators, and "
            "scenario branches for the next 24-72 hours."
        ),
    },
)


@dataclass
class HypothesisDraft:
    """One hypothesis draft."""

    stance_id: str
    stance_label: str
    content: str
    source: str  # "cloud:nvidia", "ollama", "rule_based"
    duration_ms: int = 0
    error: str = ""


@dataclass
class MultiHypothesisResult:
    """Result of multi-hypothesis synthesis."""

    drafts: list[HypothesisDraft] = field(default_factory=list)
    best_stance: str = ""
    merged_block: str = ""
    comparison_notes: str = ""
    total_duration_ms: int = 0
    enabled: bool = True
    llm_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "llm_used": self.llm_used,
            "draft_count": len(self.drafts),
            "best_stance": self.best_stance,
            "merged_chars": len(self.merged_block),
            "comparison_notes": self.comparison_notes,
            "total_duration_ms": self.total_duration_ms,
            "drafts": [
                {
                    "stance_id": d.stance_id,
                    "stance_label": d.stance_label,
                    "source": d.source,
                    "chars": len(d.content),
                    "duration_ms": d.duration_ms,
                    "error": d.error,
                }
                for d in self.drafts
            ],
        }


def multi_hypothesis_enabled() -> bool:
    return get_config().multi_hypothesis_enabled


def _num_drafts() -> int:
    return get_config().multi_hypothesis_num_drafts


# ---------------------------------------------------------------------------
# LLM-based draft generation
# ---------------------------------------------------------------------------


def _build_draft_prompt(query: str, context: str, stance_prompt: str) -> list[dict]:
    """Build messages for a single draft LLM call."""
    system = (
        "You are WorldBase AI — a spatial intelligence analyst. "
        "Produce a concise analytical assessment based ONLY on the evidence "
        "provided below. Do not fabricate data.\n\n"
        f"{stance_prompt}\n\n"
        "EVIDENCE:\n"
        f"{context[:4000]}\n\n"
        f"QUERY: {query}\n\n"
        "Assessment (2-4 paragraphs, cite evidence where possible):"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]


async def _call_ollama(
    model: str,
    messages: list[dict],
    *,
    timeout: float = 30.0,
) -> str:
    """Call local Ollama for a single draft."""

    import httpx

    host = os.getenv("OLLAMA_HOST", "127.0.0.1:11434").split(",")[0].strip()
    url = f"http://{host}/api/chat"
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
    }
    if "qwen3" in model.lower():
        body["think"] = False

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        return (data.get("message") or {}).get("content", "")


async def _call_cloud(
    provider: str,
    model: str,
    messages: list[dict],
    *,
    timeout: float = 30.0,
) -> str:
    """Call a cloud OpenAI-compatible provider for a single draft."""

    import httpx

    from chat_routing import (
        DEFAULT_BASE_URLS,
        PROVIDER_ENV_BASE_URLS,
        PROVIDER_ENV_KEYS,
        openai_chat_completions_url,
        select_api_key,
        select_base_url,
    )

    env_key = PROVIDER_ENV_KEYS.get(provider)
    api_key = select_api_key(provider, None, os.getenv(env_key) if env_key else None)
    if not api_key:
        raise ValueError(f"No API key for {provider}")

    env_base_name = PROVIDER_ENV_BASE_URLS.get(provider)
    env_base = os.getenv(env_base_name) if env_base_name else None
    default_base = DEFAULT_BASE_URLS.get(provider, "")
    base_url = select_base_url(provider, None, env_base, default_base)
    url = openai_chat_completions_url(base_url)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = "https://worldbase.local"
        headers["X-Title"] = "WorldBase"

    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.6,
        "max_tokens": 1024,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""


async def _try_llm_draft(
    query: str,
    context: str,
    stance: dict,
) -> HypothesisDraft | None:
    """Try to generate a draft via LLM (cloud first, Ollama fallback)."""
    messages = _build_draft_prompt(query, context, stance["prompt"])
    start = time.monotonic()

    # Try cloud providers in order
    from chat_model_router import available_providers, _default_model_for

    cloud_providers = [p for p in available_providers() if p != "ollama"]
    for provider in cloud_providers:
        try:
            model = _default_model_for(provider)
            content = await asyncio.wait_for(
                _call_cloud(provider, model, messages, timeout=25.0),
                timeout=30.0,
            )
            if content and content.strip():
                return HypothesisDraft(
                    stance_id=stance["id"],
                    stance_label=stance["label"],
                    content=content.strip(),
                    source=f"cloud:{provider}",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )
        except (asyncio.TimeoutError, Exception):
            continue

    # Fallback: Ollama
    try:
        model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        content = await asyncio.wait_for(
            _call_ollama(model, messages, timeout=25.0),
            timeout=30.0,
        )
        if content and content.strip():
            return HypothesisDraft(
                stance_id=stance["id"],
                stance_label=stance["label"],
                content=content.strip(),
                source="ollama",
                duration_ms=int((time.monotonic() - start) * 1000),
            )
    except (asyncio.TimeoutError, Exception):
        pass

    return None


# ---------------------------------------------------------------------------
# Rule-based draft generation (0 VRAM fallback)
# ---------------------------------------------------------------------------


def _rule_based_draft(query: str, context: str, stance: dict) -> HypothesisDraft:
    """Generate a structurally different draft from the context (no LLM)."""
    start = time.monotonic()
    lines = [ln.strip() for ln in context.splitlines() if ln.strip()]

    # Extract source-tagged lines
    source_lines = [ln for ln in lines if ln.startswith("[") or ln.startswith("===")]

    if stance["label"] == "baseline":
        content = "=== HYPOTHESIS A (Baseline Assessment) ===\n"
        content += f"Query: {query}\n\n"
        content += "Known facts from evidence:\n"
        for ln in source_lines[:8]:
            content += f"  - {ln[:200]}\n"
        content += "\nUncertainties: Data gaps may exist in areas not covered by available feeds.\n"
        content += "Confidence: MEDIUM (based on available evidence).\n"

    elif stance["label"] == "adversarial":
        content = "=== HYPOTHESIS B (Adversarial Review) ===\n"
        content += f"Query: {query}\n\n"
        content += "Challenged claims:\n"
        for ln in source_lines[:5]:
            content += f"  - CHALLENGE: {ln[:150]}\n"
        content += "\nAssumptions to verify:\n"
        content += "  - Source reliability and recency not independently verified.\n"
        content += "  - Correlation does not imply causation.\n"
        content += "  - Single-source claims lack corroboration.\n"
        content += "\nAlternative explanations should be considered.\n"
        content += "Confidence: LOW-MEDIUM (requires additional sourcing).\n"

    else:  # forecast
        content = "=== HYPOTHESIS C (Forecast & Implications) ===\n"
        content += f"Query: {query}\n\n"
        content += "Current indicators:\n"
        for ln in source_lines[:5]:
            content += f"  - {ln[:150]}\n"
        content += "\n24-72h projections:\n"
        content += "  - Scenario 1 (likely): Continuation of observed patterns.\n"
        content += "  - Scenario 2 (possible): Escalation if indicators intensify.\n"
        content += "  - Scenario 3 (low-prob): De-escalation or resolution.\n"
        content += "\nKey indicators to monitor: feed volume, geographic spread, source diversity.\n"
        content += "Confidence: LOW (forward-looking, subject to change).\n"

    return HypothesisDraft(
        stance_id=stance["id"],
        stance_label=stance["label"],
        content=content,
        source="rule_based",
        duration_ms=int((time.monotonic() - start) * 1000),
    )


# ---------------------------------------------------------------------------
# Draft comparison
# ---------------------------------------------------------------------------


def _compare_drafts(drafts: list[HypothesisDraft]) -> tuple[str, str]:
    """Compare drafts and return (best_stance_id, comparison_notes).

    Scoring heuristic:
    - Longer content = more thorough (up to a cap)
    - Rule-based drafts get a small penalty vs LLM drafts
    - Adversarial stance gets a bonus for risk assessment
    """
    if not drafts:
        return "", "No drafts to compare."

    scores: dict[str, float] = {}
    notes_parts: list[str] = []

    for d in drafts:
        score = 0.0
        # Content length score (cap at 2000 chars)
        score += min(len(d.content), 2000) / 1000.0

        # LLM drafts get a quality bonus
        if d.source.startswith("cloud:") or d.source == "ollama":
            score += 0.5
            notes_parts.append(
                f"  {d.stance_id} ({d.stance_label}): LLM-generated, {len(d.content)} chars"
            )
        else:
            notes_parts.append(
                f"  {d.stance_id} ({d.stance_label}): rule-based, {len(d.content)} chars"
            )

        # Stance-specific bonuses
        if d.stance_label == "adversarial":
            score += 0.3  # critical thinking bonus
        elif d.stance_label == "forecast":
            score += 0.2  # forward-looking bonus

        # Error penalty
        if d.error:
            score -= 1.0

        scores[d.stance_id] = score

    best = max(scores, key=lambda k: scores[k])

    notes = f"Draft comparison ({len(drafts)} drafts):\n"
    notes += "\n".join(notes_parts)
    notes += f"\nSelected: {best} (score={scores[best]:.2f})"

    return best, notes


def _merge_drafts(drafts: list[HypothesisDraft], best_stance: str) -> str:
    """Merge drafts into a single synthesis block, best first."""
    if not drafts:
        return ""

    # Sort: best first, then others
    ordered = sorted(drafts, key=lambda d: 0 if d.stance_id == best_stance else 1)

    parts = ["=== MULTI-HYPOTHESIS SYNTHESIS ===\n"]
    for i, d in enumerate(ordered):
        header = f"--- Draft {d.stance_id} ({d.stance_label})"
        if d.stance_id == best_stance:
            header += " [SELECTED]"
        header += f" via {d.source} ---\n"
        parts.append(header)
        parts.append(d.content)
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_multi_hypothesis(
    query: str,
    context: str,
    *,
    num_drafts: int | None = None,
) -> MultiHypothesisResult:
    """Generate multiple hypothesis drafts and compare them.

    Args:
        query: The user's question.
        context: The evidence/context block to analyze.
        num_drafts: Override config default (min 2).

    Returns:
        MultiHypothesisResult with all drafts and the merged synthesis.
    """
    if not multi_hypothesis_enabled():
        return MultiHypothesisResult(enabled=False)

    n = num_drafts or _num_drafts()
    n = max(2, min(n, len(STANCES)))

    stances = STANCES[:n]
    loop_start = time.monotonic()

    # Try LLM drafts in parallel
    llm_tasks = [_try_llm_draft(query, context, stance) for stance in stances]
    llm_results = await asyncio.gather(*llm_tasks, return_exceptions=True)

    drafts: list[HypothesisDraft] = []
    llm_used = False

    for i, result in enumerate(llm_results):
        stance = stances[i]
        if isinstance(result, Exception) or result is None:
            # Fall back to rule-based
            drafts.append(_rule_based_draft(query, context, stance))
        else:
            drafts.append(result)
            llm_used = True

    # Compare and merge
    best_stance, notes = _compare_drafts(drafts)
    merged = _merge_drafts(drafts, best_stance)

    total_ms = int((time.monotonic() - loop_start) * 1000)

    return MultiHypothesisResult(
        drafts=drafts,
        best_stance=best_stance,
        merged_block=merged,
        comparison_notes=notes,
        total_duration_ms=total_ms,
        llm_used=llm_used,
    )


def format_hypothesis_trace_line(result: MultiHypothesisResult) -> str:
    """Format result as a single line for system prompt injection."""
    if not result.enabled:
        return ""
    sources = [d.source for d in result.drafts]
    return (
        f"MULTI-HYPOTHESIS. Drafts: {len(result.drafts)}, "
        f"Best: {result.best_stance}, LLM: {result.llm_used}, "
        f"Sources: [{', '.join(sources)}]"
    )
