"""Online feed anomaly scores — River HalfSpaceTrees (CPU-only fallback: z-score)."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/anomalies", tags=["anomalies-river"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

# Scalar signals polled from existing WorldBase feeds (self URL or in-process later)
_FEED_METRICS = [
    ("aircraft_count", "/api/aircraft"),
    ("quake_count", "/api/earthquakes?period=day&magnitude=2.5"),
    ("gdacs_count", "/api/gdacs"),
    ("pegel_alerts", "/api/pegel"),
    ("hazard_count", "/api/hazards"),
]

_UA = {"User-Agent": "WorldBase/1.0"}
_SELF = os.getenv("WORLDBASE_SELF", "http://127.0.0.1:8002").rstrip("/")
_CACHE: dict[str, tuple[float, dict]] = {}


def _conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_river_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS river_models (
                feed_key TEXT PRIMARY KEY,
                model_json TEXT NOT NULL,
                sample_count INTEGER DEFAULT 0,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS river_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_key TEXT NOT NULL,
                value REAL NOT NULL,
                score REAL NOT NULL,
                is_anomaly INTEGER NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_river_scores_feed ON river_scores(feed_key, recorded_at);
        """)
        conn.commit()


def _load_model(feed_key: str) -> Any:
    try:
        from river import anomaly

        with _conn() as conn:
            row = conn.execute(
                "SELECT model_json, sample_count FROM river_models WHERE feed_key = ?",
                (feed_key,),
            ).fetchone()
        if row and row["model_json"]:
            state = json.loads(row["model_json"])
            m = anomaly.HalfSpaceTrees(seed=42)
            m = m.from_dict(state)
            return m, int(row["sample_count"] or 0)
        return anomaly.HalfSpaceTrees(seed=42), 0
    except ImportError:
        return None, 0


def _save_model(feed_key: str, model: Any, sample_count: int):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    blob = json.dumps(model.to_dict())
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO river_models (feed_key, model_json, sample_count, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(feed_key) DO UPDATE SET
                model_json=excluded.model_json,
                sample_count=excluded.sample_count,
                updated_at=excluded.updated_at
            """,
            (feed_key, blob, sample_count, now),
        )
        conn.commit()


def _zscore_anomaly(history: list[float], value: float) -> tuple[float, bool]:
    if len(history) < 8:
        return 0.0, False
    mean = sum(history) / len(history)
    var = sum((x - mean) ** 2 for x in history) / len(history)
    std = math.sqrt(var) if var > 1e-9 else 1e-9
    z = abs(value - mean) / std
    return round(min(1.0, z / 4.0), 4), z >= 3.0


def _extract_metric(feed_key: str, data: dict) -> float | None:
    if feed_key == "aircraft_count":
        return float(len(data.get("states") or []))
    if feed_key == "quake_count":
        return float(data.get("count") or len(data.get("earthquakes") or []))
    if feed_key == "gdacs_count":
        return float(data.get("count") or len(data.get("alerts") or []))
    if feed_key == "pegel_alerts":
        return float(
            data.get("alerts")
            or sum(
                1
                for g in (data.get("gauges") or [])
                if g.get("severity") in ("high", "critical")
            )
        )
    if feed_key == "hazard_count":
        return float(data.get("count") or len(data.get("alerts") or []))
    return None


async def _fetch_metric(client: httpx.AsyncClient, path: str) -> dict:
    url = path if path.startswith("http") else f"{_SELF}{path}"
    r = await client.get(url, headers=_UA, timeout=25.0)
    r.raise_for_status()
    return r.json()


async def scan_feeds() -> dict:
    """Update online models and return current anomaly flags."""
    from datetime import datetime, timezone

    results = []
    errors = []
    engine = "river"

    async with httpx.AsyncClient(timeout=30.0) as client:
        for feed_key, path in _FEED_METRICS:
            try:
                data = await _fetch_metric(client, path)
                value = _extract_metric(feed_key, data)
                if value is None:
                    continue

                model, n = _load_model(feed_key)
                score = 0.0
                is_anom = False

                if model is not None:
                    model.learn_one({"v": value})
                    score = float(model.score_one({"v": value}))
                    # River scores: higher = more anomalous (typically 0–1 range)
                    is_anom = score >= 0.65 and n >= 15
                    _save_model(feed_key, model, n + 1)
                else:
                    engine = "zscore"
                    with _conn() as conn:
                        rows = conn.execute(
                            "SELECT value FROM river_scores WHERE feed_key = ? ORDER BY id DESC LIMIT 40",
                            (feed_key,),
                        ).fetchall()
                    hist = [float(r["value"]) for r in reversed(rows)]
                    score, is_anom = _zscore_anomaly(hist, value)

                now = datetime.now(timezone.utc).isoformat()
                with _conn() as conn:
                    conn.execute(
                        "INSERT INTO river_scores (feed_key, value, score, is_anomaly, recorded_at) VALUES (?, ?, ?, ?, ?)",
                        (feed_key, value, score, 1 if is_anom else 0, now),
                    )
                    conn.commit()

                results.append(
                    {
                        "feed": feed_key,
                        "value": value,
                        "score": round(score, 4),
                        "anomaly": is_anom,
                        "samples": n + 1,
                    }
                )
            except Exception as e:
                errors.append(f"{feed_key}: {e}")

    out = {
        "engine": engine,
        "count": len(results),
        "signals": results,
        "anomalies": [r for r in results if r["anomaly"]],
        "errors": errors or None,
        "scanned_at": time.time(),
    }
    return out


async def get_river_state(max_age: float = 60.0) -> dict:
    key = "scan"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < max_age:
        return cached[1]
    out = await scan_feeds()
    _CACHE[key] = (time.time(), out)
    return out


@router.get("/river")
async def river_anomalies():
    """Online anomaly scores per feed (River or z-score fallback). Cached 60s."""
    return await get_river_state(60.0)
