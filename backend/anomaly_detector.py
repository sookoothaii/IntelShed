"""V4-23 Anomaly Detection — Isolation Forest on feed time series.

Trains a scikit-learn ``IsolationForest`` model on historical feed metrics
to detect unusual patterns across GDELT, earthquake, CAMS PM2.5, AIS position
counts, and fusion hotspot counts.

CPU-only, 0 VRAM.  Training uses a rolling 30-day window and retrains daily.

Feature flag: ``WORLDBASE_ANOMALY_DETECTION=0`` (default off, opt-in).
Briefing flag: ``WORLDBASE_BRIEFING_ANOMALY=0`` (default off, opt-in).

Model persistence: ``data/anomaly_if_model.json`` (sklearn) or
                    ``data/anomaly_if_stats.json`` (z-score fallback).

Endpoints:
    POST /api/anomalies/detect        — run detection on latest feed metrics
    GET  /api/anomalies/iso           — list detected anomalies
    POST /api/anomalies/iso/train     — retrain model from historical data
    GET  /api/anomalies/iso/status    — model status + metrics

FtM: detected anomalies are ingested as ``Event`` entities with ``type=anomaly``.
Briefing: "ANOMALY ALERT" block when new anomalies are detected.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query

from auth.security import verify_api_key
from structured_log import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

_MODEL_DIR = os.getenv(
    "WORLDBASE_ANOMALY_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
_IF_MODEL_PATH = os.path.join(_MODEL_DIR, "anomaly_if_model.json")
_IF_STATS_PATH = os.path.join(_MODEL_DIR, "anomaly_if_stats.json")

_SELF = os.getenv("WORLDBASE_SELF", "http://127.0.0.1:8002").rstrip("/")
_UA = {"User-Agent": "WorldBase/1.0"}
_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 300.0  # 5 min

_ROLLING_WINDOW_DAYS = int(os.getenv("WORLDBASE_ANOMALY_WINDOW_DAYS", "30"))
_CONTAMINATION = float(os.getenv("WORLDBASE_ANOMALY_CONTAMINATION", "0.1"))
_MIN_SAMPLES = int(os.getenv("WORLDBASE_ANOMALY_MIN_SAMPLES", "14"))

router = APIRouter(prefix="/api/anomalies", tags=["anomaly-detection"])


def _enabled() -> bool:
    return os.getenv("WORLDBASE_ANOMALY_DETECTION", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _briefing_enabled() -> bool:
    return os.getenv("WORLDBASE_BRIEFING_ANOMALY", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Feed metrics — same signals as anomaly_river but used for batch training
# ---------------------------------------------------------------------------

_FEED_METRICS: list[tuple[str, str]] = [
    ("gdelt_event_count", "/api/gdelt/pulse/local"),
    ("gdelt_geo_count", "/api/gdelt/geo/local"),
    ("earthquake_count", "/api/earthquakes?period=day&magnitude=2.5"),
    ("cams_pm25_avg", "/api/airquality"),
    ("ais_position_count", "/api/aircraft"),
    ("fusion_hotspot_count", "/api/fusion/hotspots"),
    ("gdacs_count", "/api/gdacs"),
    ("hazard_count", "/api/hazards"),
]


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_anomaly_db() -> None:
    """Create anomaly detection tables if missing."""
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS anomaly_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_key TEXT NOT NULL,
                value REAL NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_anomaly_metrics_feed
                ON anomaly_metrics(feed_key, recorded_at);

            CREATE TABLE IF NOT EXISTS anomaly_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_key TEXT NOT NULL,
                value REAL NOT NULL,
                score REAL NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT,
                ftm_entity_id TEXT,
                detected_at TEXT NOT NULL,
                ingested INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_anomaly_detections_feed
                ON anomaly_detections(feed_key, detected_at);
            """
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Metric extraction
# ---------------------------------------------------------------------------


