"""Prometheus metrics collector for WorldBase (I4).

Exposes gauges and a histogram via GET /api/metrics in Prometheus exposition format.
No external dependencies — pure string formatting. When prometheus_client is
installed, uses its registry; otherwise falls back to manual exposition.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


def metrics_enabled() -> bool:
    return os.getenv("WORLDBASE_METRICS", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _collect_feed_counts() -> dict[str, float]:
    """Count fresh/stale/error feeds from feed_cache."""
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        c = conn.cursor()
        c.execute("SELECT key, value, cached_at FROM feed_cache")
        now = datetime.now(timezone.utc)
        fresh = stale = error = 0
        for key, value_json, cached_at in c.fetchall():
            meta: dict = {}
            if value_json and len(value_json) < 120_000:
                try:
                    import json

                    val = json.loads(value_json)
                    if isinstance(val, dict):
                        meta = val
                except Exception:
                    pass
            if meta.get("error"):
                error += 1
                continue
            try:
                age = (now - datetime.fromisoformat(cached_at)).total_seconds()
                from connector_registry import feed_ttl_sec

                ttl = feed_ttl_sec(key)
                if age < ttl:
                    fresh += 1
                else:
                    stale += 1
            except Exception:
                stale += 1
        conn.close()
        return {"fresh": fresh, "stale": stale, "error": error}
    except Exception:
        return {"fresh": 0, "stale": 0, "error": 0}


def _collect_briefing_metrics() -> dict[str, float]:
    """Briefing quality score and age from SQLite."""
    try:
        import json as _json

        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT created_at, sources FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        created_at, sources_json = row
        sources = {}
        if sources_json:
            try:
                sources = _json.loads(sources_json)
            except Exception:
                pass
        quality = (sources.get("quality") or {}).get("score")
        meta = (sources.get("quality") or {}).get("meta") or {}
        age_s = 0.0
        if created_at:
            try:
                ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_s = (datetime.now(timezone.utc) - ts).total_seconds()
            except Exception:
                pass
        result: dict[str, float] = {}
        if quality is not None:
            result["briefing_quality_score"] = _safe_float(quality)
        result["briefing_age_seconds"] = age_s
        if meta.get("prediction_pending") is not None:
            result["prediction_pending"] = _safe_float(meta["prediction_pending"])
        if meta.get("prediction_accuracy_30d") is not None:
            result["prediction_accuracy_30d"] = _safe_float(
                meta["prediction_accuracy_30d"]
            )
        return result
    except Exception:
        return {}


def _collect_graph_counts() -> dict[str, float]:
    """DuckDB entity/edge counts via ftm_store.graph_stats."""
    try:
        import ftm_store

        st = ftm_store.store_status()
        if not st.get("ready"):
            return {}
        stats = ftm_store.graph_stats()
        result: dict[str, float] = {}
        if "entities" in stats:
            result["duckdb_entity_count"] = _safe_float(stats["entities"])
        if "edges" in stats:
            result["duckdb_edge_count"] = _safe_float(stats["edges"])
        return result
    except Exception:
        return {}


def _collect_duckdb_queue() -> dict[str, float]:
    """DuckDB write queue backlog."""
    try:
        import duckdb_queue

        q = duckdb_queue.get_queue()
        if q.enabled:
            return {"duckdb_queue_backlog": _safe_float(q.backlog)}
    except Exception:
        pass
    return {}


def _collect_ais() -> dict[str, float]:
    """AIS stream status and vessel count."""
    try:
        import ais_bridge

        result: dict[str, float] = {}
        if ais_bridge._STREAM.get("connected"):
            result["ais_stream_connected"] = 1.0
        else:
            result["ais_stream_connected"] = 0.0
        vessels = ais_bridge._STREAM.get("buffer") or []
        result["ais_vessel_count"] = _safe_float(len(vessels))
        return result
    except Exception:
        return {}


def _collect_ollama() -> dict[str, float]:
    """Ollama reachability (sync quick check)."""
    try:
        import httpx

        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        r = httpx.get(f"{host}/api/tags", timeout=3.0)
        return {"ollama_reachable": 1.0 if r.status_code == 200 else 0.0}
    except Exception:
        return {"ollama_reachable": 0.0}


def _collect_pi_edge() -> dict[str, float]:
    """Pi edge online status from node_registry table."""
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute("SELECT node_id, online FROM node_registry").fetchall()
        conn.close()
        pi = next((r for r in rows if r[0] == "offgrid-pi"), None)
        if not pi:
            pi = rows[0] if len(rows) == 1 else None
        if pi:
            return {"pi_edge_online": 1.0 if pi[1] else 0.0}
    except Exception:
        pass
    return {"pi_edge_online": 0.0}


def _collect_rag() -> dict[str, float]:
    """RAG query count and latency p95 from rag_memory in-memory tracker."""
    try:
        import rag_memory

        stats = rag_memory.query_stats()
        result: dict[str, float] = {}
        if "count" in stats:
            result["rag_query_count"] = _safe_float(stats["count"])
        if "p95_ms" in stats:
            result["rag_query_latency_p95"] = _safe_float(stats["p95_ms"]) / 1000.0
        return result
    except Exception:
        return {}


# Health check latency histogram (in-memory)
_health_check_times: list[float] = []
_HIST_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]


def record_health_check_duration(duration_s: float) -> None:
    """Record a health check duration for the histogram."""
    global _health_check_times
    _health_check_times.append(duration_s)
    if len(_health_check_times) > 1000:
        _health_check_times = _health_check_times[-500:]


def _format_histogram() -> str:
    """Format health_check_duration_seconds histogram in Prometheus format."""
    samples = _health_check_times
    n = len(samples)
    if n == 0:
        lines = [
            "# HELP health_check_duration_seconds Health check response time",
            "# TYPE health_check_duration_seconds histogram",
            'health_check_duration_seconds_bucket{le="+Inf"} 0',
            "health_check_duration_seconds_count 0",
            "health_check_duration_seconds_sum 0",
        ]
        return "\n".join(lines)

    total = sum(samples)
    lines = [
        "# HELP health_check_duration_seconds Health check response time",
        "# TYPE health_check_duration_seconds histogram",
    ]
    for bucket in _HIST_BUCKETS:
        count = sum(1 for s in samples if s <= bucket)
        lines.append(f'health_check_duration_seconds_bucket{{le="{bucket}"}} {count}')
    lines.append(f'health_check_duration_seconds_bucket{{le="+Inf"}} {n}')
    lines.append(f"health_check_duration_seconds_count {n}")
    lines.append(f"health_check_duration_seconds_sum {round(total, 6)}")
    return "\n".join(lines)


def collect_all() -> dict[str, float]:
    """Collect all metrics into a single dict."""
    all_metrics: dict[str, float] = {}
    all_metrics.update(_collect_feed_counts())
    all_metrics.update(_collect_briefing_metrics())
    all_metrics.update(_collect_graph_counts())
    all_metrics.update(_collect_duckdb_queue())
    all_metrics.update(_collect_ais())
    all_metrics.update(_collect_ollama())
    all_metrics.update(_collect_pi_edge())
    all_metrics.update(_collect_rag())
    return all_metrics


def render_prometheus() -> str:
    """Render all metrics in Prometheus exposition format."""
    if not metrics_enabled():
        return "# Metrics disabled (WORLDBASE_METRICS=0)\n"

    m = collect_all()
    lines: list[str] = []

    # Gauges
    gauge_defs = [
        ("feed_fresh_count", "Number of fresh feeds"),
        ("feed_stale_count", "Number of stale feeds"),
        ("feed_error_count", "Number of feeds with errors"),
        ("briefing_quality_score", "Latest briefing quality score (0-1)"),
        ("briefing_age_seconds", "Age of latest briefing in seconds"),
        ("duckdb_entity_count", "Total FtM entities in DuckDB"),
        ("duckdb_edge_count", "Total FtM edges in DuckDB"),
        ("duckdb_queue_backlog", "DuckDB write queue backlog size"),
        ("ais_stream_connected", "AIS stream connected (1=yes, 0=no)"),
        ("ais_vessel_count", "Number of AIS vessels in buffer"),
        ("ollama_reachable", "Ollama API reachable (1=yes, 0=no)"),
        ("pi_edge_online", "Pi edge node online (1=yes, 0=no)"),
        ("prediction_pending", "Pending prediction watch items"),
        ("prediction_accuracy_30d", "30-day prediction accuracy (0-1)"),
        ("rag_query_count", "Total RAG queries"),
        ("rag_query_latency_p95", "RAG query p95 latency in seconds"),
    ]

    for name, help_text in gauge_defs:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        val = m.get(name)
        if val is not None:
            lines.append(f"{name} {val}")
        else:
            lines.append(f"{name} 0")

    # Histogram
    lines.append(_format_histogram())

    return "\n".join(lines) + "\n"
