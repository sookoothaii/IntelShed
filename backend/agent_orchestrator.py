"""P3+ — Multi-Agent Orchestrator for WorldBase (rule-based, 0 VRAM).

Coordinates a small team of CPU-only agents over the existing query router,
RAG memory, graph subgraph, spatial search, and corroboration modules.  No
LLM is used for routing decisions; the final synthesis is a deterministic merge
of context blocks so the orchestrator stays lightweight and fail-soft.

Each phase runs under a configurable timeout and is guarded by a lightweight
in-memory circuit breaker.  Phase traces include timing in milliseconds.

Env:
  WORLDBASE_AGENT_ORCHESTRATOR=1 (default off, opt-in)
  WORLDBASE_AGENT_ORCHESTRATOR_MAX_WORKERS=8 (cap for parallel sub-agents)
  WORLDBASE_AGENT_ORCHESTRATOR_PHASE_TIMEOUT=10.0 (seconds per phase)
  WORLDBASE_AGENT_ORCHESTRATOR_CIRCUIT_BREAKER_THRESHOLD=3 (failures before skip)
  WORLDBASE_AGENT_ORCHESTRATOR_CIRCUIT_BREAKER_WINDOW=60 (seconds to remember failures)
  WORLDBASE_AGENT_BUS=1 (required for HUD phase updates)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from config import get_config

# P1 — Blackboard (optional, opt-in via WORLDBASE_BLACKBOARD=1)
from agent_blackboard import (
    Blackboard,
    blackboard_enabled,
    conflicts_block_to_text,
    evidence_block_to_text,
    extract_entities_from_query,
    timeline_block_to_text,
)

_VALID_ROUTES = ("vector", "graph", "spatial", "hybrid", "live")


class AgentPhase(str, Enum):
    COVERAGE = "coverage"
    RETRIEVAL = "retrieval"
    SPATIAL = "spatial"
    CORROBORATION = "corroboration"
    SYNTHESIS = "synthesis"


# P7 — Agent Role Personas (0 VRAM, prompt-prefix only)
_PERSONAS: dict[str, str] = {
    AgentPhase.COVERAGE.value: (
        "You are a geospatial OSINT analyst. "
        "Extract entities, locations, and actors with precision. "
        "Identify the operational area and any named entities in the query."
    ),
    AgentPhase.RETRIEVAL.value: (
        "You are a provenance clerk. "
        "Prioritize evidence by source reliability and recency. "
        "Tag each piece of evidence with its source and a confidence level."
    ),
    AgentPhase.SPATIAL.value: (
        "You are a spatial intelligence analyst. "
        "Assess geographic proximity and co-location patterns. "
        "Highlight any spatial correlations between entities and events."
    ),
    AgentPhase.CORROBORATION.value: (
        "You are a red-team reviewer. "
        "Flag unsupported claims and demand additional evidence. "
        "Mark each claim as [corroborated] or [uncorroborated] with supporting evidence IDs."
    ),
    AgentPhase.SYNTHESIS.value: (
        "You are an intelligence editor. "
        "Produce concise, actionable assessments with clear sourcing. "
        "Prefix every claim with evidence IDs and a confidence tag (HIGH/MEDIUM/LOW)."
    ),
}


def persona_prefix(phase: str) -> str:
    """Return the persona prompt prefix for a given phase (empty if none)."""
    return _PERSONAS.get(phase, "")


# ---------------------------------------------------------------------------
# Circuit breaker state (per-process, per agent phase)
# ---------------------------------------------------------------------------

_circuit_breakers: dict[str, dict[str, Any]] = {}


def _circuit_state(name: str) -> dict[str, Any]:
    cfg = get_config()
    return _circuit_breakers.setdefault(
        name,
        {
            "failures": 0,
            "last_failure": 0.0,
            "threshold": cfg.agent_orchestrator_circuit_breaker_threshold,
            "window": cfg.agent_orchestrator_circuit_breaker_window,
        },
    )


def _circuit_open(name: str) -> bool:
    """Return True if the agent should be skipped due to recent failures."""
    state = _circuit_state(name)
    now = time.monotonic()
    if state["failures"] >= state["threshold"]:
        if now - state["last_failure"] < state["window"]:
            return True
        # Window expired; reset and allow retry
        state["failures"] = 0
    return False


def _record_failure(name: str) -> None:
    state = _circuit_state(name)
    state["failures"] += 1
    state["last_failure"] = time.monotonic()


def _record_success(name: str) -> None:
    state = _circuit_state(name)
    if state["failures"] > 0:
        state["failures"] = 0


def _circuit_summary() -> dict[str, dict[str, Any]]:
    return {name: dict(state) for name, state in _circuit_breakers.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def orchestrator_enabled() -> bool:
    return get_config().agent_orchestrator_enabled


def two_pass_enabled() -> bool:
    return get_config().two_pass_enabled


def _is_analyze_command(query: str) -> bool:
    """Check if the query is an explicit /analyze command or analysis-class query."""
    q = (query or "").strip().lower()
    if q.startswith("/analyze"):
        return True
    analysis_markers = (
        "analyze",
        "assess",
        "investigate",
        "evaluate",
        "what is the situation",
        "give me an intelligence",
        "intelligence assessment",
        "in-depth analysis",
    )
    return any(marker in q for marker in analysis_markers)


def _max_workers() -> int:
    return max(1, min(64, get_config().agent_orchestrator_max_workers))


def _phase_timeout() -> float:
    return max(1.0, get_config().agent_orchestrator_phase_timeout)


def _truthy_env(val: str | None) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _normalize_route(route: str | None) -> str:
    r = (route or "").strip().lower()
    if r in _VALID_ROUTES:
        return r
    from query_router import classify_query

    return classify_query("")


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_thin_block(block: str) -> bool:
    """Heuristic used when chat_agentic is unavailable."""
    low = (block or "").lower()
    thin_markers = (
        "crag fallback",
        "low confidence",
        "low retrieval",
        "unavailable",
        "no bbox",
        "no rag memory",
        "weak memory",
        "empty",
    )
    has_thin = any(m in low for m in thin_markers)
    return len(block) < 200 or (has_thin and len(block) < 400)


def _unique_lines(base: str, *extra_blocks: str) -> str:
    """Merge blocks keeping only lines not already present in base."""
    existing = set((base or "").lower().splitlines())
    out_lines: list[str] = []
    for blk in extra_blocks:
        for line in (blk or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower() not in existing:
                out_lines.append(stripped)
                existing.add(stripped.lower())
    if not out_lines:
        return base
    return (base or "").rstrip() + "\n\n" + "\n".join(out_lines)


async def _run_with_timeout(
    coro: Any,
    name: str,
    *,
    timeout: float | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Run a coroutine with a timeout and return (result, timing_meta)."""
    deadline = timeout or _phase_timeout()
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(coro, timeout=deadline)
        duration_ms = int((time.monotonic() - start) * 1000)
        _record_success(name)
        return result, {"duration_ms": duration_ms, "timed_out": False}
    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start) * 1000)
        _record_failure(name)
        raise
    except Exception:
        _record_failure(name)
        raise


