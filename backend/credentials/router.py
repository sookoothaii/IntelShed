"""Credential status API — never returns secret values."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth.security import verify_lan_auth
from credentials.registry import provider_status, providers_status
from credentials.store import (
    delete_credential,
    list_credentials,
    set_credential,
)

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


# ---------------------------------------------------------------------------
# Session 7 — Credential Manager CRUD
# ---------------------------------------------------------------------------


@router.get("")
async def list_stored_credentials():
    """List all operator-set credentials (masked, never exposes secrets)."""
    return {"credentials": list_credentials()}


class CredentialInput(BaseModel):
    env_var: str
    value: str


@router.post("")
async def set_stored_credential(
    body: CredentialInput,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Set or update a credential.  Value is persisted and applied to env."""
    env_var = body.env_var.strip().upper()
    if not env_var:
        return {"error": "env_var is required"}
    if not body.value.strip():
        return {"error": "value is required"}
    return set_credential(env_var, body.value.strip())


@router.delete("/{env_var}")
async def delete_stored_credential(
    env_var: str,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Remove a stored credential."""
    return delete_credential(env_var.upper())
