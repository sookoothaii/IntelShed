"""Briefing generation Celery task scheduled by Celery Beat every 6 hours.

Calls ``POST /api/briefing/generate`` on the backend API via HTTP.
The backend process handles all briefing logic (agentic loop, LLM calls,
entity graph queries, alerting). The Celery worker is a thin dispatcher
with retry and exponential backoff.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from config import get_config
from structured_log import get_logger
from tasks.celery_app import celery_app

log = get_logger(__name__)

_cfg = get_config()

_API_KEY = os.getenv("WORLDBASE_API_KEY", "")
_BACKEND_URL = _cfg.celery_backend_url
_BRIEFING_MAX_RETRIES = 3
_BRIEFING_MAX_BACKOFF = int(os.getenv("WORLDBASE_BRIEFING_MAX_BACKOFF_SEC", "600"))


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _API_KEY:
        h["X-API-Key"] = _API_KEY
    return h


@celery_app.task(
    bind=True,
    name="tasks.briefing.generate_briefing",
    autoretry_for=(httpx.HTTPError, OSError, ConnectionError),
    retry_backoff=60,
    retry_backoff_max=_BRIEFING_MAX_BACKOFF,
    retry_jitter=True,
    max_retries=_BRIEFING_MAX_RETRIES,
    retry_kwargs={"countdown": 30},
)
def generate_briefing(self, lang: str | None = None) -> dict[str, Any]:
    """Generate a security briefing via the backend API.

    Args:
        lang: Optional language code (e.g. ``en``, ``de``). Defaults to
            the backend's configured briefing language.

    Returns:
        Briefing summary dict from the backend.

    Raises:
        Retryable: ``httpx.HTTPError``, ``OSError``, ``ConnectionError``
            — automatically retried with exponential backoff.
        Non-retryable: HTTP 4xx — logged and returned as error dict.
    """
    url = f"{_BACKEND_URL}/api/briefing/generate"
    params = {}
    if lang:
        params["lang"] = lang
    try:
        resp = httpx.post(url, params=params, headers=_headers(), timeout=600.0)
        resp.raise_for_status()
        data = resp.json()
        log.info("celery_briefing_generated", result_keys=list(data.keys()))
        return data
    except httpx.ReadTimeout as exc:
        log.warning("celery_briefing_read_timeout", error=str(exc))
        return {"error": "read timeout"}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500:
            log.warning(
                "celery_briefing_server_error",
                status=status,
                body=exc.response.text[:500],
            )
            raise self.retry(exc=exc)
        if 400 <= status < 500:
            log.error(
                "celery_briefing_client_error",
                status=status,
                body=exc.response.text[:500],
            )
            return {"error": f"HTTP {status}"}
        raise self.retry(exc=exc)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        log.warning("celery_briefing_retry", error=str(exc))
        raise