async def _publish_phase(title: str, lines: list[str]) -> int:
    """Publish a lightweight phase event to the Agent Bus if enabled."""
    try:
        import agent_bus

        if not agent_bus.agent_bus_enabled():
            return 0
        body = agent_bus.AgentPublishBody(
            action="agent_phase",
            title=title,
            lines=lines,
        )
        result = await agent_bus.publish_action(body)
        return int(result.get("delivered", 0))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Individual agents
# ---------------------------------------------------------------------------


async def _coverage_agent(
    query: str,
    route: str,
    initial_block: str,
    bb: Blackboard | None = None,
) -> dict[str, Any]:
    """Phase 1 — assess whether the initial retrieval block is sufficient."""
    # P1 — extract entities into the blackboard
    if bb is not None:
        bb.extracted_entities = extract_entities_from_query(query)

    if _circuit_open("coverage"):
        return {
            "phase": AgentPhase.COVERAGE.value,
            "route": route,
            "skipped": True,
            "reason": "circuit_open",
            "needs_retrieve": _is_thin_block(initial_block),
            "gaps": ["thin_block"] if _is_thin_block(initial_block) else [],
        }

    try:
        import chat_agentic

        if chat_agentic.chat_agentic_enabled():
            coverage, timing = await _run_with_timeout(
                asyncio.to_thread(chat_agentic.assess_coverage, query, initial_block),
                "coverage",
            )
            return {
                "phase": AgentPhase.COVERAGE.value,
                "route": route,
                "char_count": coverage.get("char_count", 0),
                "unique_sources": coverage.get("unique_sources", 0),
                "gaps": coverage.get("gaps", []),
                "needs_retrieve": coverage.get("needs_retrieve", False),
                "using": "chat_agentic",
                **timing,
            }
    except Exception as exc:
        return {
            "phase": AgentPhase.COVERAGE.value,
            "route": route,
            "error": str(exc)[:200],
            "needs_retrieve": _is_thin_block(initial_block),
            "gaps": ["thin_block"],
            **{"duration_ms": 0, "timed_out": isinstance(exc, asyncio.TimeoutError)},
        }

    return {
        "phase": AgentPhase.COVERAGE.value,
        "route": route,
        "char_count": len(initial_block),
        "needs_retrieve": _is_thin_block(initial_block),
        "gaps": ["thin_block"] if _is_thin_block(initial_block) else [],
        "using": "fallback",
    }


