"""HTTP surface for dynamic feature flags (J2).

Endpoints:
- GET  /api/admin/flags          — list all flags with state + source
- POST /api/admin/flags/{key}    — toggle a flag (body: {"enabled": true})
- GET  /api/admin/flags/log      — audit log of flag changes
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/admin", tags=["admin"])


class FlagUpdate(BaseModel):
    enabled: bool
    updated_by: str = "operator"


@router.get("/flags")
async def list_flags(_auth: str | None = Depends(verify_lan_auth)):
    import features

    return {"flags": features.get_all_flags()}


@router.post("/flags/{key}")
async def set_flag(
    key: str,
    body: FlagUpdate,
    _auth: str | None = Depends(verify_lan_auth),
):
    import features

    result = features.set_flag(key, body.enabled, body.updated_by)
    return result


@router.get("/flags/log")
async def flag_log(
    limit: int = 100,
    _auth: str | None = Depends(verify_lan_auth),
):
    import features

    return {"entries": features.get_flag_log(limit=limit)}
