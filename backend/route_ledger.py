"""P6a — Route Outcome Ledger for adaptive query router weight adjustment.

Records query router outcomes (route chosen, hit count, user feedback signal)
in a SQLite table and periodically recomputes empirical success rates per route.
A rule-based weight adjuster boosts routes that outperform the baseline.

All operations are fail-soft: any SQLite error is logged and skipped.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Any

from config import get_config

log = logging.getLogger(__name__)

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

_VALID_ROUTES = ("vector", "graph", "spatial", "hybrid", "live")

# In-memory cache of route weights (route -> weight 0.0–1.0)
_route_weights: dict[str, float] = {r: 1.0 / len(_VALID_ROUTES) for r in _VALID_ROUTES}
_last_recompute: float = 0.0
_pending_records: int = 0


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_route_ledger_db() -> None:
    """Create the route_outcomes table if it doesn't exist."""
    try:
        with _conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS route_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    route TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    block_chars INTEGER DEFAULT 0,
                    duration_ms INTEGER DEFAULT 0,
                    success INTEGER,
                    recorded_at TEXT NOT NULL,
                    query_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_route_outcomes_route
                    ON route_outcomes(route);
                CREATE INDEX IF NOT EXISTS idx_route_outcomes_recorded
                    ON route_outcomes(recorded_at);
            """)
            conn.commit()
    except Exception as exc:
        log.warning("route_ledger init failed: %s", exc)


def record_outcome(
    query: str,
    route: str,
    *,
    hit_count: int = 0,
    block_chars: int = 0,
    duration_ms: int = 0,
    success: int | None = None,
) -> None:
    """Record a single routing outcome. Fail-soft."""
    if not get_config().route_ledger_enabled:
        return
    if route not in _VALID_ROUTES:
        return
    global _pending_records
    try:
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        qhash = str(hash(query) & 0xFFFFFFFF)
        with _conn() as conn:
            conn.execute(
                "INSERT INTO route_outcomes "
                "(query, route, hit_count, block_chars, duration_ms, success, recorded_at, query_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    query[:500],
                    route,
                    hit_count,
                    block_chars,
                    duration_ms,
                    success,
                    ts,
                    qhash,
                ),
            )
            conn.commit()
        _pending_records += 1
    except Exception as exc:
        log.warning("route_ledger record failed: %s", exc)


def _compute_success_rate(rows: list[sqlite3.Row]) -> float:
    """Compute empirical success rate from outcome rows."""
    if not rows:
        return 0.5
    total = 0
    scored = 0
    for row in rows:
        s = row["success"]
        if s is not None:
            total += 1
            scored += int(s)
        else:
            # No explicit success signal — use heuristic: hit_count > 0 and block_chars > 200
            total += 1
            if row["hit_count"] > 0 and row["block_chars"] > 200:
                scored += 1
    if total == 0:
        return 0.5
    return scored / total


def recompute_weights() -> dict[str, float]:
    """Recompute route weights from empirical success rates.

    Called lazily when _pending_records >= recompute_n threshold.
    Returns the new weight dict.
    """
    global _route_weights, _last_recompute, _pending_records

    try:
        with _conn() as conn:
            # Look at last 500 outcomes per route
            weights: dict[str, float] = {}
            for route in _VALID_ROUTES:
                rows = conn.execute(
                    "SELECT hit_count, block_chars, success FROM route_outcomes "
                    "WHERE route = ? ORDER BY id DESC LIMIT 500",
                    (route,),
                ).fetchall()
                rate = _compute_success_rate(rows)
                # Smooth: blend empirical with prior (0.5)
                weights[route] = 0.3 * 0.5 + 0.7 * rate

            # Normalize so weights sum to 1.0
            total = sum(weights.values())
            if total > 0:
                weights = {r: w / total for r, w in weights.items()}
            else:
                weights = {r: 1.0 / len(_VALID_ROUTES) for r in _VALID_ROUTES}

            _route_weights = weights
            _last_recompute = time.monotonic()
            _pending_records = 0
            return dict(weights)
    except Exception as exc:
        log.warning("route_ledger recompute failed: %s", exc)
        return dict(_route_weights)


def get_route_weights() -> dict[str, float]:
    """Return current route weights, recomputing if threshold is met."""
    if not get_config().route_ledger_enabled:
        return {r: 1.0 / len(_VALID_ROUTES) for r in _VALID_ROUTES}

    threshold = get_config().route_ledger_recompute_n
    if _pending_records >= threshold:
        recompute_weights()
    return dict(_route_weights)


def get_route_stats() -> dict[str, Any]:
    """Return summary statistics for all routes."""
    try:
        with _conn() as conn:
            stats: dict[str, Any] = {}
            for route in _VALID_ROUTES:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt, "
                    "AVG(hit_count) as avg_hits, "
                    "AVG(block_chars) as avg_chars, "
                    "SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as wins, "
                    "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as losses "
                    "FROM route_outcomes WHERE route = ?",
                    (route,),
                ).fetchone()
                total = row["cnt"] if row else 0
                wins = row["wins"] if row and row["wins"] is not None else 0
                losses = row["losses"] if row and row["losses"] is not None else 0
                scored = wins + losses
                stats[route] = {
                    "total": total,
                    "avg_hits": round(row["avg_hits"], 2)
                    if row and row["avg_hits"]
                    else 0,
                    "avg_chars": round(row["avg_chars"], 2)
                    if row and row["avg_chars"]
                    else 0,
                    "success_rate": round(wins / scored, 3) if scored > 0 else None,
                    "weight": round(_route_weights.get(route, 0), 4),
                }
            stats["_meta"] = {
                "pending_records": _pending_records,
                "recompute_threshold": get_config().route_ledger_recompute_n,
                "last_recompute_ts": _last_recompute,
                "enabled": get_config().route_ledger_enabled,
            }
            return stats
    except Exception as exc:
        log.warning("route_ledger stats failed: %s", exc)
        return {"error": str(exc)[:200]}