async def _retrieval_agent(
    query: str,
    route: str,
    base_block: str,
    gaps: list[str],
    bb: Blackboard | None = None,
) -> tuple[str, dict[str, Any]]:
    """Phase 2 — targeted retrieval to fill coverage gaps."""
    from query_router import route_retrieval

    if _circuit_open("retrieval"):
        meta = {
            "phase": AgentPhase.RETRIEVAL.value,
            "route": route,
            "skipped": True,
            "reason": "circuit_open",
        }
        return base_block, meta

    meta: dict[str, Any] = {
        "phase": AgentPhase.RETRIEVAL.value,
        "route": route,
        "queries": [query],
        "retrieved": 0,
        "errors": [],
    }

    try:
        result, timing = await _run_with_timeout(
            route_retrieval(query, route=route),
            "retrieval",
        )
        block = result.get("block", "")
        hits = result.get("hits") or []
        meta["retrieved"] = len(hits)
        meta["route"] = result.get("route", route)
        meta.update(timing)
        # P1/P3 — register evidence in the blackboard
        if bb is not None:
            _register_evidence(bb, hits, route)
            bb.retrieval_decisions.append(
                _make_retrieval_decision(route, query, len(hits))
            )
        merged = _unique_lines(base_block, block)
        if not _is_thin_block(merged) or route == "hybrid":
            return merged, meta
    except Exception as exc:
        meta["errors"].append(str(exc)[:200])
        meta.update(
            {"duration_ms": 0, "timed_out": isinstance(exc, asyncio.TimeoutError)}
        )

    # Secondary route if the first pass is still thin or failed
    secondary = "hybrid" if route in ("vector", "graph", "live") else "vector"
    try:
        result2, timing2 = await _run_with_timeout(
            route_retrieval(query, route=secondary),
            "retrieval",
        )
        block2 = result2.get("block", "")
        hits2 = result2.get("hits") or []
        meta["retrieved"] += len(hits2)
        meta["secondary_route"] = secondary
        meta.update(timing2)
        # P1/P3 — register secondary evidence
        if bb is not None:
            _register_evidence(bb, hits2, secondary)
            bb.retrieval_decisions.append(
                _make_retrieval_decision(secondary, query, len(hits2))
            )
        merged = _unique_lines(base_block, block2)
        return merged, meta
    except Exception as exc:
        meta["errors"].append(str(exc)[:200])
        return base_block, meta


