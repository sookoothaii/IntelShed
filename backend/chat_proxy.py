"""LLM proxy endpoints — /api/models, /api/chat, /api/providers.

Extracted from routes/chat.py (Phase 2). Handles provider fan-out,
SSE streaming, firewall gate, and the chat message preparation pipeline.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

import chat_routing
import chat_tools
from auth.security import verify_api_key
from middleware.rate_limit import rate_limit_general

from chat_context import (
    OLLAMA_HOSTS,
    _is_embed_model,
    _models_cache,
    _MODELS_CACHE_TTL,
    build_chat_context,
)

router = APIRouter(tags=["chat"])


@router.get("/api/models")
async def list_models():
    """List available Ollama chat models (embed models excluded from chat picker)."""
    now = time.time()
    if _models_cache["data"] and now - _models_cache["ts"] < _MODELS_CACHE_TTL:
        return _models_cache["data"]

    last_err = None
    for host in OLLAMA_HOSTS:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"http://{host}/api/tags")
                r.raise_for_status()
                data = r.json()
                all_models = data.get("models", [])
                chat_models = [
                    m for m in all_models if not _is_embed_model(m.get("name", ""))
                ]
                default_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
                chat_names = [m.get("name") for m in chat_models]
                all_names = [m.get("name") for m in all_models]
                if default_model not in chat_names:
                    for n in chat_names:
                        if n and n.split(":")[0] == default_model.split(":")[0]:
                            default_model = n
                            break
                payload = {
                    "host": host,
                    "count": len(chat_models),
                    "default": default_model
                    if default_model in chat_names
                    else (chat_names[0] if chat_names else None),
                    "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                    "embed_available": any(_is_embed_model(n or "") for n in all_names),
                    "models": [
                        {
                            "name": m.get("name"),
                            "size": m.get("size"),
                            "parameter_size": m.get("details", {}).get(
                                "parameter_size"
                            ),
                        }
                        for m in chat_models
                    ],
                }
                if not chat_models and all_models:
                    payload["warning"] = (
                        "Only embedding models found. Run: ollama pull qwen3:8b"
                    )
                _models_cache["ts"] = now
                _models_cache["data"] = payload
                return payload
        except Exception as e:
            last_err = str(e)
            continue
    err = {
        "error": "Ollama not reachable",
        "detail": last_err,
        "hosts_tried": OLLAMA_HOSTS,
        "hint": (
            "1) Start Ollama (ollama.com)  2) ollama pull qwen3:8b  "
            "3) backend/.env → OLLAMA_HOST=127.0.0.1:11434  4) .\\start.ps1"
        ),
    }
    return err


@router.get("/api/chat/context")
async def chat_context_endpoint(q: str = "", api_key: str = Depends(verify_api_key)):
    """Return the chat context block for inspection / smoke testing.

    When ?q= is provided, returns query-enriched context (P1).
    """
    ctx = await build_chat_context(query=q if q else None)
    return {"context": ctx, "query": q or None}


# --- P2: Synthesis directive builder ---

_DOMAIN_TEMPLATES: dict[str, str] = {
    "earthquake": (
        "\nDOMAIN TEMPLATE (seismic event):\n"
        "- Magnitude/depth → potential damage radius\n"
        "- Nearby population centers → humanitarian impact\n"
        "- Coastal location → tsunami risk assessment\n"
        "- Regional political stability → response capacity\n"
        "- Energy infrastructure → supply chain impact\n"
        "- Historical seismicity → pattern context\n"
    ),
    "volcano": (
        "\nDOMAIN TEMPLATE (volcanic event):\n"
        "- VEI/eruption type → ash dispersion radius\n"
        "- Wind direction → ash fall zones, aviation risk\n"
        "- Nearby population → evacuation needs\n"
        "- Thermal/CO2 emissions → health hazards\n"
    ),
    "flood": (
        "\nDOMAIN TEMPLATE (flood event):\n"
        "- Affected area and population → humanitarian impact\n"
        "- Critical infrastructure → disruption assessment\n"
        "- Weather pattern → duration and escalation risk\n"
        "- Agricultural impact → food security implications\n"
    ),
    "cyclone": (
        "\nDOMAIN TEMPLATE (cyclone/typhoon event):\n"
        "- Category/wind speed → damage potential\n"
        "- Track forecast → areas at risk\n"
        "- Storm surge → coastal flooding risk\n"
        "- Evacuation status → population safety\n"
    ),
    "fire": (
        "\nDOMAIN TEMPLATE (wildfire event):\n"
        "- Fire size/intensity → containment difficulty\n"
        "- Wind/terrain → spread direction and speed\n"
        "- Population/property → evacuation needs\n"
        "- Air quality → health impact radius\n"
    ),
    "conflict": (
        "\nDOMAIN TEMPLATE (conflict/attack event):\n"
        "- Actors involved → motivation and capability\n"
        "- Casualties/displacement → humanitarian impact\n"
        "- Regional stability → escalation risk\n"
        "- Economic assets → supply chain disruption\n"
        "- International response → diplomatic implications\n"
    ),
    "vessel": (
        "\nDOMAIN TEMPLATE (maritime event):\n"
        "- Vessel type/cargo → incident severity\n"
        "- Location (port/straight/open sea) → jurisdiction\n"
        "- AIS data → track history and anomalies\n"
        "- Nearby vessels → collision/assistance potential\n"
    ),
    "cyber": (
        "\nDOMAIN TEMPLATE (cyber event):\n"
        "- CVE/exploit details → affected systems\n"
        "- Threat actor → capability and motivation\n"
        "- Sector impact → cascading effects\n"
        "- Ransomware group → leak site timeline\n"
        "- Darkweb mentions → threat intelligence\n"
    ),
    "protest": (
        "\nDOMAIN TEMPLATE (civil unrest event):\n"
        "- Scale/intensity → disruption level\n"
        "- Grievances → underlying causes\n"
        "- Government response → escalation risk\n"
        "- Economic impact → business disruption\n"
    ),
}


def _build_synthesis_directive(
    event_type: str | None = None,
    intent: str = "general",
) -> str:
    """Build P2 synthesis directive with SATs, evidence weighting, red-team, and actionable.

    Returns a string appended to the system prompt when enriched context is present.
    All sections are controlled by env flags (default on).
    """
    parts: list[str] = []

    # Synthesis directive
    if os.getenv("WORLDBASE_CHAT_SYNTHESIS_DIRECTIVE", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        parts.append(
            "\nANALYSIS DIRECTIVE (query-enriched context is present):\n"
            "- Cross-reference the event with ALL provided telemetry sources:\n"
            "  * GDELT events near the location → political/social context\n"
            "  * FtM graph entities → who/what is connected to this location\n"
            "  * Fusion hotspots → is this a pattern or isolated event?\n"
            "  * ReliefWeb crises → humanitarian situation\n"
            "  * Maritime AIS → port/vessel activity if coastal\n"
            "- Assess IMPLICATIONS, not just facts:\n"
            "  * What infrastructure is at risk?\n"
            "  * What political/economic factors amplify or mitigate?\n"
            "  * What should the operator monitor next?\n"
            "- If data is sparse for a source, say 'DATA GAP: [source]' — do not speculate.\n"
        )

    # Domain-specific template
    if (
        os.getenv("WORLDBASE_CHAT_DOMAIN_TEMPLATES", "1").strip()
        in ("1", "true", "yes", "on")
        and event_type
        and event_type in _DOMAIN_TEMPLATES
    ):
        parts.append(_DOMAIN_TEMPLATES[event_type])

    # Structured Analytic Techniques (SATs)
    if os.getenv("WORLDBASE_CHAT_SATS", "1").strip() in ("1", "true", "yes", "on"):
        parts.append(
            "\nSTRUCTURED ANALYTIC TECHNIQUES (mandatory when enriched context present):\n"
            "- KEY ASSUMPTIONS CHECK: Begin the analysis by listing 2-3 implicit "
            "assumptions that underpin your assessment. State them explicitly: "
            "'We assume that...'\n"
            "- ANALYSIS OF COMPETING HYPOTHESES (ACH): When the event is ambiguous, "
            "present at least two competing hypotheses and evaluate each against the "
            "available evidence. Do not default to the most obvious explanation.\n"
            "- DEVIL'S ADVOCACY: End every analysis with a 'COUNTERARGUMENT' section "
            "that argues against your own main thesis. What evidence would change "
            "this assessment?\n"
            "- INDICATORS & WARNINGS: Conclude with specific, observable signals "
            "that would confirm or refute the assessment. Format as a watchlist.\n"
        )

    # Evidence weighting
    if os.getenv("WORLDBASE_CHAT_EVIDENCE_WEIGHTING", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        parts.append(
            "\nEVIDENCE WEIGHTING (for each key claim in the analysis):\n"
            "- List supporting sources with confidence: "
            "[HIGH — direct measurement], [MEDIUM — indirect], [LOW — negative evidence]\n"
            "- State overall claim confidence: HIGH / MEDIUM / LOW\n"
            "- If single-source and uncorroborated, tag as "
            "[SINGLE-SOURCE — unverified]\n"
        )

    # Red-team review
    if os.getenv("WORLDBASE_CHAT_RED_TEAM", "1").strip() in ("1", "true", "yes", "on"):
        parts.append(
            "\nBLIND SPOTS & LIMITATIONS (mandatory section):\n"
            "- List data sources that were unavailable or sparse\n"
            "- Note temporal limitations (data freshness, window size)\n"
            "- Identify analytical gaps (e.g. no HUMINT, no SAR, AIS coverage)\n"
            "- State the data cutoff timestamp\n"
        )

    # Actionable intelligence
    if os.getenv("WORLDBASE_CHAT_ACTIONABLE", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        parts.append(
            "\nRECOMMENDED ACTIONS (mandatory closing block):\n"
            "1. MONITOR: [specific signal to watch] (source: [feed/API])\n"
            "2. VERIFY: [specific verification step] (method: [SAR/cross-source/HUMINT])\n"
            "3. ALERT: [threshold or trigger for escalation]\n"
            "4. ESCALATE: [condition that requires senior analyst notification]\n"
        )

    # Fusion matrix
    if os.getenv("WORLDBASE_CHAT_FUSION_MATRIX", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        parts.append(
            "\nFUSION MATRIX (include when multiple sources are enriched):\n"
            "                    USGS    GDELT    FtM    AIS    ReliefWeb\n"
            "Event details      ████    ░░░░     ░░░░   ░░░░   ░░░░\n"
            "Political context  ░░░░    ████     ██░░   ░░░░   ░░░░\n"
            "Infrastructure     ██░░    ░░░░     ████   ░░░░   ░░░░\n"
            "Maritime           ░░░░    ░░░░     ░░░░   ████   ░░░░\n"
            "Humanitarian       ░░░░    ░░░░     ░░░░   ░░░░   ████\n"
            "LEGEND: ████ = direct data, ██░░ = indirect, ░░░░ = no data\n"
            "(Fill in actual coverage based on enriched context blocks above)\n"
        )

    return "".join(parts)


# ---------------------------------------------------------------------------
# Auto web search — when user explicitly requests live data / DuckDuckGo
# ---------------------------------------------------------------------------

_WEB_SEARCH_TRIGGERS = {
    "duckduckgo",
    "web search",
    "web-search",
    "search the web",
    "search web",
    "live data",
    "live search",
    "live research",
    "recherche",
    "suche im web",
    "suche duckduckgo",
    "nutze duckduckgo",
    "use duckduckgo",
    "use web search",
    "google it",
    "look it up",
    "look up",
    "fetch live",
    "current data",
    "aktuelle daten",
    "echtzeit",
    "real-time data",
    "realtime data",
    "internet search",
    "online search",
    "browse the web",
    "suche im internet",
    "im internet suchen",
    "suche im netz",
    "search the internet",
    "search online",
    "find online",
    "suche infos",
    "suche informationen",
    "suche mir",
    "search for info",
    "find information",
    "check noch einmal",
    "check again",
    "prüfe nach",
    "schau nach",
    "nachprüfen",
    "schauen sie nach",
    "look again",
    "check for info",
    "suche nach",
    "search for",
    "check for details",
}

# Regex patterns for more flexible matching (e.g. "suche ... im internet")
_WEB_SEARCH_PATTERNS = [
    re.compile(r"\bsuche\b.*\binternet\b", re.IGNORECASE),
    re.compile(r"\bsuche\b.*\bweb\b", re.IGNORECASE),
    re.compile(r"\bsuche\b.*\bonline\b", re.IGNORECASE),
    re.compile(r"\bsearch\b.*\binternet\b", re.IGNORECASE),
    re.compile(r"\bsearch\b.*\bweb\b", re.IGNORECASE),
    re.compile(r"\bsearch\b.*\bonline\b", re.IGNORECASE),
    re.compile(r"\bfind\b.*\binternet\b", re.IGNORECASE),
    re.compile(r"\bfind\b.*\bweb\b", re.IGNORECASE),
    re.compile(r"\brecherche\b.*\binternet\b", re.IGNORECASE),
    re.compile(r"\brecherche\b.*\bweb\b", re.IGNORECASE),
    re.compile(r"\bcheck\b.*\binfo\b", re.IGNORECASE),
    re.compile(r"\bcheck\b.*\bnach\b", re.IGNORECASE),
    re.compile(r"\bprüf\b.*\binfo\b", re.IGNORECASE),
    re.compile(r"\bsuche\b.*\bnach\b", re.IGNORECASE),
    re.compile(r"\bschau\b.*\bnach\b", re.IGNORECASE),
    re.compile(r"\blook\b.*\bagain\b", re.IGNORECASE),
    re.compile(r"\bcheck\b.*\bagai\b", re.IGNORECASE),
    re.compile(r"\bfind\b.*\binfo\b", re.IGNORECASE),
]


def _wants_web_search(text: str) -> bool:
    """Detect if the user explicitly requests web search / live data."""
    if not text or len(text) < 5:
        return False
    lower = text.lower()
    if any(trigger in lower for trigger in _WEB_SEARCH_TRIGGERS):
        return True
    return any(p.search(text) for p in _WEB_SEARCH_PATTERNS)


async def _auto_web_search(query: str) -> str:
    """Fetch DuckDuckGo results and format as context block.

    Reuses the /api/search endpoint logic (chat_context.search_web).
    Returns formatted string or empty string on failure.
    """
    try:
        from chat_context import search_web

        result = await search_web(q=query, n=5)
        if result.get("results"):
            lines = []
            for i, r in enumerate(result["results"]):
                lines.append(
                    f"[{i + 1}] {r.get('title', '')}\n"
                    f"{r.get('snippet', '')}\n"
                    f"URL: {r.get('url', '')}"
                )
            return "\n\n".join(lines)
    except Exception:
        pass
    return ""


async def _prepare_chat_messages(
    payload: dict,
) -> tuple[list, dict | None, dict | None, str, list[str]]:
    """Firewall scan + WorldBase context. Returns (messages, firewall_meta, block_payload, user_text, context_blocks)."""
    firewall_meta = None
    messages = list(payload.get("messages", []))
    user_text = ""

    # Layer 2: Session Guard — multi-turn attack detection
    from firewall_bridge import _extract_user_text

    user_text = _extract_user_text(messages)
    session_id = (
        payload.get("chat_session_id") or payload.get("session_id") or "default"
    )
    if user_text:
        try:
            from session_guard import get_guard as get_session_guard

            sg = get_session_guard()
            session_result = sg.check_session(str(session_id), user_text)
            if session_result["action"] in ("block", "lock"):
                block_payload = {
                    "error": "Session guard triggered",
                    "detail": f"Session score {session_result['session_score']} — action: {session_result['action']}",
                    "guard": {"layer": "session", **session_result},
                }
                return messages, {"session_guard": session_result}, block_payload
            firewall_meta = (
                {"session_guard": session_result}
                if session_result["action"] == "warn"
                else None
            )
        except Exception:
            pass

    if payload.get("firewall"):
        from firewall_bridge import guard_chat_user_text

        if user_text:
            fw_meta, block_payload = await guard_chat_user_text(
                user_text,
                session_id=str(session_id) if session_id else None,
            )
            if block_payload:
                return messages, fw_meta, block_payload
            if fw_meta:
                firewall_meta = {**(firewall_meta or {}), **{"firewall": fw_meta}}

    search_results = payload.get("search_results", "")
    entity_context = payload.get("entity_context", "")
    want_ctx = bool(payload.get("context"))

    # Reuse user_text already extracted for enrichment (P1) and RAG routing
    user_q = user_text

    # Auto-web-search: if the user explicitly requests DuckDuckGo / web search
    # / live research but no pre-fetched search_results were sent by the frontend
    # (i.e. the 🔍 toggle was off), fetch them now.
    # When entity_context is present, use the entity title as the search query
    # (the user is asking about the selected target, not their literal words).
    if not search_results and user_q and _wants_web_search(user_q):
        search_query = user_q
        if entity_context:
            elines = entity_context.split("\n")
            entity_title = re.sub(r"^Entity:\s*", "", elines[0]).strip()
            area = ""
            date = ""
            cat = ""
            for line in elines[1:]:
                if line.startswith("AREA:"):
                    area = line.replace("AREA:", "").strip()
                elif line.startswith("DATE:"):
                    date = line.replace("DATE:", "").strip()
                elif line.startswith("CATEGORY:"):
                    cat = line.replace("CATEGORY:", "").strip()
            parts = [p for p in [entity_title, cat, area, date] if p and len(p) > 1]
            if parts:
                search_query = " ".join(parts)
            elif entity_title and len(entity_title) > 3:
                search_query = entity_title
        search_results = await _auto_web_search(search_query)

    # Pass query to build_chat_context for query-aware enrichment
    ctx = await build_chat_context(query=user_q) if want_ctx else ""

    rag_block = ""
    route_tag = ""
    agentic_trace_line = ""
    if want_ctx:
        from query_router import router_enabled, route_label

        if len(user_q) >= 8:
            if router_enabled():
                from rag_crag import build_routed_block

                routed = await build_routed_block(user_q)
                rag_block = routed.get("block", "")
                route_tag = route_label(routed.get("route", "vector"))
            else:
                from rag_crag import build_rag_crag_block

                rag_block = await build_rag_crag_block(user_q)

            # P3: Agentic chat loop — coverage → retrieve → corroboration
            from chat_agentic import (
                chat_agentic_enabled,
                run_chat_agentic_loop,
                format_agentic_trace_line,
            )

            if chat_agentic_enabled() and rag_block:
                rag_block, agentic_trace = await run_chat_agentic_loop(
                    user_q, rag_block
                )
                agentic_trace_line = format_agentic_trace_line(agentic_trace)

    # Layer 1: RAG Integrity Guard — scan context blocks for indirect injection
    rag_integrity_meta = None
    if rag_block:
        try:
            from rag_integrity import scan_rag_block as _scan_rag

            rag_block, rag_scan = _scan_rag(rag_block, source="rag_memory")
            if rag_scan["blocked"]:
                rag_integrity_meta = rag_scan
        except Exception:
            pass
    if ctx:
        try:
            from rag_integrity import scan_rag_block as _scan_rag

            ctx, ctx_scan = _scan_rag(ctx, source="briefing")
            if ctx_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or ctx_scan
        except Exception:
            pass
    if entity_context:
        try:
            from rag_integrity import scan_rag_block as _scan_rag

            entity_context, ent_scan = _scan_rag(entity_context, source="ftm_entity")
            if ent_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or ent_scan
        except Exception:
            pass
    if search_results:
        try:
            from rag_integrity import scan_rag_block as _scan_rag

            search_results, sr_scan = _scan_rag(search_results, source="web_search")
            if sr_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or sr_scan
        except Exception:
            pass
    if rag_integrity_meta:
        firewall_meta = {
            **(firewall_meta or {}),
            **{"rag_integrity": rag_integrity_meta},
        }

    provider = payload.get("provider", "ollama")
    host_label = "local Ollama" if provider == "ollama" else provider

    if ctx or entity_context or search_results or rag_block:
        parts = []
        context_blocks_for_budget: list[tuple[str, str]] = []
        if ctx:
            parts.append("=== INTERNAL TELEMETRY ===\n" + ctx)
            context_blocks_for_budget.append(("INTERNAL TELEMETRY", ctx))
        if rag_block:
            prefix = ""
            if route_tag:
                prefix = f"Retrieval mode: {route_tag}"
            if agentic_trace_line:
                prefix = (
                    (prefix + "\n" + agentic_trace_line).strip()
                    if prefix
                    else agentic_trace_line
                )
            if prefix:
                parts.append(f"{prefix}\n\n" + rag_block)
            else:
                parts.append(rag_block)
            context_blocks_for_budget.append(("RAG MEMORY", rag_block))
        if entity_context:
            parts.append("=== SELECTED TARGET (Globe) ===\n" + entity_context)
            context_blocks_for_budget.append(("SELECTED TARGET", entity_context))
        if search_results:
            parts.append("=== WEB SEARCH RESULTS ===\n" + search_results)
            context_blocks_for_budget.append(("WEB SEARCH RESULTS", search_results))
        entity_rules = (
            "\nENTITY PROTOCOL:\n"
            "- The SELECTED TARGET block is the ONLY source of data about that entity.\n"
            "- List the exact fields present in the block before analyzing.\n"
            "- Do NOT add details (dates, timestamps, coordinates, source names, URLs) "
            "not in the block.\n"
            "- Do NOT reference GDELT, GDACS, ReliefWeb, USGS, NIFC, WFCA, or any feed "
            "source unless its data appears in a context block above.\n"
            "- If no === INTERNAL TELEMETRY === block is present, you have NO live feed "
            "access. State this if asked.\n"
            if entity_context
            else ""
        )

        # P2: Synthesis directive + SATs + evidence weighting + red-team + actionable
        # Injected when query-enriched context is present
        synthesis_directive = ""
        has_enriched = "=== QUERY-ENRICHED CONTEXT ===" in (ctx or "")
        if has_enriched:
            try:
                from chat_context_enricher import get_query_event_type, get_query_intent

                event_type = get_query_event_type(user_q)
                intent = get_query_intent(user_q)
                synthesis_directive = _build_synthesis_directive(
                    event_type=event_type, intent=intent
                )
            except Exception:
                synthesis_directive = _build_synthesis_directive()

        # Build explicit list of available context blocks
        available_blocks = []
        if ctx:
            available_blocks.append("INTERNAL TELEMETRY")
        if rag_block:
            available_blocks.append("RAG MEMORY")
        if entity_context:
            available_blocks.append("SELECTED TARGET")
        if search_results:
            available_blocks.append("WEB SEARCH RESULTS")
        blocks_list = ", ".join(available_blocks) if available_blocks else "NONE"

        system_prompt_base = (
            f"You are WorldBase AI — {host_label} on a spatial intelligence workstation.\n\n"
            "ROLE: You are a RAW DATA INTERPRETER, not a creative writer. Your job is to "
            "interpret the data blocks below and answer the user's question. You are NOT "
            "an analyst who fills gaps with plausible-sounding narrative.\n\n"
            f"AVAILABLE CONTEXT BLOCKS: {blocks_list}\n"
            "If a block is not listed above, its data is NOT available. Do not reference it.\n\n"
            "CAPABILITIES (be honest if asked):\n"
            "- Direct internet: only when WEB SEARCH RESULTS block is present (operator "
            "enabled 🔍 or auto-search triggered). Not live browsing.\n"
            "- Live feeds: only when INTERNAL TELEMETRY block is present (CTX mode).\n"
            "- RAG MEMORY: indexed briefings/feeds when block is present.\n"
            "- Tools may query WorldBase APIs (situations, OSINT lookups, "
            "spatial_query for 'within X km of Y' questions).\n"
            "- GLOBE CONTROL: When the user asks to show, focus, or navigate to "
            "any place, call the focus_globe tool.\n\n"
            "PROTOCOL (follow exactly):\n"
            "1. ANSWER FIRST: 1-3 sentences in the user's language, based ONLY on "
            "data in the blocks above.\n"
            "2. SOURCE DISCIPLINE: Every factual claim must come from a listed block. "
            "If a claim is not supported by block data, say 'DATA GAP: [topic]'.\n"
            "3. NO FABRICATION: Do not invent URLs, dates, timestamps, coordinates, "
            "source names, statistics, or details not present in the blocks.\n"
            "4. NO SOURCE NAME-DROPPING: Do not mention GDELT, USGS, ReliefWeb, GDACS, "
            "NIFC, or any source unless its data is in a block above.\n"
            "5. HONESTY OVER CONFIDENCE: 'I don't have that data' is the correct answer "
            "when data is absent. Dry truth is valued over confident fabrication.\n"
            "6. CONCISE: Keep responses short. No padding with speculation or generic "
            "background knowledge.\n" + entity_rules + synthesis_directive
        )

        # P2+ Context budget: enforce token budget, provenance-based truncation,
        # and refuse path when retrieval quality is too low.
        system_content = ""
        budget_meta: dict[str, Any] | None = None
        try:
            import context_budget

            if context_blocks_for_budget:
                budget_result = context_budget.apply_budget(
                    system_prompt_base,
                    context_blocks_for_budget,
                )
                if not budget_result.ok:
                    block_payload = {
                        "error": "Context budget refused",
                        "detail": budget_result.refusal_reason,
                        "quality_score": budget_result.quality_score,
                    }
                    return (
                        messages,
                        firewall_meta,
                        block_payload,
                        user_text,
                        [t for _, t in context_blocks_for_budget],
                    )
                system_content, budget_meta = context_budget.format_context_from_result(
                    budget_result
                )
            else:
                system_content = system_prompt_base
        except Exception:
            system_content = system_prompt_base + "\n\n" + "\n\n".join(parts)

        system_msg = {
            "role": "system",
            "content": system_content,
        }
        messages = [system_msg] + messages
        if budget_meta:
            firewall_meta = {**(firewall_meta or {}), **budget_meta}
    elif not any(m.get("role") == "system" for m in messages):
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are WorldBase AI ({host_label}). No live feeds or web search are "
                    "attached to this message unless the operator enables CTX or 🔍. "
                    "Answer honestly and concisely in the user's language. "
                    "Do not invent URLs or claim internet access you do not have. "
                    "If the user asks to show or navigate to a place, call focus_globe."
                ),
            }
        ] + messages

    # Collect context blocks for claim auditor
    context_blocks: list[str] = []
    if ctx:
        context_blocks.append(ctx)
    if rag_block:
        context_blocks.append(rag_block)
    if entity_context:
        context_blocks.append(entity_context)
    if search_results:
        context_blocks.append(search_results)

    return messages, firewall_meta, None, user_text, context_blocks


# Known feed/data source names that must only appear if their data is in context
_KNOWN_SOURCES = [
    "GDELT",
    "USGS",
    "ReliefWeb",
    "GDACS",
    "NIFC",
    "WFCA",
    "AISStream",
    "OpenSky",
    "NewsData",
    "EONET",
    "FIRMS",
    "Sentinel",
    "CAMS",
    "HDX",
    "OCHA",
    "ENTSO-E",
    "SMARD",
    "Blitzortung",
    "Ransomware.live",
    "RansomLook",
    "USA Today",
    "Gannett",
    "Reuters",
    "AP News",
    "BBC",
    "DuckDuckGo",
]

# Patterns for specific fabricated details
_URL_RE = re.compile(r"https?://[^\s\)\]]+", re.IGNORECASE)
_DATE_TIME_RE = re.compile(
    r"\b\d{1,2}:\d{2}\s*(?:AM|PM|UTC|EDT|EST|PDT|PST)?\b", re.IGNORECASE
)


def _claim_auditor(
    response_text: str, context_blocks: list[str]
) -> tuple[str, dict | None]:
    """Post-generation claim verification.

    Checks the LLM response for source names, URLs, and timestamps that
    do not appear in any context block. If found, appends a verification
    warning to the response. Does NOT modify the response body — only appends.
    """
    if not response_text or not context_blocks:
        return response_text, None

    combined_ctx = " ".join(context_blocks)
    ctx_lower = combined_ctx.lower()
    resp_lower = response_text.lower()

    violations: list[str] = []

    # Check 1: Source names not in context
    for src in _KNOWN_SOURCES:
        if src.lower() in resp_lower and src.lower() not in ctx_lower:
            violations.append(f"Source '{src}' referenced but not in context blocks")

    # Check 2: URLs not in context (extract all URLs from response, check if in context)
    resp_urls = set(_URL_RE.findall(response_text))
    for url in resp_urls:
        if url.lower() not in ctx_lower:
            violations.append(f"URL '{url}' not found in context blocks")

    # Check 3: Specific times (e.g. "8:03 AM") not in context
    resp_times = set(_DATE_TIME_RE.findall(response_text))
    for ts in resp_times:
        if ts.lower() not in ctx_lower:
            violations.append(f"Timestamp '{ts}' not found in context blocks")

    if not violations:
        return response_text, None

    warning = "\n\n---\n⚠ **CLAIM AUDITOR WARNING**: The following claims could not be verified against context data:\n"
    for v in violations[:10]:
        warning += f"- {v}\n"
    warning += (
        "\nThese may be fabricated. Verify with 🔍 web search or CTX telemetry mode.\n"
        "---\n"
    )

    meta = {
        "claim_auditor": {
            "violations": violations[:10],
            "violation_count": len(violations),
        }
    }
    return response_text + warning, meta


def _apply_output_guard(
    response_text: str, user_text: str = ""
) -> tuple[str, dict | None]:
    """Layer 3: Output Guard — scan LLM response for leaks/echo before returning."""
    try:
        from output_guard import check_output

        result = check_output(response_text, user_text)
        if result["blocked"]:
            return result["sanitized"], {"output_guard": result}
    except Exception:
        pass
    return response_text, None


@router.post("/api/chat")
@rate_limit_general()
async def chat_proxy(
    request: Request, payload: dict, api_key: str = Depends(verify_api_key)
):
    """Proxy chat requests to LLM providers. Supports SSE streaming.

    Providers: ollama (default), openai, anthropic, groq, openrouter, nvidia.
    Set payload['context'] = True to inject live WorldBase state as a system message.
    Set payload['firewall'] = True to route user messages through the LLM-Security-Firewall.
    """
    from ollama_config import chat_timeout, keep_alive
    import chat_routing

    opts = chat_routing.resolve_chat_options(
        payload,
        default_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
    )
    provider = opts["provider"]
    model = opts["model"]
    use_stream = opts["use_stream"]
    use_tools = opts["use_tools"]
    force_fast = opts["force_fast"]

    def _ollama_chat_body(model_name: str, messages: list, *, stream: bool) -> dict:
        return chat_routing.build_ollama_chat_body(
            model_name,
            messages,
            stream=stream,
            force_fast=force_fast,
            keep_alive=keep_alive(),
        )

    # ------------------------------------------------------------------
    # OLLAMA (local, default)
    # ------------------------------------------------------------------
    if provider == "ollama":
        if use_stream:

            async def ollama_stream():
                yield f"data: {json.dumps({'status': 'preparing'})}\n\n"
                (
                    messages,
                    firewall_meta,
                    block_msg,
                    user_text,
                    context_blocks,
                ) = await _prepare_chat_messages(payload)
                if block_msg:
                    yield f"data: {json.dumps(block_msg)}\n\n"
                    return
                if firewall_meta:
                    yield f"data: {json.dumps({'firewall_result': firewall_meta})}\n\n"
                last_err = None
                ollama_timeout = chat_timeout()
                for host in OLLAMA_HOSTS:
                    host = host.strip()
                    try:
                        if use_tools:
                            yield f"data: {json.dumps({'status': 'tools'})}\n\n"
                            async for event in chat_tools.stream_ollama_with_tools(
                                host, model, messages, max_rounds=4
                            ):
                                if event.get("token"):
                                    yield f"data: {json.dumps({'token': event['token']})}\n\n"
                                elif event.get("status"):
                                    yield f"data: {json.dumps(event)}\n\n"
                                elif event.get("client_action"):
                                    yield f"data: {json.dumps({'client_action': event['client_action']})}\n\n"
                                elif event.get("done"):
                                    yield f"data: {json.dumps({'done': True})}\n\n"
                            return
                        yield f"data: {json.dumps({'status': 'generating'})}\n\n"
                        url = f"http://{host}/api/chat"
                        chat_body = _ollama_chat_body(model, messages, stream=True)
                        async with httpx.AsyncClient(timeout=ollama_timeout) as client:
                            async with client.stream(
                                "POST",
                                url,
                                json=chat_body,
                            ) as r:
                                r.raise_for_status()
                                async for line in r.aiter_lines():
                                    if not line.strip():
                                        continue
                                    try:
                                        data = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    if data.get("done"):
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    content = data.get("message", {}).get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                        return
                    except httpx.ConnectError:
                        last_err = f"Ollama not reachable at {host}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
                yield f"data: {json.dumps({'error': last_err or 'Ollama not reachable'})}\n\n"

            return StreamingResponse(ollama_stream(), media_type="text/event-stream")

        (
            messages,
            firewall_meta,
            block_msg,
            user_text,
            context_blocks,
        ) = await _prepare_chat_messages(payload)
        if block_msg:
            return block_msg

        last_err = None
        for host in OLLAMA_HOSTS:
            host = host.strip()
            try:
                if use_tools:
                    final_msgs, actions = await chat_tools.run_ollama_with_tools(
                        host, model, messages, max_rounds=4
                    )
                    text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                    text, og_meta = _apply_output_guard(text, user_text)
                    text, ca_meta = _claim_auditor(text, context_blocks)
                    audit_meta = og_meta or {}
                    if ca_meta:
                        audit_meta = {**audit_meta, **ca_meta}
                    return {
                        "message": {"role": "assistant", "content": text},
                        "client_actions": actions,
                        "done": True,
                        **(
                            {"firewall_result": {**(firewall_meta or {}), **audit_meta}}
                            if audit_meta
                            else {}
                        ),
                    }
                url = f"http://{host}/api/chat"
                async with httpx.AsyncClient(timeout=chat_timeout()) as client:
                    r = await client.post(
                        url,
                        json=_ollama_chat_body(model, messages, stream=False),
                    )
                    r.raise_for_status()
                    data = r.json()
                    # Layer 3: Output Guard on non-streaming Ollama response
                    resp_text = (data.get("message") or {}).get("content", "")
                    if resp_text:
                        resp_text, og_meta = _apply_output_guard(resp_text, user_text)
                        resp_text, ca_meta = _claim_auditor(resp_text, context_blocks)
                        data.setdefault("message", {})["content"] = resp_text
                        audit_meta = og_meta or {}
                        if ca_meta:
                            audit_meta = {**audit_meta, **ca_meta}
                        if audit_meta:
                            data["firewall_result"] = {
                                **(firewall_meta or {}),
                                **audit_meta,
                            }
                    return data
            except httpx.ConnectError:
                last_err = f"Ollama not reachable at {host}"
                continue
            except httpx.HTTPStatusError as e:
                detail = ""
                try:
                    detail = e.response.text[:200]
                except Exception:
                    pass
                status = e.response.status_code
                if status == 404:
                    return {
                        "error": f"Model '{model}' not found. Run: ollama pull {model}",
                        "host": host,
                        "status": status,
                    }
                return {
                    "error": f"Ollama HTTP {status} at {host}",
                    "detail": detail,
                }
            except Exception as e:
                last_err = str(e)
                continue

        return {
            "error": last_err or "Ollama not running. Install from ollama.com",
            "hosts_tried": OLLAMA_HOSTS,
        }

    # ------------------------------------------------------------------
    # EXTERNAL PROVIDERS (OpenAI-compatible or Anthropic)
    # ------------------------------------------------------------------
    (
        messages,
        firewall_meta,
        block_msg,
        user_text,
        context_blocks,
    ) = await _prepare_chat_messages(payload)
    if block_msg:
        if use_stream:
            return StreamingResponse(
                (f"data: {json.dumps(block_msg)}\n\n" async for _ in [1]),
                media_type="text/event-stream",
            )
        return block_msg

    api_keys = (
        payload.get("api_keys") if isinstance(payload.get("api_keys"), dict) else None
    )
    api_base_urls = (
        payload.get("api_base_urls")
        if isinstance(payload.get("api_base_urls"), dict)
        else None
    )

    if api_base_urls:
        for prov, raw in api_base_urls.items():
            if not isinstance(raw, str) or not raw.strip():
                continue
            env_name = chat_routing.PROVIDER_ENV_BASE_URLS.get(prov)
            env_base = os.getenv(env_name) if env_name else None
            try:
                chat_routing.assert_safe_provider_base_url(prov, raw, env_base=env_base)
            except ValueError as exc:
                return {"error": str(exc), "provider": prov}

    PROVIDER_CONFIG = {
        "openai": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "openai",
                    api_base_urls,
                    os.getenv("OPENAI_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["openai"],
                )
            ),
            "key": chat_routing.select_api_key(
                "openai", api_keys, os.getenv("OPENAI_API_KEY")
            ),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "groq": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "groq",
                    api_base_urls,
                    os.getenv("GROQ_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["groq"],
                )
            ),
            "key": chat_routing.select_api_key(
                "groq", api_keys, os.getenv("GROQ_API_KEY")
            ),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "openrouter": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "openrouter",
                    api_base_urls,
                    os.getenv("OPENROUTER_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["openrouter"],
                )
            ),
            "key": chat_routing.select_api_key(
                "openrouter", api_keys, os.getenv("OPENROUTER_API_KEY")
            ),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "nvidia": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "nvidia",
                    api_base_urls,
                    os.getenv("NVIDIA_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["nvidia"],
                )
            ),
            "key": chat_routing.select_api_key(
                "nvidia", api_keys, os.getenv("NVIDIA_API_KEY")
            ),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
    }

    if provider in PROVIDER_CONFIG:
        cfg = PROVIDER_CONFIG[provider]
        api_key = cfg["key"]
        if not api_key:
            return {
                "error": (
                    f"No API key for {provider}. Add it in the HUD settings "
                    f"or set {provider.upper()}_API_KEY in .env"
                ),
                "provider": provider,
            }

        headers = {
            "Content-Type": "application/json",
            cfg["header"]: cfg["prefix"] + api_key,
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://worldbase.local"
            headers["X-Title"] = "WorldBase"

        body = {
            "model": model,
            "messages": messages,
            "stream": use_stream,
            "temperature": 0.15 if provider == "nvidia" else 0.7,
            "top_p": 0.4 if provider == "nvidia" else 0.9,
            "max_tokens": (1024 if force_fast else 2048)
            if provider == "nvidia"
            else (2048 if force_fast else 8192),
        }

        # ----- Tool-calling loop (full WorldBase access for cloud models) -----
        if use_tools:
            if use_stream:

                async def openai_tools_stream():
                    try:
                        async for event in chat_tools.stream_openai_with_tools(
                            cfg["url"], headers, model, messages, max_rounds=4
                        ):
                            yield f"data: {json.dumps(event)}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'error': f'{provider} tool stream error: {e}'})}\n\n"

                return StreamingResponse(
                    openai_tools_stream(), media_type="text/event-stream"
                )

            try:
                final_msgs, actions = await chat_tools.run_openai_with_tools(
                    cfg["url"], headers, model, messages, max_rounds=4
                )
                text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                text, og_meta = _apply_output_guard(text, user_text)
                text, ca_meta = _claim_auditor(text, context_blocks)
                audit_meta = og_meta or {}
                if ca_meta:
                    audit_meta = {**audit_meta, **ca_meta}
                return {
                    "message": {"role": "assistant", "content": text},
                    "client_actions": actions,
                    "done": True,
                    "provider": provider,
                    **(
                        {"firewall_result": {**(firewall_meta or {}), **audit_meta}}
                        if audit_meta
                        else {}
                    ),
                }
            except httpx.HTTPStatusError as e:
                return {
                    "error": f"{provider} HTTP {e.response.status_code}",
                    "detail": e.response.text[:300],
                    "provider": provider,
                }
            except Exception as e:
                return {
                    "error": f"{provider} tool request failed: {e}",
                    "provider": provider,
                }

        if use_stream:

            async def openai_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream(
                            "POST", cfg["url"], headers=headers, json=body
                        ) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    if payload_text.strip() == "[DONE]":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    delta = (chunk.get("choices") or [{}])[0].get(
                                        "delta", {}
                                    )
                                    content = (
                                        delta.get("content")
                                        or delta.get("reasoning_content")
                                        or ""
                                    )
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'{provider} stream error: {e}'})}\n\n"

            return StreamingResponse(openai_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(cfg["url"], headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                choice = data.get("choices", [{}])[0]
                msg = choice.get("message", {})
                resp_text = (
                    msg.get("content")
                    or msg.get("reasoning_content")
                    or choice.get("text", "")
                    or ""
                )
                resp_text, og_meta = _apply_output_guard(resp_text, user_text)
                resp_text, ca_meta = _claim_auditor(resp_text, context_blocks)
                audit_meta = og_meta or {}
                if ca_meta:
                    audit_meta = {**audit_meta, **ca_meta}
                return {
                    "message": {
                        "role": "assistant",
                        "content": resp_text,
                    },
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                    **(
                        {"firewall_result": {**(firewall_meta or {}), **audit_meta}}
                        if audit_meta
                        else {}
                    ),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"{provider} HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"{provider} request failed: {e}", "provider": provider}

    # ------------------------------------------------------------------
    # ANTHROPIC (Messages API, non-OpenAI format)
    # ------------------------------------------------------------------
    if provider == "anthropic":
        api_key = chat_routing.select_api_key(
            "anthropic", api_keys, os.getenv("ANTHROPIC_API_KEY")
        )
        if not api_key:
            return {
                "error": (
                    "No API key for anthropic. Add it in the HUD settings "
                    "or set ANTHROPIC_API_KEY in .env"
                ),
                "provider": provider,
            }

        url = chat_routing.anthropic_messages_url(
            chat_routing.select_base_url(
                "anthropic",
                api_base_urls,
                os.getenv("ANTHROPIC_BASE_URL"),
                chat_routing.DEFAULT_BASE_URLS["anthropic"],
            )
        )
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        # Extract system message if present
        system_text = ""
        chat_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text = m.get("content", "")
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": 4096,
            "stream": use_stream,
        }
        if system_text:
            body["system"] = system_text

        if use_stream:

            async def anthropic_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream(
                            "POST", url, headers=headers, json=body
                        ) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    t = chunk.get("type", "")
                                    if t == "content_block_delta":
                                        text = chunk.get("delta", {}).get("text", "")
                                        if text:
                                            yield f"data: {json.dumps({'token': text})}\n\n"
                                    elif t == "message_stop":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'anthropic stream error: {e}'})}\n\n"

            return StreamingResponse(anthropic_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                content_blocks = data.get("content", [])
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")
                text, og_meta = _apply_output_guard(text, user_text)
                return {
                    "message": {"role": "assistant", "content": text},
                    "done": True,
                    **(
                        {"firewall_result": {**(firewall_meta or {}), **og_meta}}
                        if og_meta
                        else {}
                    ),
                    "provider": provider,
                    "model": data.get("model"),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"anthropic HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"anthropic request failed: {e}", "provider": provider}

    return {
        "error": f"Unknown provider '{provider}'",
        "available": ["ollama", "openai", "anthropic", "groq", "openrouter"],
    }


@router.get("/api/providers")
def list_providers():
    """Catalog of LLM providers.

    All providers are listed so the operator can configure a key in the HUD even
    when ``.env`` has none. ``key_set`` reports whether an ``.env`` key exists;
    ``supports_tools`` flags providers wired to the WorldBase tool loop.
    """
    catalog = [
        {
            "id": "ollama",
            "name": "Ollama (Local)",
            "models": [],
            "requires_key": False,
            "env_key": None,
            "env_base": None,
            "default_base_url": None,
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
            "requires_key": True,
            "env_key": "OPENAI_API_KEY",
            "env_base": "OPENAI_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["openai"],
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "models": [
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
                "claude-3-haiku-20240307",
            ],
            "requires_key": True,
            "env_key": "ANTHROPIC_API_KEY",
            "env_base": "ANTHROPIC_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["anthropic"],
        },
        {
            "id": "groq",
            "name": "Groq",
            "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
            "requires_key": True,
            "env_key": "GROQ_API_KEY",
            "env_base": "GROQ_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["groq"],
        },
        {
            "id": "openrouter",
            "name": "OpenRouter",
            "models": [
                "openai/gpt-4o",
                "anthropic/claude-3.5-sonnet",
                "meta-llama/llama-3.3-70b-instruct",
            ],
            "requires_key": True,
            "env_key": "OPENROUTER_API_KEY",
            "env_base": "OPENROUTER_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["openrouter"],
        },
        {
            "id": "nvidia",
            "name": "NVIDIA NIM",
            "models": [
                "qwen/qwen3.5-122b-a10b",
                "qwen/qwen3.5-397b-a17b",
                "deepseek-ai/deepseek-v4-flash",
            ],
            "requires_key": True,
            "env_key": "NVIDIA_API_KEY",
            "env_base": "NVIDIA_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["nvidia"],
        },
    ]
    providers = []
    for p in catalog:
        env_key_name = p.pop("env_key")
        env_base_name = p.pop("env_base")
        providers.append(
            {
                **p,
                "key_set": bool(os.getenv(env_key_name)) if env_key_name else False,
                "base_url_set": bool(os.getenv(env_base_name))
                if env_base_name
                else False,
                "supports_tools": chat_routing.provider_supports_tools(p["id"]),
            }
        )
    default_provider = os.getenv("WORLDBASE_CHAT_PROVIDER", "ollama")
    default_model = os.getenv(
        "WORLDBASE_CHAT_MODEL", os.getenv("OLLAMA_MODEL", "qwen3:8b")
    )
    if default_provider not in chat_routing.SUPPORTED_PROVIDERS:
        default_provider = "ollama"
        default_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    return {
        "providers": providers,
        "default_provider": default_provider,
        "default_model": default_model,
    }
