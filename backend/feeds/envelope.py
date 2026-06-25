"""Shared feed response envelope contract (Phase 0 safety net).

Bridges today hand-build similar dicts; this module validates the observability
fields that /api/health, trust probes, and STAC feed snapshots rely on.
Phase 2 can promote these helpers into a FeedConnector runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Fields /api/health extracts from feed_cache JSON (see main.py health builder).
HEALTH_META_KEYS = frozenset(
    {
        "count",
        "source",
        "sources",
        "updated",
        "error",
        "stale",
        "demo_mode",
        "geocoded",
    }
)

# Rows returned under /api/health → feeds[key]
HEALTH_ROW_KEYS = frozenset(
    {
        "cached_at",
        "age_sec",
        "ttl_sec",
        "fresh",
        "status",
    }
)


def extract_health_feed_meta(val: dict[str, Any]) -> dict[str, Any]:
    """Mirror /api/health feed_cache meta extraction."""
    meta: dict[str, Any] = {}
    if "count" in val:
        meta["count"] = val.get("count")
    src = val.get("source") or val.get("sources")
    if src is not None:
        meta["source"] = src
    if "updated" in val:
        meta["updated"] = val.get("updated")
    if val.get("error"):
        meta["error"] = val.get("error")
    if "stale" in val:
        meta["stale"] = val.get("stale")
    if "demo_mode" in val:
        meta["demo_mode"] = val.get("demo_mode")
    geocoded = val.get("geocoded") or val.get("count_mapped")
    if geocoded is not None:
        meta["geocoded"] = geocoded
    return meta


def _has_provenance(payload: dict[str, Any]) -> bool:
    src = payload.get("source")
    if isinstance(src, str) and src.strip():
        return True
    sources = payload.get("sources")
    if isinstance(sources, list) and sources:
        return True
    upstream = payload.get("upstream")
    if isinstance(upstream, list) and upstream:
        return True
    return False


def validate_feed_payload(payload: Any, *, endpoint: str = "") -> list[str]:
    """Return contract violations (empty list = ok). No network."""
    prefix = f"{endpoint}: " if endpoint else ""
    if not isinstance(payload, dict):
        return [f"{prefix}payload must be a dict"]

    violations: list[str] = []

    if "count" not in payload:
        violations.append(f"{prefix}missing count")
    else:
        count = payload["count"]
        if not isinstance(count, int) or count < 0:
            violations.append(f"{prefix}count must be a non-negative int")

    if not _has_provenance(payload):
        # Maritime and some edge payloads use demo_mode / stream flags instead.
        if not payload.get("demo_mode") and payload.get("stream_connected") is None:
            violations.append(f"{prefix}missing source, sources, or upstream")

    if "stale" in payload and not isinstance(payload["stale"], bool):
        violations.append(f"{prefix}stale must be bool when present")

    if (
        "error" in payload
        and payload["error"] is not None
        and not isinstance(payload["error"], str)
    ):
        violations.append(f"{prefix}error must be str or null when present")

    if (
        "updated" in payload
        and payload["updated"] is not None
        and not isinstance(payload["updated"], str)
    ):
        violations.append(f"{prefix}updated must be str when present")

    return violations


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FeedEnvelope:
    """Observability fields shared by /api/health, trust probes, and STAC feeds."""

    count: int
    source: str | None = None
    sources: list[str] | None = None
    upstream: list[str] | None = None
    updated: str | None = None
    stale: bool = False
    error: str | None = None
    cached_at: str | None = None
    demo_mode: bool | None = None
    stream_connected: bool | None = None
    geocoded: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def merge(self, **fields: Any) -> dict[str, Any]:
        """Build a contract-shaped payload dict (extra bridge fields last)."""
        return build_feed_envelope(self, **fields)


def build_feed_envelope(envelope: FeedEnvelope, **fields: Any) -> dict[str, Any]:
    """Assemble a feed payload from envelope observability fields + bridge data."""
    out: dict[str, Any] = {"count": envelope.count}
    if envelope.source is not None:
        out["source"] = envelope.source
    if envelope.sources is not None:
        out["sources"] = envelope.sources
    if envelope.upstream is not None:
        out["upstream"] = envelope.upstream
    updated = envelope.updated or utc_now_iso()
    out["updated"] = updated
    if envelope.cached_at is not None:
        out["cached_at"] = envelope.cached_at
    if envelope.stale:
        out["stale"] = True
    if envelope.error is not None:
        out["error"] = envelope.error
    elif "error" not in fields:
        out["error"] = None
    if envelope.demo_mode is not None:
        out["demo_mode"] = envelope.demo_mode
    if envelope.stream_connected is not None:
        out["stream_connected"] = envelope.stream_connected
    if envelope.geocoded is not None:
        out["geocoded"] = envelope.geocoded
    if envelope.extra:
        out.update(envelope.extra)
    out.update(fields)
    return out


def validate_health_feed_row(row: Any, *, cache_key: str = "") -> list[str]:
    """Validate a single /api/health feeds[cache_key] row."""
    prefix = f"{cache_key}: " if cache_key else ""
    if not isinstance(row, dict):
        return [f"{prefix}row must be a dict"]

    violations: list[str] = []
    for key in ("cached_at", "age_sec", "ttl_sec", "fresh", "status"):
        if key not in row:
            violations.append(f"{prefix}missing {key}")

    if (
        "fresh" in row
        and row["fresh"] is not None
        and not isinstance(row["fresh"], bool)
    ):
        violations.append(f"{prefix}fresh must be bool or null")

    if "status" in row and row["status"] not in (
        None,
        "fresh",
        "warn",
        "stale",
        "unknown",
    ):
        violations.append(f"{prefix}unexpected status {row['status']!r}")

    return violations


def validate_health_feeds(feeds: Any) -> list[str]:
    """Validate every /api/health feeds[...] row against the structural contract.

    Lenient on count/provenance because many live feeds legitimately store
    ``count: null`` (e.g. airquality, weather, markets). Catches drift in the
    health builder itself: missing cached_at/status, bad status enum, bad types.
    """
    if not isinstance(feeds, dict):
        return ["feeds must be a dict"]
    violations: list[str] = []
    for cache_key, row in feeds.items():
        violations.extend(validate_health_feed_row(row, cache_key=str(cache_key)))
    return violations
