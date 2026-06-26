"""Context budget manager for chat prompts.

Enforces a hard token budget per context section, truncates by provenance score
(highest first), and provides a refuse path when the overall retrieval quality
is too low to ground a reliable answer.

Env:
  WORLDBASE_CONTEXT_BUDGET=1 (default on)
  WORLDBASE_CONTEXT_BUDGET_SYSTEM=1200
  WORLDBASE_CONTEXT_BUDGET_EVIDENCE=2000
  WORLDBASE_CONTEXT_BUDGET_RAG=1500
  WORLDBASE_CONTEXT_BUDGET_AUX=500
  WORLDBASE_CONTEXT_BUDGET_REFUSE_THRESHOLD=0.35
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any


# Default budget allocation (tokens)
_DEFAULT_BUDGET: dict[str, int] = {
    "system": 1200,
    "evidence": 2000,
    "rag": 1500,
    "aux": 500,
}

# Section name -> budget category
_SECTION_CATEGORIES: dict[str, str] = {
    "system": "system",
    "internal telemetry": "evidence",
    "rag memory": "rag",
    "selected target": "evidence",
    "web search results": "rag",
}

# Markers that indicate low-quality / fallback context
_LOW_QUALITY_MARKERS = (
    "crag fallback",
    "low confidence",
    "low retrieval",
    "no rag memory",
    "weak memory",
    "unavailable",
    "empty",
    "no data",
)


@dataclass
class Section:
    name: str
    text: str
    category: str
    provenance_score: float
    original_tokens: int
    final_tokens: int
    truncated: bool


@dataclass
class BudgetResult:
    ok: bool
    refusal_reason: str | None
    sections: list[Section]
    total_tokens: int
    estimated_input_tokens: int
    quality_score: float
    system_prompt: str
    system_prompt_tokens: int


def budget_enabled() -> bool:
    return os.getenv("WORLDBASE_CONTEXT_BUDGET", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _env_budget() -> dict[str, int]:
    out = dict(_DEFAULT_BUDGET)
    for key in out:
        env = os.getenv(f"WORLDBASE_CONTEXT_BUDGET_{key.upper()}")
        if env:
            try:
                out[key] = max(100, int(env))
            except ValueError:
                pass
    return out


def _estimate_tokens(text: str) -> int:
    """Estimate tokens without tiktoken."""
    if not text:
        return 0
    # tiktoken fallback if available
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        pass
    # Rough heuristic: ~0.75 words per token
    words = len(text.split())
    return max(1, int(words / 0.75))


def _detect_category(section_name: str) -> str:
    name_lower = section_name.lower()
    for key, cat in _SECTION_CATEGORIES.items():
        if key in name_lower:
            return cat
    return "aux"


def _extract_sources(text: str) -> set[str]:
    """Extract source tags like [gdacs], [GDELT], [usgs]."""
    return {s.lower() for s in re.findall(r"\[([a-zA-Z0-9_\-]+)\]", text)}


def _section_provenance_score(text: str) -> float:
    """Score a context block by source reliability and corroboration."""
    try:
        import provenance
    except Exception:
        return 0.5

    sources = _extract_sources(text)
    if not sources:
        # No source tags → cannot verify provenance
        return 0.25

    scores = [provenance.source_reliability(s) for s in sources]
    avg = sum(scores) / len(scores)

    # Corroboration bonus: 2+ independent sources
    corroboration = min(len(sources) - 1, 3)
    boost = 0.0
    if corroboration >= 2:
        boost = 0.15
    elif corroboration >= 1:
        boost = 0.05

    # Penalty for low-quality markers
    text_lower = text.lower()
    if any(m in text_lower for m in _LOW_QUALITY_MARKERS):
        boost -= 0.25

    return round(max(0.0, min(1.0, avg + boost)), 3)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, preserving source tags."""
    # Simple sentence splitter; keep bullet lines intact
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "*", "•", "===", "  ")):
            out.append(stripped)
        else:
            # Split on sentence boundaries
            parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", stripped)
            out.extend(p.strip() for p in parts if p.strip())
    return out


def _truncate_section(text: str, budget: int, score: float) -> tuple[str, bool, int]:
    """Truncate section to budget by sentence, highest provenance first."""
    estimated = _estimate_tokens(text)
    if estimated <= budget:
        return text, False, estimated

    sentences = _split_sentences(text)
    if not sentences:
        return text, False, estimated

    # For now, keep sentences in order; future: sort by provenance per sentence
    kept: list[str] = []
    tokens_used = 0
    for sent in sentences:
        sent_tokens = _estimate_tokens(sent)
        if tokens_used + sent_tokens > budget:
            break
        kept.append(sent)
        tokens_used += sent_tokens

    # Always keep at least 1 sentence if budget > 0 (avoid zero-token sections)
    if not kept and sentences and budget > 0:
        kept.append(sentences[0])
        tokens_used = _estimate_tokens(sentences[0])

    return "\n".join(kept), True, tokens_used


def _refuse_threshold() -> float:
    try:
        return float(os.getenv("WORLDBASE_CONTEXT_BUDGET_REFUSE_THRESHOLD", "0.35"))
    except ValueError:
        return 0.35


def _system_prompt_for_budget() -> str:
    return (
        "\nCONTEXT BUDGET PROTOCOL:\n"
        "- The context below is pre-truncated to fit the model's input window.\n"
        "- Prioritize high-provenance sources over low-reliability ones.\n"
        "- If a section is truncated, do not invent missing details.\n"
        "- If data is absent, say 'DATA GAP: [topic]' rather than speculate.\n"
    )


