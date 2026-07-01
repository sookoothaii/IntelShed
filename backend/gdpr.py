"""V4-06 — GDPR export and deletion of personal data.

Provides:
  - export_personal_data(entity_id) → structured JSON bundle of all PII
  - delete_personal_data(entity_id) → purges entity from FtM + SQLite stores
  - list_data_subjects(query)       → find Person entities by name/email/id
  - FastAPI router with /api/gdpr/* endpoints (operator-only)

GDPR Art. 15 (right of access) and Art. 17 (right to erasure) compliance.
All operations are logged to the audit trail.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from starlette.status import HTTP_404_NOT_FOUND

from middleware.rbac import require_operator
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/gdpr", tags=["gdpr"])


def _get_db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


# FtM Person schema properties that constitute PII under GDPR
_PII_PROPS: frozenset[str] = frozenset(
    {
        "name",
        "firstName",
        "secondName",
        "middleName",
        "fatherName",
        "motherName",
        "lastName",
        "email",
        "phone",
        "nationalId",
        "passportNumber",
        "birthDate",
        "birthPlace",
        "birthCountry",
        "deathDate",
        "address",
        "addressEntity",
        "city",
        "postalCode",
        "country",
        "latitude",
        "longitude",
        "identificationNumber",
        "registrationNumber",
        "idNumber",
        "notes",
    }
)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _ensure_gdpr_tables() -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gdpr_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    requested_by TEXT,
                    status TEXT NOT NULL DEFAULT 'completed',
                    details TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gdpr_requests_entity ON gdpr_requests(entity_id)"
            )
            conn.commit()
    except Exception as exc:
        log.warning("gdpr_table_create_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Export (Art. 15 — right of access)
# ---------------------------------------------------------------------------


def export_personal_data(entity_id: str) -> dict[str, Any]:
    """Collect all personal data associated with *entity_id*.

    Returns a structured JSON-serialisable dict with:
      - entity: core FtM entity record
      - statements: all provenance statements
      - edges: all relationships
      - sqlite_entity: legacy entity_store row (if any)
      - audit_trail: auth_audit mentions (if any)
    """
    _ensure_gdpr_tables()
    bundle: dict[str, Any] = {
        "entity_id": entity_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "entity": None,
        "statements": [],
        "edges": [],
        "intel_edges": [],
        "sqlite_entity": None,
        "audit_trail": [],
    }

    # 1. FtM entity (DuckDB)
    try:
        from ftm_store import get_entity, get_statements

        entity = get_entity(entity_id)
        if entity:
            bundle["entity"] = entity

        stmts = get_statements(entity_id)
        if stmts:
            bundle["statements"] = stmts
    except Exception as exc:
        log.warning("gdpr_export_ftm_failed", entity_id=entity_id, error=str(exc))

    # 2. FtM edges (DuckDB)
    try:
        from ftm_store import run_query_ro

        edges = run_query_ro(
            "SELECT * FROM edges WHERE source_id = ? OR target_id = ?",
            [entity_id, entity_id],
        )
        if edges:
            bundle["edges"] = edges

        intel_edges = run_query_ro(
            "SELECT * FROM intel_edges WHERE source_id = ? OR target_id = ?",
            [entity_id, entity_id],
        )
        if intel_edges:
            bundle["intel_edges"] = intel_edges
    except Exception as exc:
        log.warning("gdpr_export_edges_failed", entity_id=entity_id, error=str(exc))

    # 3. Legacy SQLite entity_store
    try:
        with _sqlite_conn() as conn:
            row = conn.execute(
                "SELECT * FROM entities WHERE id = ?", (entity_id,)
            ).fetchone()
            if row:
                bundle["sqlite_entity"] = dict(row)

            links = conn.execute(
                "SELECT * FROM entity_links WHERE from_id = ? OR to_id = ?",
                (entity_id, entity_id),
            ).fetchall()
            if links:
                bundle["entity_links"] = [dict(r) for r in links]
    except Exception as exc:
        log.warning("gdpr_export_sqlite_failed", entity_id=entity_id, error=str(exc))

    # 4. Audit trail mentions
    try:
        with _sqlite_conn() as conn:
            audit_rows = conn.execute(
                "SELECT * FROM auth_audit WHERE endpoint LIKE ? OR error LIKE ?",
                (f"%{entity_id}%", f"%{entity_id}%"),
            ).fetchall()
            if audit_rows:
                bundle["audit_trail"] = [dict(r) for r in audit_rows]
    except Exception:
        pass

    # 5. Record the request
    _record_request(
        "export", entity_id, details=json.dumps({"keys": list(bundle.keys())})
    )

    return bundle


# ---------------------------------------------------------------------------
# Deletion (Art. 17 — right to erasure)
# ---------------------------------------------------------------------------


def delete_personal_data(entity_id: str, *, hard_delete: bool = True) -> dict[str, Any]:
    """Delete all personal data for *entity_id*.

    With *hard_delete*=True (default): physically removes rows from DuckDB
    and SQLite. With hard_delete=False: anonymises PII fields in-place
    (keeps structure for referential integrity).

    Returns a summary of what was deleted.
    """
    _ensure_gdpr_tables()
    result: dict[str, Any] = {
        "entity_id": entity_id,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "mode": "hard_delete" if hard_delete else "anonymise",
        "ftm_entity": 0,
        "ftm_statements": 0,
        "ftm_edges": 0,
        "ftm_intel_edges": 0,
        "sqlite_entity": 0,
        "sqlite_links": 0,
    }

    if hard_delete:
        # 1. DuckDB: entity + statements + edges
        try:
            from ftm_connection import _conn, _LOCK

            with _LOCK:
                con = _conn()
                if con is None:
                    raise RuntimeError("DuckDB connection not available")
                con.execute("BEGIN TRANSACTION")
                try:
                    cur = con.execute("DELETE FROM entities WHERE id = ?", [entity_id])
                    result["ftm_entity"] = cur.rowcount if cur.rowcount > 0 else 0

                    cur = con.execute(
                        "DELETE FROM statements WHERE entity_id = ?", [entity_id]
                    )
                    result["ftm_statements"] = cur.rowcount if cur.rowcount > 0 else 0

                    cur = con.execute(
                        "DELETE FROM edges WHERE source_id = ? OR target_id = ?",
                        [entity_id, entity_id],
                    )
                    result["ftm_edges"] = cur.rowcount if cur.rowcount > 0 else 0

                    cur = con.execute(
                        "DELETE FROM intel_edges WHERE source_id = ? OR target_id = ?",
                        [entity_id, entity_id],
                    )
                    result["ftm_intel_edges"] = cur.rowcount if cur.rowcount > 0 else 0

                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
        except Exception as exc:
            log.error("gdpr_delete_ftm_failed", entity_id=entity_id, error=str(exc))
            result["ftm_error"] = str(exc)

        # 2. SQLite: entity_store
        try:
            with _sqlite_conn() as conn:
                cur = conn.execute("DELETE FROM entities WHERE id = ?", (entity_id,))
                result["sqlite_entity"] = cur.rowcount
                cur = conn.execute(
                    "DELETE FROM entity_links WHERE from_id = ? OR to_id = ?",
                    (entity_id, entity_id),
                )
                result["sqlite_links"] = cur.rowcount
                conn.commit()
        except Exception as exc:
            log.warning(
                "gdpr_delete_sqlite_failed", entity_id=entity_id, error=str(exc)
            )

    else:
        # Anonymise: replace PII values with [REDACTED]
        try:
            from ftm_store import get_entity
            from ftm_connection import _conn, _LOCK

            entity = get_entity(entity_id)
            if entity:
                props = entity.get("properties", {})
                redacted = {
                    k: ["[REDACTED]"] * len(v) if k in _PII_PROPS else v
                    for k, v in props.items()
                }
                with _LOCK:
                    con = _conn()
                    if con is not None:
                        con.execute(
                            "UPDATE entities SET properties = ?, caption = '[REDACTED]' WHERE id = ?",
                            [json.dumps(redacted), entity_id],
                        )
                        # Redact statement values
                        con.execute(
                            "UPDATE statements SET value = '[REDACTED]' "
                            "WHERE entity_id = ? AND prop IN (%s)"
                            % ",".join("?" * len(_PII_PROPS)),
                            [entity_id, *_PII_PROPS],
                        )
        except Exception as exc:
            log.error("gdpr_anonymise_failed", entity_id=entity_id, error=str(exc))
            result["error"] = str(exc)

    # 3. Record the request
    _record_request("delete", entity_id, details=json.dumps(result))

    # 4. Audit log
    try:
        from auth.audit import record_audit_event

        record_audit_event(
            action="gdpr_delete",
            endpoint=f"/api/gdpr/delete/{entity_id}",
            success=True,
            error=json.dumps(result),
        )
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Data subject search
# ---------------------------------------------------------------------------


def list_data_subjects(query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Search for Person entities matching *query* (name, email, id)."""
    results: list[dict[str, Any]] = []
    try:
        from ftm_store import run_query_ro

        pattern = f"%{query}%"
        rows = run_query_ro(
            """
            SELECT id, schema, caption, properties, datasets, first_seen, last_seen
            FROM entities
            WHERE schema = 'Person'
              AND (caption ILIKE ? OR properties::VARCHAR ILIKE ? OR id = ?)
            LIMIT ?
            """,
            [pattern, pattern, query, limit],
        )
        if rows:
            for r in rows:
                props = (
                    json.loads(r.get("properties", "{}")) if isinstance(r, dict) else {}
                )
                results.append(
                    {
                        "id": r.get("id") if isinstance(r, dict) else r[0],
                        "caption": r.get("caption") if isinstance(r, dict) else r[2],
                        "properties": props,
                        "datasets": json.loads(r.get("datasets", "[]"))
                        if isinstance(r, dict)
                        else [],
                        "first_seen": r.get("first_seen")
                        if isinstance(r, dict)
                        else r[5],
                        "last_seen": r.get("last_seen")
                        if isinstance(r, dict)
                        else r[6],
                    }
                )
    except Exception as exc:
        log.warning("gdpr_search_failed", query=query, error=str(exc))
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _record_request(request_type: str, entity_id: str, *, details: str = "") -> None:
    try:
        with _sqlite_conn() as conn:
            conn.execute(
                "INSERT INTO gdpr_requests (request_type, entity_id, status, details, created_at) "
                "VALUES (?, ?, 'completed', ?, ?)",
                (
                    request_type,
                    entity_id,
                    details,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
    except Exception:
        pass


def gdpr_request_history(entity_id: str | None = None, limit: int = 100) -> list[dict]:
    try:
        with _sqlite_conn() as conn:
            if entity_id:
                rows = conn.execute(
                    "SELECT * FROM gdpr_requests WHERE entity_id = ? ORDER BY id DESC LIMIT ?",
                    (entity_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM gdpr_requests ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


class DeleteRequest(BaseModel):
    hard_delete: bool = True


@router.get("/search")
async def api_search_subjects(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=500),
    _role: str | None = Depends(require_operator),
):
    return {"subjects": list_data_subjects(q, limit=limit)}


@router.get("/export/{entity_id}")
async def api_export(
    entity_id: str,
    _role: str | None = Depends(require_operator),
):
    bundle = export_personal_data(entity_id)
    if not bundle["entity"] and not bundle["sqlite_entity"]:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"Entity '{entity_id}' not found",
        )
    return bundle


@router.post("/delete/{entity_id}")
async def api_delete(
    entity_id: str,
    req: DeleteRequest = DeleteRequest(),
    _role: str | None = Depends(require_operator),
):
    return delete_personal_data(entity_id, hard_delete=req.hard_delete)


@router.get("/history")
async def api_history(
    entity_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    _role: str | None = Depends(require_operator),
):
    return {"requests": gdpr_request_history(entity_id, limit=limit)}


__all__ = [
    "export_personal_data",
    "delete_personal_data",
    "list_data_subjects",
    "gdpr_request_history",
    "router",
]