def _extract_metric(feed_key: str, data: dict) -> float | None:
    """Extract a scalar metric from a feed API response."""
    if feed_key == "gdelt_event_count":
        articles = data.get("articles") or data.get("events") or []
        return float(len(articles))
    if feed_key == "gdelt_geo_count":
        events = data.get("events") or []
        return float(len(events))
    if feed_key == "earthquake_count":
        return float(data.get("count") or len(data.get("earthquakes") or []))
    if feed_key == "cams_pm25_avg":
        cities = data.get("cities") or []
        pm25_vals = [
            float(c.get("pm25", 0)) for c in cities if c.get("pm25") is not None
        ]
        if not pm25_vals:
            return None
        return round(sum(pm25_vals) / len(pm25_vals), 2)
    if feed_key == "ais_position_count":
        states = data.get("states") or []
        return float(len(states))
    if feed_key == "fusion_hotspot_count":
        hotspots = data.get("hotspots") or []
        return float(len(hotspots))
    if feed_key == "gdacs_count":
        return float(data.get("count") or len(data.get("alerts") or []))
    if feed_key == "hazard_count":
        return float(data.get("count") or len(data.get("alerts") or []))
    return None


async def _fetch_metric(client: httpx.AsyncClient, path: str) -> dict:
    url = path if path.startswith("http") else f"{_SELF}{path}"
    r = await client.get(url, headers=_UA, timeout=25.0)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Historical data loading
# ---------------------------------------------------------------------------


def _load_history(feed_key: str, days: int = _ROLLING_WINDOW_DAYS) -> list[float]:
    """Load historical metric values for a feed from SQLite."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT value FROM anomaly_metrics WHERE feed_key = ? AND recorded_at >= ? "
            "ORDER BY recorded_at ASC",
            (feed_key, cutoff),
        ).fetchall()
    return [float(r["value"]) for r in rows]


def _load_all_history(days: int = _ROLLING_WINDOW_DAYS) -> dict[str, list[float]]:
    """Load all feed histories within the rolling window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    result: dict[str, list[float]] = {}
    with _conn() as conn:
        rows = conn.execute(
            "SELECT feed_key, value, recorded_at FROM anomaly_metrics "
            "WHERE recorded_at >= ? ORDER BY recorded_at ASC",
            (cutoff,),
        ).fetchall()
    for row in rows:
        result.setdefault(row["feed_key"], []).append(float(row["value"]))
    return result


def _store_metric(feed_key: str, value: float) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO anomaly_metrics (feed_key, value, recorded_at) VALUES (?, ?, ?)",
            (feed_key, value, now),
        )
        conn.commit()


def _store_detection(
    feed_key: str,
    value: float,
    score: float,
    severity: str,
    summary: str,
    ftm_entity_id: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO anomaly_detections "
            "(feed_key, value, score, severity, summary, ftm_entity_id, detected_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feed_key, value, score, severity, summary, ftm_entity_id, now),
        )
        conn.commit()
        return cur.lastrowid


# ---------------------------------------------------------------------------
# Isolation Forest training
# ---------------------------------------------------------------------------


def _build_feature_matrix(
    history: dict[str, list[float]],
) -> tuple[list[list[float]], list[str]]:
    """Build a multi-variate feature matrix from feed histories.

    Each row is a time step; columns are feed metrics.  Feeds with different
    lengths are truncated to the shortest common length.
    """
    if not history:
        return [], []

    feed_keys = sorted(history.keys())
    min_len = min(len(history[k]) for k in feed_keys)
    if min_len == 0:
        return [], feed_keys

    matrix: list[list[float]] = []
    for i in range(min_len):
        row = [history[k][i] for k in feed_keys]
        matrix.append(row)
    return matrix, feed_keys


