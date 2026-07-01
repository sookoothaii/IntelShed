"""V4-25 — ReAct Agent Loop (Thought / Action / Observation).

Implements a Reason-Act loop that iteratively retrieves, reflects, and
synthesises until the query is answered or max_steps is reached.

Each step:
  Thought  — rule-based reasoning about what to do next
  Action   — dispatch to query_router route_retrieval or synthesize
  Observation — the retrieved context block

The loop is 0-VRAM for routing decisions (rule-based thoughts).  An optional
LLM call can be used for the final synthesis, but the default path produces a
deterministic merged context block — consistent with the orchestrator design.

Env:
  WORLDBASE_REACT_AGENT=1 (default off, opt-in)
  WORLDBASE_REACT_AGENT_MAX_STEPS=5
  WORLDBASE_REACT_AGENT_STEP_TIMEOUT=15.0 (seconds per action)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from config import get_config

# Action vocabulary
ACTION_SEARCH = "search"
ACTION_SEARCH_ALT = "search_alt"
ACTION_SYNTHESIZE = "synthesize"
ACTION_DONE = "done"

_VALID_ACTIONS = (ACTION_SEARCH, ACTION_SEARCH_ALT, ACTION_SYNTHESIZE, ACTION_DONE)


@dataclass
class ReActStep:
    """One Thought/Action/Observation triple."""

    step: int
    thought: str
    action: str
    action_input: str
    observation: str = ""
    duration_ms: int = 0
    error: str = ""


@dataclass
class ReActTrace:
    """Full trace of a ReAct loop execution."""

    query: str
    steps: list[ReActStep] = field(default_factory=list)
    final_block: str = ""
    total_duration_ms: int = 0
    converged: bool = False
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "enabled": self.enabled,
            "converged": self.converged,
            "step_count": len(self.steps),
            "total_duration_ms": self.total_duration_ms,
            "final_block_chars": len(self.final_block),
            "steps": [
                {
                    "step": s.step,
                    "thought": s.thought,
                    "action": s.action,
                    "action_input": s.action_input,
                    "observation_chars": len(s.observation),
                    "duration_ms": s.duration_ms,
                    "error": s.error,
                }
                for s in self.steps
            ],
        }


def react_agent_enabled() -> bool:
    return get_config().react_agent_enabled


def _max_steps() -> int:
    return get_config().react_agent_max_steps


def _step_timeout() -> float:
    return get_config().react_agent_step_timeout


# ---------------------------------------------------------------------------
# Thought generator — rule-based, 0 VRAM
# ---------------------------------------------------------------------------


def _generate_thought(
    query: str,
    step: int,
    accumulated_block: str,
    prev_actions: list[str],
) -> tuple[str, str, str]:
    """Decide what to do next.

    Returns (thought, action, action_input).
    """
    block_len = len(accumulated_block)
    has_content = block_len > 200
    has_strong = any(
        m in accumulated_block.lower()
        for m in ("rag memory", "graph retrieval", "spatial", "hybrid")
    )
    searched = any(a in (ACTION_SEARCH, ACTION_SEARCH_ALT) for a in prev_actions)
    alt_searched = ACTION_SEARCH_ALT in prev_actions

    # Step 0: always search first
    if step == 0:
        return (
            f"Query requires retrieval. Block is empty ({block_len} chars). "
            f"Dispatching primary route search.",
            ACTION_SEARCH,
            query,
        )

    # If first search was thin, try alternate route
    if searched and not has_strong and not alt_searched:
        return (
            f"Primary search returned thin block ({block_len} chars, no strong markers). "
            f"Trying alternate route for broader coverage.",
            ACTION_SEARCH_ALT,
            query,
        )

    # If we have content and have searched at least once, synthesize
    if has_content:
        return (
            f"Sufficient context accumulated ({block_len} chars, strong={has_strong}). "
            f"Synthesizing final answer.",
            ACTION_SYNTHESIZE,
            query,
        )

    # Fallback: synthesize even if thin (better than looping)
    return (
        f"Max useful searches done ({block_len} chars). "
        f"Synthesizing with available context.",
        ACTION_SYNTHESIZE,
        query,
    )


# ---------------------------------------------------------------------------
# Action executors
# ---------------------------------------------------------------------------


async def _execute_search(
    query: str,
    route: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Execute a search action via query_router.route_retrieval."""
    from query_router import classify_query, route_retrieval

    if route is None:
        route = classify_query(query)

    result = await route_retrieval(query, route=route)
    block = result.get("block", "")
    meta = {
        "route": result.get("route", route),
        "hits": len(result.get("hits") or []),
    }
    return block, meta


