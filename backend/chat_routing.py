"""Pure chat routing helpers — characterization tests before main.py split (Phase 1)."""

from __future__ import annotations

from typing import Any

SUPPORTED_PROVIDERS = frozenset({"ollama", "openai", "anthropic", "groq", "openrouter"})

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def resolve_chat_options(payload: dict[str, Any], *, default_model: str) -> dict[str, Any]:
    """Mirror /api/chat provider + tool flags (no I/O)."""
    provider = payload.get("provider", "ollama")
    model = payload.get("model", default_model)
    use_stream = bool(payload.get("stream", False))
    use_tools = payload.get("use_tools", provider == "ollama")
    force_fast = bool(payload.get("force_fast") or payload.get("entity_context"))
    if force_fast:
        use_tools = False
    return {
        "provider": provider,
        "model": model,
        "use_stream": use_stream,
        "use_tools": bool(use_tools),
        "force_fast": force_fast,
    }


def provider_requires_api_key(provider: str) -> bool:
    return provider in PROVIDER_ENV_KEYS


def build_ollama_chat_body(
    model_name: str,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
    force_fast: bool,
    keep_alive: str | int,
) -> dict[str, Any]:
    """Mirror nested _ollama_chat_body in main.py chat_proxy."""
    body: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": stream,
        "keep_alive": keep_alive,
    }
    if "qwen3" in model_name.lower():
        body["think"] = False
    if force_fast:
        body["options"] = {"num_predict": 260, "temperature": 0.4}
    return body
