"""Process-local in-memory TTL cache.

Shared by the core feed endpoints (routes/core_feeds.py) and the chat context
builder (routes/chat.py), so they must read/write the SAME store (e.g. /api/chat
context reads ``quakes:day:2.5`` and ``eonet`` populated by the feed endpoints).
This is the in-memory layer; durable snapshots live in feed_registry (SQLite).
"""

from __future__ import annotations

import threading
import time
from typing import Any

# key -> (stored_at_epoch, value)
STORE: dict[str, tuple[float, Any]] = {}
_STORE_LOCK = threading.Lock()


def cache_get(key: str, ttl: float):
    """Return cached value if newer than ttl seconds, else None."""
    with _STORE_LOCK:
        item = STORE.get(key)
        if item and (time.time() - item[0]) < ttl:
            return item[1]
    return None


def cache_set(key: str, value: Any) -> None:
    with _STORE_LOCK:
        STORE[key] = (time.time(), value)


def cache_get_stale(key: str):
    """Return last cached value regardless of age (stale fallback), else None."""
    with _STORE_LOCK:
        item = STORE.get(key)
        return item[1] if item else None


def cache_invalidate(key: str) -> None:
    """Remove a key from the in-memory cache (for manual invalidation)."""
    with _STORE_LOCK:
        STORE.pop(key, None)
