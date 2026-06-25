"""JWT token encode/decode/refresh for I9 RBAC.

Uses PyJWT (HS256) for stateless token-based auth.
Access tokens: 15min TTL. Refresh tokens: 7d TTL.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

import jwt

_ALGORITHM = "HS256"
_ACCESS_TTL = int(os.getenv("WORLDBASE_JWT_ACCESS_TTL", "900"))  # 15 min
_REFRESH_TTL = int(os.getenv("WORLDBASE_JWT_REFRESH_TTL", "604800"))  # 7 days


def get_jwt_secret() -> str:
    """Return JWT secret from env, or generate a persistent one."""
    secret = os.getenv("WORLDBASE_JWT_SECRET", "").strip()
    if secret:
        return secret
    # Auto-generate and persist to env file
    secret = secrets.token_urlsafe(48)
    _persist_secret(secret)
    os.environ["WORLDBASE_JWT_SECRET"] = secret
    return secret


def _persist_secret(secret: str) -> None:
    """Persist generated JWT secret to backend/.env (best-effort)."""
    try:
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "WORLDBASE_JWT_SECRET" in content:
            return
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\n# I9 — RBAC + JWT\nWORLDBASE_JWT_SECRET={secret}\n")
    except Exception:
        pass


def encode_access_token(
    subject: str, role: str, extra: dict[str, Any] | None = None
) -> str:
    """Encode a short-lived access JWT."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + _ACCESS_TTL,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, get_jwt_secret(), algorithm=_ALGORITHM)


def encode_refresh_token(
    subject: str, role: str, extra: dict[str, Any] | None = None
) -> str:
    """Encode a long-lived refresh JWT."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "refresh",
        "iat": now,
        "exp": now + _REFRESH_TTL,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, get_jwt_secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT. Returns payload or None on failure."""
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    except Exception:
        return None


def refresh_access_token(refresh_token: str) -> dict[str, str] | None:
    """Exchange a valid refresh token for a new access + refresh pair."""
    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        return None
    subject = payload.get("sub", "")
    role = payload.get("role", "viewer")
    extra = {
        k: v
        for k, v in payload.items()
        if k not in ("sub", "role", "type", "iat", "exp")
    }
    return {
        "access_token": encode_access_token(subject, role, extra),
        "refresh_token": encode_refresh_token(subject, role, extra),
        "token_type": "bearer",
        "expires_in": _ACCESS_TTL,
    }


def token_pair(
    subject: str, role: str, extra: dict[str, Any] | None = None
) -> dict[str, str]:
    """Generate a full token pair (access + refresh)."""
    return {
        "access_token": encode_access_token(subject, role, extra),
        "refresh_token": encode_refresh_token(subject, role, extra),
        "token_type": "bearer",
        "expires_in": _ACCESS_TTL,
    }
