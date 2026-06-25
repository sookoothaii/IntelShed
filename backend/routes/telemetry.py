"""Frontend telemetry ingestion (J3).

Accepts crash reports from React Error Boundaries and logs them
via the structured logger. Integrates with I4 OpenTelemetry when available.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# Rate limit: max 20 crash reports per minute (in-memory)
_report_times: list[float] = []
_MAX_REPORTS_PER_MIN = 20


class FrontendErrorReport(BaseModel):
    component: str = Field(..., max_length=100)
    message: str = Field(..., max_length=2000)
    stack: str = Field("", max_length=4000)
    componentStack: str = Field("", max_length=2000)
    url: str = Field("", max_length=500)
    timestamp: str = Field("")


@router.post("/frontend-error")
async def frontend_error(
    report: FrontendErrorReport,
    request: Request,
    _auth: str | None = Depends(verify_lan_auth),
):
    import time

    now = time.time()
    _report_times.append(now)
    # Trim entries older than 60s
    while _report_times and _report_times[0] < now - 60:
        _report_times.pop(0)

    if len(_report_times) > _MAX_REPORTS_PER_MIN:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit: too many crash reports"},
        )

    # Use structured logger if available, otherwise print
    try:
        from structured_log import get_logger

        log = get_logger("frontend_telemetry")
        log.warning(
            "frontend_crash",
            extra={
                "schema": "frontend_error",
                "component": report.component,
                "message": report.message,
                "stack": report.stack[:500],
                "component_stack": report.componentStack[:500],
                "url": report.url,
                "client_ip": request.client.host if request.client else "",
                "timestamp": report.timestamp or datetime.now(timezone.utc).isoformat(),
            },
        )
    except ImportError:
        print(
            f"[TELEMETRY] frontend_crash component={report.component} "
            f"message={report.message[:200]}",
            flush=True,
        )

    return {"status": "logged", "component": report.component}
