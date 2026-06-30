"""Briefing pipeline state model — Kanban stages for intelligence items.

Five-stage pipeline: INGEST → ANALYZE → CORROBORATE → SYNTHESIZE → PUBLISHED.

Items are derived from the latest briefing's watch_items, insights, alerts,
and fusion_hotspots. Each item gets a stable ID and a stage in the
``briefing_pipeline`` SQLite table. The frontend Kanban board reads and
moves items between stages via the API.

Design:
- ``briefing_pipeline`` table stores per-item stage + metadata.
- ``sync_from_briefing()`` upserts items from the latest briefing, adding
  new items at INGEST and removing items no longer present.
- ``get_pipeline()`` returns items grouped by stage.
- ``move_item()`` transitions an item to a new stage with validation.
- Fail-soft: all operations return empty/error on DB failure.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlite_bootstrap import DB_PATH

logger = logging.getLogger(__name__)

STAGES = ["INGEST", "ANALYZE", "CORROBORATE", "SYNTHESIZE", "PUBLISHED"]
STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_pipeline_db() -> None:
    """Create briefing_pipeline table if missing. Called on startup."""
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS briefing_pipeline (
                item_id TEXT PRIMARY KEY,
                stage TEXT NOT NULL DEFAULT 'INGEST',
                title TEXT,
                item_type TEXT,
                confidence REAL,
                sources TEXT,
                lat REAL,
                lon REAL,
                bucket TEXT,
                payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)


def _extract_items_from_briefing(briefing: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract pipeline items from a briefing dict.

    Each item gets: item_id, item_type, title, confidence, sources, lat, lon, bucket, payload.
    """
    items: list[dict[str, Any]] = []

    for wi in briefing.get("watch_items") or []:
        item_id = (
            wi.get("id") or f"watch:{wi.get('prefix', '')}:{wi.get('title', '')[:40]}"
        )
        items.append(
            {
                "item_id": str(item_id),
                "item_type": "watch",
                "title": str(wi.get("title", ""))[:200],
                "confidence": float(wi.get("confidence") or 0),
                "sources": wi.get("sources") or [],
                "lat": wi.get("lat"),
                "lon": wi.get("lon"),
                "bucket": wi.get("bucket") or "global",
                "payload": wi,
            }
        )

    for ins in briefing.get("insights") or []:
        item_id = ins.get("id") or f"insight:{ins.get('cell_id', '')}"
        center = ins.get("center") or {}
        items.append(
            {
                "item_id": str(item_id),
                "item_type": "insight",
                "title": str(ins.get("headline", ""))[:200],
                "confidence": float(ins.get("confidence") or 0),
                "sources": ins.get("sources") or [],
                "lat": center.get("lat"),
                "lon": center.get("lon"),
                "bucket": "global",
                "payload": ins,
            }
        )

    for alert in briefing.get("alerts") or []:
        item_id = alert.get("id") or f"alert:{alert.get('title', '')[:40]}"
        items.append(
            {
                "item_id": str(item_id),
                "item_type": "alert",
                "title": str(alert.get("title") or alert.get("message", ""))[:200],
                "confidence": float(alert.get("confidence") or 0.5),
                "sources": alert.get("sources") or [],
                "lat": alert.get("lat"),
                "lon": alert.get("lon"),
                "bucket": alert.get("bucket") or "global",
                "payload": alert,
            }
        )

    for hs in briefing.get("fusion_hotspots") or []:
        cid = hs.get("cell_id") or f"{hs.get('lat', '')},{hs.get('lon', '')}"
        item_id = f"hotspot:{cid}"
        items.append(
            {
                "item_id": item_id,
                "item_type": "hotspot",
                "title": f"Fusion hotspot — {hs.get('lat', '?')},{hs.get('lon', '?')}",
                "confidence": float(hs.get("score") or 0),
                "sources": hs.get("sources") or [],
                "lat": hs.get("lat"),
                "lon": hs.get("lon"),
                "bucket": "global",
                "payload": hs,
            }
        )

    return items


