"""V4-64 Feed Circuit Breaker — per-feed circuit breaking + ETag polling.

Prevents cascading latency by tripping a circuit breaker after N consecutive
failures for each feed. After cooldown, the circuit enters half-open state,
allowing one trial request. On success, the circuit closes; on failure, it
re-opens.

Also provides ETag / Last-Modified tracking for conditional GET support.
Feed pollers can send ``If-None-Match`` and ``If-Modified-Since`` headers
to avoid re-downloading unchanged data.

Feature flag: ``WORLDBASE_FEED_CIRCUIT_BREAKER=1`` (default on).
Config:
    WORLDBASE_FEED_CB_THRESHOLD=5   — consecutive failures to trip
    WORLDBASE_FEED_CB_COOLDOWN=300  — seconds before half-open

Endpoints:
    GET /api/feeds/circuit-breaker  — status per feed
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("worldbase.feed_circuit_breaker")

router = APIRouter(prefix="/api/feeds", tags=["circuit-breaker"])


class CircuitState(str, Enum):
    CLOSED = "closed"  # normal operation
    OPEN = "open"  # tripped, requests blocked
    HALF_OPEN = "half_open"  # cooldown expired, one trial allowed


@dataclass
class FeedCircuit:
    """Per-feed circuit breaker state."""

    feed_id: str
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    last_failure_error: str = ""
    opened_at: float = 0.0
    # ETag / Last-Modified for conditional GET
    etag: str | None = None
    last_modified: str | None = None
    # Stats
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    total_not_modified: int = 0
    last_success_time: float = 0.0

    @property
    def cooldown_remaining(self) -> float:
        if self.state != CircuitState.OPEN:
            return 0.0
        elapsed = time.time() - self.opened_at
        return max(0.0, _COOLDOWN - elapsed)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def circuit_breaker_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_FEED_CIRCUIT_BREAKER", "1"))


_THRESHOLD = int(os.getenv("WORLDBASE_FEED_CB_THRESHOLD", "5"))
_COOLDOWN = float(os.getenv("WORLDBASE_FEED_CB_COOLDOWN", "300"))

_LOCK = threading.Lock()
_CIRCUITS: dict[str, FeedCircuit] = {}


def get_circuit(feed_id: str) -> FeedCircuit:
    """Get or create the circuit breaker for *feed_id*."""
    with _LOCK:
        if feed_id not in _CIRCUITS:
            _CIRCUITS[feed_id] = FeedCircuit(feed_id=feed_id)
        return _CIRCUITS[feed_id]


def can_request(feed_id: str) -> bool:
    """Check if a request is allowed for *feed_id*.

    Returns False when the circuit is OPEN and cooldown hasn't elapsed.
    Returns True when CLOSED or HALF_OPEN (allowing a trial).
    """
    if not circuit_breaker_enabled():
        return True

    circuit = get_circuit(feed_id)
    with _LOCK:
        if circuit.state == CircuitState.OPEN:
            if time.time() - circuit.opened_at >= _COOLDOWN:
                circuit.state = CircuitState.HALF_OPEN
                logger.info(f"circuit_half_open feed={feed_id}")
                return True
            return False
        return True


def record_success(
    feed_id: str,
    etag: str | None = None,
    last_modified: str | None = None,
    not_modified: bool = False,
) -> None:
    """Record a successful request for *feed_id*."""
    if not circuit_breaker_enabled():
        return

    circuit = get_circuit(feed_id)
    with _LOCK:
        circuit.total_requests += 1
        circuit.total_successes += 1
        circuit.last_success_time = time.time()
        if not_modified:
            circuit.total_not_modified += 1

        if circuit.state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
            circuit.state = CircuitState.CLOSED
            circuit.consecutive_failures = 0
            logger.info(f"circuit_closed feed={feed_id}")

        circuit.consecutive_failures = 0

        if etag:
            circuit.etag = etag
        if last_modified:
            circuit.last_modified = last_modified


def record_failure(feed_id: str, error: str = "") -> None:
    """Record a failed request for *feed_id*."""
    if not circuit_breaker_enabled():
        return

    circuit = get_circuit(feed_id)
    with _LOCK:
        circuit.total_requests += 1
        circuit.total_failures += 1
        circuit.consecutive_failures += 1
        circuit.last_failure_time = time.time()
        circuit.last_failure_error = error[:200]

        if circuit.state == CircuitState.HALF_OPEN:
            circuit.state = CircuitState.OPEN
            circuit.opened_at = time.time()
            logger.warning(f"circuit_reopened feed={feed_id} error={error[:100]}")
        elif circuit.consecutive_failures >= _THRESHOLD:
            circuit.state = CircuitState.OPEN
            circuit.opened_at = time.time()
            logger.warning(
                f"circuit_opened feed={feed_id} failures={circuit.consecutive_failures}"
            )


def get_conditional_headers(feed_id: str) -> dict[str, str]:
    """Return If-None-Match / If-Modified-Since headers for conditional GET."""
    if not circuit_breaker_enabled():
        return {}

    circuit = get_circuit(feed_id)
    headers: dict[str, str] = {}
    if circuit.etag:
        headers["If-None-Match"] = circuit.etag
    if circuit.last_modified:
        headers["If-Modified-Since"] = circuit.last_modified
    return headers


def update_conditional_headers(feed_id: str, response_headers: dict[str, Any]) -> None:
    """Extract ETag / Last-Modified from response headers and store them."""
    if not circuit_breaker_enabled():
        return

    etag = None
    last_modified = None
    for k, v in response_headers.items():
        kl = k.lower()
        if kl == "etag":
            etag = str(v)
        elif kl == "last-modified":
            last_modified = str(v)

    if etag or last_modified:
        circuit = get_circuit(feed_id)
        with _LOCK:
            if etag:
                circuit.etag = etag
            if last_modified:
                circuit.last_modified = last_modified


def get_all_circuits() -> dict[str, dict[str, Any]]:
    """Return status of all circuit breakers."""
    with _LOCK:
        out: dict[str, dict[str, Any]] = {}
        for feed_id, circuit in _CIRCUITS.items():
            out[feed_id] = {
                "state": circuit.state.value,
                "consecutive_failures": circuit.consecutive_failures,
                "last_failure_error": circuit.last_failure_error,
                "last_failure_time": (
                    datetime_from_ts(circuit.last_failure_time)
                    if circuit.last_failure_time
                    else None
                ),
                "last_success_time": (
                    datetime_from_ts(circuit.last_success_time)
                    if circuit.last_success_time
                    else None
                ),
                "opened_at": (
                    datetime_from_ts(circuit.opened_at) if circuit.opened_at else None
                ),
                "cooldown_remaining_sec": round(circuit.cooldown_remaining, 1),
                "etag": circuit.etag,
                "last_modified": circuit.last_modified,
                "stats": {
                    "total_requests": circuit.total_requests,
                    "total_failures": circuit.total_failures,
                    "total_successes": circuit.total_successes,
                    "total_not_modified": circuit.total_not_modified,
                },
            }
        return out


def reset_circuit(feed_id: str) -> bool:
    """Manually reset a circuit breaker to closed state."""
    with _LOCK:
        if feed_id in _CIRCUITS:
            circuit = _CIRCUITS[feed_id]
            circuit.state = CircuitState.CLOSED
            circuit.consecutive_failures = 0
            circuit.opened_at = 0.0
            return True
        return False


def _datetime_from_ts(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# Alias for use in get_all_circuits
datetime_from_ts = _datetime_from_ts


@router.get("/circuit-breaker")
async def get_circuit_breaker_status():
    """Circuit breaker status per feed."""
    return JSONResponse(
        content={
            "enabled": circuit_breaker_enabled(),
            "threshold": _THRESHOLD,
            "cooldown_sec": _COOLDOWN,
            "feeds": get_all_circuits(),
        }
    )
