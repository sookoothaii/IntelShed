"""Smart Model Router — query complexity classifier + provider fallback chain.

When WORLDBASE_SMART_ROUTER=1 and the user has not explicitly chosen a provider,
this module classifies the query complexity and selects the best provider+model
combination. If the selected provider fails (timeout, auth error, rate limit),
it falls back through a configurable chain.

Fallback chain (default): NVIDIA NIM -> Groq -> OpenRouter -> Ollama

Zero VRAM — pure rule-based classification, no model inference needed.
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def smart_router_enabled() -> bool:
    return os.getenv("WORLDBASE_SMART_ROUTER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def cloud_ai_enabled() -> bool:
    """WORLDBASE_CLOUD_AI gates whether cloud providers are auto-selected."""
    return os.getenv("WORLDBASE_CLOUD_AI", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Complexity classifier — rule-based, 0 VRAM
# ---------------------------------------------------------------------------

_COMPLEXITY_KEYWORDS_ANALYTICAL = {
    "analyze",
    "analysis",
    "assess",
    "assessment",
    "compare",
    "comparison",
    "correlate",
    "correlation",
    "forecast",
    "predict",
    "implication",
    "scenario",
    "hypothetical",
    "strategy",
    "strategic",
    "evaluate",
    "investigate",
    "derive",
    "infer",
    "synthesize",
    "synthesis",
    "red team",
    "devil's advocate",
    "competing hypothesis",
    "ach",
    "analyse",
    "bewerte",
    "korreliere",
    "prognose",
    "vorhersage",
    "implikation",
    "szenario",
    "strategie",
    "untersuche",
}

_COMPLEXITY_KEYWORDS_FACTUAL = {
    "what is",
    "who is",
    "where is",
    "when did",
    "how many",
    "list",
    "show me",
    "find",
    "lookup",
    "count",
    "status",
    "define",
    "definition",
    "meaning",
    "translate",
    "was ist",
    "wer ist",
    "wo ist",
    "wann",
    "wie viele",
    "liste",
    "zeige",
    "finde",
    "anzahl",
    "definition",
}

_COMPLEXITY_KEYWORDS_SIMPLE = {
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "ok",
    "yes",
    "no",
    "help",
    "ping",
    "test",
    "clear",
    "reset",
    "stop",
    "hallo",
    "danke",
    "ja",
    "nein",
    "hilfe",
    "stopp",
}

_MULTI_SENTENCE_THRESHOLD = 120  # chars — long queries lean analytical
_QUESTION_MARK_THRESHOLD = 3  # multiple questions lean analytical


def classify_complexity(query: str) -> str:
    """Classify query complexity: 'simple', 'factual', or 'analytical'.

    Rule-based heuristics:
    - Greeting/short commands -> simple
    - Factoid questions (what/who/where/when/how many) -> factual
    - Analysis/assessment/forecast keywords or long multi-question -> analytical
    - Default: factual
    """
    if not query or not query.strip():
        return "simple"

    lower = query.lower().strip()

    # Simple: very short or greeting keywords
    if len(lower) < 15 and any(
        lower.startswith(k) for k in _COMPLEXITY_KEYWORDS_SIMPLE
    ):
        return "simple"
    if lower in _COMPLEXITY_KEYWORDS_SIMPLE:
        return "simple"

    # Analytical: keyword match
    for kw in _COMPLEXITY_KEYWORDS_ANALYTICAL:
        if kw in lower:
            return "analytical"

    # Analytical: long query with multiple question marks
    if len(query) > _MULTI_SENTENCE_THRESHOLD:
        qmark_count = query.count("?")
        if qmark_count >= _QUESTION_MARK_THRESHOLD:
            return "analytical"

    # Factual: factoid keywords
    for kw in _COMPLEXITY_KEYWORDS_FACTUAL:
        if kw in lower:
            return "factual"

    # Default: if short, simple; if long, analytical
    if len(lower) < 40:
        return "simple"
    if len(lower) > 200:
        return "analytical"
    return "factual"


# ---------------------------------------------------------------------------
# Provider availability check
# ---------------------------------------------------------------------------


def _provider_has_key(provider: str) -> bool:
    """Check if a provider has an API key configured (env or HUD-supplied)."""
    from chat_routing import PROVIDER_ENV_KEYS

    env_key = PROVIDER_ENV_KEYS.get(provider)
    if not env_key:
        return provider == "ollama"  # ollama needs no key
    return bool(os.getenv(env_key))


def available_providers(api_keys: dict[str, Any] | None = None) -> list[str]:
    """Return ordered list of providers that have credentials configured."""
    # Check HUD-supplied keys first
    hud_keys = set()
    if api_keys and isinstance(api_keys, dict):
        for prov, key in api_keys.items():
            if isinstance(key, str) and key.strip():
                hud_keys.add(prov)

    chain = get_fallback_chain()
    result = []
    for prov in chain:
        if prov == "ollama":
            result.append(prov)  # always available locally
        elif prov in hud_keys or _provider_has_key(prov):
            result.append(prov)
    return result


# ---------------------------------------------------------------------------
# Fallback chain configuration
# ---------------------------------------------------------------------------

_DEFAULT_FALLBACK_CHAIN = ["nvidia", "groq", "openrouter", "ollama"]

# Complexity -> preferred provider mapping
_COMPLEXITY_PROVIDER_MAP: dict[str, list[str]] = {
    "simple": ["ollama"],  # simple queries always go local
    "factual": ["groq", "nvidia", "ollama"],  # fast factual lookups
    "analytical": ["nvidia", "openrouter", "ollama"],  # heavy reasoning
}


def get_fallback_chain() -> list[str]:
    """Parse WORLDBASE_SMART_ROUTER_CHAIN env or return default."""
    raw = os.getenv("WORLDBASE_SMART_ROUTER_CHAIN", "")
    if raw.strip():
        parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
        if parts:
            return parts
    return list(_DEFAULT_FALLBACK_CHAIN)


def select_provider(
    query: str,
    *,
    api_keys: dict[str, Any] | None = None,
    explicit_provider: str | None = None,
) -> tuple[str, str, str]:
    """Select provider, model, and complexity for a query.

    Returns (provider, model, complexity).

    If explicit_provider is set (user chose in HUD), respect it.
    If cloud AI is disabled, always return ollama.
    """
    complexity = classify_complexity(query)

    # Respect explicit user choice
    if explicit_provider and explicit_provider != "auto":
        return explicit_provider, "", complexity

    # Cloud AI gate
    if not cloud_ai_enabled():
        return "ollama", "", complexity

    # Get complexity-ordered preference
    preferred = _COMPLEXITY_PROVIDER_MAP.get(complexity, _DEFAULT_FALLBACK_CHAIN)
    avail = available_providers(api_keys)

    # Pick first available from complexity preference
    for prov in preferred:
        if prov in avail:
            model = _default_model_for(prov)
            return prov, model, complexity

    # Fallback: first available from full chain
    for prov in avail:
        model = _default_model_for(prov)
        return prov, model, complexity

    # Last resort: ollama
    return "ollama", "", complexity


def _default_model_for(provider: str) -> str:
    """Default model per provider (can be overridden via env)."""
    env_map = {
        "nvidia": "WORLDBASE_NVIDIA_MODEL",
        "groq": "WORLDBASE_GROQ_MODEL",
        "openrouter": "WORLDBASE_OPENROUTER_MODEL",
        "openai": "WORLDBASE_OPENAI_MODEL",
        "anthropic": "WORLDBASE_ANTHROPIC_MODEL",
        "ollama": "OLLAMA_MODEL",
    }
    env_key = env_map.get(provider, "OLLAMA_MODEL")
    defaults = {
        "nvidia": "stepfun-ai/step-3.7-flash",
        "groq": "llama-3.3-70b-versatile",
        "openrouter": "meta-llama/llama-3.3-70b-instruct",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
        "ollama": "qwen3:8b",
    }
    return os.getenv(env_key, defaults.get(provider, "qwen3:8b"))


# ---------------------------------------------------------------------------
# Fallback execution helper
# ---------------------------------------------------------------------------


class FallbackResult:
    """Result of a fallback attempt."""

    __slots__ = ("provider", "model", "response", "error", "attempted")

    def __init__(
        self,
        provider: str,
        model: str,
        response: dict | None = None,
        error: str | None = None,
        attempted: list[str] | None = None,
    ):
        self.provider = provider
        self.model = model
        self.response = response
        self.error = error
        self.attempted = attempted or []


def should_fallback(error_response: dict | str) -> bool:
    """Determine if an error response should trigger fallback.

    Fallback on: timeout, 429 (rate limit), 500-503 (server errors),
    auth errors (401/403), connection errors.
    Do NOT fallback on: 400 (bad request), 404 (model not found),
    content policy violations, or successful responses.
    """
    if isinstance(error_response, str):
        lower = error_response.lower()
        return any(
            kw in lower
            for kw in (
                "timeout",
                "timed out",
                "connect error",
                "connection refused",
                "rate limit",
                "too many requests",
                "502",
                "503",
                "service unavailable",
            )
        )

    if isinstance(error_response, dict):
        error_str = str(error_response.get("error", ""))
        detail_str = str(error_response.get("detail", ""))
        combined = (error_str + " " + detail_str).lower()

        # Don't fallback on client errors that won't change with a different provider
        if "not found" in combined and "model" in combined:
            return False
        if "context budget" in combined:
            return False
        if "session guard" in combined:
            return False
        if "firewall" in combined and "blocked" in combined:
            return False

        # Fallback on transient/retryable errors
        fallback_keywords = [
            "timeout",
            "timed out",
            "connect error",
            "connection refused",
            "rate limit",
            "too many requests",
            "429",
            "500",
            "502",
            "503",
            "service unavailable",
            "bad gateway",
            "internal server error",
            "overloaded",
        ]
        return any(kw in combined for kw in fallback_keywords)

    return False


def next_fallback_provider(
    current: str,
    attempted: list[str],
    api_keys: dict[str, Any] | None = None,
) -> str | None:
    """Return the next provider to try after current fails.

    Returns None if no more providers in the chain.
    """
    chain = get_fallback_chain()
    avail = available_providers(api_keys)

    # Build ordered list: providers after current in chain, that are available
    try:
        idx = chain.index(current)
    except ValueError:
        idx = -1

    for prov in chain[idx + 1 :]:
        if prov not in attempted and prov in avail:
            return prov

    # If we exhausted chain after current, try any remaining available
    for prov in avail:
        if prov not in attempted and prov != current:
            return prov

    return None
