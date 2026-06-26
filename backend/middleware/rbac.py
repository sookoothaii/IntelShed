"""RBAC role-based access control middleware for I9.

Provides FastAPI dependencies for role-based endpoint protection.
Drop-in replacement for verify_lan_auth when RBAC is enabled.

Roles:
  - operator: full access (all endpoints)
  - viewer: read-only (GET only, no chat/MCP/briefing-generate)
  - node: Pi ingest + pull only (scoped to /api/node/*)

When WORLDBASE_RBAC=0 (default), all RBAC checks are bypassed (backward compatible).
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from auth.jwt import decode_token
from auth.security import (
    API_KEY,
    INGEST_TOKEN,
    _LOOPBACK_CLIENTS,
    lan_exposed,
)
from config import get_config

Role = Literal["operator", "viewer", "node"]

_ROLE_HIERARCHY: dict[str, int] = {"operator": 3, "viewer": 1, "node": 1}

_bearer_scheme = HTTPBearer(auto_error=False)


def rbac_enabled() -> bool:
    return get_config().rbac_enabled


def _key_scope(api_key: str) -> Role | None:
    """Determine role from API key or node token."""
    import hmac

    if API_KEY and api_key and hmac.compare_digest(API_KEY, api_key):
        return "operator"
    return None


def _node_scope(node_token: str) -> Role | None:
    import hmac

    if INGEST_TOKEN and node_token and hmac.compare_digest(INGEST_TOKEN, node_token):
        return "node"
    return None


def _role_from_request(request: Request) -> Role | None:
    """Extract role from request — JWT bearer, API key, or node token."""
    # 1. Try JWT bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            role = payload.get("role", "viewer")
            if role in _ROLE_HIERARCHY:
                return role  # type: ignore[return-value]

    # 2. Try X-API-Key
    api_key = request.headers.get("X-API-Key", "")
    role = _key_scope(api_key)
    if role:
        return role

    # 3. Try X-Node-Token
    node_token = request.headers.get("X-Node-Token", "")
    role = _node_scope(node_token)
    if role:
        return role

    return None


def _is_loopback(request: Request) -> bool:
    client_host = (request.client.host if request.client else "").lower()
    return client_host in _LOOPBACK_CLIENTS


def _is_node_path(path: str) -> bool:
    return path.startswith("/api/node")


def _is_write_method(method: str) -> bool:
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def verify_role(required_role: Role):
    """FastAPI dependency factory: require at least `required_role`.

    Usage:
        @router.post("/api/briefing/generate", dependencies=[Depends(verify_role("operator"))])
        async def generate_briefing(): ...
    """

    async def _dependency(request: Request) -> str | None:
        if not rbac_enabled():
            # RBAC disabled — fall back to existing lan_auth behavior
            if not lan_exposed():
                return None
            if _is_loopback(request):
                return "loopback"
            role = _role_from_request(request)
            if role:
                return role
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing credentials",
            )

        # RBAC enabled
        role = _role_from_request(request)

        # Loopback clients without credentials get viewer (read-only)
        if role is None and _is_loopback(request) and not lan_exposed():
            role = "operator"  # local dev: full access
        elif role is None:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Authentication required (JWT, API key, or node token)",
            )

        # Node role: restricted to /api/node/*
        if role == "node" and not _is_node_path(request.url.path):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Node role is restricted to /api/node/* endpoints",
            )

        # Viewer role: no write methods
        if role == "viewer" and _is_write_method(request.method):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail="Viewer role cannot perform write operations",
            )

        # Check role hierarchy
        if _ROLE_HIERARCHY.get(role, 0) < _ROLE_HIERARCHY.get(required_role, 0):
            raise HTTPException(
                status_code=HTTP_403_FORBIDDEN,
                detail=f"Requires role '{required_role}' or higher (current: '{role}')",
            )

        return role

    return _dependency


# Convenience dependencies
require_operator = verify_role("operator")
require_viewer = verify_role("viewer")
require_node = verify_role("node")
