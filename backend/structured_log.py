"""Structured JSON logger with secret redaction.

Emits one JSON line per log record to stdout. Sensitive values (API keys,
tokens, passwords) are redacted automatically.

Usage::

    from structured_log import get_logger
    log = get_logger(__name__)
    log.info("briefing_generated", count=5, quality=1.0)
    log.error("ftm_store_failed", error="DuckDB invalidated")

Produces::

    {"ts":"2026-06-25T18:30:00+07:00","level":"INFO","logger":"lifespan","msg":"briefing_generated","count":5,"quality":1.0}
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

# Keys whose values should be redacted in any log output.
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "passwd",
        "authorization",
        "auth",
        "credential",
        "private_key",
        "node_ingest_token",
        "node_admin_token",
        "cesium_ion_token",
        "aisstream_api_key",
        "newsdata_api_key",
        "entsoe_security_token",
        "opensky_client_secret",
        "firewall_host",
    }
)

# Env var names that contain secrets — their values should never be logged.
_SENSITIVE_ENV_PATTERNS = re.compile(
    r"(TOKEN|SECRET|KEY|PASSWORD|PASSWD|CREDENTIAL|PRIVATE_KEY)",
    re.IGNORECASE,
)


def _redact_value(value: object, key: str) -> object:
    """Redact a value if its key looks sensitive."""
    if key.lower() in _SENSITIVE_KEYS or _SENSITIVE_ENV_PATTERNS.search(key):
        return "[REDACTED]"
    if isinstance(value, str) and len(value) > 4:
        # Check if the string value matches any env secret value
        for env_key, env_val in os.environ.items():
            if _SENSITIVE_ENV_PATTERNS.search(env_key) and env_val and env_val in value:
                return value.replace(env_val, "[REDACTED]")
    return value


def _redact_dict(d: dict) -> dict:
    """Recursively redact sensitive values in a dict."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = _redact_dict(v)
        elif isinstance(v, list):
            out[k] = [
                _redact_dict(i) if isinstance(i, dict) else _redact_value(i, k)
                for i in v
            ]
        else:
            out[k] = _redact_value(v, k)
    return out


class JsonFormatter(logging.Formatter):
    """One-line JSON per record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge extra fields from record.__dict__
        for key, val in record.__dict__.items():
            if key in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
                "message",
            ):
                continue
            if key == "_extra" and isinstance(val, dict):
                payload.update(val)
            else:
                payload[key] = val
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        payload = _redact_dict(payload)
        return json.dumps(payload, default=str, ensure_ascii=False)


class StructuredLogger:
    """Wrapper around logging.Logger that accepts arbitrary kwargs.

    Usage::

        log = get_logger(__name__)
        log.info("event_name", key1=val1, key2=val2)
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, msg: str, **kwargs: object) -> None:
        self._logger.log(level, msg, extra={"_extra": kwargs})

    def info(self, msg: str, **kwargs: object) -> None:
        self._log(logging.INFO, msg, **kwargs)

    def warning(self, msg: str, **kwargs: object) -> None:
        self._log(logging.WARNING, msg, **kwargs)

    def error(self, msg: str, **kwargs: object) -> None:
        self._log(logging.ERROR, msg, **kwargs)

    def debug(self, msg: str, **kwargs: object) -> None:
        self._log(logging.DEBUG, msg, **kwargs)


def get_logger(name: str = "worldbase") -> StructuredLogger:
    """Return a configured logger that emits JSON to stdout.

    Idempotent: calling multiple times with the same name returns the same
    logger without adding duplicate handlers.
    """
    inner = logging.getLogger(name)
    if not inner.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        inner.addHandler(handler)
        inner.setLevel(logging.INFO)
        inner.propagate = False
    return StructuredLogger(inner)
