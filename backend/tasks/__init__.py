"""Celery task queue for WorldBase background work.

Activated via ``WORLDBASE_TASK_QUEUE=celery``. When disabled (default),
``lifespan.py`` asyncio autopilot loops handle feed ingest and briefing
generation as before.
"""

from tasks.celery_app import celery_app

__all__ = ["celery_app"]
