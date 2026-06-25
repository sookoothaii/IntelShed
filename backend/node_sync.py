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

from node_briefing import *  # noqa: F401,F403
from node_briefing import router as _briefing_router

# Merge both routers into one for registry compatibility
router = APIRouter(prefix="/api", tags=["node-sync"])
router.routes.extend(_ingest_router.routes)
router.routes.extend(_briefing_router.routes)
