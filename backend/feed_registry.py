"""Shared SQLite feed_cache persistence for observability (/api/health)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone


def db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def write(key: str, payload: dict) -> None:
    """Persist feed snapshot for health dashboard and stale fallback."""
    try:
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO feed_cache (key, value, cached_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def read(key: str) -> dict | None:
    try:
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute("SELECT value FROM feed_cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None
