"""Webhook alerting with dedup + rate-limit (I4).

Posts JSON alerts to WORLDBASE_ALERT_WEBHOOK when conditions fire.
Dedup via SQLite alert_dedup table: max 1 alert per 15 min per condition.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import httpx


def _db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


_DEDUP_WINDOW_S = int(os.getenv("WORLDBASE_ALERT_DEDUP_S", "900"))  # 15 min


def _webhook_url() -> str | None:
    url = os.getenv("WORLDBASE_ALERT_WEBHOOK", "").strip()
    return url or None


def _init_alert_db() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alert_dedup (
                condition  TEXT PRIMARY KEY,
                last_fired REAL NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _should_fire(condition: str) -> bool:
    """Check dedup table — True if not fired in the dedup window."""
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        c = conn.cursor()
        c.execute(
            "SELECT last_fired FROM alert_dedup WHERE condition = ?", (condition,)
        )
        row = c.fetchone()
        now = time.time()
        if row and (now - row[0]) < _DEDUP_WINDOW_S:
            conn.close()
            return False
        conn.execute(
            "INSERT OR REPLACE INTO alert_dedup (condition, last_fired) VALUES (?, ?)",
            (condition, now),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return True


def _post_webhook(payload: dict[str, Any]) -> bool:
    url = _webhook_url()
    if not url:
        return False
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        return r.status_code < 300
    except Exception:
        return False


def check_and_alert(
    trust_score: int,
    feed_fresh: int,
    feed_stale: int,
    duckdb_queue_backlog: int = 0,
) -> list[dict[str, Any]]:
    """Evaluate alert conditions and fire webhooks if needed.

    Returns list of fired alerts (for logging/testing).
    """
    _init_alert_db()
    fired: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc).isoformat()

    conditions = [
        (
            "trust_score_low",
            trust_score < 3,
            {
                "alert": "trust_score_low",
                "severity": "warning",
                "message": f"Trust score {trust_score}/4 — below threshold",
                "trust_score": trust_score,
                "timestamp": ts,
            },
        ),
        (
            "feeds_stale_majority",
            feed_stale > feed_fresh and feed_fresh > 0,
            {
                "alert": "feeds_stale_majority",
                "severity": "warning",
                "message": f"Stale feeds ({feed_stale}) exceed fresh ({feed_fresh})",
                "feed_fresh": feed_fresh,
                "feed_stale": feed_stale,
                "timestamp": ts,
            },
        ),
        (
            "duckdb_queue_backlog_high",
            duckdb_queue_backlog > 40,
            {
                "alert": "duckdb_queue_backlog_high",
                "severity": "critical",
                "message": f"DuckDB queue backlog {duckdb_queue_backlog} > 40",
                "backlog": duckdb_queue_backlog,
                "timestamp": ts,
            },
        ),
    ]

    for condition_key, should_trigger, payload in conditions:
        if should_trigger and _should_fire(condition_key):
            payload["source"] = "worldbase-pc"
            _post_webhook(payload)
            fired.append(payload)

    return fired
