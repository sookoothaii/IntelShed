"""API quota tracking + cost monitor (J5).

Records per-source per-day API calls in SQLite `api_quota` table.
Enforces configurable daily limits with hard stop at 100%.
Integrates with I4 alerting at 80% threshold.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from structured_log import get_logger

log = get_logger("quota_monitor")

_ALERT_THRESHOLD = float(os.getenv("WORLDBASE_QUOTA_ALERT_THRESHOLD", "0.8"))


def _monitor_enabled() -> bool:
    return os.getenv("WORLDBASE_QUOTA_MONITOR", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


# Default daily limits per source (can be overridden via WORLDBASE_QUOTA_LIMIT_{SOURCE})
_DEFAULT_LIMITS: dict[str, int] = {
    "aisstream": 5000,
    "newsdata": 200,
    "opensky": 4000,
    "cesium_ion": 1000000,
    "entsoe": 5000,
    "gdelt": 10000,
    "eonet": 1000,
    "gdacs": 1000,
    "cams": 10000,
    "hdx": 1000,
    "reliefweb": 1000,
    "aishub": 1000,
    "myshiptracking": 1000,
}

# Estimated cost per call (USD) — rough figures for cost dashboard
_COST_PER_CALL: dict[str, float] = {
    "aisstream": 0.0,
    "newsdata": 0.001,
    "opensky": 0.0,
    "cesium_ion": 0.0,
    "entsoe": 0.0,
    "gdelt": 0.0,
    "eonet": 0.0,
    "gdacs": 0.0,
    "cams": 0.0,
    "hdx": 0.0,
}


def _db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


def monitor_enabled() -> bool:
    return _monitor_enabled()


def _get_limit(source: str) -> int:
    env_key = f"WORLDBASE_QUOTA_LIMIT_{source.upper()}"
    env_val = os.getenv(env_key)
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return _DEFAULT_LIMITS.get(source.lower(), 0)


def _get_cost_per_call(source: str) -> float:
    return _COST_PER_CALL.get(source.lower(), 0.0)


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def init_quota_db() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_quota (
                source       TEXT NOT NULL,
                endpoint     TEXT NOT NULL,
                day          TEXT NOT NULL,
                count        INTEGER DEFAULT 0,
                limit_val    INTEGER DEFAULT 0,
                cost_usd_est REAL DEFAULT 0.0,
                last_call_at REAL DEFAULT 0,
                PRIMARY KEY (source, endpoint, day)
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("quota_init_failed", error=str(exc))


def record_call(source: str, endpoint: str = "") -> None:
    """Record one API call for a source. Fail-soft — never raises."""
    if not _monitor_enabled():
        return
    try:
        day = _utc_day()
        now = time.time()
        limit = _get_limit(source)
        cost = _get_cost_per_call(source)
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            INSERT INTO api_quota (source, endpoint, day, count, limit_val, cost_usd_est, last_call_at)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            ON CONFLICT(source, endpoint, day)
            DO UPDATE SET count = count + 1,
                          cost_usd_est = cost_usd_est + ?,
                          last_call_at = ?
            """,
            (source, endpoint, day, limit, cost, now, cost, now),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.debug("quota_record_failed", error=str(exc))


def is_quota_exceeded(source: str) -> bool:
    """Check if source has hit its daily limit. Returns False if no limit configured."""
    if not monitor_enabled():
        return False
    limit = _get_limit(source)
    if limit <= 0:
        return False
    try:
        day = _utc_day()
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT count FROM api_quota WHERE source = ? AND day = ?",
            (source, day),
        ).fetchone()
        conn.close()
        if row and row[0] >= limit:
            return True
    except Exception:
        pass
    return False


