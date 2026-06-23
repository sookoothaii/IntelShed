"""Aircraft trail persistence — short rolling history per ICAO24.

Once per scan cycle we snapshot the unified aircraft feed and persist
``(icao24, lat, lon, alt, speed, heading, recorded_at)`` rows. The frontend can
then ask for ``/api/aircraft/trails?icao24=…&minutes=30`` and draw the path
behind any clicked aircraft on the Cesium globe.

Design choices:

* Single SQLite table ``aircraft_trail`` with a covering index on
  ``(icao24, recorded_at DESC)``.
* Automatic pruning: rows older than ``AIRCRAFT_TRAIL_MAX_HOURS`` (default 6h)
  are deleted on each snapshot; a hard row cap of
  ``AIRCRAFT_TRAIL_MAX_ROWS`` (default 200_000) protects against runaway
  growth on a busy ADS-B feed.
* No background scheduler from this module — the existing autopilot loop in
  ``main.py`` calls ``snapshot_now()`` periodically.
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from auth.security import verify_lan_auth

import aircraft_provider

router = APIRouter(prefix="/api/aircraft", tags=["aircraft-trails"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_MAX_HOURS = float(os.getenv("AIRCRAFT_TRAIL_MAX_HOURS", "6"))
_MAX_ROWS = int(os.getenv("AIRCRAFT_TRAIL_MAX_ROWS", "200000"))
_MIN_INTERVAL_SEC = float(os.getenv("AIRCRAFT_TRAIL_MIN_INTERVAL", "20"))
_last_snapshot_ts = 0.0


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_trail_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS aircraft_trail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                icao24 TEXT NOT NULL,
                callsign TEXT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                alt REAL,
                speed REAL,
                heading REAL,
                recorded_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_trail_icao_time
                ON aircraft_trail (icao24, recorded_at DESC);
            CREATE INDEX IF NOT EXISTS idx_trail_time
                ON aircraft_trail (recorded_at DESC);
        """)
        conn.commit()


def _decode_state_row(s: list) -> dict | None:
    """OpenSky state vector indices.

    [0]=icao24 [1]=callsign [5]=longitude [6]=latitude [7]=baro_altitude
    [9]=velocity [10]=true_track [13]=geo_altitude
    """
    if not s or len(s) < 11:
        return None
    icao = (s[0] or "").lower().strip()
    if not icao:
        return None
    lon, lat = s[5], s[6]
    if lon is None or lat is None:
        return None
    try:
        return {
            "icao24": icao,
            "callsign": (s[1] or "").strip(),
            "lon": float(lon),
            "lat": float(lat),
            "alt": float(s[7]) if s[7] is not None else (float(s[13]) if len(s) > 13 and s[13] is not None else None),
            "speed": float(s[9]) if s[9] is not None else None,
            "heading": float(s[10]) if s[10] is not None else None,
        }
    except (ValueError, TypeError):
        return None


async def snapshot_now(force: bool = False) -> dict:
    """Persist the current aircraft feed into the trail table.

    Returns a small dict describing what happened — useful for debugging
    the autopilot loop.
    """
    global _last_snapshot_ts
    now = time.time()
    if not force and (now - _last_snapshot_ts) < _MIN_INTERVAL_SEC:
        return {"skipped": True, "reason": "rate_limited", "min_interval_sec": _MIN_INTERVAL_SEC}

    data = aircraft_provider.last_known_states()
    source = (data or {}).get("source")
    if not data or not data.get("states"):
        try:
            data, source = await aircraft_provider.fetch_live_states(timeout=10.0)
        except Exception as e:
            return {"error": str(e), "stored": 0}
    states = (data or {}).get("states") or []
    rows: list[tuple] = []
    for raw in states:
        item = _decode_state_row(raw)
        if not item:
            continue
        rows.append(
            (
                item["icao24"],
                item["callsign"],
                item["lat"],
                item["lon"],
                item["alt"],
                item["speed"],
                item["heading"],
                now,
            )
        )

    if not rows:
        _last_snapshot_ts = now
        return {"stored": 0, "source": source, "states_in_feed": len(states)}

    with _conn() as conn:
        conn.executemany(
            """
            INSERT INTO aircraft_trail
              (icao24, callsign, lat, lon, alt, speed, heading, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        # Time-based prune
        cutoff = now - (_MAX_HOURS * 3600)
        conn.execute("DELETE FROM aircraft_trail WHERE recorded_at < ?", (cutoff,))
        # Hard row cap (keeps the SQLite file bounded even if a feed misbehaves)
        n = conn.execute("SELECT COUNT(*) FROM aircraft_trail").fetchone()[0]
        if n > _MAX_ROWS:
            extra = n - _MAX_ROWS
            conn.execute(
                "DELETE FROM aircraft_trail WHERE id IN "
                "(SELECT id FROM aircraft_trail ORDER BY id ASC LIMIT ?)",
                (extra,),
            )
        conn.commit()

    _last_snapshot_ts = now
    return {"stored": len(rows), "source": source, "states_in_feed": len(states), "ts": now}


@router.get("/trails")
def get_trail(
    icao24: str = Query(..., min_length=3, max_length=8, description="ICAO24 hex (e.g. ae63e2)"),
    minutes: int = Query(30, ge=1, le=360),
    max_points: int = Query(400, ge=10, le=2000),
):
    """Return the rolling trail for one aircraft."""
    icao = icao24.lower().strip()
    cutoff = time.time() - (minutes * 60)
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT lat, lon, alt, speed, heading, recorded_at
            FROM aircraft_trail
            WHERE icao24 = ? AND recorded_at >= ?
            ORDER BY recorded_at ASC
            LIMIT ?
            """,
            (icao, cutoff, max_points),
        ).fetchall()
    points = [
        {
            "lat": r["lat"],
            "lon": r["lon"],
            "alt": r["alt"],
            "speed": r["speed"],
            "heading": r["heading"],
            "t": r["recorded_at"],
        }
        for r in rows
    ]
    return {
        "icao24": icao,
        "minutes": minutes,
        "count": len(points),
        "points": points,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/trails/stats")
def trail_stats():
    """How much history is persisted right now — useful for the DATA panel."""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM aircraft_trail").fetchone()[0] or 0
        distinct = conn.execute(
            "SELECT COUNT(DISTINCT icao24) FROM aircraft_trail"
        ).fetchone()[0] or 0
        bounds = conn.execute(
            "SELECT MIN(recorded_at) AS oldest, MAX(recorded_at) AS newest FROM aircraft_trail"
        ).fetchone()
    oldest = bounds["oldest"] if bounds else None
    newest = bounds["newest"] if bounds else None
    return {
        "rows": total,
        "aircraft": distinct,
        "oldest_sec_ago": round(time.time() - oldest, 1) if oldest else None,
        "newest_sec_ago": round(time.time() - newest, 1) if newest else None,
        "max_hours": _MAX_HOURS,
        "max_rows": _MAX_ROWS,
    }


@router.post("/trails/snapshot")
async def trail_snapshot_now(_auth: str | None = Depends(verify_lan_auth)):
    """Manual trigger (rate-limited by AIRCRAFT_TRAIL_MIN_INTERVAL)."""
    return await snapshot_now(force=False)
