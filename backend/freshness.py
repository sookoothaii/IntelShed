"""Single source of truth for feed freshness classification.

Consumers:
  - routes/health.py   → vocab="health" (fresh/warn/stale/unknown)
  - feed_drift.py      → vocab="drift"  (fresh/aging/stale/error/missing)

The two vocabularies exist for API-contract compatibility: /api/health rows
are validated by feeds.envelope.validate_health_feed_row which expects
fresh/warn/stale/unknown.  feed_drift reports use the richer drift set.
"""

from __future__ import annotations


def classify_freshness(
    age_sec: float | None,
    ttl_sec: float,
    *,
    error: str | None = None,
    stale_flag: bool = False,
    has_payload: bool = True,
    vocab: str = "drift",
) -> str:
    """Classify feed freshness into a status string.

    Parameters
    ----------
    age_sec : seconds since cached_at, or None if unparseable
    ttl_sec : TTL for this feed key
    error   : upstream error string from payload, or None
    stale_flag : payload.stale boolean
    has_payload : False when no cache row exists at all
    vocab   : "drift" (default) or "health"

    Returns
    -------
    str — one of:
      drift:  fresh | aging | stale | error | missing
      health: fresh | warn  | stale | unknown
    """
    if not has_payload:
        return "missing" if vocab == "drift" else "unknown"

    if error:
        return "error" if vocab == "drift" else "stale"

    if stale_flag:
        return "stale"

    if age_sec is None:
        return "unknown" if vocab == "health" else "missing"

    if age_sec < ttl_sec:
        return "fresh"

    if age_sec < ttl_sec * 2:
        return "aging" if vocab == "drift" else "warn"

    return "stale"
