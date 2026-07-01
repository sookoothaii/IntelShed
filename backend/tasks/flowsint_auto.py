"""Celery task for automatic Flowsint enrichment of briefing IOCs.

Runs after briefing generation. Calls the backend's auto-enrich endpoint
which extracts IOCs from the latest briefing, enriches them via Flowsint,
and ingests results as FtM entities + globe pins.
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
_MAX_RETRIES = 3


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if _API_KEY:
        h["X-API-Key"] = _API_KEY
    return h


@celery_app.task(
    bind=True,
    name="tasks.flowsint_auto.auto_enrich",
    autoretry_for=(httpx.HTTPError, OSError, ConnectionError),
    retry_backoff=120,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=_MAX_RETRIES,
)
def auto_enrich_briefing(self) -> dict[str, Any]:
    """Run Flowsint auto-enrichment on the latest briefing.

    Calls ``POST /api/flowsint/auto-enrich`` on the backend. The backend
    extracts IOCs, runs Flowsint enrichers, and ingests results.
    """
    if os.getenv("WORLDBASE_FLOWSINT_AUTO_ENRICH", "0").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return {"enabled": False, "reason": "WORLDBASE_FLOWSINT_AUTO_ENRICH not set"}

    url = f"{_BACKEND_URL}/api/flowsint/auto-enrich"
    try:
        resp = httpx.post(url, headers=_headers(), timeout=300.0)
        resp.raise_for_status()
        data = resp.json()
        log.info(
            "celery_flowsint_auto_enrich_done",
            enriched=data.get("enriched", 0),
            entities=data.get("entities_created", 0),
            pins=data.get("pins_created", 0),
        )
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status >= 500:
            log.warning("celery_flowsint_auto_enrich_server_error", status=status)
            raise self.retry(exc=exc)
        log.error("celery_flowsint_auto_enrich_client_error", status=status)
        return {"error": f"HTTP {status}"}
    except (httpx.HTTPError, OSError, ConnectionError) as exc:
        log.warning("celery_flowsint_auto_enrich_retry", error=str(exc)[:200])
        raise
