"""Trust probes API."""

from __future__ import annotations

from fastapi import APIRouter

import trust_probes

router = APIRouter(prefix="/api/trust", tags=["trust"])


@router.get("")
async def trust_status():
    """Synthetic field-ops trust score (0–4) + probe details."""
    return await trust_probes.run_trust_probes()
