"""Auth API routes for I9 — JWT token exchange + key rotation.

POST /api/auth/token     — exchange API key for JWT pair
POST /api/auth/refresh   — refresh access token
POST /api/auth/rotate    — rotate API key (grace period)
GET  /api/auth/scopes    — current key scopes
"""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from auth.jwt import decode_token, refresh_access_token, token_pair
from auth.security import (
    API_KEY,
    INGEST_TOKEN,
    _truthy_env,
    lan_exposed,
    verify_lan_auth,
)
from middleware.rbac import rbac_enabled, _key_scope, _node_scope

router = APIRouter(prefix="/api/auth", tags=["auth"])

_ROTATION_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "worldbase.db",
)
_GRACE_PERIOD_S = int(os.getenv("WORLDBASE_KEY_GRACE_PERIOD", "86400"))  # 24h


def _init_rotation_db() -> None:
    try:
        conn = sqlite3.connect(_ROTATION_DB)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS key_rotation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_key_hash TEXT NOT NULL,
                new_key TEXT NOT NULL,
                rotated_at TEXT NOT NULL,
                grace_expires TEXT NOT NULL,
                revoked INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _hash_key(key: str) -> str:
    import hashlib

    return hashlib.sha256(key.encode()).hexdigest()


class TokenRequest(BaseModel):
    api_key: str = ""
    node_token: str = ""


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/token")
async def exchange_token(req: TokenRequest):
    """Exchange an API key or node token for a JWT access + refresh pair."""
    if not rbac_enabled():
        return {
            "enabled": False,
            "message": "WORLDBASE_RBAC=0 — JWT auth disabled, use X-API-Key directly",
        }

    # Check API key → operator role
    if req.api_key and API_KEY and hmac.compare_digest(API_KEY, req.api_key):
        return token_pair("api-key", "operator")

    # Check node token → node role
    if req.node_token and INGEST_TOKEN and hmac.compare_digest(INGEST_TOKEN, req.node_token):
        return token_pair("node-token", "node")

    # Check rotated keys in grace period
    role = _check_rotated_keys(req.api_key, req.node_token)
    if role:
        return token_pair("rotated-key", role)

    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid API key or node token",
    )


@router.post("/refresh")
async def refresh_token(req: RefreshRequest):
    """Refresh an access token using a refresh token."""
    if not rbac_enabled():
        return {
            "enabled": False,
            "message": "WORLDBASE_RBAC=0 — JWT auth disabled",
        }

    result = refresh_access_token(req.refresh_token)
    if not result:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    return result


@router.post("/rotate")
async def rotate_api_key(_auth: str | None = Depends(verify_lan_auth)):
    """Generate a new API key. Old key valid for grace period (24h default).

    Requires existing operator credentials.
    """
    if not API_KEY:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="WORLDBASE_API_KEY not set — nothing to rotate",
        )

    _init_rotation_db()

    new_key = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    grace_expires = (now.timestamp() + _GRACE_PERIOD_S)

    try:
        conn = sqlite3.connect(_ROTATION_DB)
        conn.execute(
            "INSERT INTO key_rotation (old_key_hash, new_key, rotated_at, grace_expires) VALUES (?, ?, ?, ?)",
            (
                _hash_key(API_KEY),
                new_key,
                now.isoformat(),
                datetime.fromtimestamp(grace_expires, tz=timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Rotation log failed: {e}",
        )

    # Update env in memory
    os.environ["WORLDBASE_API_KEY"] = new_key

    # Persist to .env (best-effort)
    _persist_new_key(new_key)

    return {
        "new_api_key": new_key,
        "old_key_valid_until": datetime.fromtimestamp(
            grace_expires, tz=timezone.utc
        ).isoformat(),
        "grace_period_seconds": _GRACE_PERIOD_S,
        "message": f"Old key valid for {_GRACE_PERIOD_S // 3600}h grace period. Update clients.",
    }


@router.get("/scopes")
async def get_scopes(_auth: str | None = Depends(verify_lan_auth)):
    """Return current key scope configuration."""
    return {
        "rbac_enabled": rbac_enabled(),
        "api_key_set": bool(API_KEY),
        "api_key_scope": "operator" if API_KEY else None,
        "node_token_set": bool(INGEST_TOKEN),
        "node_token_scope": "node" if INGEST_TOKEN else None,
        "roles": ["operator", "viewer", "node"],
        "jwt_access_ttl": int(os.getenv("WORLDBASE_JWT_ACCESS_TTL", "900")),
        "jwt_refresh_ttl": int(os.getenv("WORLDBASE_JWT_REFRESH_TTL", "604800")),
    }


def _check_rotated_keys(api_key: str, node_token: str) -> str | None:
    """Check if credentials match a rotated key in grace period."""
    try:
        conn = sqlite3.connect(_ROTATION_DB)
        now = datetime.now(timezone.utc).isoformat()
        rows = conn.execute(
            "SELECT new_key, old_key_hash, grace_expires, revoked FROM key_rotation WHERE revoked = 0"
        ).fetchall()
        conn.close()

        for new_key, old_hash, grace_expires, _revoked in rows:
            # Check if grace period still active
            try:
                expires_dt = datetime.fromisoformat(grace_expires)
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                if expires_dt < datetime.now(timezone.utc):
                    continue
            except Exception:
                continue

            # New key matches → operator
            if api_key and hmac.compare_digest(new_key, api_key):
                return "operator"

            # Old key hash matches → operator (grace period)
            if api_key and hmac.compare_digest(old_hash, _hash_key(api_key)):
                return "operator"

        return None
    except Exception:
        return None


def _persist_new_key(new_key: str) -> None:
    """Best-effort: update WORLDBASE_API_KEY in backend/.env."""
    try:
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        updated = False
        with open(env_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.strip().startswith("WORLDBASE_API_KEY="):
                    f.write(f"WORLDBASE_API_KEY={new_key}\n")
                    updated = True
                else:
                    f.write(line)
            if not updated:
                f.write(f"\nWORLDBASE_API_KEY={new_key}\n")
    except Exception:
        pass
