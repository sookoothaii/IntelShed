"""Minimal .env loader and startup security checks (no extra dependency)."""

from __future__ import annotations

import os

from structured_log import get_logger

log = get_logger(__name__)


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
        log.warning("security_node_token_missing", detail=msg)
    else:
        log.info("security_node_token_set")

    if not api_key and not ingest and not dev_mode:
        log.warning("security_no_auth", detail="No WORLDBASE_API_KEY or NODE_INGEST_TOKEN set. All endpoints unauthenticated. Set WORLDBASE_INSECURE_DEV=1 to acknowledge.")
    elif dev_mode and not api_key and not ingest:
        log.warning("security_insecure_dev", detail="Running in INSECURE DEV MODE. All endpoints unauthenticated. Do NOT use in production.")
    else:
        if api_key:
            log.info("security_api_key_set")

    if admin and admin != ingest:
        log.info("security_admin_token_separate")
    elif ingest and not admin:
        log.info("security_admin_token_not_set", detail="NODE_ADMIN_TOKEN not set — admin endpoints fall back to NODE_INGEST_TOKEN. Set NODE_ADMIN_TOKEN separately for privilege separation.")
