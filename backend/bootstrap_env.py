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
    api_key = os.getenv("WORLDBASE_API_KEY", "")
    admin = os.getenv("NODE_ADMIN_TOKEN", "")
    require = _truthy(os.getenv("WORLDBASE_REQUIRE_NODE_TOKEN", ""))
    dev_mode = _truthy(os.getenv("WORLDBASE_INSECURE_DEV", ""))

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
        print("[SECURITY] Node ingest API protected (NODE_INGEST_TOKEN set).", flush=True)

    if not api_key and not ingest and not dev_mode:
        print(
            "[SECURITY] WARNING: No WORLDBASE_API_KEY or NODE_INGEST_TOKEN set. "
            "All endpoints are unauthenticated. "
            "Set WORLDBASE_INSECURE_DEV=1 to acknowledge and suppress this warning.",
            flush=True,
        )
    elif dev_mode and not api_key and not ingest:
        print(
            "[SECURITY] Running in INSECURE DEV MODE (WORLDBASE_INSECURE_DEV=1). "
            "All endpoints unauthenticated. Do NOT use in production.",
            flush=True,
        )
    else:
        if api_key:
            print("[SECURITY] API key auth enabled (WORLDBASE_API_KEY set).", flush=True)

    if admin and admin != ingest:
        print("[SECURITY] Admin token is separate from ingest token (NODE_ADMIN_TOKEN set).", flush=True)
    elif ingest and not admin:
        print(
            "[SECURITY] NOTE: NODE_ADMIN_TOKEN not set — admin endpoints fall back to NODE_INGEST_TOKEN. "
            "Set NODE_ADMIN_TOKEN separately for privilege separation.",
            flush=True,
        )
