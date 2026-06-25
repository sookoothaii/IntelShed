"""Data Lineage store + trace (J4).

Tracks feed→entity→briefing→insight→watch_item dependencies in SQLite.
When a source is corrected, downstream targets can be invalidated and refreshed.

Tables:
  lineage: source_id, source_type, target_id, target_type, edge_type, created_at

Edge types:
  feed_item→entity, entity→briefing, entity→insight,
  entity→watch_item, feed_item→fusion_cell

WORLDBASE_LINEAGE=0 (default off — adds write overhead to ingest).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH", "") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def lineage_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_LINEAGE", "0"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_lineage_db() -> None:
    """Create lineage table if not exists."""
    try:
        conn = _get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS lineage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_lineage_source ON lineage(source_id, source_type);
            CREATE INDEX IF NOT EXISTS idx_lineage_target ON lineage(target_id, target_type);
            CREATE INDEX IF NOT EXISTS idx_lineage_edge ON lineage(edge_type);
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_edge(
    source_id: str,
    source_type: str,
    target_id: str,
    target_type: str,
    edge_type: str,
) -> None:
    """Record a lineage edge from source to target."""
    if not lineage_enabled():
        return
    init_lineage_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO lineage (source_id, source_type, target_id, target_type, edge_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (source_id, source_type, target_id, target_type, edge_type, now),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_feed_to_entity(feed_item_id: str, entity_id: str) -> None:
    """Trace: feed item → FtM entity."""
    record_edge(feed_item_id, "feed_item", entity_id, "entity", "feed_item→entity")


def record_entity_to_briefing(entity_id: str, briefing_id: str) -> None:
    """Trace: entity → briefing."""
    record_edge(entity_id, "entity", briefing_id, "briefing", "entity→briefing")


def record_entity_to_insight(entity_id: str, insight_id: str) -> None:
    """Trace: entity → insight."""
    record_edge(entity_id, "entity", insight_id, "insight", "entity→insight")


def record_entity_to_watch_item(entity_id: str, watch_item_id: str) -> None:
    """Trace: entity → watch item."""
    record_edge(entity_id, "entity", watch_item_id, "watch_item", "entity→watch_item")


def record_feed_to_fusion(feed_item_id: str, fusion_cell_id: str) -> None:
    """Trace: feed item → fusion cell."""
    record_edge(
        feed_item_id,
        "feed_item",
        fusion_cell_id,
        "fusion_cell",
        "feed_item→fusion_cell",
    )


def get_downstream(
    source_id: str, source_type: str | None = None
) -> list[dict[str, Any]]:
    """Get all direct downstream targets for a source."""
    init_lineage_db()
    conn = _get_conn()
    if source_type:
        rows = conn.execute(
            "SELECT * FROM lineage WHERE source_id = ? AND source_type = ? ORDER BY created_at DESC",
            (source_id, source_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM lineage WHERE source_id = ? ORDER BY created_at DESC",
            (source_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_upstream(
    target_id: str, target_type: str | None = None
) -> list[dict[str, Any]]:
    """Get all direct upstream sources for a target."""
    init_lineage_db()
    conn = _get_conn()
    if target_type:
        rows = conn.execute(
            "SELECT * FROM lineage WHERE target_id = ? AND target_type = ? ORDER BY created_at DESC",
            (target_id, target_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM lineage WHERE target_id = ? ORDER BY created_at DESC",
            (target_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_full_impact(entity_id: str) -> dict[str, Any]:
    """Get full downstream impact chain for an entity.

    Returns all briefings, insights, watch items, and fusion cells
    that depend on this entity (transitive — follows feed→entity→* chain).
    """
    init_lineage_db()
    conn = _get_conn()

    # Direct downstream
    direct = conn.execute(
        "SELECT * FROM lineage WHERE source_id = ? AND source_type = 'entity'",
        (entity_id,),
    ).fetchall()

    # Also check if this entity is a feed item target (feed→entity)
    feed_sources = conn.execute(
        "SELECT source_id FROM lineage WHERE target_id = ? AND edge_type = 'feed_item→entity'",
        (entity_id,),
    ).fetchall()

    # For each feed source, get other entities from same feed
    sibling_entities: list[dict[str, Any]] = []
    for fs in feed_sources:
        siblings = conn.execute(
            "SELECT target_id, edge_type FROM lineage WHERE source_id = ? AND edge_type = 'feed_item→entity'",
            (fs["source_id"],),
        ).fetchall()
        for s in siblings:
            if s["target_id"] != entity_id:
                sibling_entities.append(
                    {"entity_id": s["target_id"], "feed_item_id": fs["source_id"]}
                )

    conn.close()

    # Categorize direct downstream
    briefings: list[str] = []
    insights: list[str] = []
    watch_items: list[str] = []
    fusion_cells: list[str] = []

    for row in direct:
        target_type = row["target_type"]
        target_id = row["target_id"]
        if target_type == "briefing":
            briefings.append(target_id)
        elif target_type == "insight":
            insights.append(target_id)
        elif target_type == "watch_item":
            watch_items.append(target_id)
        elif target_type == "fusion_cell":
            fusion_cells.append(target_id)

    return {
        "entity_id": entity_id,
        "briefings": briefings,
        "insights": insights,
        "watch_items": watch_items,
        "fusion_cells": fusion_cells,
        "feed_sources": [r["source_id"] for r in feed_sources],
        "sibling_entities": sibling_entities,
        "total_downstream": len(briefings)
        + len(insights)
        + len(watch_items)
        + len(fusion_cells),
    }


def delete_edges(source_id: str, source_type: str | None = None) -> int:
    """Delete lineage edges for a source. Returns count deleted."""
    init_lineage_db()
    conn = _get_conn()
    if source_type:
        cursor = conn.execute(
            "DELETE FROM lineage WHERE source_id = ? AND source_type = ?",
            (source_id, source_type),
        )
    else:
        cursor = conn.execute(
            "DELETE FROM lineage WHERE source_id = ?",
            (source_id,),
        )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def lineage_stats() -> dict[str, Any]:
    """Get lineage table statistics."""
    init_lineage_db()
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) as c FROM lineage").fetchone()["c"]
    by_edge = conn.execute(
        "SELECT edge_type, COUNT(*) as c FROM lineage GROUP BY edge_type ORDER BY c DESC"
    ).fetchall()
    conn.close()
    return {
        "enabled": lineage_enabled(),
        "total_edges": total,
        "by_edge_type": {r["edge_type"]: r["c"] for r in by_edge},
    }
