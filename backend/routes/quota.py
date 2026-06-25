"""API quota monitoring endpoints (J5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/quota", tags=["quota"])


@router.get("")
async def quota_status(_auth: str | None = Depends(verify_lan_auth)):
    """Full quota dashboard: per-source usage, limits, cost, 7-day trend."""
    import quota_monitor

    return quota_monitor.get_quota_status()


@router.get("/alerts")
async def quota_alerts(_auth: str | None = Depends(verify_lan_auth)):
    """Check for 80% threshold + exceeded alerts."""
    import quota_monitor

    return {"alerts": quota_monitor.check_alerts()}


@router.get("/{source}")
async def quota_source(source: str, _auth: str | None = Depends(verify_lan_auth)):
    """Usage for a specific source today."""
    import quota_monitor

    return quota_monitor.get_usage(source)
