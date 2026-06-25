"""Credential status API — never returns secret values."""

from __future__ import annotations

from fastapi import APIRouter, Query

from credentials.registry import provider_status, providers_status

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


@router.get("/status")
async def credentials_status(
    category: str | None = Query(None, description="Filter by category"),
):
    """Provider configuration summary for the operator HUD."""
    return providers_status(category=category)


@router.get("/status/{provider_id}")
async def credential_provider(provider_id: str):
    """Single provider status."""
    st = provider_status(provider_id)
    if not st:
        return {"error": "unknown provider", "id": provider_id}
    return st