async def _spatial_agent(
    query: str,
    base_block: str,
    bb: Blackboard | None = None,
) -> tuple[str, dict[str, Any]]:
    """Phase 3 — bbox-filtered spatial retrieval + proximity context."""
    from query_router import route_retrieval

    if _circuit_open("spatial"):
        meta = {
            "phase": AgentPhase.SPATIAL.value,
            "route": "spatial",
            "skipped": True,
            "reason": "circuit_open",
        }
        return base_block, meta

    meta: dict[str, Any] = {
        "phase": AgentPhase.SPATIAL.value,
        "route": "spatial",
        "retrieved": 0,
        "errors": [],
    }

    try:
        result, timing = await _run_with_timeout(
            route_retrieval(query, route="spatial"),
            "spatial",
        )
        block = result.get("block", "")
        hits = result.get("hits") or []
        meta["retrieved"] = len(hits)
        meta["route"] = result.get("route", "spatial")
        meta.update(timing)
        # P1/P3 — register spatial evidence
        if bb is not None:
            _register_evidence(bb, hits, "spatial")
            bb.retrieval_decisions.append(
                _make_retrieval_decision("spatial", query, len(hits))
            )
        merged = _unique_lines(base_block, block)
        return merged, meta
    except Exception as exc:
        meta["errors"].append(str(exc)[:200])
        meta.update(
            {"duration_ms": 0, "timed_out": isinstance(exc, asyncio.TimeoutError)}
        )
        return base_block, meta


async def _corroboration_agent(
    block: str,
    bb: Blackboard | None = None,
) -> tuple[str, dict[str, Any]]:
    """Phase 4 — tag claims with corroboration status."""
    if _circuit_open("corroboration"):
        return block, {
            "phase": AgentPhase.CORROBORATION.value,
            "skipped": True,
            "reason": "circuit_open",
        }

    try:
        import chat_agentic

        if hasattr(chat_agentic, "apply_corroboration_tags"):
            (tagged, meta), timing = await _run_with_timeout(
                asyncio.to_thread(chat_agentic.apply_corroboration_tags, block),
                "corroboration",
            )
            meta["phase"] = AgentPhase.CORROBORATION.value
            meta.update(timing)
            # P1 — register claims in the blackboard
            if bb is not None:
                _register_claims(bb, tagged, meta)
            return tagged, meta
    except Exception as exc:
        return block, {
            "phase": AgentPhase.CORROBORATION.value,
            "error": str(exc)[:200],
            "duration_ms": 0,
            "timed_out": isinstance(exc, asyncio.TimeoutError),
        }

    return block, {
        "phase": AgentPhase.CORROBORATION.value,
        "skipped": True,
        "reason": "chat_agentic unavailable",
    }


