"""Impact graph — cascade refresh + invalidation (J4).

When a source entity is corrected, invalidates downstream watch items
and triggers re-briefing / re-insight generation.
"""

from __future__ import annotations

import os
from typing import Any

from lineage import (
    get_full_impact,
    get_downstream,
    lineage_enabled,
)


def get_impact(entity_id: str) -> dict[str, Any]:
    """Get full impact analysis for an entity."""
    return get_full_impact(entity_id)


def cascade_refresh(source_id: str, source_type: str = "entity") -> dict[str, Any]:
    """Invalidate all downstream targets for a source.

    Marks watch items as invalidated, triggers re-briefing flag.
    Returns summary of what was invalidated.
    """
    if not lineage_enabled():
        return {
            "enabled": False,
            "message": "WORLDBASE_LINEAGE=0 — lineage tracking disabled",
        }

    impact = get_full_impact(source_id) if source_type == "entity" else None

    if impact is None:
        # Non-entity source — get direct downstream
        downstream = get_downstream(source_id, source_type)
        impact = {
            "entity_id": source_id,
            "briefings": [
                d["target_id"] for d in downstream if d["target_type"] == "briefing"
            ],
            "insights": [
                d["target_id"] for d in downstream if d["target_type"] == "insight"
            ],
            "watch_items": [
                d["target_id"] for d in downstream if d["target_type"] == "watch_item"
            ],
            "fusion_cells": [
                d["target_id"] for d in downstream if d["target_type"] == "fusion_cell"
            ],
            "feed_sources": [],
            "sibling_entities": [],
            "total_downstream": len(downstream),
        }

    # Invalidate watch items in prediction ledger
    invalidated = 0
    if impact["watch_items"]:
        try:
            import sqlite3

            db_path = os.getenv("WORLDBASE_DB_PATH", "") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
            )
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")

            # Check if prediction_ledger table exists
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prediction_ledger'"
            ).fetchone()

            if tables:
                for item_id in impact["watch_items"]:
                    conn.execute(
                        "UPDATE prediction_ledger SET invalidated = 1, invalidation_reason = 'source corrected' WHERE id = ?",
                        (item_id,),
                    )
                    invalidated += 1
                conn.commit()

            conn.close()
        except Exception:
            pass

    return {
        "enabled": True,
        "source_id": source_id,
        "source_type": source_type,
        "briefings_affected": len(impact["briefings"]),
        "insights_affected": len(impact["insights"]),
        "watch_items_invalidated": invalidated,
        "fusion_cells_affected": len(impact["fusion_cells"]),
        "total_downstream": impact["total_downstream"],
        "requires_rebriefing": len(impact["briefings"]) > 0,
        "requires_reinsight": len(impact["insights"]) > 0,
    }


def impact_stats() -> dict[str, Any]:
    """Get impact graph statistics."""
    from lineage import lineage_stats

    stats = lineage_stats()
    return {
        "lineage": stats,
        "cascade_available": lineage_enabled(),
    }
