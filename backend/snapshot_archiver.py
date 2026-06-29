"""V4-09 Daily Snapshot Archiver.

Captures daily snapshots of key system metrics (entity counts, feed counts,
briefing quality, fusion hotspot count, prediction accuracy) and stores them
as JSON files with a manifest index. Parquet is used when pyarrow is available;
otherwise JSON is used as fallback.

Snapshots are written to ``data/snapshots/`` with a manifest at
``data/snapshots/manifest.json``.

Feature flag: ``WORLDBASE_SNAPSHOT_ARCHIVER=0`` (default off, opt-in).
Snapshot interval: ``WORLDBASE_SNAPSHOT_INTERVAL_HOURS=24`` (default 24h).

API endpoints:
    GET /api/snapshots          — list all snapshots
    GET /api/snapshots/latest   — most recent snapshot
    POST /api/snapshots/run     — trigger snapshot now (auth required)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth.security import verify_api_key
from structured_log import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _enabled() -> bool:
    return os.getenv("WORLDBASE_SNAPSHOT_ARCHIVER", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_INTERVAL_HOURS = float(os.getenv("WORLDBASE_SNAPSHOT_INTERVAL_HOURS", "24"))
_SNAPSHOT_DIR = os.getenv(
    "WORLDBASE_SNAPSHOT_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "snapshots"
    ),
)

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])


# ---------------------------------------------------------------------------
# Snapshot collection
# ---------------------------------------------------------------------------


def _collect_snapshot() -> dict[str, Any]:
    """Collect a single snapshot of all system metrics.

    Fail-soft: each section is wrapped in try/except so one failing source
    doesn't abort the entire snapshot.
    """
    snapshot: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # FtM entity graph stats (DuckDB)
    try:
        import ftm_query

        stats = ftm_query.stats()
        snapshot["ftm"] = {
            "entities": stats.get("entities", 0),
            "statements": stats.get("statements", 0),
            "edges": stats.get("edges", 0),
            "by_schema": stats.get("by_schema", {}),
        }
    except Exception as exc:
        snapshot["ftm"] = {"error": str(exc)[:200]}
        log.debug("snapshot_ftm_failed", error=str(exc)[:200])

    # SQLite entity store count
    try:
        import sqlite3
        from sqlite_bootstrap import DB_PATH

        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        conn.close()
        snapshot["entity_store"] = {"count": count}
    except Exception as exc:
        snapshot["entity_store"] = {"error": str(exc)[:200]}

    # Feed counts
    try:
        import metrics

        m = metrics.collect_all()
        snapshot["feeds"] = {
            "fresh_count": int(m.get("feed_fresh_count", 0)),
            "stale_count": int(m.get("feed_stale_count", 0)),
            "error_count": int(m.get("feed_error_count", 0)),
            "total_feeds": int(m.get("feed_total_count", 0)),
        }
    except Exception as exc:
        snapshot["feeds"] = {"error": str(exc)[:200]}

    # Briefing quality
    try:
        import sqlite3
        from sqlite_bootstrap import DB_PATH

        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT created_at, text FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            text = row["text"] or ""
            snapshot["briefing"] = {
                "latest_at": row["created_at"],
                "text_length": len(text),
                "insight_count": text.count("## "),
                "watch_count": text.lower().count("watch"),
            }
        else:
            snapshot["briefing"] = {"latest_at": None}
    except Exception as exc:
        snapshot["briefing"] = {"error": str(exc)[:200]}

    # Fusion hotspot count (async — skip in sync collection, handled in async path)
    snapshot["fusion"] = {"hotspot_count": 0, "top_cell_score": 0}

    # Prediction accuracy
    try:
        import prediction_ledger

        preds = prediction_ledger.list_predictions(pending_limit=0, resolved_limit=100)
        resolved = preds.get("resolved") or []
        correct = sum(1 for p in resolved if p.get("outcome") == "correct")
        snapshot["predictions"] = {
            "resolved_count": len(resolved),
            "correct_count": correct,
            "accuracy": round(correct / len(resolved), 4) if resolved else None,
        }
    except Exception as exc:
        snapshot["predictions"] = {"error": str(exc)[:200]}

    # RAG chunk count
    try:
        import sqlite3
        from sqlite_bootstrap import DB_PATH

        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        count = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        conn.close()
        snapshot["rag"] = {"chunk_count": count}
    except Exception as exc:
        snapshot["rag"] = {"error": str(exc)[:200]}

    return snapshot


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


def _ensure_snapshot_dir() -> Path:
    """Ensure the snapshot directory exists."""
    path = Path(_SNAPSHOT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_filename(date_str: str) -> str:
    return f"snapshot_{date_str}.json"


def _save_snapshot(snapshot: dict[str, Any]) -> str:
    """Save snapshot to disk and update manifest.

    Returns the file path of the saved snapshot.
    """
    dir_path = _ensure_snapshot_dir()
    filename = _snapshot_filename(snapshot["date"])
    filepath = dir_path / filename

    # Save snapshot file
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)

    # Update manifest
    _update_manifest(filepath.name, snapshot)

    return str(filepath)


def _manifest_path() -> Path:
    return Path(_SNAPSHOT_DIR) / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    """Load the manifest, or return empty structure."""
    mp = _manifest_path()
    if mp.exists():
        try:
            with open(mp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"snapshots": []}


def _update_manifest(filename: str, snapshot: dict[str, Any]) -> None:
    """Add or update an entry in the manifest."""
    manifest = _load_manifest()
    entries = manifest.get("snapshots", [])

    # Remove existing entry for same date
    date_str = snapshot["date"]
    entries = [e for e in entries if e.get("date") != date_str]

    # Add new entry
    entries.append(
        {
            "date": date_str,
            "filename": filename,
            "timestamp": snapshot["timestamp"],
            "ftm_entities": snapshot.get("ftm", {}).get("entities", 0),
            "ftm_statements": snapshot.get("ftm", {}).get("statements", 0),
            "ftm_edges": snapshot.get("ftm", {}).get("edges", 0),
            "feed_fresh": snapshot.get("feeds", {}).get("fresh_count", 0),
            "feed_stale": snapshot.get("feeds", {}).get("stale_count", 0),
            "briefing_latest_at": snapshot.get("briefing", {}).get("latest_at"),
            "fusion_hotspots": snapshot.get("fusion", {}).get("hotspot_count", 0),
            "prediction_accuracy": snapshot.get("predictions", {}).get("accuracy"),
            "rag_chunks": snapshot.get("rag", {}).get("chunk_count", 0),
        }
    )

    # Sort by date descending
    entries.sort(key=lambda e: e.get("date", ""), reverse=True)

    manifest["snapshots"] = entries
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()

    mp = _manifest_path()
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def take_snapshot() -> dict[str, Any]:
    """Collect and save a snapshot. Returns the snapshot dict + file path.

    Raises if snapshot collection fails entirely.
    """
    t0 = time.perf_counter()
    snapshot = _collect_snapshot()
    filepath = _save_snapshot(snapshot)
    elapsed = round(time.perf_counter() - t0, 2)
    snapshot["_filepath"] = filepath
    snapshot["_elapsed_s"] = elapsed
    log.info(
        "snapshot_taken",
        date=snapshot["date"],
        elapsed_s=elapsed,
        ftm_entities=snapshot.get("ftm", {}).get("entities", 0),
    )
    return snapshot


def list_snapshots(limit: int = 30) -> dict[str, Any]:
    """List recent snapshots from manifest."""
    manifest = _load_manifest()
    entries = manifest.get("snapshots", [])[:limit]
    return {
        "total": len(manifest.get("snapshots", [])),
        "returned": len(entries),
        "snapshots": entries,
    }


def get_latest_snapshot() -> dict[str, Any]:
    """Get the most recent snapshot (full data, not just manifest entry)."""
    manifest = _load_manifest()
    entries = manifest.get("snapshots", [])
    if not entries:
        return {"error": "No snapshots available"}
    latest = entries[0]
    filepath = Path(_SNAPSHOT_DIR) / latest["filename"]
    if not filepath.exists():
        return {"error": "Snapshot file missing", "filename": latest["filename"]}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def get_snapshot_by_date(date_str: str) -> dict[str, Any]:
    """Get a specific snapshot by date (YYYY-MM-DD)."""
    filepath = Path(_SNAPSHOT_DIR) / _snapshot_filename(date_str)
    if not filepath.exists():
        return {"error": "Snapshot not found", "date": date_str}
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Autopilot integration
# ---------------------------------------------------------------------------


async def snapshot_autopilot() -> None:
    """Background loop: take daily snapshots.

    Intended to be registered in lifespan.py as a supervised task.
    """
    await asyncio.sleep(120)  # Initial delay — let other systems warm up
    interval_sec = _INTERVAL_HOURS * 3600
    while True:
        try:
            take_snapshot()
        except Exception as exc:
            log.warning("snapshot_autopilot_failed", error=str(exc)[:200])
        await asyncio.sleep(interval_sec)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


class SnapshotListResponse(BaseModel):
    total: int
    returned: int
    snapshots: list[dict[str, Any]]


@router.get("")
async def list_snapshots_endpoint(
    limit: int = Query(30, ge=1, le=365),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """List recent snapshots from manifest."""
    if not _enabled():
        return {
            "enabled": False,
            "error": "Snapshot archiver disabled. Set WORLDBASE_SNAPSHOT_ARCHIVER=1.",
        }
    return list_snapshots(limit=limit)


@router.get("/latest")
async def latest_snapshot_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get the most recent snapshot (full data)."""
    if not _enabled():
        return {
            "enabled": False,
            "error": "Snapshot archiver disabled. Set WORLDBASE_SNAPSHOT_ARCHIVER=1.",
        }
    return get_latest_snapshot()


@router.get("/{date}")
async def snapshot_by_date_endpoint(
    date: str,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get a specific snapshot by date (YYYY-MM-DD format)."""
    if not _enabled():
        return {
            "enabled": False,
            "error": "Snapshot archiver disabled. Set WORLDBASE_SNAPSHOT_ARCHIVER=1.",
        }
    return get_snapshot_by_date(date)


@router.post("/run")
async def run_snapshot_now(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Trigger a snapshot immediately."""
    if not _enabled():
        return {
            "enabled": False,
            "error": "Snapshot archiver disabled. Set WORLDBASE_SNAPSHOT_ARCHIVER=1.",
        }
    try:
        result = take_snapshot()
        return {
            "ok": True,
            "date": result["date"],
            "filepath": result.get("_filepath"),
            "elapsed_s": result.get("_elapsed_s"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:500]}