async def _synthesis_agent(
    block: str,
    route: str,
    phases: list[dict[str, Any]],
    bb: Blackboard | None = None,
) -> tuple[str, dict[str, Any]]:
    """Phase 5 — deterministic merge of context into a final response block."""
    start = time.monotonic()
    lines = ["=== AGENT ORCHESTRATOR CONTEXT ===", f"Route: {route}"]
    for p in phases:
        label = p.get("phase", "?")
        note = f"{label}: "
        if p.get("error"):
            note += f"error={p['error'][:80]}"
        elif p.get("skipped"):
            note += f"skipped={p.get('reason', 'unknown')}"
        elif p.get("phase") == AgentPhase.COVERAGE.value:
            note += f"gaps={len(p.get('gaps', []))}"
        elif p.get("phase") == AgentPhase.RETRIEVAL.value:
            note += f"retrieved={p.get('retrieved', 0)}"
        elif p.get("phase") == AgentPhase.SPATIAL.value:
            note += f"retrieved={p.get('retrieved', 0)}"
        elif p.get("phase") == AgentPhase.CORROBORATION.value:
            note += f"corroborated={p.get('corroborated', 0)} uncorroborated={p.get('uncorroborated', 0)}"
        if p.get("duration_ms") is not None:
            note += f" ({p['duration_ms']}ms)"
        lines.append(note)

    header = "\n".join(lines)

    # P1/P3/P7 — enrich with blackboard content when available
    extra_blocks: list[str] = []
    if bb is not None:
        # P7 — persona prefix for synthesis
        persona = persona_prefix(AgentPhase.SYNTHESIS.value)
        if persona:
            extra_blocks.append(f"--- PERSONA\n{persona}")
        # P3 — evidence registry
        ev_block = evidence_block_to_text(bb)
        if ev_block:
            extra_blocks.append(f"--- EVIDENCE REGISTRY\n{ev_block}")
        # P4 — conflicts (if any were detected)
        conf_block = conflicts_block_to_text(bb)
        if conf_block:
            extra_blocks.append(conf_block)
        # P3 — temporal timeline
        tl_block = timeline_block_to_text(bb)
        if tl_block:
            extra_blocks.append(tl_block)
        bb.synthesis_draft = block

    final = f"{header}\n\n{block.lstrip()}"
    if extra_blocks:
        final += "\n\n" + "\n\n".join(extra_blocks)
    duration_ms = int((time.monotonic() - start) * 1000)
    meta = {
        "phase": AgentPhase.SYNTHESIS.value,
        "block_chars": len(final),
        "phase_count": len(phases),
        "duration_ms": duration_ms,
    }
    if bb is not None:
        meta["evidence_count"] = len(bb.evidence_registry)
        meta["conflict_count"] = len(bb.conflicts)
        meta["entity_count"] = len(bb.extracted_entities)
    return final, meta


# ---------------------------------------------------------------------------
# P5 — Critique-Refine (two-pass synthesis, opt-in)
# ---------------------------------------------------------------------------

# Checklist items that the critique agent verifies in the synthesis draft
_CRITIQUE_CHECKLIST: tuple[str, ...] = (
    "evidence",
    "blind spot",
    "assumption",
    "recommended action",
    "competing hypothesis",
    "devil",
    "conflict",
    "fusion",
    "temporal",
    "indicator",
)


