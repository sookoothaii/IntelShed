"""Shared OpenSky Network client (OAuth2 client credentials + stale-friendly fetch)."""

import os
import time

import httpx

_STATES_URL = "https://opensky-network.org/api/states/all"
_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
_TOKEN: dict = {"token": None, "exp": 0.0}


def credentials_configured() -> bool:
    cid = os.environ.get("OPENSKY_CLIENT_ID", "").strip()
    secret = os.environ.get("OPENSKY_CLIENT_SECRET", "").strip()
    return bool(cid and secret and cid != "your-username-api-client")


async def get_token() -> str | None:
    """Bearer token from OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET, or None."""
    cid = os.environ.get("OPENSKY_CLIENT_ID", "").strip()
    secret = os.environ.get("OPENSKY_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        return None
    now = time.time()
    if _TOKEN["token"] and now < _TOKEN["exp"] - 60:
        return _TOKEN["token"]
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": cid,
                "client_secret": secret,
            },
        )
        r.raise_for_status()
        tok = r.json()
    _TOKEN["token"] = tok["access_token"]
    _TOKEN["exp"] = now + float(tok.get("expires_in", 1800))
    return _TOKEN["token"]


async def fetch_states_all(timeout: float = 30.0) -> dict | None:
    """Return OpenSky states/all JSON, or None on failure."""
    headers: dict[str, str] = {}
    token = await get_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(_STATES_URL, headers=headers)
        r.raise_for_status()
        return r.json()