def sync_from_briefing(briefing: dict[str, Any]) -> int:
    """Sync items from the latest briefing into the pipeline table.

    New items are inserted at INGEST stage. Existing items keep their stage.
    Items no longer in the briefing are removed (unless PUBLISHED).

    Returns number of items upserted.
    """
    items = _extract_items_from_briefing(briefing)
    if not items:
        return 0

    now = _now_iso()
    current_ids: set[str] = set()
    count = 0

    with _db() as conn:
        for item in items:
            item_id = item["item_id"]
            current_ids.add(item_id)
            sources_json = json.dumps(item["sources"])
            payload_json = json.dumps(item["payload"], default=str)

            try:
                row = conn.execute(
                    "SELECT stage FROM briefing_pipeline WHERE item_id = ?",
                    (item_id,),
                ).fetchone()

                if row:
                    conn.execute(
                        """UPDATE briefing_pipeline SET
                            title = ?, item_type = ?, confidence = ?,
                            sources = ?, lat = ?, lon = ?, bucket = ?,
                            payload = ?, updated_at = ?
                        WHERE item_id = ?""",
                        (
                            item["title"],
                            item["item_type"],
                            item["confidence"],
                            sources_json,
                            item["lat"],
                            item["lon"],
                            item["bucket"],
                            payload_json,
                            now,
                            item_id,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT INTO briefing_pipeline
                            (item_id, stage, title, item_type, confidence,
                             sources, lat, lon, bucket, payload, created_at, updated_at)
                        VALUES (?, 'INGEST', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item_id,
                            item["title"],
                            item["item_type"],
                            item["confidence"],
                            sources_json,
                            item["lat"],
                            item["lon"],
                            item["bucket"],
                            payload_json,
                            now,
                            now,
                        ),
                    )
                count += 1
            except Exception as exc:
                logger.warning("pipeline upsert failed for %s: %s", item_id, exc)

        # Remove items no longer in briefing, except PUBLISHED ones
        try:
            all_rows = conn.execute(
                "SELECT item_id, stage FROM briefing_pipeline"
            ).fetchall()
            for r in all_rows:
                if r["item_id"] not in current_ids and r["stage"] != "PUBLISHED":
                    conn.execute(
                        "DELETE FROM briefing_pipeline WHERE item_id = ?",
                        (r["item_id"],),
                    )
        except Exception as exc:
            logger.warning("pipeline cleanup failed: %s", exc)

    return count


def get_pipeline() -> dict[str, list[dict[str, Any]]]:
    """Return items grouped by stage.

    Returns dict with all 5 stages as keys, each containing a list of item dicts.
    """
    result: dict[str, list[dict[str, Any]]] = {s: [] for s in STAGES}

    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM briefing_pipeline ORDER BY updated_at DESC"
            ).fetchall()
    except sqlite3.OperationalError:
        return result

    for row in rows:
        stage = row["stage"] if row["stage"] in STAGE_ORDER else "INGEST"
        try:
            sources = json.loads(row["sources"]) if row["sources"] else []
        except Exception:
            sources = []
        try:
            payload = json.loads(row["payload"]) if row["payload"] else {}
        except Exception:
            payload = {}

        result[stage].append(
            {
                "item_id": row["item_id"],
                "stage": stage,
                "title": row["title"] or "",
                "item_type": row["item_type"] or "",
                "confidence": row["confidence"] or 0,
                "sources": sources,
                "lat": row["lat"],
                "lon": row["lon"],
                "bucket": row["bucket"] or "global",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "payload": payload,
            }
        )

    return result


def move_item(item_id: str, target_stage: str) -> dict[str, Any]:
    """Move an item to a target stage.

    Validates that target_stage is a known stage. Returns the updated item dict
    or raises ValueError on invalid stage / missing item.

    Forward and backward moves are both allowed (operator can drag cards freely).
    """
    if target_stage not in STAGE_ORDER:
        raise ValueError(f"Invalid stage: {target_stage}. Must be one of {STAGES}")

    now = _now_iso()

    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM briefing_pipeline WHERE item_id = ?", (item_id,)
        ).fetchone()

        if not row:
            raise ValueError(f"Item not found: {item_id}")

        old_stage = row["stage"]
        conn.execute(
            "UPDATE briefing_pipeline SET stage = ?, updated_at = ? WHERE item_id = ?",
            (target_stage, now, item_id),
        )

        return {
            "item_id": item_id,
            "old_stage": old_stage,
            "new_stage": target_stage,
            "updated_at": now,
        }


def get_pipeline_flat() -> list[dict[str, Any]]:
    """Return all pipeline items as a flat list (for testing/debugging)."""
    grouped = get_pipeline()
    flat: list[dict[str, Any]] = []
    for stage in STAGES:
        flat.extend(grouped[stage])
    return flat


def clear_pipeline() -> int:
    """Remove all items from the pipeline table. Returns count deleted."""
    with _db() as conn:
        cur = conn.execute("DELETE FROM briefing_pipeline")
        return cur.rowcount
