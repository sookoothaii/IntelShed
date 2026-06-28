"""Config endpoints — Cesium Ion token proxy (Phase 2.2).

GET /api/config/cesium — returns the Cesium Ion token from backend env.
The frontend fetches this at runtime instead of baking the token into the
Vite bundle. Falls back gracefully: if no token is configured, returns
``{"token": ""}`` and the frontend uses its ellipsoid fallback.

5-minute in-memory cache to avoid repeated env reads.
"""

from __future__ import annotations

import os
import time
import threading

from fastapi import APIRouter, Depends

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/config", tags=["config"])

_cache_token: str = ""
_cache_ts: float = 0.0
_cache_lock = threading.Lock()
_CACHE_TTL_SEC = 300  # 5 min


def _get_cesium_token() -> str:
    """Read Cesium Ion token from env or .env (cached 5 min)."""
    global _cache_token, _cache_ts
    now = time.monotonic()
    with _cache_lock:
        if _cache_token and (now - _cache_ts) < _CACHE_TTL_SEC:
            return _cache_token

    token = os.getenv("CESIUM_ION_TOKEN", "").strip()
    if not token:
        token = os.getenv("VITE_CESIUM_ION_TOKEN", "").strip()

    with _cache_lock:
        _cache_token = token
        _cache_ts = now
    return token


@router.get("/cesium")
async def get_cesium_config(_auth: str | None = Depends(verify_lan_auth)):
    """Return the Cesium Ion token for frontend runtime use.

    No token is baked into the Vite bundle. The frontend calls this
    endpoint on startup and sets ``Ion.defaultAccessToken``.

    Returns ``{"token": ""}`` when no token is configured — the frontend
    falls back to ellipsoid terrain in that case.
    """
    token = _get_cesium_token()
    return {"token": token}
