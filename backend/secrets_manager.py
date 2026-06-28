"""Secret management abstraction — reads in priority order: env → .env → vault.

When ``WORLDBASE_SECRET_BACKEND=env`` (default), this is a thin wrapper around
``os.getenv`` with optional ``.env`` fallback. When set to ``azure_keyvault``,
``aws_secretsmanager``, or ``hashicorp_vault``, the corresponding SDK is
lazy-imported and queried. All vault paths are fail-soft: if the SDK is not
installed or the vault is unreachable, the env/``.env`` value is returned.

Design goals:
- Zero overhead when disabled (default) — no extra imports, no I/O.
- Drop-in replacement for ``os.getenv`` in ``config.py`` and other modules.
- No secrets are ever logged or exposed in error messages.
- Thread-safe, process-wide singleton.

Usage::

    from secrets_manager import get_secret

    api_key = get_secret("WORLDBASE_API_KEY", "")
    cesium_token = get_secret("CESIUM_ION_TOKEN", "")
"""

from __future__ import annotations

import os
import threading
from typing import Optional

_backend: str = os.getenv("WORLDBASE_SECRET_BACKEND", "env").strip().lower()
_vault_url: str = os.getenv("WORLDBASE_SECRET_VAULT_URL", "").strip()
_cache: dict[str, tuple[str, float]] = {}
_cache_lock = threading.Lock()
_cache_ttl: float = float(os.getenv("WORLDBASE_SECRET_CACHE_SEC", "300"))


def _read_dotenv(key: str) -> Optional[str]:
    """Read a key from backend/.env (best-effort, no python-dotenv dependency)."""
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".env",
    )
    if not os.path.exists(env_path):
        return None
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    val = v.strip().strip("'\"")
                    if val:
                        return val
    except Exception:
        pass
    return None


def _vault_get(key: str) -> Optional[str]:
    """Fetch a secret from the configured vault backend (lazy-import, fail-soft)."""
    if _backend == "azure_keyvault":
        return _azure_keyvault_get(key)
    elif _backend == "aws_secretsmanager":
        return _aws_sm_get(key)
    elif _backend == "hashicorp_vault":
        return _hvac_get(key)
    return None


def _azure_keyvault_get(key: str) -> Optional[str]:
    try:
        from azure.keyvault.secrets import SecretClient  # type: ignore[import-untyped]
        from azure.identity import DefaultAzureCredential  # type: ignore[import-untyped]

        if not _vault_url:
            return None
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=_vault_url, credential=credential)
        secret = client.get_secret(key)
        return secret.value
    except Exception:
        return None


def _aws_sm_get(key: str) -> Optional[str]:
    try:
        import boto3  # type: ignore[import-untyped]

        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=key)
        return resp.get("SecretString")
    except Exception:
        return None


def _hvac_get(key: str) -> Optional[str]:
    try:
        import hvac  # type: ignore[import-untyped]

        if not _vault_url:
            return None
        client = hvac.Client(url=_vault_url)
        if not client.is_authenticated():
            return None
        resp = client.secrets.kv.v2.read_secret_version(path=key)
        return resp["data"]["data"].get("value")
    except Exception:
        return None


def get_secret(key: str, default: str = "") -> str:
    """Read a secret in priority order: env var → .env file → vault backend.

    Args:
        key: Environment variable name (e.g. ``WORLDBASE_API_KEY``).
        default: Fallback value if the secret is not found anywhere.

    Returns:
        The secret value as a string, or ``default`` if not found.
    """
    import time

    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and (now - cached[1]) < _cache_ttl:
            return cached[0]

    # 1. Process environment (highest priority — already loaded by uvicorn/start.ps1)
    val = os.getenv(key)
    if val and val.strip():
        result = val.strip()
        with _cache_lock:
            _cache[key] = (result, now)
        return result

    # 2. .env file (for scripts run outside uvicorn, e.g. rotate_api_key.py)
    val = _read_dotenv(key)
    if val:
        result = val.strip()
        with _cache_lock:
            _cache[key] = (result, now)
        return result

    # 3. Vault backend (optional, lazy-import)
    if _backend != "env":
        val = _vault_get(key)
        if val:
            result = val.strip()
            with _cache_lock:
                _cache[key] = (result, now)
            return result

    with _cache_lock:
        _cache[key] = (default, now)
    return default


def get_backend() -> str:
    """Return the current secret backend name."""
    return _backend


def clear_cache() -> None:
    """Clear the in-memory secret cache (for tests)."""
    with _cache_lock:
        _cache.clear()


__all__ = ["get_secret", "get_backend", "clear_cache"]
