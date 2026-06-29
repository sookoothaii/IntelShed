"""STIX 2.1 / MISP export API routes.

Read-only endpoints for interop with threat intelligence platforms.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intel/stix", tags=["intel"])


@router.get("/export")
async def stix_export_entity(
    entity_id: str = Query(..., description="FtM entity ID to export"),
):
    """Export a single FtM entity (with neighbours + edges) as a STIX 2.1 bundle."""
    try:
        from stix_export import export_entity_stix

        bundle = export_entity_stix(entity_id)
        if bundle.get("error"):
            raise HTTPException(status_code=404, detail=bundle["error"])
        return bundle
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("stix export failed")
        raise HTTPException(
            status_code=503, detail=f"stix export failed: {str(exc)[:200]}"
        ) from exc


@router.get("/report")
async def stix_export_briefing(
    briefing_id: str = Query(..., description="Briefing ID to export as STIX Report"),
):
    """Export a briefing as a STIX 2.1 Report bundle with referenced entities."""
    try:
        from stix_export import export_briefing_stix

        # Fetch briefing from node_sync
        import node_sync

        briefing = await node_sync.latest_briefing()
        if not briefing:
            raise HTTPException(status_code=404, detail="no briefing available")
        bundle = export_briefing_stix(briefing)
        return bundle
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("stix briefing export failed")
        raise HTTPException(
            status_code=503, detail=f"stix report failed: {str(exc)[:200]}"
        ) from exc


@router.get("/misp/export")
async def misp_export_entity(
    entity_id: str = Query(..., description="FtM entity ID to export as MISP event"),
):
    """Export a FtM entity as a MISP event JSON."""
    try:
        from stix_export import export_misp_event

        event = export_misp_event(entity_id)
        if event.get("error"):
            raise HTTPException(status_code=404, detail=event["error"])
        return event
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("misp export failed")
        raise HTTPException(
            status_code=503, detail=f"misp export failed: {str(exc)[:200]}"
        ) from exc
