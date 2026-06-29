"""Celery app configuration with Redis broker and Beat schedule.

Workers call the backend API via HTTP (httpx) to avoid DuckDB single-process
file lock conflicts. The backend process owns all DuckDB writes; Celery
workers are thin HTTP dispatchers with retry and exponential backoff.

Start worker:  celery -A tasks.celery_app worker --loglevel=info
Start beat:    celery -A tasks.celery_app beat --loglevel=info
Start flower:  celery -A tasks.celery_app flower --port=5555
"""

from __future__ import annotations

import os

from celery import Celery

from config import get_config

_cfg = get_config()

celery_app = Celery(
    "worldbase",
    broker=_cfg.celery_broker_url,
    backend=_cfg.celery_result_backend,
    include=["tasks.feeds", "tasks.briefing"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=300,
    task_time_limit=360,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    broker_pool_limit=10,
    redis_backend_health_check_interval=30,
)

# ---------------------------------------------------------------------------
# Beat schedule — per-feed ingest + briefing generation
# ---------------------------------------------------------------------------

_feed_interval = int(os.getenv("WORLDBASE_FEED_INGEST_INTERVAL", "600"))
_briefing_interval = int(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "21600"))

# Feed sources scheduled by Beat (must match FEED_SOURCES in feed_ingest.py)
_FEED_SOURCES = [
    "gdacs",
    "gdelt_geo",
    "gdelt_pulse",
    "gdelt_geo_west_asia",
    "gdelt_pulse_west_asia",
    "eonet",
    "maritime",
]

beat_schedule: dict = {
    f"ingest-feed-{src}": {
        "task": "tasks.feeds.ingest_feed",
        "schedule": _feed_interval,
        "args": (src,),
    }
    for src in _FEED_SOURCES
}

beat_schedule["generate-briefing"] = {
    "task": "tasks.briefing.generate_briefing",
    "schedule": _briefing_interval,
    "args": (),
}

celery_app.conf.beat_schedule = beat_schedule
