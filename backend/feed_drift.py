"""Feed count drift — SQL snapshots on feed_cache (no WhyLogs dependency)."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_DRIFT_RATIO = float(os.getenv("WORLDBASE_FEED_DRIFT_RATIO", "0.1"))
_MIN_BASELINE = int(os.getenv("WORLDBASE_FEED_DRIFT_MIN_COUNT", "5"))
_SNAPSHOT_INTERVAL_S = float(os.getenv("WORLDBASE_FEED_DRIFT_SNAPSHOT_INTERVAL_S", "3600"))
_BASELINE_MIN_AGE_S = float(os.getenv("WORLDBASE_FEED_DRIFT_BASELINE_MIN_AGE_S", "6")) * 3600.0
_BASELINE_MAX_AGE_S = float(os.getenv("WORLDBASE_FEED_DRIFT_BASELINE_MAX_AGE_S", "48")) * 3600.0

_DEFAULT_WATCH = (
    "gdacs_v3",
    "quakes:day",
    "cve",
    "wildfires",
    "outages",
    "pegel",
    "energy_de",
    "hazards",
)


def _watch_keys() -> tuple[str, ...]:
    raw = os.getenv("WORLDBASE_FEED_DRIFT_WATCH", "")
    if raw.strip():
        return tuple(k.strip() for k in raw.split(",") if k.strip())
    return _DEFAULT_WATCH


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_drift_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS feed_count_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL,
                count INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feed_snap_key_time
                ON feed_count_snapshots(cache_key, recorded_at);
        """)
        conn.commit()


def extract_count(payload: dict[str, Any] | None) -> int | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("count")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    for field in (
        "items",
        "articles",
        "alerts",
        "events",
        "earthquakes",
        "volcanoes",
        "vulnerabilities",
        "cities",
    ):
        arr = payload.get(field)
        if isinstance(arr, list):
            return len(arr)
    return None


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _read_feed_cache(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute("SELECT key, value, cached_at FROM feed_cache ORDER BY key"):
        meta: dict[str, Any] = {"cached_at": row["cached_at"]}
        try:
            val = json.loads(row["value"] or "{}")
            if isinstance(val, dict):
                meta["payload"] = val
                meta["count"] = extract_count(val)
                meta["error"] = val.get("error")
                meta["stale"] = val.get("stale")
                meta["source"] = val.get("source") or val.get("sources")
        except Exception:
            meta["payload"] = None
            meta["count"] = None
        out[row["key"]] = meta
    return out


def record_snapshots(conn: sqlite3.Connection, feeds: dict[str, dict[str, Any]], now: datetime) -> int:
    n = 0
    for key, meta in feeds.items():
        count = meta.get("count")
        if count is None:
            continue
        last = conn.execute(
            """
            SELECT recorded_at FROM feed_count_snapshots
            WHERE cache_key = ?
            ORDER BY recorded_at DESC
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if last:
            last_ts = _parse_ts(last["recorded_at"])
            if last_ts and (now - last_ts).total_seconds() < _SNAPSHOT_INTERVAL_S:
                continue
        conn.execute(
            "INSERT INTO feed_count_snapshots (cache_key, count, recorded_at) VALUES (?, ?, ?)",
            (key, int(count), now.isoformat()),
        )
        n += 1
    return n


def _baseline_for_key(
    conn: sqlite3.Connection,
    key: str,
    now: datetime,
) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT count, recorded_at FROM feed_count_snapshots
        WHERE cache_key = ?
        ORDER BY recorded_at DESC
        LIMIT 50
        """,
        (key,),
    ).fetchall()
    for row in rows:
        ts = _parse_ts(row["recorded_at"])
        if not ts:
            continue
        age_s = (now - ts).total_seconds()
        if _BASELINE_MIN_AGE_S <= age_s <= _BASELINE_MAX_AGE_S:
            return {"count": int(row["count"]), "recorded_at": row["recorded_at"], "age_hours": round(age_s / 3600, 1)}
    return None


def detect_drift(feeds: dict[str, dict[str, Any]], conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    drifting: list[dict[str, Any]] = []
    watch = set(_watch_keys())
    for key in watch:
        meta = feeds.get(key)
        if not meta:
            continue
        current = meta.get("count")
        if current is None:
            continue
        baseline = _baseline_for_key(conn, key, now)
        if not baseline:
            continue
        prev = int(baseline["count"])
        curr = int(current)
        if prev < _MIN_BASELINE:
            continue
        if curr < prev * _DRIFT_RATIO:
            drop_pct = round(100.0 * (1.0 - curr / prev), 1) if prev else 0.0
            drifting.append(
                {
                    "cache_key": key,
                    "previous_count": prev,
                    "current_count": curr,
                    "drop_pct": drop_pct,
                    "baseline_at": baseline["recorded_at"],
                    "baseline_age_hours": baseline["age_hours"],
                    "error": meta.get("error"),
                }
            )
    return drifting


def build_freshness(feeds: dict[str, dict[str, Any]], now: datetime, *, limit: int = 12) -> list[dict[str, Any]]:
    from connector_registry import CONNECTOR_CATALOG, feed_ttl_sec

    key_to_connector: dict[str, str] = {}
    for cid, spec in CONNECTOR_CATALOG.items():
        if spec.cache_key:
            key_to_connector[spec.cache_key] = cid

    rows: list[dict[str, Any]] = []
    watch = _watch_keys()
    for key in watch:
        meta = feeds.get(key)
        if not meta:
            rows.append({"cache_key": key, "connector_id": key_to_connector.get(key), "status": "missing"})
            continue
        cached_at = _parse_ts(meta.get("cached_at"))
        age_sec = round((now - cached_at).total_seconds(), 1) if cached_at else None
        ttl = feed_ttl_sec(key)
        fresh = age_sec is not None and age_sec < ttl
        err = meta.get("error")
        stale = bool(meta.get("stale"))
        if err:
            status = "error"
        elif stale:
            status = "stale"
        elif fresh:
            status = "fresh"
        elif age_sec is not None and age_sec < ttl * 2:
            status = "aging"
        else:
            status = "stale"
        rows.append(
            {
                "cache_key": key,
                "connector_id": key_to_connector.get(key),
                "count": meta.get("count"),
                "age_sec": age_sec,
                "ttl_sec": ttl,
                "fresh": fresh,
                "status": status,
                "source": meta.get("source"),
                "error": str(err)[:80] if err else None,
            }
        )
    return rows[:limit]


def check_feed_drift() -> dict[str, Any]:
    """Snapshot counts, detect >90% drops vs 6–48h baseline, summarize freshness."""
    now = datetime.now(timezone.utc)
    init_drift_db()
    with _conn() as conn:
        feeds = _read_feed_cache(conn)
        recorded = record_snapshots(conn, feeds, now)
        drifting = detect_drift(feeds, conn, now)
        conn.commit()
    freshness = build_freshness(feeds, now)
    ok = len(drifting) == 0
    detail = "no drift" if ok else f"{len(drifting)} feed(s) dropped >{int((1 - _DRIFT_RATIO) * 100)}%"
    return {
        "ok": ok,
        "detail": detail,
        "drifting": drifting,
        "freshness": freshness,
        "snapshots_recorded": recorded,
        "watch_keys": list(_watch_keys()),
        "threshold_ratio": _DRIFT_RATIO,
        "min_baseline_count": _MIN_BASELINE,
    }
