"""Prometheus metrics endpoint (I4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from auth.security import verify_lan_auth

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics", response_class=PlainTextResponse)
async def metrics_endpoint(_auth: str | None = Depends(verify_lan_auth)):
    """Prometheus exposition format — gauges + histogram."""
    import metrics as _metrics

    return PlainTextResponse(
        _metrics.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
