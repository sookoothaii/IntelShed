"""Phase 2 feed connector runner — TTL cache, stale fallback, feed_cache persist.

Includes a per-feed circuit breaker (3-state: CLOSED → OPEN → HALF_OPEN)
with exponential backoff on repeated failures.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

import feed_registry

from feeds.envelope import FeedEnvelope, utc_now_iso, validate_feed_payload


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-feed circuit breaker with exponential backoff.

    CLOSED → OPEN after *failure_threshold* failures within a rolling window.
    OPEN → HALF_OPEN after *reset_timeout* (doubles on each open, capped at *max_backoff*).
    HALF_OPEN → CLOSED on success, → OPEN on failure.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout_sec: float = 60.0,
        max_backoff_sec: float = 900.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.reset_timeout_sec = reset_timeout_sec
        self.max_backoff_sec = max_backoff_sec
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float = 0.0
        self._current_timeout = reset_timeout_sec
        self._consecutive_opens = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if time.time() - self._opened_at >= self._current_timeout:
                self._state = CircuitState.HALF_OPEN
        return self._state

    @property
    def open_until(self) -> str | None:
        if self.state == CircuitState.OPEN:
            from datetime import datetime, timezone

            ts = self._opened_at + self._current_timeout
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return None

    def record_success(self) -> None:
        self._failures = 0
        self._consecutive_opens = 0
        self._current_timeout = self.reset_timeout_sec
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == CircuitState.HALF_OPEN:
            self._trip_open()
            return
        if self._failures >= self.failure_threshold:
            self._trip_open()

    def _trip_open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.time()
        self._consecutive_opens += 1
        self._current_timeout = min(
            self.reset_timeout_sec * (2 ** (self._consecutive_opens - 1)),
            self.max_backoff_sec,
        )

    def can_attempt(self) -> bool:
        return self.state != CircuitState.OPEN


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
        self._breaker: CircuitBreaker | None = None
        self._cb_init_done = False

    def _ensure_breaker(self) -> CircuitBreaker | None:
        """Lazily create a circuit breaker from config (fail-soft)."""
        if self._cb_init_done:
            return self._breaker
        self._cb_init_done = True
        try:
            from config import get_config

            cfg = get_config()
            if not cfg.feed_circuit_breaker_enabled:
                return None
            self._breaker = CircuitBreaker(
                failure_threshold=cfg.feed_circuit_breaker_failure_threshold,
                reset_timeout_sec=cfg.feed_circuit_breaker_reset_timeout_sec,
                max_backoff_sec=cfg.feed_circuit_breaker_max_backoff_sec,
            )
        except Exception:
            pass
        return self._breaker

    @property
    def circuit_state(self) -> str:
        cb = self._ensure_breaker()
        return cb.state.value if cb else "disabled"

    @property
    def circuit_open_until(self) -> str | None:
        cb = self._ensure_breaker()
        return cb.open_until if cb else None

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
        """TTL hit → fetch → stale memory/disk → empty error payload.

        Circuit breaker skips the fetch call when OPEN, serving stale data instead.
        """
        cached = self.get_cached(subkey)
        if cached is not None:
            return cached
        # J5: hard stop if quota exceeded — serve stale instead of fetching
        try:
            import quota_monitor

            if quota_monitor.is_quota_exceeded(self.cache_key):
                stale = self.stale_from_memory(
                    "quota_exceeded"
                ) or self.stale_from_disk("quota_exceeded")
                if stale:
                    return stale
                return self.empty_payload("quota_exceeded", source=self.default_source)
        except Exception:
            pass

        # Circuit breaker: skip fetch when OPEN, serve stale
        cb = self._ensure_breaker()
        if cb and not cb.can_attempt():
            err = f"circuit_open_until={cb.open_until}"
            stale = self.stale_from_memory(err, subkey) or self.stale_from_disk(err)
            if stale:
                return stale
            return self.empty_payload(err, source=self.default_source)

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
            if cb:
                cb.record_success()
            return payload
        except Exception as exc:
            err = str(exc)
            if cb:
                cb.record_failure()
            stale = self.stale_from_memory(err, subkey) or self.stale_from_disk(err)
            if stale:
                return stale
            return self.empty_payload(err)
