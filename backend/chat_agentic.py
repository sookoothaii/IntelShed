"""P3 — Agentic loop for chat (coverage -> retrieve -> corroboration).

Adapts the briefing agentic loop (briefing_agentic.py) for chat context.
Instead of operating on a digest dict with local/regional/global buckets,
it operates on a RAG text block attached to the chat system prompt.

Phases:
  1. Coverage  — is the RAG block sufficient for this query?
  2. Retrieve  — if gap, targeted RAG search via query_router routes
  3. Corroboration — tag claims with [corroborated] / [uncorroborated]

Env:
  WORLDBASE_CHAT_AGENTIC=1 (default off, opt-in)
  WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS=3
"""

from __future__ import annotations

import os
import re
from typing import Any

_MAX_ROUNDS = 3
_MIN_BLOCK_CHARS = 200

_THIN_MARKERS = (
    "crag fallback",
    "low confidence",
    "low retrieval",
    "unavailable",
    "no bbox",
    "no rag memory",
    "weak memory",
)

_STRONG_MARKERS = (
    "high confidence",
    "rag memory",
    "graph retrieval",
    "spatial",
    "hybrid",
)


def chat_agentic_enabled() -> bool:
    return os.getenv("WORLDBASE_CHAT_AGENTIC", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def max_rounds() -> int:
    try:
        return int(os.getenv("WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS", "3"))
    except ValueError:
        return _MAX_ROUNDS


# --- Phase 1: Coverage ---

def assess_coverage(query: str, rag_block: str) -> dict[str, Any]:
    """Phase 1 -- assess whether the RAG block has sufficient content for the query."""
    block = (rag_block or "").strip()
    block_lower = block.lower()

    char_count = len(block)
    has_strong = any(m in block_lower for m in _STRONG_MARKERS)
    has_thin = any(m in block_lower for m in _THIN_MARKERS)

    source_lines = re.findall(r"\[([^\]]+)\]\s", block)
    unique_sources = set(
        s.lower() for s in source_lines
        if s.lower() not in ("?", "memory")
        and not s.replace(".", "").replace("-", "").isdigit()
    )

    gaps: list[str] = []
    if char_count == 0:
        gaps.append("empty_block")
    if char_count < _MIN_BLOCK_CHARS:
        gaps.append("block_too_short")
    if has_thin and not has_strong:
        gaps.append("low_confidence")
    if char_count > 0 and len(unique_sources) < 1:
        gaps.append("no_source_tags")

    return {
        "phase": "coverage",
        "char_count": char_count,
        "unique_sources": len(unique_sources),
        "has_strong": has_strong,
        "has_thin": has_thin,
        "gaps": gaps,
        "needs_retrieve": bool(gaps),
    }


# --- Phase 2: Retrieve ---

async def _retrieve_augmented(
    query: str, rag_block: str, gaps: list[str],
) -> tuple[str, dict[str, Any]]:
    """Phase 2 -- targeted RAG search to fill coverage gaps."""
    from query_router import classify_query, route_retrieval

    route = classify_query(query)
    meta: dict[str, Any] = {
        "phase": "retrieve",
        "route": route,
        "queries": [query],
        "retrieved": 0,
        "errors": [],
    }

    extra_lines: list[str] = []

    try:
        result = await route_retrieval(query, route=route)
        new_block = result.get("block", "")
        hits = result.get("hits") or []
        meta["retrieved"] = len(hits)
        meta["route"] = result.get("route", route)

        if new_block:
            existing_lower = rag_block.lower()
            for line in new_block.split("\n"):
                ls = line.strip()
                if ls and ls.lower() not in existing_lower:
                    extra_lines.append(ls)
    except Exception as exc:
        meta["errors"].append(str(exc)[:200])

    # Secondary route if first was thin
    if not extra_lines and route != "hybrid":
        try:
            secondary = "hybrid" if route in ("vector", "graph") else "vector"
            result2 = await route_retrieval(query, route=secondary)
            new_block2 = result2.get("block", "")
            hits2 = result2.get("hits") or []
            if new_block2:
                existing_lower = (rag_block + "\n" + "\n".join(extra_lines)).lower()
                for line in new_block2.split("\n"):
                    ls = line.strip()
                    if ls and ls.lower() not in existing_lower:
                        extra_lines.append(ls)
                meta["retrieved"] += len(hits2)
                meta["secondary_route"] = secondary
        except Exception as exc:
            meta["errors"].append(str(exc)[:200])

    merged_block = rag_block
    if extra_lines:
        separator = "\n\n=== AGENTIC RETRIEVAL (coverage gap fill) ===\n"
        merged_block = rag_block.rstrip() + separator + "\n".join(extra_lines)

    return merged_block, meta


# --- Phase 3: Corroboration ---

_SOURCE_BRACKET_RE = re.compile(r"\[([^\]]+)\]")


def _is_real_source(s: str) -> bool:
    """Filter out numeric scores, section markers, and non-source brackets."""
    if s.replace(".", "").replace("-", "").isdigit():
        return False
    if s.lower() in ("crag fallback", "low confidence", "top", "high confidence"):
        return False
    if len(s) > 30:
        return False
    return True


def _word_overlap(a: str, b: str) -> float:
    wa = set(re.findall(r"\w{4,}", a.lower()))
    wb = set(re.findall(r"\w{4,}", b.lower()))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def apply_corroboration_tags(rag_block: str) -> tuple[str, dict[str, Any]]:
    """Phase 3 -- tag claims with corroboration status.

    Parses source-tagged lines, counts independent sources, and appends
    ``[corroborated]`` or ``[uncorroborated]`` markers.
    """
    if not rag_block or not rag_block.strip():
        return rag_block, {
            "phase": "corroboration",
            "source_count": 0,
            "uncorroborated": 0,
            "corroborated": 0,
            "tagged_lines": 0,
        }

    lines = rag_block.split("\n")
    all_sources: set[str] = set()
    tagged_lines: list[tuple[int, str, list[str]]] = []

    for i, line in enumerate(lines):
        raw_sources = _SOURCE_BRACKET_RE.findall(line)
        clean = [s.lower() for s in raw_sources if _is_real_source(s)]
        if clean:
            all_sources.update(clean)
            tagged_lines.append((i, line, clean))

    uncorroborated = 0
    corroborated = 0

    for idx, line, sources in tagged_lines:
        shared = False
        for other_idx, other_line, other_sources in tagged_lines:
            if other_idx == idx:
                continue
            if set(sources) & set(other_sources):
                continue
            if _word_overlap(line, other_line) >= 0.15:
                shared = True
                break

        if shared:
            corroborated += 1
            if "[corroborated]" not in lines[idx].lower():
                lines[idx] = lines[idx].rstrip() + " [corroborated]"
        else:
            uncorroborated += 1
            if "[uncorroborated]" not in lines[idx].lower():
                lines[idx] = lines[idx].rstrip() + " [uncorroborated]"

    tagged_block = "\n".join(lines)

    return tagged_block, {
        "phase": "corroboration",
        "source_count": len(all_sources),
        "corroborated": corroborated,
        "uncorroborated": uncorroborated,
        "tagged_lines": len(tagged_lines),
    }


# --- Main entry point ---

async def run_chat_agentic_loop(
    query: str,
    rag_block: str = "",
) -> tuple[str, dict[str, Any]]:
    """Run up to three agentic phases for chat context.

    Returns (enriched_rag_block, trace_metadata).
    """
    if not chat_agentic_enabled():
        return rag_block, {"enabled": False, "rounds": 0, "phases": []}

    rounds = max_rounds()
    trace: dict[str, Any] = {
        "enabled": True,
        "rounds": 0,
        "phases": [],
        "max_rounds": rounds,
    }

    block = rag_block or ""

    # Phase 1: Coverage
    coverage = assess_coverage(query, block)
    trace["phases"].append(coverage)
    trace["rounds"] += 1

    # Phase 2: Retrieve (if gaps and rounds remaining)
    gaps = coverage.get("gaps") or []
    if gaps and trace["rounds"] < rounds:
        block, retrieve_meta = await _retrieve_augmented(query, block, gaps)
        trace["phases"].append(retrieve_meta)
        trace["rounds"] += 1

    # Phase 3: Corroboration (if rounds remaining)
    if trace["rounds"] < rounds:
        block, corro_meta = apply_corroboration_tags(block)
        trace["phases"].append(corro_meta)
        trace["rounds"] += 1

    trace["final_chars"] = len(block)
    trace["status"] = "done"

    return block, trace


def format_agentic_trace_line(trace: dict[str, Any]) -> str:
    """Format trace as a single line for system prompt injection."""
    if not trace or not trace.get("enabled"):
        return ""
    phases = [p.get("phase", "?") for p in trace.get("phases") or []]
    return f"AGENTIC. Phases run: [{', '.join(phases)}]"
