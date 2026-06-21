"""Minimal .env loader and startup security checks (no extra dependency)."""

from __future__ import annotations

import os


def load_env() -> None:
    """Load backend/.env without overriding real environment variables."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _truthy(val: str) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


def log_security_startup() -> None:
    ingest = os.getenv("NODE_INGEST_TOKEN", "")
    require = _truthy(os.getenv("WORLDBASE_REQUIRE_NODE_TOKEN", ""))
    if not ingest:
        msg = (
            "NODE_INGEST_TOKEN not set — /api/node/* is open on the bind address. "
            "Run scripts/setup-node-security.ps1 (PC) and sync token to the Pi."
        )
        if require:
            raise RuntimeError(
                "[SECURITY] WORLDBASE_REQUIRE_NODE_TOKEN is set but NODE_INGEST_TOKEN is empty. "
                "Refusing to start. " + msg
            )
        print("[SECURITY] " + msg, flush=True)
    else:
        print("[SECURITY] Node ingest/admin API protected (NODE_INGEST_TOKEN set).", flush=True)
