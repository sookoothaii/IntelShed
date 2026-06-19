"""Thin template for a community HTTP JSON feed connector.

Copy this file, register the connector in connector_registry.CONNECTOR_CATALOG,
and wire a FastAPI route in main.py (or a dedicated router module).

Requirements:
- No secrets in client bundle; read API keys from env via credentials.registry.
- Fail-soft: return stale cache or {count: 0} on upstream errors.
- Call feed_registry.write_auto(cache_key, payload) after each successful fetch.
- Add a YAML mapping under backend/ingest/mappings/ if rows should land in FtM.

Example env (optional provider — add to credentials/registry.py if keyed):

    MY_FEED_API_KEY=...

Example manifest entry (connector_registry.py):

    "my_feed": ConnectorManifest(
        id="my_feed",
        name="My Community Feed",
        category="osint",
        endpoints=("/api/my-feed",),
        ttl_sec=600,
        license="MIT / provider terms",
        region=("global",),
        credential_ids=("my_feed_provider",),
        cache_key="my_feed",
        bridge="connectors/my_feed.py",
    )
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

import feed_registry

_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_TTL = float(os.getenv("MY_FEED_TTL", "600"))
_CACHE_KEY = "my_feed"
_UPSTREAM = os.getenv("MY_FEED_URL", "https://example.com/api/events.json").strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fetch_my_feed(*, timeout: float = 15.0) -> dict[str, Any]:
    """Fetch upstream JSON and persist to feed_cache."""
    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["data"]

    api_key = os.getenv("MY_FEED_API_KEY", "").strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(_UPSTREAM, headers=headers)
            resp.raise_for_status()
            raw = resp.json()
        items = raw if isinstance(raw, list) else raw.get("items") or raw.get("events") or []
        out = {
            "count": len(items),
            "items": items[:500],
            "source": _UPSTREAM,
            "updated": _now_iso(),
        }
        _CACHE["ts"] = now
        _CACHE["data"] = out
        feed_registry.write_auto(_CACHE_KEY, out)
        return out
    except Exception as exc:
        stale = feed_registry.read(_CACHE_KEY) or _CACHE["data"]
        if stale:
            stale = dict(stale)
            stale["stale"] = True
            stale["error"] = str(exc)[:200]
            return stale
        return {"count": 0, "items": [], "source": _UPSTREAM, "updated": _now_iso(), "error": str(exc)[:200]}
