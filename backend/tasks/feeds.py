"""Per-feed Celery tasks with retry policy and exponential backoff.

Each task calls ``POST /api/intel/feeds/run?sources=<name>`` on the backend
API via HTTP. The backend process owns all DuckDB writes; the Celery worker
is a thin dispatcher. Retry policy handles transient HTTP failures
(backend down, timeout); the backend's feed circuit breaker handles
feed-source-level failures (API rate limits, dead upstreams).

Circuit breaker integration: when the backend returns HTTP 503 (feed
circuit breaker open), the task is retried with exponential backoff
up to ``max_retries``. After max retries, the task fails silently
(fail-soft) to avoid blocking the Beat schedule.
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
_FEED_CB_MAX_RETRIES = 5
_FEED_CB_MAX_BACKOFF = int(os.getenv("WORLDBASE_FEED_CB_MAX_BACKOFF_SEC", "900"))


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _API_KEY:
        h["X-API-Key"] = _API_KEY
    return h


@celery_app.task(
    bind=True,
    name="tasks.feeds.ingest_feed",
    autoretry_for=(httpx.HTTPError, OSError, ConnectionError),
    retry_backoff=60,
    retry_backoff_max=_FEED_CB_MAX_BACKOFF,
    retry_jitter=True,
    max_retries=_FEED_CB_MAX_RETRIES,
    retry_kwargs={"countdown": 60},
)
def ingest_feed(self, source_name: str) -> dict[str, Any]:
    """Ingest a single feed source via the backend API.

    Args:
        source_name: Feed source id (e.g. ``gdacs``, ``gdelt_geo``, ``maritime``).

    Returns:
        Summary dict from the backend's feed ingest endpoint.

    Raises:
        Retryable: ``httpx.HTTPError``, ``OSError``, ``ConnectionError``
            — automatically retried with exponential backoff.
        Non-retryable: HTTP 4xx (except 429) — logged and returned as error dict.
    """
    url = f"{_BACKEND_URL}/api/intel/feeds/run"
    params = {"sources": source_name, "skip_post_ingest": "true"}
    try:
        resp = httpx.post(url, params=params, headers=_headers(), timeout=600.0)
        resp.raise_for_status()
        data = resp.json()
        log.info("celery_feed_ingested", source=source_name, result=data)
        return data
    except httpx.ReadTimeout as exc:
        # Backend is alive but slow — retrying adds load. Fail soft;
        # next Beat schedule will retry naturally.
        log.warning(
            "celery_feed_read_timeout",
            source=source_name,
            error=str(exc),
        )
        return {"error": "read timeout", "source": source_name}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 503:
            # Feed circuit breaker open — retry with backoff
            log.warning(
                "celery_feed_circuit_breaker_open",
                source=source_name,
                status=status,
            )
            raise self.retry(exc=exc)
        if 400 <= status < 500 and status != 429:
            # Non-retryable client error — fail soft
            log.error(
                "celery_feed_client_error",
                source=source_name,
                status=status,
                body=exc.response.text[:500],
            )
            return {"error": f"HTTP {status}", "source": source_name}
        # 5xx and 429 — retry
        raise self.retry(exc=exc)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        log.warning("celery_feed_retry", source=source_name, error=str(exc))
        raise


@celery_app.task(
    bind=True,
    name="tasks.feeds.post_ingest_pipeline",
    autoretry_for=(httpx.HTTPError, OSError, ConnectionError),
    retry_backoff=60,
    retry_backoff_max=_FEED_CB_MAX_BACKOFF,
    retry_jitter=True,
    max_retries=3,
)
def post_ingest_pipeline(self) -> dict[str, Any]:
    """Run the post-ingest intelligence pipeline via the backend API.

    Calls ``POST /api/intel/feeds/post-ingest`` which runs spatial edges,
    semantic edges, sanction edges, and subgraph export. Scheduled by Beat
    with a 120s countdown offset after per-feed ingest tasks fire.
    """
    url = f"{_BACKEND_URL}/api/intel/feeds/post-ingest"
    try:
        resp = httpx.post(url, headers=_headers(), timeout=600.0)
        resp.raise_for_status()
        data = resp.json()
        log.info("celery_post_ingest_pipeline", result=data)
        return data
    except httpx.ReadTimeout as exc:
        log.warning("celery_post_ingest_read_timeout", error=str(exc))
        return {"error": "read timeout"}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 503:
            log.warning("celery_post_ingest_circuit_breaker_open", status=status)
            raise self.retry(exc=exc)
        if 400 <= status < 500 and status != 429:
            log.error(
                "celery_post_ingest_client_error",
                status=status,
                body=exc.response.text[:500],
            )
            return {"error": f"HTTP {status}"}
        raise self.retry(exc=exc)
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        log.warning("celery_post_ingest_retry", error=str(exc))
        raise


@celery_app.task(
    bind=True,
    name="tasks.feeds.ingest_all_feeds",
    autoretry_for=(httpx.HTTPError, OSError, ConnectionError),
    retry_backoff=60,
    retry_backoff_max=_FEED_CB_MAX_BACKOFF,
    retry_jitter=True,
    max_retries=3,
)
def ingest_all_feeds(self) -> dict[str, Any]:
    """Ingest all feed sources in a single backend call.

    Convenience task for manual triggering or when per-feed scheduling
    is not needed.
    """
    url = f"{_BACKEND_URL}/api/intel/feeds/run"
    try:
        resp = httpx.post(url, headers=_headers(), timeout=600.0)
        resp.raise_for_status()
        data = resp.json()
        log.info("celery_all_feeds_ingested", result=data)
        return data
    except httpx.ReadTimeout as exc:
        log.warning("celery_all_feeds_read_timeout", error=str(exc))
        return {"error": "read timeout"}
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code >= 500:
            raise self.retry(exc=exc)
        return {"error": f"HTTP {exc.response.status_code}"}
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        log.warning("celery_all_feeds_retry", error=str(exc))
        raise
