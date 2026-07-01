"""Cache stampede protection — coalesce concurrent cache-misses into a single upstream fetch.

When multiple concurrent requests miss the cache for the same key, only the first
request triggers the upstream fetch. All concurrent waiters share the same
``asyncio.Future`` and receive the result simultaneously.

Integration:
    from cache_coalesce import cached_fetch_json

    data = await cached_fetch_json(
        key="eonet",
        ttl=300,
        fetcher=lambda: _fetch_eonet(),
    )

Works with the existing ``runtime_cache`` in-memory store and ``feed_registry``
SQLite persistence.  When ``WORLDBASE_CACHE_COALESCE=0`` (default on), the
module is a thin pass-through that still caches but does not coalesce.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable

import runtime_cache
import feed_registry

_log = logging.getLogger("worldbase.cache_coalesce")

# Feature flag
_ENABLED = os.getenv("WORLDBASE_CACHE_COALESCE", "1").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# In-flight futures: key -> asyncio.Future
# Concurrent callers for the same key await the same future.
_inflight: dict[str, asyncio.Future[Any]] = {}
_inflight_lock = asyncio.Lock()


async def cached_fetch_json(
    key: str,
    ttl: float,
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
    *,
    persist: bool = False,
) -> dict[str, Any]:
    """Return cached JSON for *key*, or fetch via *fetcher* and cache the result.

    If multiple coroutines call this with the same *key* simultaneously and the
    cache is empty/stale, only the first one invokes *fetcher*. The others
    await the same future and receive the identical result.

    Args:
        key: Cache key (same namespace as ``runtime_cache``).
        ttl: Time-to-live in seconds. ``0`` means always fetch.
        fetcher: Async callable that performs the upstream fetch.
        persist: If ``True``, also write to ``feed_registry`` (SQLite/disk).

    Returns:
        The cached or freshly-fetched payload dict.
    """
    # Fast path: cache hit
    if ttl > 0:
        cached = runtime_cache.cache_get(key, ttl=ttl)
        if cached is not None:
            return cached

    # Cache miss — coalesce or direct fetch
    if not _ENABLED:
        return await _do_fetch(key, ttl, fetcher, persist)

    # Try to register as the leader for this key
    is_leader = False
    waiter_future: asyncio.Future[dict[str, Any]] | None = None

    await _inflight_lock.acquire()
    try:
        # Double-check cache after acquiring lock
        if ttl > 0:
            cached = runtime_cache.cache_get(key, ttl=ttl)
            if cached is not None:
                return cached

        existing = _inflight.get(key)
        if existing is not None and not existing.done():
            # We're a waiter — await the existing future
            _log.debug("cache_coalesce_wait key=%s", key)
            waiter_future = existing
        else:
            # We're the leader — create a future
            is_leader = True
            waiter_future = asyncio.get_event_loop().create_future()
            _inflight[key] = waiter_future
    finally:
        _inflight_lock.release()

    if is_leader:
        # Leader: do the fetch, then resolve the future
        try:
            result = await _do_fetch(key, ttl, fetcher, persist)
            if not waiter_future.done():
                waiter_future.set_result(result)
            return result
        except Exception as exc:
            if not waiter_future.done():
                waiter_future.set_exception(exc)
            raise
        finally:
            async with _inflight_lock:
                _inflight.pop(key, None)
    else:
        # Waiter: await the leader's result
        return await waiter_future


async def _do_fetch(
    key: str,
    ttl: float,
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
    persist: bool,
) -> dict[str, Any]:
    """Perform the actual upstream fetch and cache the result."""
    payload = await fetcher()
    # Write to in-memory cache
    runtime_cache.cache_set(key, payload)
    # Optionally persist to SQLite/disk
    if persist:
        try:
            feed_registry.write_auto(key, payload)
        except Exception as exc:
            _log.warning("cache_coalesce_persist_failed key=%s error=%s", key, exc)
    return payload


def get_inflight_count() -> int:
    """Return the number of currently in-flight coalesced requests."""
    return len(_inflight)


def is_coalescing_enabled() -> bool:
    """Return True if cache coalescing is enabled."""
    return _ENABLED


def clear_inflight() -> None:
    """Clear all in-flight futures (for testing)."""
    _inflight.clear()
