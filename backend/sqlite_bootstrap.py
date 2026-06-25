"""SQLite worldbase.db bootstrap — schema init and feed_cache pruning.

Kept at backend root (not under db/) so imports do not load db/__init__.py
(Postgres ORM package uses backend.db.* paths incompatible with cwd=backend).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import entity_store
import ftm_store

DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

entity_store.set_db_path(DB_PATH)
ftm_store.set_db_path()

_FEED_CACHE_MAX_AGE_SEC = float(
    os.getenv("WORLDBASE_FEED_CACHE_MAX_AGE_SEC", 7 * 24 * 3600)
)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS aircraft (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24 TEXT,
                callsign TEXT,
                origin_country TEXT,
                latitude REAL,
                longitude REAL,
                altitude REAL,
                velocity REAL,
                heading REAL,
                recorded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS satellites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                tle1 TEXT,
                tle2 TEXT,
                recorded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS feed_cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                cached_at TEXT,
                ttl_seconds INTEGER DEFAULT 300
            );
        """)
        # Migrate existing DBs: add ttl_seconds column if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(feed_cache)").fetchall()]
        if "ttl_seconds" not in cols:
            conn.execute(
                "ALTER TABLE feed_cache ADD COLUMN ttl_seconds INTEGER DEFAULT 300"
            )
        # Indexes (after migration so ttl_seconds column always exists)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_cache_cached_at ON feed_cache(cached_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feed_cache_ttl ON feed_cache(ttl_seconds)"
        )
        conn.commit()


def prune_feed_cache(max_age_sec: float = _FEED_CACHE_MAX_AGE_SEC) -> int:
    """Drop feed_cache rows older than max_age_sec. Fail-soft (never raises)."""
    removed: list[str] = []
    try:
        now = datetime.now(timezone.utc)
        with get_db() as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            rows = conn.execute("SELECT key, cached_at FROM feed_cache").fetchall()
            for r in rows:
                try:
                    age = (now - datetime.fromisoformat(r["cached_at"])).total_seconds()
                except Exception:
                    continue
                if age > max_age_sec:
                    removed.append(r["key"])
            for key in removed:
                conn.execute("DELETE FROM feed_cache WHERE key = ?", (key,))
            conn.commit()
        if removed:
            print(
                f"[CACHE] pruned {len(removed)} abandoned feed_cache keys "
                f"(> {max_age_sec / 3600:.0f}h): {removed}",
                flush=True,
            )
    except Exception as e:
        print(f"[CACHE] prune skipped: {e}", flush=True)
    return len(removed)