async def _execute_search_alt(
    query: str,
    primary_route: str,
) -> tuple[str, dict[str, Any]]:
    """Execute an alternate-route search."""
    from query_router import route_retrieval

    # Pick a different route
    alt_map = {
        "vector": "hybrid",
        "graph": "hybrid",
        "spatial": "hybrid",
        "hybrid": "vector",
        "live": "hybrid",
    }
    alt_route = alt_map.get(primary_route, "vector")

    result = await route_retrieval(query, route=alt_route)
    block = result.get("block", "")
    meta = {
        "route": result.get("route", alt_route),
        "hits": len(result.get("hits") or []),
    }
    return block, meta


def _merge_blocks(base: str, new: str) -> str:
    """Merge two context blocks, deduplicating lines."""
    if not new or not new.strip():
        return base
    if not base:
        return new

    existing = set(base.lower().splitlines())
    new_lines: list[str] = []
    for line in new.splitlines():
        stripped = line.strip()
        if stripped and stripped.lower() not in existing:
            new_lines.append(stripped)
            existing.add(stripped.lower())

    if not new_lines:
        return base
    return base.rstrip() + "\n\n" + "\n".join(new_lines)


def _synthesize(block: str, query: str) -> str:
    """Produce a final synthesis block (deterministic, 0 VRAM)."""
    header = f"=== REACT SYNTHESIS ===\nQuery: {query}\n"
    header += f"Context chars: {len(block)}\n{'=' * 40}\n\n"
    return header + block.lstrip()


# ---------------------------------------------------------------------------
# Main ReAct loop
# ---------------------------------------------------------------------------


async def run_react_loop(
    query: str,
    initial_block: str = "",
    *,
    max_steps: int | None = None,
) -> ReActTrace:
    """Run the ReAct Thought/Action/Observation loop.

    Returns a ReActTrace with all steps and the final synthesized block.
    """
    if not react_agent_enabled():
        return ReActTrace(query=query, enabled=False, final_block=initial_block)

    steps_limit = max_steps or _max_steps()
    timeout = _step_timeout()

    trace = ReActTrace(query=query)
    accumulated = initial_block or ""
    prev_actions: list[str] = []
    primary_route: str | None = None

    loop_start = time.monotonic()

    for step_num in range(steps_limit):
        step_start = time.monotonic()

        # Thought
        thought, action, action_input = _generate_thought(
            query, step_num, accumulated, prev_actions
        )

        # Execute action
        observation = ""
        error = ""

        if action == ACTION_DONE:
            trace.converged = True
            break

        elif action == ACTION_SEARCH:
            try:
                obs_block, meta = await asyncio.wait_for(
                    _execute_search(query), timeout=timeout
                )
                observation = obs_block
                primary_route = meta.get("route")
                accumulated = _merge_blocks(accumulated, observation)
            except asyncio.TimeoutError:
                error = "search timed out"
            except Exception as exc:
                error = str(exc)[:200]

        elif action == ACTION_SEARCH_ALT:
            try:
                obs_block, meta = await asyncio.wait_for(
                    _execute_search_alt(query, primary_route or "vector"),
                    timeout=timeout,
                )
                observation = obs_block
                accumulated = _merge_blocks(accumulated, observation)
            except asyncio.TimeoutError:
                error = "alt search timed out"
            except Exception as exc:
                error = str(exc)[:200]

        elif action == ACTION_SYNTHESIZE:
            accumulated = _synthesize(accumulated, query)
            trace.converged = True

        duration_ms = int((time.monotonic() - step_start) * 1000)

        trace.steps.append(
            ReActStep(
                step=step_num,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation[:500],  # truncate for trace
                duration_ms=duration_ms,
                error=error,
            )
        )
        prev_actions.append(action)

        if trace.converged:
            break

    # If we never synthesized (ran out of steps), do it now
    if not trace.converged and accumulated:
        accumulated = _synthesize(accumulated, query)
        trace.steps.append(
            ReActStep(
                step=len(trace.steps),
                thought="Max steps reached. Force-synthesizing.",
                action=ACTION_SYNTHESIZE,
                action_input=query,
                observation="",
                duration_ms=0,
            )
        )

    trace.final_block = accumulated
    trace.total_duration_ms = int((time.monotonic() - loop_start) * 1000)

    return trace


def format_react_trace_line(trace: ReActTrace) -> str:
    """Format trace as a single line for system prompt injection."""
    if not trace.enabled:
        return ""
    steps = len(trace.steps)
    actions = [s.action for s in trace.steps]
    return f"REACT. Steps: {steps}, Actions: [{', '.join(actions)}], Converged: {trace.converged}"
