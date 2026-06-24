"""Shared feed_cache persistence for observability (/api/health).

Supports both SQLite (legacy) and PostgreSQL (via SQLAlchemy).
PostgreSQL is used when DATABASE_URL is set.
"""

from __future__ import annotations

import json
import os
import sqlite3
import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Legacy SQLite support (fallback)
def db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def write(key: str, payload: dict) -> None:
    """Persist feed snapshot for health dashboard and stale fallback.

    Uses SQLite as default. For PostgreSQL, use async_write() instead.
    """
    try:
        from connector_registry import feed_ttl_sec

        ttl = int(feed_ttl_sec(key))
        conn = sqlite3.connect(db_path())
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO feed_cache (key, value, cached_at, ttl_seconds) VALUES (?, ?, ?, ?)",
            (key, json.dumps(payload), datetime.now(timezone.utc).isoformat(), ttl),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def read(key: str) -> dict | None:
    """Read feed snapshot from SQLite cache."""
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


# PostgreSQL async support (new)
async def async_write(session: AsyncSession, key: str, payload: dict) -> None:
    """Async write feed cache using SQLAlchemy session.
    
    Usage:
        async with get_db_context() as db:
            await async_write(db, "feed_name", data)
    """
    try:
        from db.models import FeedCache
        from sqlalchemy import select
        
        # Check if entry exists
        result = await session.execute(
            select(FeedCache).where(FeedCache.key == key)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            existing.value_json = payload
            existing.cached_at = datetime.now(timezone.utc)
        else:
            new_cache = FeedCache(
                key=key,
                value_json=payload,
                cached_at=datetime.now(timezone.utc),
            )
            session.add(new_cache)
        
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def async_read(session: AsyncSession, key: str) -> dict | None:
    """Async read feed cache using SQLAlchemy session.
    
    Usage:
        async with get_db_context() as db:
            data = await async_read(db, "feed_name")
    """
    try:
        from db.models import FeedCache
        from sqlalchemy import select
        
        result = await session.execute(
            select(FeedCache).where(FeedCache.key == key)
        )
        cache_entry = result.scalar_one_or_none()
        
        if cache_entry:
            return cache_entry.value_json
    except Exception:
        pass
    return None


def is_postgres_mode() -> bool:
    """Check if PostgreSQL mode is enabled via DATABASE_URL."""
    return bool(os.getenv("DATABASE_URL", "").strip())


# Unified write function (auto-detects database)
def write_auto(key: str, payload: dict) -> None:
    """Write feed cache with automatic backend detection.
    
    Uses PostgreSQL if DATABASE_URL is set, otherwise SQLite.
    Handles async PostgreSQL transparently in sync context.
    """
    if is_postgres_mode():
        try:
            from db.database import get_db_context
            
            async def _write():
                async with get_db_context() as db:
                    await async_write(db, key, payload)
            
            try:
                # Try to get existing event loop
                loop = asyncio.get_running_loop()
                # Schedule in background if loop is running
                asyncio.create_task(_write())
            except RuntimeError:
                # No loop running, create one
                asyncio.run(_write())
        except Exception:
            # Fallback to SQLite on any error
            write(key, payload)
    else:
        write(key, payload)


# Unified read function (auto-detects database)  
def read_auto(key: str) -> dict | None:
    """Read feed cache with automatic backend detection.
    
    Uses PostgreSQL if DATABASE_URL is set, otherwise SQLite.
    Note: PostgreSQL reads in sync context will fallback to SQLite
    for performance (async read should be used directly in async code).
    """
    # For reads, prefer SQLite for simplicity in sync bridges
    # Async code should use async_read() directly
    return read(key)
