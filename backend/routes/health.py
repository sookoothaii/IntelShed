"""Health + liveness endpoints — /api/health/ping, /api/health.

Extracted from main.py (Phase 1 decortication). Reports DB connectivity, the
feed_cache freshness table (age/ttl/status per key), FtM graph status, and
credential coverage. Uses feed_registry.db_path() so it stays decoupled from
main.py's get_db()/DB_PATH.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter

import feed_registry
from connector_registry import feed_ttl_sec as _feed_ttl_sec

router = APIRouter(tags=["health"])


def _feed_status(age_sec: float | None) -> str:
    """fresh | warn | stale | unknown"""
    if age_sec is None:
        return "unknown"
    if age_sec < 300:
        return "fresh"
    if age_sec < 3600:
        return "warn"
    return "stale"


@router.get("/api/health/ping")
async def health_ping():
    """Fast liveness probe for the HUD status bar (no feed parsing)."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@router.get("/api/health")
async def health():
    db_file = feed_registry.db_path()

    # Determine database type
    db_type = "sqlite"
    db_connected = False
    if os.getenv("DATABASE_URL"):
        db_type = "postgresql" if "postgresql" in os.getenv("DATABASE_URL", "").lower() else "other"
        # Test connection
        try:
            from db.database import health_check as pg_health
            db_connected = await pg_health()
        except Exception:
            db_connected = False
    else:
        # Test SQLite
        try:
            conn = sqlite3.connect(db_file, timeout=2.0)
            conn.execute("SELECT 1")
            conn.close()
            db_connected = True
        except Exception:
            db_connected = False

    def _build():
        now = datetime.now(timezone.utc)
        feeds = {}
        try:
            conn = sqlite3.connect(db_file, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")
            c = conn.cursor()
            c.execute("SELECT key, value, cached_at FROM feed_cache ORDER BY key")
            for key, value_json, cached_at in c.fetchall():
                meta: dict = {}
                if value_json and len(value_json) < 120_000:
                    try:
                        val = json.loads(value_json)
                        if isinstance(val, dict):
                            from feeds.envelope import extract_health_feed_meta

                            meta.update(extract_health_feed_meta(val))
                    except Exception:
                        pass
                try:
                    age = (now - datetime.fromisoformat(cached_at)).total_seconds()
                    ttl = _feed_ttl_sec(key)
                    feeds[key] = {
                        "cached_at": cached_at,
                        "age_sec": round(age, 1),
                        "ttl_sec": ttl,
                        "fresh": age < ttl,
                        "status": _feed_status(age),
                        **meta,
                    }
                except Exception:
                    feeds[key] = {"cached_at": cached_at, "age_sec": None, "fresh": None, "status": "unknown", **meta}
            conn.close()
        except Exception:
            pass
        fresh_n = sum(1 for f in feeds.values() if f.get("fresh"))
        stale_n = sum(1 for f in feeds.values() if f.get("status") == "stale")
        err_n = sum(1 for f in feeds.values() if f.get("error"))
        try:
            from credentials.registry import is_configured, provider_for_feed

            for fk, fm in feeds.items():
                pid = provider_for_feed(fk)
                if pid:
                    fm["provider_id"] = pid
                    fm["key_configured"] = is_configured(pid)
        except Exception:
            pass
        return {
            "status": "ok",
            "time": now.isoformat(),
            "feeds": feeds,
            "feed_count": len(feeds),
            "feeds_fresh": fresh_n,
            "feeds_stale": stale_n,
            "feeds_error": err_n,
        }

    result = await asyncio.to_thread(_build)
    result["database"] = db_type
    result["db_connected"] = db_connected
    try:
        import ftm_store
        result["ftm"] = ftm_store.store_status()
    except Exception:
        result["ftm"] = {"ready": False, "error": "unavailable"}
    try:
        from credentials.registry import providers_status
        result["credentials"] = {
            "configured": providers_status()["configured"],
            "total": providers_status()["count"],
            "url": "/api/credentials/status",
        }
    except Exception:
        pass
    return result