async def _critique_agent(
    draft: str,
    bb: Blackboard | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """P5 — Critique the synthesis draft against a coverage checklist.

    Returns (gaps, meta) where gaps is a list of missing checklist items.
    """
    start = time.monotonic()
    if _circuit_open("critique"):
        return [], {
            "phase": "critique",
            "skipped": True,
            "reason": "circuit_open",
        }

    draft_lower = (draft or "").lower()
    gaps: list[str] = []

    for item in _CRITIQUE_CHECKLIST:
        if item not in draft_lower:
            gaps.append(item)

    # Check evidence coverage from blackboard
    if bb is not None:
        # If we have evidence but the draft doesn't reference any [EVIDENCE-NNN]
        if bb.evidence_registry:
            has_evidence_ref = "[evidence-" in draft_lower
            if not has_evidence_ref:
                gaps.append("evidence_id_reference")

        # If we have conflicts but draft doesn't mention them
        if bb.conflicts:
            has_conflict_ref = any(
                kw in draft_lower for kw in ("conflict", "contradict", "however")
            )
            if not has_conflict_ref:
                gaps.append("conflict_mention")

    # Store critique notes in the blackboard
    if bb is not None:
        bb.critique_notes = (
            f"Gaps found: {', '.join(gaps)}" if gaps else "No gaps detected."
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    meta: dict[str, Any] = {
        "phase": "critique",
        "gaps": gaps,
        "gap_count": len(gaps),
        "checklist_size": len(_CRITIQUE_CHECKLIST),
        "duration_ms": duration_ms,
    }
    if bb is not None:
        meta["evidence_count"] = len(bb.evidence_registry)
        meta["conflict_count"] = len(bb.conflicts)
    return gaps, meta


async def _revise_synthesis(
    draft: str,
    gaps: list[str],
    query: str,
    route: str,
    bb: Blackboard | None = None,
) -> tuple[str, dict[str, Any]]:
    """P5 — Targeted re-retrieval for identified gaps, then revise the draft.

    If gaps are found, performs one additional retrieval round focused on
    the gap topics, then appends the new evidence to the synthesis block.
    """
    start = time.monotonic()
    if not gaps:
        return draft, {
            "phase": "revise",
            "retrieved": 0,
            "gaps_addressed": 0,
            "duration_ms": 0,
        }

    from query_router import route_retrieval

    new_block = draft
    retrieved = 0

    # Build a targeted query from gaps
    gap_query = f"{query} {' '.join(gaps[:3])}"

    try:
        result, timing = await _run_with_timeout(
            route_retrieval(gap_query, route="hybrid"),
            "revise",
        )
        block = result.get("block", "")
        hits = result.get("hits") or []
        retrieved = len(hits)
        if block:
            new_block = _unique_lines(draft, block)
        # Register new evidence in blackboard
        if bb is not None and hits:
            _register_evidence(bb, hits, "hybrid")
    except Exception as exc:
        return draft, {
            "phase": "revise",
            "error": str(exc)[:200],
            "retrieved": 0,
            "gaps_addressed": 0,
            "duration_ms": int((time.monotonic() - start) * 1000),
            "timed_out": isinstance(exc, asyncio.TimeoutError),
        }

    # Re-enrich with blackboard content after additional retrieval
    if bb is not None:
        extra_blocks: list[str] = []
        ev_block = evidence_block_to_text(bb)
        if ev_block:
            extra_blocks.append(f"--- EVIDENCE REGISTRY (revised)\n{ev_block}")
        conf_block = conflicts_block_to_text(bb)
        if conf_block:
            extra_blocks.append(conf_block)
        tl_block = timeline_block_to_text(bb)
        if tl_block:
            extra_blocks.append(tl_block)
        if extra_blocks:
            new_block += "\n\n" + "\n\n".join(extra_blocks)

    # Add a critique summary header
    gap_summary = ", ".join(gaps[:5])
    new_block = (
        f"=== CRITIQUE-REFINE (two-pass) ===\n"
        f"Gaps identified: {gap_summary}\n"
        f"Re-retrieval: {retrieved} hits\n"
        f"{'=' * 40}\n\n"
        f"{new_block}"
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    meta = {
        "phase": "revise",
        "retrieved": retrieved,
        "gaps_addressed": len(gaps),
        "duration_ms": duration_ms,
    }
    return new_block, meta


def _register_evidence(
    bb: Blackboard,
    hits: list[dict[str, Any]],
    route: str,
) -> None:
    """Register retrieval hits as evidence items in the blackboard."""
    from provenance import score_provenance

    for hit in hits:
        if not isinstance(hit, dict):
            continue
        text = str(hit.get("text") or hit.get("content") or "")[:500]
        if not text.strip():
            continue
        source = str(hit.get("source") or hit.get("feed") or route)
        url = str(hit.get("url") or hit.get("link") or "")
        retrieved_at = str(hit.get("timestamp") or hit.get("date") or "")
        # Compute provenance score
        try:
            p_score = score_provenance(source=source)
        except Exception:
            p_score = 0.5
        bb.add_evidence(
            source=source,
            text=text,
            url=url,
            retrieved_at=retrieved_at,
            provenance_score=p_score,
        )


def _make_retrieval_decision(
    route: str,
    query: str,
    hits: int,
) -> Any:
    """Create a RetrievalDecision record for the blackboard."""
    from agent_blackboard import RetrievalDecision

    return RetrievalDecision(
        route=route,
        query=query,
        hits=hits,
    )


def _register_claims(
    bb: Blackboard,
    tagged_block: str,
    meta: dict[str, Any],
) -> None:
    """Extract claims from the corroboration-tagged block and register them."""
    import re

    # Extract [corroborated] and [uncorroborated] tagged lines
    pattern = r"\[(corroborated|uncorroborated)\]\s*(.+)"
    matches = re.findall(pattern, tagged_block, re.IGNORECASE)
    for tag, text in matches:
        is_uncorroborated = tag.lower() == "uncorroborated"
        confidence = "LOW" if is_uncorroborated else "MEDIUM"
        bb.add_claim(
            claim=text.strip()[:300],
            confidence=confidence,
            uncorroborated=is_uncorroborated,
        )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def orchestrate(
    query: str,
    route: str | None = None,
    *,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Run the multi-agent orchestration pipeline.

    Returns a dict with the final merged context block, the route used, a
    complete phase trace (including timing), circuit breaker state, and the
    number of HUD subscribers that received phase updates.
    """
    if not orchestrator_enabled():
        return {
            "query": query,
            "enabled": False,
            "route": route,
            "final_block": "",
            "phases": [],
            "hud_delivered": 0,
            "circuit_breakers": _circuit_summary(),
        }

    workers = max_workers or _max_workers()
    _ = workers  # reserved for future parallel sub-agent limits

    from query_router import classify_query, route_retrieval

    resolved_route = route if route in _VALID_ROUTES else classify_query(query)

    trace: dict[str, Any] = {
        "query": query,
        "route": resolved_route,
        "enabled": True,
        "started_at": _now_utc(),
        "phases": [],
    }
    hud_delivered = 0

    # P1 — Create shared blackboard when enabled
    bb: Blackboard | None = None
    if blackboard_enabled():
        bb = Blackboard(query=query, route=resolved_route)

    # Phase 0: initial route retrieval (required for coverage)
    try:
        initial, _ = await _run_with_timeout(
            route_retrieval(query, route=resolved_route),
            "route_retrieval",
        )
        block = initial.get("block", "")
        # P1/P3 — register initial evidence
        if bb is not None:
            _register_evidence(bb, initial.get("hits") or [], resolved_route)
    except Exception as exc:
        trace["initial_error"] = str(exc)[:200]
        block = ""

    # Phase 1: Coverage
    coverage = await _coverage_agent(query, resolved_route, block, bb=bb)
    trace["phases"].append(coverage)
    hud_delivered += await _publish_phase(
        "Coverage",
        [
            f"route={resolved_route}",
            f"gaps={len(coverage.get('gaps', []))}",
            f"needs_retrieve={coverage.get('needs_retrieve', False)}",
        ],
    )

    gaps = coverage.get("gaps", [])
    needs_retrieve = bool(gaps) or coverage.get("needs_retrieve", False)
    run_spatial = resolved_route in ("spatial", "hybrid")

    # Phase 2 + 3: Retrieval and Spatial (parallel where independent)
    pending_tasks: list[asyncio.Task[tuple[str, dict[str, Any]]]] = []
    if needs_retrieve:
        pending_tasks.append(
            asyncio.create_task(
                _retrieval_agent(query, resolved_route, block, gaps, bb=bb)
            )
        )
    if run_spatial:
        pending_tasks.append(asyncio.create_task(_spatial_agent(query, block, bb=bb)))

    if pending_tasks:
        try:
            results = await asyncio.gather(*pending_tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    trace["phases"].append(
                        {
                            "phase": "agent_error",
                            "error": str(res)[:200],
                        }
                    )
                    continue
                new_block, meta = res
                block = _unique_lines(block, new_block)
                trace["phases"].append(meta)
                hud_delivered += await _publish_phase(
                    meta.get("phase", "Agent").capitalize(),
                    [f"retrieved={meta.get('retrieved', 0)}"]
                    if "retrieved" in meta
                    else [],
                )
        except Exception as exc:
            trace["phases"].append({"phase": "agent_error", "error": str(exc)[:200]})

    # Phase 4: Corroboration
    block, corro_meta = await _corroboration_agent(block, bb=bb)
    trace["phases"].append(corro_meta)
    hud_delivered += await _publish_phase(
        "Corroboration",
        [
            f"corroborated={corro_meta.get('corroborated', 0)}",
            f"uncorroborated={corro_meta.get('uncorroborated', 0)}",
        ],
    )

    # P4 — Conflict detection (after evidence is registered)
    if bb is not None and bb.evidence_registry:
        try:
            import conflict_detection

            detected = conflict_detection.detect_conflicts(bb.evidence_registry)
            for cp in detected:
                bb.add_conflict(
                    eid_a=cp["evidence_id_a"],
                    eid_b=cp["evidence_id_b"],
                    conflict_type=cp["conflict_type"],
                    description=cp["description"],
                    severity=cp["severity"],
                )
        except Exception:
            pass  # fail-soft

    # Phase 5: Synthesis
    final_block, synth_meta = await _synthesis_agent(
        block, resolved_route, trace["phases"], bb=bb
    )
    trace["phases"].append(synth_meta)

    # P5 — Critique-Refine (two-pass synthesis, opt-in)
    two_pass = two_pass_enabled() and _is_analyze_command(query)
    if two_pass:
        try:
            gaps, critique_meta = await _critique_agent(final_block, bb=bb)
            trace["phases"].append(critique_meta)
            if gaps:
                revised_block, revise_meta = await _revise_synthesis(
                    final_block, gaps, query, resolved_route, bb=bb
                )
                trace["phases"].append(revise_meta)
                final_block = revised_block
        except Exception as exc:
            trace["phases"].append(
                {
                    "phase": "critique",
                    "error": str(exc)[:200],
                    "skipped": True,
                }
            )

    trace["final_block_chars"] = len(final_block)
    trace["finished_at"] = _now_utc()
    trace["hud_delivered"] = hud_delivered
    trace["circuit_breakers"] = _circuit_summary()

    result: dict[str, Any] = {
        "query": query,
        "route": resolved_route,
        "enabled": True,
        "final_block": final_block,
        "final_block_chars": len(final_block),
        "two_pass": two_pass,
        "phases": trace["phases"],
        "hud_delivered": hud_delivered,
        "started_at": trace["started_at"],
        "finished_at": trace["finished_at"],
        "circuit_breakers": trace["circuit_breakers"],
        **(
            {"initial_error": trace["initial_error"]}
            if "initial_error" in trace
            else {}
        ),
    }

    # P1 — Include blackboard state when enabled
    if bb is not None:
        result["blackboard"] = bb.condensed()

    return result


async def agent_status() -> dict[str, Any]:
    """Runtime status of the orchestrator and the agent bus."""
    try:
        import agent_bus

        bus_enabled = agent_bus.agent_bus_enabled()
        subscribers = agent_bus.subscriber_count()
        layers = sorted(agent_bus.GLOBE_LAYER_KEYS)
    except Exception:
        bus_enabled = False
        subscribers = 0
        layers = []

    return {
        "enabled": orchestrator_enabled(),
        "max_workers": _max_workers(),
        "phase_timeout": _phase_timeout(),
        "circuit_breakers": _circuit_summary(),
        "agent_bus_enabled": bus_enabled,
        "agent_bus_subscribers": subscribers,
        "supported_routes": list(_VALID_ROUTES),
        "supported_phases": [p.value for p in AgentPhase],
        "globe_layers": layers,
        "blackboard_enabled": blackboard_enabled(),
        "two_pass_enabled": two_pass_enabled(),
    }
