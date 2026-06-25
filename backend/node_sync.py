"""WorldBase — node sync compat layer (PC brain <-> Pi edge as one organism).

Phase 2 refactor: implementation split into node_ingest.py (telemetry, commands,
SSE, mesh) and node_briefing.py (snapshot, alerts, LLM briefing, Pi pull).
This module re-exports everything for backward compatibility and merges both
routers into a single ``router`` for the registry.
"""

from __future__ import annotations

from fastapi import APIRouter

from node_ingest import *  # noqa: F401,F403
from node_ingest import router as _ingest_router
from node_ingest import (  # noqa: F401
    _db,
    DB_PATH,
    SENSOR_THRESHOLDS,
    _verify_node_secret,
    _verify_admin_secret,
    init_node_db,
    init_command_db,
    _store_sensors,
    _notify_node_update,
    _node_update_queues,
    _node_update_generator,
)

from node_briefing import *  # noqa: F401,F403
from node_briefing import router as _briefing_router
from node_briefing import (  # noqa: F401
    SELF_URL,
    OLLAMA_HOSTS,
    OLLAMA_MODEL,
    _BRIEFING_LOCK,
    _SNAPSHOT_CACHE,
    _SNAPSHOT_CACHE_AT,
    _SNAPSHOT_CACHE_LOCK,
    _snapshot_cache_ttl_sec,
    invalidate_snapshot_cache,
    snapshot_cache_age_sec,
    warm_snapshot_cache,
    _gdelt_snapshot_meta,
    _gather_snapshot_uncached,
    _gather_snapshot,
    _compile_alerts,
    _ollama_briefing,
    generate_briefing,
    generate_briefing_internal,
    _generate_briefing_unlocked,
    latest_briefing,
    predictions_status,
    _compress_briefing,
    _pull_payload_digest,
    _briefing_hash,
    _node_pull_delta_enabled,
    node_pull,
    node_pull_mesh,
)

# Merge both routers into one for registry compatibility
router = APIRouter(prefix="/api", tags=["node-sync"])
router.routes.extend(_ingest_router.routes)
router.routes.extend(_briefing_router.routes)