def get_usage(source: str, day: str | None = None) -> dict[str, Any]:
    """Get current usage for a source on a given day (default: today)."""
    day = day or _utc_day()
    limit = _get_limit(source)
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(
            "SELECT endpoint, count, cost_usd_est, last_call_at FROM api_quota WHERE source = ? AND day = ?",
            (source, day),
        ).fetchall()
        conn.close()
        total_count = sum(r[1] for r in rows)
        total_cost = sum(r[2] for r in rows)
        return {
            "source": source,
            "day": day,
            "count": total_count,
            "limit": limit,
            "remaining": max(0, limit - total_count) if limit > 0 else -1,
            "pct": round(total_count / limit, 4) if limit > 0 else 0.0,
            "cost_usd_est": round(total_cost, 6),
            "exceeded": total_count >= limit if limit > 0 else False,
            "endpoints": [
                {
                    "endpoint": r[0],
                    "count": r[1],
                    "cost_usd_est": r[2],
                    "last_call_at": r[3],
                }
                for r in rows
            ],
        }
    except Exception:
        return {
            "source": source,
            "day": day,
            "count": 0,
            "limit": limit,
            "remaining": limit if limit > 0 else -1,
            "pct": 0.0,
            "cost_usd_est": 0.0,
            "exceeded": False,
            "endpoints": [],
        }


def get_quota_status() -> dict[str, Any]:
    """Full quota dashboard: all sources, today's usage, 7-day trend."""
    day = _utc_day()
    sources = set(_DEFAULT_LIMITS.keys())
    # Also include any sources seen in the DB
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute("SELECT DISTINCT source FROM api_quota").fetchall()
        conn.close()
        for r in rows:
            sources.add(r[0])
    except Exception:
        pass

    today = []
    exceeded_sources = []
    for src in sorted(sources):
        usage = get_usage(src, day)
        today.append(usage)
        if usage["exceeded"]:
            exceeded_sources.append(src)

    # 7-day trend
    trend: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(
            """
            SELECT day, source, SUM(count) as total_count, SUM(cost_usd_est) as total_cost
            FROM api_quota
            WHERE day >= date('now', '-7 days')
            GROUP BY day, source
            ORDER BY day DESC, source
            """
        ).fetchall()
        conn.close()
        for r in rows:
            trend.append(
                {
                    "day": r[0],
                    "source": r[1],
                    "count": r[2],
                    "cost_usd_est": round(r[3], 6),
                }
            )
    except Exception:
        pass

    total_cost_today = sum(u["cost_usd_est"] for u in today)
    total_calls_today = sum(u["count"] for u in today)

    return {
        "enabled": monitor_enabled(),
        "day": day,
        "alert_threshold": _ALERT_THRESHOLD,
        "sources": today,
        "quota_exceeded": exceeded_sources,
        "total_calls_today": total_calls_today,
        "total_cost_today_usd": round(total_cost_today, 6),
        "trend_7d": trend,
    }


def check_alerts() -> list[dict[str, Any]]:
    """Check for 80% threshold alerts — integrates with I4 alerting."""
    if not _monitor_enabled():
        return []
    fired: list[dict[str, Any]] = []
    day = _utc_day()
    # Gather all sources: defaults + any seen in DB today
    sources = set(_DEFAULT_LIMITS.keys())
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(
            "SELECT DISTINCT source FROM api_quota WHERE day = ?", (day,)
        ).fetchall()
        conn.close()
        for r in rows:
            sources.add(r[0])
    except Exception:
        pass
    for source in sources:
        usage = get_usage(source, day)
        limit = usage["limit"]
        if limit <= 0:
            continue
        if usage["pct"] >= _ALERT_THRESHOLD and not usage["exceeded"]:
            fired.append(
                {
                    "alert": "quota_80_percent",
                    "severity": "warning",
                    "source": source,
                    "count": usage["count"],
                    "limit": limit,
                    "pct": usage["pct"],
                    "message": f"API quota for {source} at {usage['pct']:.0%} ({usage['count']}/{limit})",
                }
            )
        elif usage["exceeded"]:
            fired.append(
                {
                    "alert": "quota_exceeded",
                    "severity": "critical",
                    "source": source,
                    "count": usage["count"],
                    "limit": limit,
                    "message": f"API quota for {source} exceeded ({usage['count']}/{limit}) — feed stopped",
                }
            )
    return fired