def apply_budget(
    system_prompt: str,
    context_blocks: list[tuple[str, str]],
    *,
    auxiliary: str = "",
) -> BudgetResult:
    """Apply token budget to context blocks.

    Args:
        system_prompt: The system prompt text (always counted against system budget).
        context_blocks: List of (section_name, text) tuples.
        auxiliary: Extra text not tied to a section.

    Returns:
        BudgetResult with ok=False and refusal_reason if quality is too low.
    """
    if not budget_enabled():
        all_text = system_prompt + "\n\n" + "\n\n".join(t for _, t in context_blocks)
        return BudgetResult(
            ok=True,
            refusal_reason=None,
            sections=[],
            total_tokens=_estimate_tokens(all_text),
            estimated_input_tokens=_estimate_tokens(all_text),
            quality_score=0.5,
            system_prompt=system_prompt,
            system_prompt_tokens=_estimate_tokens(system_prompt),
        )

    budget = _env_budget()
    system_budget = budget["system"]
    system_tokens = _estimate_tokens(system_prompt)
    system_truncated = system_tokens > system_budget

    if system_truncated:
        # System prompt is mandatory; if it exceeds budget, we have a problem
        return BudgetResult(
            ok=False,
            refusal_reason="System prompt exceeds token budget",
            sections=[],
            total_tokens=system_tokens,
            estimated_input_tokens=system_tokens,
            quality_score=0.0,
            system_prompt=system_prompt[:system_budget],
            system_prompt_tokens=system_budget,
        )

    # Apply system prompt budget note
    system_prompt = system_prompt + _system_prompt_for_budget()
    system_tokens = _estimate_tokens(system_prompt)
    if system_tokens > system_budget:
        system_prompt = system_prompt[: int(system_budget * 4)]
        system_tokens = _estimate_tokens(system_prompt)

    sections: list[Section] = []
    category_usage: dict[str, int] = {k: 0 for k in budget}
    total_tokens = system_tokens

    # Score and sort blocks by provenance (highest first) within same category
    scored_blocks: list[tuple[str, str, float]] = []
    for name, text in context_blocks:
        if not text:
            continue
        score = _section_provenance_score(text)
        scored_blocks.append((name, text, score))

    # Sort each category by provenance descending
    by_category: dict[str, list[tuple[str, str, float]]] = {}
    for name, text, score in scored_blocks:
        cat = _detect_category(name)
        by_category.setdefault(cat, []).append((name, text, score))
    for cat in by_category:
        by_category[cat].sort(key=lambda x: x[2], reverse=True)

    # Process sections, highest provenance category first (evidence > rag > aux)
    priority = ["evidence", "rag", "aux"]
    for cat in priority:
        cat_budget = budget.get(cat, 500)
        for name, text, score in by_category.get(cat, []):
            remaining = max(0, cat_budget - category_usage[cat])
            if remaining <= 0:
                continue
            truncated_text, truncated, used = _truncate_section(text, remaining, score)
            section = Section(
                name=name,
                text=truncated_text,
                category=cat,
                provenance_score=score,
                original_tokens=_estimate_tokens(text),
                final_tokens=used,
                truncated=truncated,
            )
            sections.append(section)
            category_usage[cat] += used
            total_tokens += used

    if auxiliary:
        aux_budget = max(0, budget["aux"] - category_usage["aux"])
        if aux_budget > 0:
            aux_tokens = _estimate_tokens(auxiliary)
            if aux_tokens > aux_budget:
                auxiliary = auxiliary[: int(aux_budget * 4)]
                aux_tokens = _estimate_tokens(auxiliary)
            category_usage["aux"] += aux_tokens
            total_tokens += aux_tokens

    # Quality score: weighted average of section provenance scores
    if sections:
        weights = [s.final_tokens for s in sections]
        total_weight = sum(weights)
        quality_score = (
            sum(s.provenance_score * w for s, w in zip(sections, weights))
            / total_weight
            if total_weight > 0
            else 0.0
        )
    else:
        quality_score = 0.0

    threshold = _refuse_threshold()
    if quality_score < threshold:
        return BudgetResult(
            ok=False,
            refusal_reason=f"Context quality {quality_score:.2f} below threshold {threshold}",
            sections=sections,
            total_tokens=total_tokens,
            estimated_input_tokens=total_tokens,
            quality_score=quality_score,
            system_prompt=system_prompt,
            system_prompt_tokens=system_tokens,
        )

    return BudgetResult(
        ok=True,
        refusal_reason=None,
        sections=sections,
        total_tokens=total_tokens,
        estimated_input_tokens=total_tokens,
        quality_score=quality_score,
        system_prompt=system_prompt,
        system_prompt_tokens=system_tokens,
    )


def format_context_from_result(result: BudgetResult) -> tuple[str, dict[str, Any]]:
    """Render BudgetResult sections back into a single context string + metadata."""
    parts = [result.system_prompt]
    for section in result.sections:
        parts.append(f"\n=== {section.name.upper()} ===\n{section.text}")

    meta = {
        "context_budget": {
            "ok": result.ok,
            "total_tokens": result.total_tokens,
            "quality_score": result.quality_score,
            "sections": [
                {
                    "name": s.name,
                    "category": s.category,
                    "provenance_score": s.provenance_score,
                    "original_tokens": s.original_tokens,
                    "final_tokens": s.final_tokens,
                    "truncated": s.truncated,
                }
                for s in result.sections
            ],
        }
    }
    return "\n\n".join(parts), meta