def train_model() -> dict[str, Any]:
    """Train Isolation Forest from historical feed metrics.

    Falls back to z-score statistics when sklearn is not installed.
    """
    if not _enabled():
        return {
            "enabled": False,
            "error": "Anomaly detection disabled. Set WORLDBASE_ANOMALY_DETECTION=1.",
        }

    history = _load_all_history()
    total_samples = sum(len(v) for v in history.values())

    if total_samples < _MIN_SAMPLES:
        return {
            "enabled": True,
            "ok": False,
            "error": f"Insufficient historical data: {total_samples} < {_MIN_SAMPLES} minimum",
            "feeds": len(history),
            "total_samples": total_samples,
        }

    matrix, feed_keys = _build_feature_matrix(history)
    if not matrix:
        return {
            "enabled": True,
            "ok": False,
            "error": "No valid feature matrix from history",
            "feeds": len(history),
        }

    t0 = time.perf_counter()

    try:
        from sklearn.ensemble import IsolationForest

        n_samples = len(matrix)
        n_estimators = min(100, max(10, n_samples * 2))
        contamination = min(_CONTAMINATION, 0.5)

        clf = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=42,
            n_jobs=1,
        )
        clf.fit(matrix)

        # Persist model via joblib/pickle
        Path(_MODEL_DIR).mkdir(parents=True, exist_ok=True)
        import pickle

        with open(_IF_MODEL_PATH, "wb") as f:
            pickle.dump(clf, f)

        # Also save metadata
        meta = {
            "model_type": "isolation_forest",
            "feed_keys": feed_keys,
            "n_samples": n_samples,
            "n_estimators": n_estimators,
            "contamination": contamination,
            "trained_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(_IF_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        elapsed = round(time.perf_counter() - t0, 2)
        log.info(
            "anomaly_if_trained",
            samples=n_samples,
            feeds=len(feed_keys),
            elapsed_s=elapsed,
        )
        return {
            "enabled": True,
            "ok": True,
            "model_type": "isolation_forest",
            "samples": n_samples,
            "feeds": len(feed_keys),
            "feed_keys": feed_keys,
            "n_estimators": n_estimators,
            "contamination": contamination,
            "elapsed_s": elapsed,
        }

    except ImportError:
        log.info("sklearn not installed, falling back to z-score statistics")
        return _train_zscore(history)
    except Exception as exc:
        log.warning("anomaly_if_train_failed", error=str(exc)[:200])
        return _train_zscore(history)


def _train_zscore(history: dict[str, list[float]]) -> dict[str, Any]:
    """Fallback: compute per-feed mean/std for z-score anomaly detection."""
    stats: dict[str, dict[str, float]] = {}
    for key, values in history.items():
        if len(values) < 3:
            continue
        mean = sum(values) / len(values)
        var = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(var) if var > 1e-9 else 1e-9
        stats[key] = {"mean": mean, "std": std}

    Path(_MODEL_DIR).mkdir(parents=True, exist_ok=True)
    meta = {
        "model_type": "zscore",
        "stats": stats,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_feeds": len(stats),
    }
    with open(_IF_STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return {
        "enabled": True,
        "ok": True,
        "model_type": "zscore",
        "feeds": len(stats),
        "feed_keys": sorted(stats.keys()),
    }


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _load_model() -> tuple[Any | None, dict | None]:
    """Load trained model and metadata."""
    # Try sklearn model first
    try:
        import pickle

        if os.path.exists(_IF_MODEL_PATH):
            with open(_IF_MODEL_PATH, "rb") as f:
                clf = pickle.load(f)
            meta = {}
            if os.path.exists(_IF_STATS_PATH):
                with open(_IF_STATS_PATH, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            return clf, meta
    except Exception:
        pass

    # Fallback to z-score stats
    try:
        if os.path.exists(_IF_STATS_PATH):
            with open(_IF_STATS_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("model_type") == "zscore":
                return None, meta
    except Exception:
        pass
    return None, None


def _severity_from_score(score: float) -> str:
    """Map anomaly score to severity."""
    if score >= 0.8:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _detect_isolation_forest(
    clf: Any, meta: dict, current_metrics: dict[str, float]
) -> list[dict[str, Any]]:
    """Run Isolation Forest detection on current metrics."""
    feed_keys = meta.get("feed_keys", [])
    if not feed_keys:
        return []

    # Build feature vector in the same order as training
    feature_vector = []
    available_keys = []
    for key in feed_keys:
        val = current_metrics.get(key)
        if val is not None:
            feature_vector.append(val)
            available_keys.append(key)

    if not available_keys:
        return []

    # Predict anomaly score
    # IsolationForest: -1 = anomaly, 1 = normal
    # score_samples: lower = more anomalous (negative)
    # We normalize to 0-1 where higher = more anomalous
    import numpy as np

    X = np.array([feature_vector])
    predictions = clf.predict(X)
    raw_scores = clf.score_samples(X)
    # Convert: normal score ~0, anomaly score < 0
    # Normalize: score = min(1.0, -raw_score / 0.5)
    normalized_score = min(1.0, max(0.0, -float(raw_scores[0]) / 0.5))
    is_anomaly = predictions[0] == -1

    if not is_anomaly:
        return []

    # Per-feed contribution: deviation from expected
    results = []
    for i, key in enumerate(available_keys):
        val = feature_vector[i]
        # Use feature importance-like approach: check if this value is extreme
        # For Isolation Forest, we use path length as proxy
        # Simplified: flag all feeds in the anomalous row
        score = normalized_score
        severity = _severity_from_score(score)
        summary = f"Anomaly detected in {key}: value={val:.2f}, score={score:.3f}"
        results.append(
            {
                "feed": key,
                "value": val,
                "score": round(score, 4),
                "severity": severity,
                "summary": summary,
            }
        )
    return results


def _detect_zscore(
    meta: dict, current_metrics: dict[str, float]
) -> list[dict[str, Any]]:
    """Run z-score based detection."""
    stats = meta.get("stats", {})
    results = []

    for key, val in current_metrics.items():
        s = stats.get(key)
        if not s:
            continue
        mean = s["mean"]
        std = s["std"]
        z = abs(val - mean) / std
        score = min(1.0, z / 4.0)
        if z >= 3.0:
            severity = _severity_from_score(score)
            summary = (
                f"Anomaly detected in {key}: value={val:.2f}, "
                f"z-score={z:.2f} (mean={mean:.2f}, std={std:.2f})"
            )
            results.append(
                {
                    "feed": key,
                    "value": val,
                    "score": round(score, 4),
                    "severity": severity,
                    "summary": summary,
                }
            )
    return results


async def detect_anomalies() -> dict[str, Any]:
    """Fetch current feed metrics and run anomaly detection.

    Returns a dict with detected anomalies, model info, and errors.
    Fail-soft: returns disabled dict when feature flag is off.
    """
    if not _enabled():
        return {"enabled": False, "count": 0, "anomalies": [], "errors": None}

    # Fetch current metrics
    current_metrics: dict[str, float] = {}
    errors: list[str] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for feed_key, path in _FEED_METRICS:
            try:
                data = await _fetch_metric(client, path)
                val = _extract_metric(feed_key, data)
                if val is not None:
                    current_metrics[feed_key] = val
                    # Store for future training
                    _store_metric(feed_key, val)
            except Exception as e:
                errors.append(f"{feed_key}: {e}")

    if not current_metrics:
        return {
            "enabled": True,
            "count": 0,
            "anomalies": [],
            "errors": errors or None,
            "message": "No metrics could be collected",
        }

    # Load model
    clf, meta = _load_model()
    if clf is None and meta is None:
        return {
            "enabled": True,
            "count": 0,
            "anomalies": [],
            "errors": errors or None,
            "metrics_collected": len(current_metrics),
            "message": "No trained model. Run POST /api/anomalies/iso/train first.",
        }

    # Detect
    if clf is not None and meta and meta.get("model_type") == "isolation_forest":
        anomalies = _detect_isolation_forest(clf, meta, current_metrics)
        model_type = "isolation_forest"
    elif meta and meta.get("model_type") == "zscore":
        anomalies = _detect_zscore(meta, current_metrics)
        model_type = "zscore"
    else:
        anomalies = []
        model_type = "unknown"

    # Store detections
    for a in anomalies:
        det_id = _store_detection(
            a["feed"], a["value"], a["score"], a["severity"], a["summary"]
        )
        a["detection_id"] = det_id

    return {
        "enabled": True,
        "model_type": model_type,
        "count": len(anomalies),
        "anomalies": anomalies,
        "metrics_collected": len(current_metrics),
        "errors": errors or None,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def list_detections(
    feed: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List stored anomaly detections from SQLite."""
    query = "SELECT * FROM anomaly_detections"
    params: list[Any] = []
    conditions: list[str] = []

    if feed:
        conditions.append("feed_key = ?")
        params.append(feed)
    if since:
        conditions.append("detected_at >= ?")
        params.append(since)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY detected_at DESC LIMIT ?"
    params.append(limit)

    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def model_status() -> dict[str, Any]:
    """Get anomaly detection model status."""
    if not _enabled():
        return {"enabled": False, "error": "Anomaly detection disabled."}

    model_exists = os.path.exists(_IF_MODEL_PATH)
    stats_exists = os.path.exists(_IF_STATS_PATH)
    model_type = None
    meta: dict[str, Any] = {}

    if stats_exists:
        try:
            with open(_IF_STATS_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            model_type = meta.get("model_type")
        except Exception:
            pass

    # Count historical samples
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM anomaly_metrics").fetchone()
    total_metrics = row["n"] if row else 0

    # Count detections
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) as n FROM anomaly_detections").fetchone()
    total_detections = row["n"] if row else 0

    return {
        "enabled": True,
        "model_type": model_type,
        "model_trained": model_type is not None,
        "model_path": _IF_MODEL_PATH if model_exists else None,
        "stats_path": _IF_STATS_PATH if stats_exists else None,
        "total_metrics": total_metrics,
        "total_detections": total_detections,
        "rolling_window_days": _ROLLING_WINDOW_DAYS,
        "contamination": _CONTAMINATION,
        "min_samples": _MIN_SAMPLES,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# FtM Event ingestion
# ---------------------------------------------------------------------------


def ingest_anomalies_as_events(anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    """Ingest detected anomalies as FtM Event entities.

    Each anomaly becomes an ``Event`` entity with ``type=anomaly``,
    ``startDate``, ``summary``, and provenance metadata.  Fail-soft.
    """
    if not anomalies:
        return {"count": 0, "ids": [], "error": None}

    try:
        import ftm_query

        ids: list[str] = []
        seen_at = datetime.now(timezone.utc).isoformat()

        for a in anomalies:
            feed_key = a.get("feed", "unknown")
            score = a.get("score", 0)
            summary = a.get("summary", "")
            det_id = a.get("detection_id", "")

            props: dict[str, list[str]] = {
                "name": [f"Anomaly: {feed_key}"],
                "summary": [summary],
                "startDate": [seen_at[:10]],
                "type": ["anomaly"],
                "source": ["anomaly_detector"],
                "confidence": [str(round(score, 2))],
            }

            ent = ftm_query.make_entity(
                "Event",
                [f"anomaly:{feed_key}:{det_id}:{seen_at}"],
                props,
            )
            ftm_query.upsert(ent, dataset="anomaly_detection", seen_at=seen_at)
            ids.append(ent.id)

            # Mark as ingested
            if det_id:
                with _conn() as conn:
                    conn.execute(
                        "UPDATE anomaly_detections SET ingested = 1, ftm_entity_id = ? "
                        "WHERE id = ?",
                        (ent.id, det_id),
                    )
                    conn.commit()

        return {"count": len(ids), "ids": ids, "error": None}

    except Exception as exc:
        log.warning("anomaly_ftm_ingest_failed", error=str(exc)[:200])
        return {"count": 0, "ids": [], "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# Briefing integration
# ---------------------------------------------------------------------------


async def gather_anomaly_digest(hours: int = 24, max_lines: int = 5) -> dict[str, Any]:
    """Collect anomaly detections for the briefing pipeline.

    Returns a digest dict with 'enabled', 'count', 'lines', and 'anomalies'.
    Fail-soft: returns disabled dict on any error.
    """
    if not _enabled() or not _briefing_enabled():
        return {"enabled": False, "count": 0, "lines": [], "anomalies": []}

    try:
        # Get recent detections
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        detections = list_detections(since=since, limit=max_lines * 3)

        if not detections:
            return {"enabled": True, "count": 0, "lines": [], "anomalies": []}

        # Build digest lines
        lines: list[dict[str, Any]] = []
        for det in detections[:max_lines]:
            feed = det.get("feed_key", "unknown")
            value = det.get("value", 0)
            score = det.get("score", 0)
            severity = det.get("severity", "medium")
            summary = det.get("summary", "")
            det_time = det.get("detected_at", "")[:10]

            text = f"[{severity.upper()}] {feed}: {summary[:120]}"
            if det_time:
                text += f" — {det_time}"

            lines.append(
                {
                    "text": text,
                    "feed": feed,
                    "value": value,
                    "score": score,
                    "severity": severity,
                    "summary": summary,
                    "detected_at": det.get("detected_at"),
                    "ftm_entity_id": det.get("ftm_entity_id"),
                    "sources": ["anomaly_detector"],
                    "source": "anomaly_detector",
                }
            )

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "anomalies": detections[:max_lines],
        }
    except Exception as exc:
        log.debug("anomaly_digest_failed", error=str(exc)[:200])
        return {
            "enabled": False,
            "count": 0,
            "lines": [],
            "anomalies": [],
            "error": str(exc)[:200],
        }


def build_anomaly_watch_items(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate watch items for high-severity anomaly detections."""
    items: list[dict[str, Any]] = []
    for line in (digest.get("lines") or [])[:3]:
        severity = line.get("severity", "medium")
        if severity not in ("critical", "high"):
            continue
        feed = line.get("feed", "unknown")
        items.append(
            {
                "id": f"anomaly:{feed}:{line.get('detected_at', '')}",
                "prefix": "anomaly",
                "title": f"Feed anomaly: {feed} — {line.get('summary', '')[:100]}",
                "horizon_h": 48,
                "confidence": line.get("score", 0.5),
                "sources": ["anomaly_detector"],
                "bucket": "global",
                "entity_id": line.get("ftm_entity_id"),
            }
        )
    return items


# ---------------------------------------------------------------------------
# Autopilot
# ---------------------------------------------------------------------------


_ANOMALY_AUTOPILOT_INTERVAL = int(
    os.getenv("WORLDBASE_ANOMALY_AUTOPILOT_INTERVAL", "3600")
)  # 1h default


async def anomaly_autopilot() -> None:
    """Background loop: collect metrics, detect anomalies, retrain daily."""
    await asyncio.sleep(120)  # initial delay
    last_train = 0.0
    train_interval = 86400  # 24h

    while True:
        try:
            result = await detect_anomalies()
            if result.get("enabled") and result.get("anomalies"):
                # Ingest into FtM
                ingest_anomalies_as_events(result["anomalies"])
                log.info(
                    "anomaly_autopilot_detected",
                    count=result["count"],
                    feeds=[a["feed"] for a in result["anomalies"]],
                )
        except Exception as e:
            log.warning("anomaly_autopilot_detect_failed", error=str(e)[:200])

        # Retrain daily
        now = time.time()
        if now - last_train > train_interval:
            try:
                train_result = train_model()
                if train_result.get("ok"):
                    last_train = now
                    log.info(
                        "anomaly_autopilot_retrained",
                        model_type=train_result.get("model_type"),
                    )
            except Exception as e:
                log.warning("anomaly_autopilot_train_failed", error=str(e)[:200])

        await asyncio.sleep(_ANOMALY_AUTOPILOT_INTERVAL)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.post("/detect")
async def detect_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Run anomaly detection on current feed metrics."""
    result = await detect_anomalies()
    # Auto-ingest into FtM if anomalies found
    if result.get("anomalies"):
        ingest_result = ingest_anomalies_as_events(result["anomalies"])
        result["ftm_ingest"] = ingest_result
    return result


@router.get("/iso")
async def list_anomalies_endpoint(
    feed: str = Query("", description="Filter by feed key"),
    since: str = Query("", description="ISO timestamp filter"),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """List detected anomalies from storage."""
    detections = list_detections(feed=feed or None, since=since or None, limit=limit)
    return {
        "enabled": _enabled(),
        "count": len(detections),
        "anomalies": detections,
    }


@router.post("/iso/train")
async def train_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Train Isolation Forest model from historical feed metrics."""
    return train_model()


@router.get("/iso/status")
async def status_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get anomaly detection model status."""
    return model_status()


# Late import to avoid circular dependency in lifespan
import asyncio  # noqa: E402
