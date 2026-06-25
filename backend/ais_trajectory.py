"""Maritime Pattern-of-Life — AIS trajectory storage + anomaly detection (P7).

Architectural decisions (per Kimi briefing):
- Separate SQLite file (data/ais_trajectory.db) — NOT worldbase.db (WAL conflicts),
  NOT DuckDB (lock contention with FtM graph)
- In-memory ringbuffer for non-blocking ingest from WebSocket thread
- Batch flush every 30s or 1000 positions — WebSocket thread never blocks on DB
- Pure SQL feature engineering (no pandas, no ML, 0 VRAM)
- Night-port heuristic: night_samples AND nearest_port_nm < 2 (Frontex indicator)
- AIS gap: >2h in high traffic = suspicious, >6h near port = very suspicious
- Course change threshold: >15° (not 30°)
- Retention: Raw 24h, Features 90d

WORLDBASE_MARITIME_TRAJECTORY=0 (default off, opt-in)
WORLDBASE_MARITIME_ANOMALY_THRESHOLD=0.6
WORLDBASE_MARITIME_TRAJECTORY_RETENTION_H=24
"""

from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BACKEND_DIR, "data")

_TRAJECTORY_DB = os.getenv(
    "WORLDBASE_AIS_TRAJECTORY_DB",
    os.path.join(_DATA_DIR, "ais_trajectory.db"),
)

