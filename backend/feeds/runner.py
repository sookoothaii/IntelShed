"""Phase 2 feed connector runner — TTL cache, stale fallback, feed_cache persist."""

from __future__ import annotations

import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

import feed_registry

from feeds.envelope import FeedEnvelope, utc_now_iso, validate_feed_payload


def _warn_violations(cache_key: str, violations: list[str]) -> None:
    """Surface envelope contract drift on stderr (fail-soft: never raises)."""
    if violations:
        print(
            f"[feed-contract] {cache_key} drift: {violations}",
            file=sys.stderr,
            flush=True,
        )


class FeedConnector:
    """Shared fetch/cache/persist shell for HTTP JSON feed bridges."""

    def __init__(
        self,
        cache_key: str,
        *,
        ttl_sec: float = 600.0,
        default_source: str | None = None,
    ) -> None:
        self.cache_key = cache_key
        self.ttl_sec = ttl_sec
        self.default_source = default_source
        self._mem: dict[str, tuple[float, dict[str, Any]]] = {}

    def _slot(self, subkey: str = "") -> str:
        return subkey or self.cache_key

    def get_cached(self, subkey: str = "") -> dict[str, Any] | None:
        hit = self._mem.get(self._slot(subkey))
        if hit and (time.time() - hit[0]) < self.ttl_sec:
            return hit[1]
        return None

    def set_cached(self, payload: dict[str, Any], subkey: str = "") -> None:
        self._mem[self._slot(subkey)] = (time.time(), payload)

    def peek_memory(self, subkey: str = "") -> dict[str, Any] | None:
        """Last in-memory payload regardless of TTL (stale-while-revalidate)."""
        hit = self._mem.get(self._slot(subkey))
        return hit[1] if hit else None

    def read_disk(self) -> dict[str, Any] | None:
        return feed_registry.read(self.cache_key)

    def empty_payload(
        self, error: str, *, source: str | None = None, **extra: Any
    ) -> dict[str, Any]:
        env = FeedEnvelope(
            count=0,
            source=source or self.default_source,
            updated=utc_now_iso(),
            stale=False,
            error=error,
        )
        return env.merge(**extra)

    def build(
        self,
        envelope: FeedEnvelope,
        *,
        persist: bool = True,
        subkey: str = "",
        **fields: Any,
    ) -> dict[str, Any]:
        """Finalize envelope payload: validate, memory-cache, optional feed_cache write."""
        payload = envelope.merge(**fields)
        if envelope.source is None and envelope.sources is None and self.default_source:
            payload.setdefault("source", self.default_source)
        _warn_violations(
            self.cache_key, validate_feed_payload(payload, endpoint=self.cache_key)
        )
        if persist and not payload.get("stale") and not payload.get("error"):
            feed_registry.write_auto(self.cache_key, payload)
        self.set_cached(payload, subkey)
        return payload

    def stale_from_memory(self, error: str, subkey: str = "") -> dict[str, Any] | None:
        hit = self._mem.get(self._slot(subkey))
        if not hit:
            return None
        out = dict(hit[1])
        out["stale"] = True
        out["error"] = error
        return out

    def stale_from_disk(self, error: str) -> dict[str, Any] | None:
        row = self.read_disk()
        if not row:
            return None
        return {**row, "stale": True, "error": error}

    async def run(
        self,
        fetch: Callable[[], Awaitable[dict[str, Any]]],
        *,
        subkey: str = "",
        persist: bool = True,
    ) -> dict[str, Any]:
        """TTL hit → fetch → stale memory/disk → empty error payload."""
        cached = self.get_cached(subkey)
        if cached is not None:
            return cached
        # J5: hard stop if quota exceeded — serve stale instead of fetching
        try:
            import quota_monitor
            if quota_monitor.is_quota_exceeded(self.cache_key):
                stale = self.stale_from_memory("quota_exceeded") or self.stale_from_disk("quota_exceeded")
                if stale:
                    return stale
                return self.empty_payload("quota_exceeded", source=self.default_source)
        except Exception:
            pass
        try:
            payload = await fetch()
            # J5: record API call for quota tracking
            try:
                import quota_monitor
                quota_monitor.record_call(self.cache_key)
            except Exception:
                pass
            if "updated" not in payload:
                payload["updated"] = utc_now_iso()
            if self.default_source:
                payload.setdefault("source", self.default_source)
            _warn_violations(
                self.cache_key, validate_feed_payload(payload, endpoint=self.cache_key)
            )
            if persist and not payload.get("stale") and not payload.get("error"):
                # Disk persists under cache_key only; subkey segments memory.
                # A subkeyed feed's disk stale-fallback returns the last-written
                # window (self-labeled via payload fields) — acceptable degraded mode.
                feed_registry.write_auto(self.cache_key, payload)
            self.set_cached(payload, subkey)
            return payload
        except Exception as exc:
            err = str(exc)
            stale = self.stale_from_memory(err, subkey) or self.stale_from_disk(err)
            if stale:
                return stale
            return self.empty_payload(err)
