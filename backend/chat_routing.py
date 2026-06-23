"""Pure chat routing helpers — characterization tests before main.py split (Phase 1)."""

from __future__ import annotations

from typing import Any

from urllib.parse import urlparse

SUPPORTED_PROVIDERS = frozenset({"ollama", "openai", "anthropic", "groq", "openrouter"})

PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

PROVIDER_ENV_BASE_URLS = {
    "openai": "OPENAI_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "groq": "GROQ_BASE_URL",
    "openrouter": "OPENROUTER_BASE_URL",
}

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


_OPENAI_COMPATIBLE = frozenset({"openai", "groq", "openrouter"})

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def resolve_chat_options(payload: dict[str, Any], *, default_model: str) -> dict[str, Any]:
    """Mirror /api/chat provider + tool flags (no I/O)."""
    provider = payload.get("provider", "ollama")
    model = payload.get("model", default_model)
    use_stream = bool(payload.get("stream", False))
    # Tools default ON for Ollama; for other providers the UI sends an explicit flag.
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


def provider_supports_tools(provider: str) -> bool:
    """Providers with a WorldBase tool-calling loop (Ollama + OpenAI-compatible)."""
    return provider == "ollama" or provider in _OPENAI_COMPATIBLE


def select_api_key(provider: str, api_keys: dict[str, Any] | None, env_key: str | None) -> str | None:
    """Prefer a UI-supplied key for this provider, else the .env key.

    ``api_keys`` is an optional ``{provider: key}`` map from the request body so
    the operator can configure keys in the HUD without editing ``.env``.
    """
    if api_keys:
        candidate = api_keys.get(provider)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return env_key


def select_base_url(
    provider: str,
    base_urls: dict[str, Any] | None,
    env_base: str | None,
    default_base: str,
) -> str:
    """Resolve provider base URL: HUD override → .env → catalog default."""
    if base_urls:
        candidate = base_urls.get(provider)
        if isinstance(candidate, str) and candidate.strip():
            return assert_safe_provider_base_url(provider, candidate, env_base=env_base)
    if env_base and env_base.strip():
        return normalize_base_url(env_base)
    return normalize_base_url(default_base)


def normalize_base_url(raw: str) -> str:
    return raw.strip().rstrip("/")


def _hostname_from_url(url: str) -> str | None:
    host = urlparse(normalize_base_url(url)).hostname
    return host.lower() if host else None


def allowed_hosts_for_provider(provider: str, env_base: str | None) -> set[str]:
    hosts: set[str] = set()
    default = DEFAULT_BASE_URLS.get(provider)
    if default:
        h = _hostname_from_url(default)
        if h:
            hosts.add(h)
    if env_base and env_base.strip():
        h = _hostname_from_url(env_base)
        if h:
            hosts.add(h)
    return hosts


def assert_safe_provider_base_url(provider: str, url: str, *, env_base: str | None = None) -> str:
    """Reject HUD-supplied base URLs that would SSRF or exfiltrate server keys."""
    u = normalize_base_url(url)
    parsed = urlparse(u)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not scheme or not host:
        raise ValueError("Invalid provider base URL")
    if host in _LOOPBACK_HOSTS:
        if scheme not in ("http", "https"):
            raise ValueError("Loopback provider base URL must use http or https")
        return u
    if scheme != "https":
        raise ValueError("Provider base URL must use HTTPS")
    if host not in allowed_hosts_for_provider(provider, env_base):
        raise ValueError(f"Base URL host not allowed for provider {provider}")
    return u


def openai_chat_completions_url(base_or_full: str) -> str:
    """Accept ``https://host/v1`` or a full ``.../chat/completions`` endpoint."""
    u = normalize_base_url(base_or_full)
    if u.endswith("/chat/completions"):
        return u
    return f"{u}/chat/completions"


def anthropic_messages_url(base_or_full: str) -> str:
    """Accept ``https://host/v1`` or a full ``.../messages`` endpoint."""
    u = normalize_base_url(base_or_full)
    if u.endswith("/messages"):
        return u
    return f"{u}/messages"


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
