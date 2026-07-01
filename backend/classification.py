"""V4-10 — Classification labels and federation gate.

Provides:
  - Classification levels: UNCLASSIFIED < CONFIDENTIAL < SECRET < TOP_SECRET
  - Per-entity classification labels stored in SQLite
  - Per-dataset default classification
  - Federation gate: filters entities/feeds by max classification level
    before sharing with federated nodes
  - FastAPI router with /api/classification/* endpoints

When a federated node requests data, the gate strips any entity whose
classification exceeds the node's clearance level.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND

from middleware.rbac import require_operator, require_viewer
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/classification", tags=["classification"])


def _get_db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


# ---------------------------------------------------------------------------
# Classification levels (ordered — higher = more restricted)
# ---------------------------------------------------------------------------


class ClassificationLevel(IntEnum):
    UNCLASSIFIED = 0
    CONFIDENTIAL = 1
    SECRET = 2
    TOP_SECRET = 3

    @classmethod
    def from_string(cls, label: str) -> "ClassificationLevel":
        """Parse a classification label string. Case-insensitive, hyphen-tolerant."""
        normalized = label.strip().upper().replace("-", "_").replace(" ", "_")
        try:
            return cls[normalized]
        except KeyError:
            raise ValueError(f"Unknown classification level: {label}")

    def label(self) -> str:
        return self.name


# Mapping for string ↔ int
_LEVEL_MAP: dict[str, int] = {
    "UNCLASSIFIED": 0,
    "CONFIDENTIAL": 1,
    "SECRET": 2,
    "TOP_SECRET": 3,
}

_LEVEL_NAMES: dict[int, str] = {v: k for k, v in _LEVEL_MAP.items()}

# Default classification for new entities (env-configurable)
_DEFAULT_LEVEL = os.getenv("WORLDBASE_DEFAULT_CLASSIFICATION", "UNCLASSIFIED")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_classification_tables() -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entity_classification (
                    entity_id TEXT PRIMARY KEY,
                    level INTEGER NOT NULL DEFAULT 0,
                    level_label TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
                    classified_by TEXT,
                    reason TEXT,
                    classified_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_classification (
                    dataset TEXT PRIMARY KEY,
                    default_level INTEGER NOT NULL DEFAULT 0,
                    default_level_label TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS federation_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_name TEXT,
                    max_clearance INTEGER NOT NULL DEFAULT 0,
                    max_clearance_label TEXT NOT NULL DEFAULT 'UNCLASSIFIED',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
    except Exception as exc:
        log.warning("classification_table_create_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Entity classification
# ---------------------------------------------------------------------------


def classify_entity(
    entity_id: str,
    level: str | int,
    *,
    classified_by: str = "system",
    reason: str = "",
) -> dict[str, Any]:
    """Set the classification level for an entity."""
    _ensure_classification_tables()
    if isinstance(level, str):
        level_enum = ClassificationLevel.from_string(level)
    else:
        level_enum = ClassificationLevel(level)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO entity_classification "
                "(entity_id, level, level_label, classified_by, reason, classified_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entity_id,
                    int(level_enum),
                    level_enum.label(),
                    classified_by,
                    reason,
                    now,
                    now,
                ),
            )
            conn.commit()
            return {
                "entity_id": entity_id,
                "level": int(level_enum),
                "level_label": level_enum.label(),
                "classified_by": classified_by,
                "reason": reason,
                "updated_at": now,
            }
    except Exception as exc:
        log.warning("classify_entity_failed", entity_id=entity_id, error=str(exc))
        return {"error": str(exc)}


def get_entity_classification(entity_id: str) -> dict[str, Any] | None:
    """Get the classification level for an entity, or default if unset."""
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entity_classification WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    # Return default
    default = ClassificationLevel.from_string(_DEFAULT_LEVEL)
    return {
        "entity_id": entity_id,
        "level": int(default),
        "level_label": default.label(),
        "classified_by": None,
        "reason": "default",
        "classified_at": None,
        "updated_at": None,
    }


def bulk_classify_entities(
    entity_ids: list[str], level: str | int, *, reason: str = ""
) -> int:
    """Classify multiple entities at once. Returns count classified."""
    count = 0
    for eid in entity_ids:
        result = classify_entity(eid, level, reason=reason)
        if "error" not in result:
            count += 1
    return count


def remove_entity_classification(entity_id: str) -> bool:
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "DELETE FROM entity_classification WHERE entity_id = ?",
                (entity_id,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dataset classification
# ---------------------------------------------------------------------------


def set_dataset_default(dataset: str, level: str | int) -> dict[str, Any]:
    _ensure_classification_tables()
    if isinstance(level, str):
        level_enum = ClassificationLevel.from_string(level)
    else:
        level_enum = ClassificationLevel(level)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO dataset_classification "
                "(dataset, default_level, default_level_label, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (dataset, int(level_enum), level_enum.label(), now),
            )
            conn.commit()
            return {
                "dataset": dataset,
                "default_level": int(level_enum),
                "default_level_label": level_enum.label(),
                "updated_at": now,
            }
    except Exception as exc:
        return {"error": str(exc)}


def get_dataset_default(dataset: str) -> dict[str, Any]:
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT * FROM dataset_classification WHERE dataset = ?",
                (dataset,),
            ).fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    default = ClassificationLevel.from_string(_DEFAULT_LEVEL)
    return {
        "dataset": dataset,
        "default_level": int(default),
        "default_level_label": default.label(),
    }


# ---------------------------------------------------------------------------
# Federation nodes
# ---------------------------------------------------------------------------


def register_federation_node(
    node_id: str,
    max_clearance: str | int,
    *,
    node_name: str = "",
    active: bool = True,
) -> dict[str, Any]:
    _ensure_classification_tables()
    if isinstance(max_clearance, str):
        level_enum = ClassificationLevel.from_string(max_clearance)
    else:
        level_enum = ClassificationLevel(max_clearance)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO federation_nodes "
                "(node_id, node_name, max_clearance, max_clearance_label, active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    node_id,
                    node_name,
                    int(level_enum),
                    level_enum.label(),
                    int(active),
                    now,
                    now,
                ),
            )
            conn.commit()
            return {
                "node_id": node_id,
                "node_name": node_name,
                "max_clearance": int(level_enum),
                "max_clearance_label": level_enum.label(),
                "active": active,
                "updated_at": now,
            }
    except Exception as exc:
        return {"error": str(exc)}


def list_federation_nodes() -> list[dict[str, Any]]:
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM federation_nodes ORDER BY node_id"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def remove_federation_node(node_id: str) -> bool:
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            cur = conn.execute(
                "DELETE FROM federation_nodes WHERE node_id = ?", (node_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Federation gate — filter entities by clearance
# ---------------------------------------------------------------------------


def federation_gate(
    entity_ids: list[str],
    max_clearance: str | int,
) -> tuple[list[str], list[str]]:
    """Filter entity IDs by classification level.

    Returns (allowed_ids, blocked_ids).
    Entities without an explicit classification default to UNCLASSIFIED.
    """
    if isinstance(max_clearance, str):
        max_level = int(ClassificationLevel.from_string(max_clearance))
    else:
        max_level = int(ClassificationLevel(max_clearance))

    allowed: list[str] = []
    blocked: list[str] = []

    # Batch lookup
    _ensure_classification_tables()
    classified: dict[str, int] = {}
    try:
        with _sqlite_conn() as conn:
            placeholders = ",".join("?" * len(entity_ids))
            rows = conn.execute(
                f"SELECT entity_id, level FROM entity_classification WHERE entity_id IN ({placeholders})",
                entity_ids,
            ).fetchall()
            classified = {r["entity_id"]: r["level"] for r in rows}
    except Exception:
        pass

    for eid in entity_ids:
        level = classified.get(eid, 0)  # default UNCLASSIFIED
        if level <= max_level:
            allowed.append(eid)
        else:
            blocked.append(eid)

    return allowed, blocked


def filter_entities_by_clearance(
    entities: list[dict[str, Any]],
    max_clearance: str | int,
) -> list[dict[str, Any]]:
    """Filter a list of entity dicts by classification clearance.

    Each entity dict must have an 'id' key. Entities exceeding the clearance
    are dropped. Entities without classification default to UNCLASSIFIED.
    """
    if not entities:
        return []
    ids = [e.get("id", "") for e in entities if e.get("id")]
    allowed, _blocked = federation_gate(ids, max_clearance)
    allowed_set = set(allowed)
    return [e for e in entities if e.get("id") in allowed_set]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def classification_stats() -> dict[str, Any]:
    _ensure_classification_tables()
    try:
        with _sqlite_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM entity_classification"
            ).fetchone()[0]
            by_level = conn.execute(
                "SELECT level, level_label, COUNT(*) as cnt "
                "FROM entity_classification GROUP BY level, level_label ORDER BY level"
            ).fetchall()
            datasets = conn.execute(
                "SELECT COUNT(*) FROM dataset_classification"
            ).fetchone()[0]
            nodes = conn.execute(
                "SELECT COUNT(*) FROM federation_nodes WHERE active = 1"
            ).fetchone()[0]
            return {
                "total_classified_entities": total,
                "by_level": [
                    {"level": r["level"], "label": r["level_label"], "count": r["cnt"]}
                    for r in by_level
                ],
                "dataset_defaults": datasets,
                "active_federation_nodes": nodes,
                "default_level": _DEFAULT_LEVEL,
            }
    except Exception as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class ClassifyRequest(BaseModel):
    entity_id: str
    level: str
    classified_by: str = "api"
    reason: str = ""


class BulkClassifyRequest(BaseModel):
    entity_ids: list[str]
    level: str
    reason: str = ""


class DatasetLevelRequest(BaseModel):
    dataset: str
    level: str


class FederationNodeRequest(BaseModel):
    node_id: str
    max_clearance: str
    node_name: str = ""
    active: bool = True


class GateRequest(BaseModel):
    entity_ids: list[str]
    max_clearance: str


@router.get("/levels")
async def api_levels(
    _role: str | None = Depends(require_viewer),
):
    return {
        "levels": [
            {"name": k, "value": v, "label": k}
            for k, v in sorted(_LEVEL_MAP.items(), key=lambda x: x[1])
        ],
        "default": _DEFAULT_LEVEL,
    }


@router.get("/entity/{entity_id}")
async def api_get_entity(
    entity_id: str,
    _role: str | None = Depends(require_viewer),
):
    result = get_entity_classification(entity_id)
    return result


@router.post("/entity")
async def api_classify_entity(
    req: ClassifyRequest,
    _role: str | None = Depends(require_operator),
):
    return classify_entity(
        req.entity_id, req.level, classified_by=req.classified_by, reason=req.reason
    )


@router.post("/entity/bulk")
async def api_bulk_classify(
    req: BulkClassifyRequest,
    _role: str | None = Depends(require_operator),
):
    count = bulk_classify_entities(req.entity_ids, req.level, reason=req.reason)
    return {"classified": count, "total": len(req.entity_ids)}


@router.delete("/entity/{entity_id}")
async def api_remove_entity(
    entity_id: str,
    _role: str | None = Depends(require_operator),
):
    if not remove_entity_classification(entity_id):
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND, detail="No classification found"
        )
    return {"removed": True}


@router.post("/dataset")
async def api_set_dataset(
    req: DatasetLevelRequest,
    _role: str | None = Depends(require_operator),
):
    return set_dataset_default(req.dataset, req.level)


@router.get("/dataset/{dataset}")
async def api_get_dataset(
    dataset: str,
    _role: str | None = Depends(require_viewer),
):
    return get_dataset_default(dataset)


@router.post("/federation/node")
async def api_register_node(
    req: FederationNodeRequest,
    _role: str | None = Depends(require_operator),
):
    return register_federation_node(
        req.node_id, req.max_clearance, node_name=req.node_name, active=req.active
    )


@router.get("/federation/nodes")
async def api_list_nodes(
    _role: str | None = Depends(require_viewer),
):
    return {"nodes": list_federation_nodes()}


@router.delete("/federation/node/{node_id}")
async def api_remove_node(
    node_id: str,
    _role: str | None = Depends(require_operator),
):
    if not remove_federation_node(node_id):
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Node not found")
    return {"removed": True}


@router.post("/gate")
async def api_gate(
    req: GateRequest,
    _role: str | None = Depends(require_viewer),
):
    allowed, blocked = federation_gate(req.entity_ids, req.max_clearance)
    return {"allowed": allowed, "blocked": blocked, "total": len(req.entity_ids)}


@router.get("/stats")
async def api_stats(
    _role: str | None = Depends(require_viewer),
):
    return classification_stats()


__all__ = [
    "ClassificationLevel",
    "classify_entity",
    "get_entity_classification",
    "bulk_classify_entities",
    "remove_entity_classification",
    "set_dataset_default",
    "get_dataset_default",
    "register_federation_node",
    "list_federation_nodes",
    "remove_federation_node",
    "federation_gate",
    "filter_entities_by_clearance",
    "classification_stats",
    "router",
]