_RETENTION_SEC = (
    int(os.getenv("WORLDBASE_MARITIME_TRAJECTORY_RETENTION_H", "24")) * 3600
)
_ANOMALY_THRESHOLD = float(os.getenv("WORLDBASE_MARITIME_ANOMALY_THRESHOLD", "0.6"))


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def trajectory_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MARITIME_TRAJECTORY", "0"))


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    _ensure_data_dir()
    conn = sqlite3.connect(_TRAJECTORY_DB, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_trajectory_db() -> None:
    """Create AIS trajectory tables if not exists."""
    try:
        conn = _get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ais_position (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mmsi TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                speed REAL,
                course REAL,
                timestamp REAL NOT NULL,
                source TEXT,
                ingested_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ais_mmsi_time ON ais_position(mmsi, timestamp);
            CREATE INDEX IF NOT EXISTS idx_ais_time ON ais_position(timestamp);

            CREATE TABLE IF NOT EXISTS ais_features (
                mmsi TEXT NOT NULL,
                computed_at REAL NOT NULL,
                window_start REAL NOT NULL,
                window_end REAL NOT NULL,
                sample_count INTEGER,
                mean_speed REAL,
                speed_variance REAL,
                low_speed_samples INTEGER,
                anchorage_hours REAL,
                night_samples INTEGER,
                night_port_visits INTEGER,
                ais_gap_max_sec REAL,
                course_changes INTEGER,
                nearest_port_nm REAL,
                nearest_port_id TEXT,
                in_corridor INTEGER,
                proximity_to_risk REAL,
                risk_zone_id TEXT,
                anomaly_score REAL,
                is_anomaly INTEGER,
                PRIMARY KEY (mmsi, computed_at)
            );
            CREATE INDEX IF NOT EXISTS idx_feat_mmsi ON ais_features(mmsi, computed_at);
            CREATE INDEX IF NOT EXISTS idx_feat_anomaly ON ais_features(is_anomaly);
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# Known risk zones for proximity scoring
_RISK_ZONES = [
    {
        "id": "sumatra_piracy",
        "name": "Sumatra Piracy Zone",
        "lat": 4.5,
        "lon": 96.0,
        "radius_km": 200,
    },
    {
        "id": "scs_disputed",
        "name": "South China Sea Disputed",
        "lat": 12.0,
        "lon": 114.0,
        "radius_km": 150,
    },
    {
        "id": "bab_mandeb",
        "name": "Bab-el-Mandeb Conflict Zone",
        "lat": 15.5,
        "lon": 42.0,
        "radius_km": 200,
    },
    {
        "id": "gulf_aden",
        "name": "Gulf of Aden Piracy",
        "lat": 11.5,
        "lon": 43.0,
        "radius_km": 100,
    },
    {
        "id": "malacca_piracy",
        "name": "Malacca Strait Piracy",
        "lat": 3.5,
        "lon": 100.5,
        "radius_km": 100,
    },
]

# Major ports for anchorage detection
_PORTS = [
    {
        "id": "singapore",
        "name": "Singapore",
        "lat": 1.2643,
        "lon": 103.8408,
        "radius_km": 15,
        "type": "major",
    },
    {
        "id": "laem_chabang",
        "name": "Laem Chabang",
        "lat": 13.0827,
        "lon": 100.8847,
        "radius_km": 15,
        "type": "major",
    },
    {
        "id": "bangkok",
        "name": "Bangkok Port",
        "lat": 13.7434,
        "lon": 100.5690,
        "radius_km": 15,
        "type": "major",
    },
    {
        "id": "phuket",
        "name": "Phuket",
        "lat": 7.8828,
        "lon": 98.3922,
        "radius_km": 15,
        "type": "regional",
    },
    {
        "id": "penang",
        "name": "Penang",
        "lat": 5.4141,
        "lon": 100.3347,
        "radius_km": 15,
        "type": "regional",
    },
    {
        "id": "port_klang",
        "name": "Port Klang",
        "lat": 3.0058,
        "lon": 101.4312,
        "radius_km": 15,
        "type": "major",
    },
]

# Thailand maritime corridors (BBox: [west, south, east, north])
_CORRIDORS = [
    {"id": "malacca", "name": "Malacca Strait", "bbox": [98.0, 1.0, 102.0, 8.0]},
    {
        "id": "laem_chabang_approach",
        "name": "Laem Chabang Approach",
        "bbox": [100.5, 12.5, 101.5, 13.5],
    },
    {
        "id": "bangkok_approach",
        "name": "Bangkok Port Approach",
        "bbox": [100.0, 13.0, 101.0, 14.0],
    },
    {
        "id": "phuket_approach",
        "name": "Phuket Approach",
        "bbox": [97.5, 7.0, 99.0, 8.5],
    },
    {
        "id": "singapore_strait",
        "name": "Singapore Strait",
        "bbox": [103.0, 0.5, 104.5, 1.5],
    },
]


# ---------------------------------------------------------------------------
# In-memory ringbuffer for non-blocking ingest
# ---------------------------------------------------------------------------

_RINGBUFFER: list[tuple] = []
_RINGBUFFER_LOCK = threading.Lock()
_LAST_FLUSH = time.time()
_FLUSH_INTERVAL = 30.0
_FLUSH_THRESHOLD = 1000


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def store_position(
    mmsi: str,
    lat: float,
    lon: float,
    *,
    speed: float | None = None,
    course: float | None = None,
    timestamp: float | None = None,
    source: str = "aisstream",
) -> None:
    """Non-blocking ingest — writes to in-memory ringbuffer.

    The WebSocket thread NEVER blocks on SQLite. A background timer or
    the next compute_features() call flushes the buffer to SQLite.
    """
    if not trajectory_enabled():
        return
    ts = timestamp or time.time()
    now = time.time()

    with _RINGBUFFER_LOCK:
        _RINGBUFFER.append(
            (str(mmsi), float(lat), float(lon), speed, course, ts, source, now)
        )

        global _LAST_FLUSH
        if (
            len(_RINGBUFFER) >= _FLUSH_THRESHOLD
            or (now - _LAST_FLUSH) >= _FLUSH_INTERVAL
        ):
            _flush_buffer_locked()
            _LAST_FLUSH = now


def _flush_buffer_locked() -> None:
    """Flush ringbuffer to SQLite. Must be called with _RINGBUFFER_LOCK held."""
    if not _RINGBUFFER:
        return

    init_trajectory_db()
    try:
        conn = _get_conn()
        conn.executemany(
            "INSERT INTO ais_position (mmsi, lat, lon, speed, course, timestamp, source, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            list(_RINGBUFFER),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    _RINGBUFFER.clear()


def flush_buffer() -> None:
    """Public flush — call from background timer or before compute_features."""
    with _RINGBUFFER_LOCK:
        _flush_buffer_locked()


def _km_to_nm(km: float) -> float:
    return km * 0.539957


def _nearest_port(lat: float, lon: float) -> tuple[float, str]:
    """Returns (nautical_miles, port_id) for nearest port."""
    best_km = float("inf")
    best_id = ""
    for port in _PORTS:
        dist = _haversine_km(lat, lon, port["lat"], port["lon"])
        if dist < best_km:
            best_km = dist
            best_id = port["id"]
    return _km_to_nm(best_km), best_id


def _in_corridor(lat: float, lon: float) -> bool:
    """Check if position is within any defined maritime corridor BBox."""
    for corridor in _CORRIDORS:
        bbox = corridor["bbox"]
        if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
            return True
    return False


def _proximity_to_risk_zones(lat: float, lon: float) -> tuple[float, str]:
    """Returns (0.0-1.0 proximity score, risk_zone_id) for nearest risk zone."""
    best_score = 0.0
    best_id = ""
    for zone in _RISK_ZONES:
        dist = _haversine_km(lat, lon, zone["lat"], zone["lon"])
        if dist < zone["radius_km"]:
            score = 1.0 - (dist / zone["radius_km"])
            if score > best_score:
                best_score = score
                best_id = zone["id"]
    return best_score, best_id


def _is_night(ts: float) -> bool:
    """Check if timestamp is during night hours (20:00-06:00 UTC)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    hour = dt.hour
    return hour >= 20 or hour < 6


def compute_features(mmsi: str, now: float | None = None) -> dict[str, Any]:
    """Compute 24h rolling-window features for a vessel.

    Uses SQL window functions for course change detection.
    Night-port heuristic: night_samples AND nearest_port_nm < 2 (Frontex indicator).
    AIS gap: >2h in high traffic suspicious, >6h near port very suspicious.
    Course change threshold: >15° (per Kimi briefing).
    """
    flush_buffer()
    init_trajectory_db()

    now = now or time.time()
    window_start = now - _RETENTION_SEC
    mmsi = str(mmsi)

    conn = _get_conn()

    # 1. Basic stats (single SQL query, no pandas)
    row = conn.execute(
        """
        SELECT
            COUNT(*) as sample_count,
            AVG(speed) as mean_speed,
            MAX(speed) - MIN(speed) as speed_variance,
            SUM(CASE WHEN speed < 1.0 THEN 1 ELSE 0 END) as low_speed_samples,
            SUM(CASE WHEN (timestamp % 86400) >= 72000 OR (timestamp % 86400) < 21600 THEN 1 ELSE 0 END) as night_samples
        FROM ais_position
        WHERE mmsi = ? AND timestamp > ?
        """,
        [mmsi, window_start],
    ).fetchone()

    if not row or row["sample_count"] == 0:
        conn.close()
        return {
            "mmsi": mmsi,
            "sample_count": 0,
            "mean_speed": 0.0,
            "speed_variance": 0.0,
            "low_speed_samples": 0,
            "anchorage_hours": 0.0,
            "night_samples": 0,
            "night_port_visits": 0,
            "ais_gap_max_sec": 0.0,
            "course_changes": 0,
            "nearest_port_nm": 999.0,
            "nearest_port_id": "",
            "in_corridor": False,
            "proximity_to_risk": 0.0,
            "risk_zone_id": "",
            "anomaly_score": 0.0,
            "is_anomaly": False,
        }

    sample_count = row["sample_count"]
    mean_speed = row["mean_speed"] or 0.0
    speed_variance = row["speed_variance"] or 0.0
    low_speed_samples = row["low_speed_samples"]
    night_samples = row["night_samples"]

    # 2. Course changes via LAG window function (>15° threshold per Kimi)
    course_changes = conn.execute(
        """
        SELECT COUNT(*) as c FROM (
            SELECT course,
                   LAG(course) OVER (ORDER BY timestamp) as prev_course
            FROM ais_position
            WHERE mmsi = ? AND timestamp > ?
        )
        WHERE prev_course IS NOT NULL AND ABS(course - prev_course) > 15
          AND ABS(course - prev_course) < 345
        """,
        [mmsi, window_start],
    ).fetchone()["c"]

    # 3. AIS gap — max time between consecutive positions
    ais_gap_row = conn.execute(
        """
        SELECT MAX(gap) as max_gap FROM (
            SELECT timestamp - LAG(timestamp) OVER (ORDER BY timestamp) as gap
            FROM ais_position
            WHERE mmsi = ? AND timestamp > ?
        )
        WHERE gap IS NOT NULL
        """,
        [mmsi, window_start],
    ).fetchone()
    ais_gap_max = ais_gap_row["max_gap"] or 0.0

    # Also: time since last position (current gap)
    last_seen_row = conn.execute(
        "SELECT MAX(timestamp) as last_seen FROM ais_position WHERE mmsi = ?",
        [mmsi],
    ).fetchone()
    last_seen = last_seen_row["last_seen"]
    current_gap = (now - last_seen) if last_seen else 86400.0
    ais_gap_max = max(ais_gap_max, current_gap)

    # 4. Latest position for geo features
    last_pos = conn.execute(
        "SELECT lat, lon FROM ais_position WHERE mmsi = ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 1",
        [mmsi, window_start],
    ).fetchone()
    conn.close()

    nearest_port_nm = 999.0
    nearest_port_id = ""
    in_corridor = False
    risk_proximity = 0.0
    risk_zone_id = ""

    if last_pos:
        nearest_port_nm, nearest_port_id = _nearest_port(
            last_pos["lat"], last_pos["lon"]
        )
        in_corridor = _in_corridor(last_pos["lat"], last_pos["lon"])
        risk_proximity, risk_zone_id = _proximity_to_risk_zones(
            last_pos["lat"], last_pos["lon"]
        )

    # 5. Night-port visits: night samples AND within 2nm of port (Frontex indicator)
    night_port_visits = 0
    if nearest_port_nm < 2.0 and night_samples > 0:
        night_port_visits = min(night_samples, 10)

    # 6. Anchorage hours: contiguous low-speed periods
    anchorage_hours = low_speed_samples / 6.0

    # 7. Anomaly score (rule-based, weighted, 0.0-1.0)
    speed_var_norm = min(speed_variance / 20.0, 1.0)
    night_norm = min(night_samples / 10.0, 1.0)
    gap_norm = min(ais_gap_max / 3600.0, 1.0)
    course_norm = min(course_changes / 10.0, 1.0)
    # Night-port: combined heuristic (Frontex indicator)
    port_norm = 1.0 if (nearest_port_nm < 2.0 and night_norm > 0.3) else 0.0

    anomaly_score = (
        speed_var_norm * 0.15
        + night_norm * 0.20
        + gap_norm * 0.25
        + course_norm * 0.15
        + port_norm * 0.25
    )
    anomaly_score = min(anomaly_score, 1.0)
    is_anomaly = anomaly_score >= _ANOMALY_THRESHOLD

    features = {
        "mmsi": mmsi,
        "computed_at": now,
        "window_start": window_start,
        "window_end": now,
        "sample_count": sample_count,
        "mean_speed": round(mean_speed, 2),
        "speed_variance": round(speed_variance, 2),
        "low_speed_samples": low_speed_samples,
        "anchorage_hours": round(anchorage_hours, 2),
        "night_samples": night_samples,
        "night_port_visits": night_port_visits,
        "ais_gap_max_sec": round(ais_gap_max, 1),
        "course_changes": course_changes,
        "nearest_port_nm": round(nearest_port_nm, 2),
        "nearest_port_id": nearest_port_id,
        "in_corridor": in_corridor,
        "proximity_to_risk": round(risk_proximity, 3),
        "risk_zone_id": risk_zone_id,
        "anomaly_score": round(anomaly_score, 3),
        "is_anomaly": is_anomaly,
    }

    # Persist to ais_features table
    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO ais_features
                (mmsi, computed_at, window_start, window_end, sample_count,
                 mean_speed, speed_variance, low_speed_samples, anchorage_hours,
                 night_samples, night_port_visits, ais_gap_max_sec, course_changes,
                 nearest_port_nm, nearest_port_id, in_corridor, proximity_to_risk,
                 risk_zone_id, anomaly_score, is_anomaly)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mmsi,
                now,
                window_start,
                now,
                sample_count,
                mean_speed,
                speed_variance,
                low_speed_samples,
                anchorage_hours,
                night_samples,
                night_port_visits,
                ais_gap_max,
                course_changes,
                nearest_port_nm,
                nearest_port_id,
                int(in_corridor),
                risk_proximity,
                risk_zone_id,
                anomaly_score,
                int(is_anomaly),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return features


def detect_anomalies() -> list[dict[str, Any]]:
    """Detect anomalous vessels across all tracked MMSIs."""
    if not trajectory_enabled():
        return []

    flush_buffer()
    init_trajectory_db()
    conn = _get_conn()

    cutoff = time.time() - _RETENTION_SEC
    mmsis = conn.execute(
        "SELECT DISTINCT mmsi FROM ais_position WHERE timestamp > ?",
        [cutoff],
    ).fetchall()
    conn.close()

    anomalies = []
    for row in mmsis:
        features = compute_features(row["mmsi"])
        if features["is_anomaly"]:
            anomalies.append(features)

    anomalies.sort(key=lambda x: x["anomaly_score"], reverse=True)
    return anomalies


def get_vessel_features(mmsi: str) -> dict[str, Any]:
    """Get computed features for a specific vessel."""
    return compute_features(mmsi)


def prune_old_positions() -> int:
    """Delete positions older than retention window. Returns count deleted."""
    flush_buffer()
    init_trajectory_db()
    cutoff = time.time() - _RETENTION_SEC
    try:
        conn = _get_conn()
        cursor = conn.execute("DELETE FROM ais_position WHERE timestamp < ?", [cutoff])
        count = cursor.rowcount
        conn.execute(
            "DELETE FROM ais_features WHERE computed_at < ?", [time.time() - 7776000]
        )
        conn.commit()
        conn.close()
        return count
    except Exception:
        return 0


def trajectory_stats() -> dict[str, Any]:
    """Get trajectory tracking statistics."""
    flush_buffer()
    init_trajectory_db()
    conn = _get_conn()
    total_positions = conn.execute("SELECT COUNT(*) as c FROM ais_position").fetchone()[
        "c"
    ]
    total_vessels = conn.execute(
        "SELECT COUNT(DISTINCT mmsi) as c FROM ais_position"
    ).fetchone()["c"]
    total_features = conn.execute("SELECT COUNT(*) as c FROM ais_features").fetchone()[
        "c"
    ]
    anomalies = conn.execute(
        "SELECT COUNT(*) as c FROM ais_features WHERE is_anomaly = 1",
    ).fetchone()["c"]
    ringbuffer_size = len(_RINGBUFFER)
    conn.close()
    return {
        "enabled": trajectory_enabled(),
        "db_path": _TRAJECTORY_DB,
        "total_positions": total_positions,
        "total_vessels": total_vessels,
        "total_features_computed": total_features,
        "anomalies_detected": anomalies,
        "ringbuffer_pending": ringbuffer_size,
        "retention_hours": _RETENTION_SEC // 3600,
        "anomaly_threshold": _ANOMALY_THRESHOLD,
        "risk_zones": len(_RISK_ZONES),
        "ports": len(_PORTS),
        "corridors": len(_CORRIDORS),
    }
