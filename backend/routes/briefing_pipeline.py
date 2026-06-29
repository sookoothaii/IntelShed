"""Briefing pipeline Kanban API routes.

GET  /api/briefing/pipeline       — all items grouped by stage
POST /api/briefing/pipeline/move  — move an item to a different stage
POST /api/briefing/pipeline/sync   — sync pipeline from latest briefing
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.security import verify_lan_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/briefing/pipeline", tags=["briefing-pipeline"])


class MoveRequest(BaseModel):
    item_id: str = Field(..., description="Pipeline item ID to move")
    target_stage: str = Field(
        ...,
        description="Target stage: INGEST, ANALYZE, CORROBORATE, SYNTHESIZE, or PUBLISHED",
    )


@router.get("")
async def get_pipeline(_auth: str | None = Depends(verify_lan_auth)):
    """Return all pipeline items grouped by stage."""
    import briefing_pipeline

    return {
        "stages": briefing_pipeline.STAGES,
        "pipeline": briefing_pipeline.get_pipeline(),
    }


@router.post("/move")
async def move_item(
    body: MoveRequest,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Move a pipeline item to a different stage."""
    import briefing_pipeline

    try:
        result = briefing_pipeline.move_item(body.item_id, body.target_stage)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("pipeline move failed")
        raise HTTPException(
            status_code=500, detail=f"pipeline move failed: {exc}"
        ) from exc


@router.post("/sync")
async def sync_pipeline(_auth: str | None = Depends(verify_lan_auth)):
    """Sync pipeline items from the latest stored briefing."""
    import briefing_pipeline
    import node_briefing

    try:
        briefing = await node_briefing.latest_briefing()
        count = briefing_pipeline.sync_from_briefing(briefing)
        return {"synced": count, "stages": briefing_pipeline.STAGES}
    except Exception as exc:
        logger.exception("pipeline sync failed")
        raise HTTPException(
            status_code=500, detail=f"pipeline sync failed: {exc}"
        ) from exc
