"""V4-08 FTS5 Global Search — unified search across entities, RAG memory, briefings.

Creates a SQLite FTS5 virtual table that indexes content from multiple sources:
  - FtM entities (caption + schema + id) from DuckDB
  - RAG chunks (text) from SQLite rag_chunks
  - Entity store (label + type) from SQLite entities
  - Briefings (text) from SQLite briefings

The FTS5 index is rebuilt on demand or incrementally updated. Search results
are merged and ranked by BM25 score with source-type weighting.

Environment variables:
  WORLDBASE_GLOBAL_SEARCH=1  — enable global search endpoint
  WORLDBASE_GLOBAL_SEARCH_LIMIT — max results per query (default: 20)
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from auth.security import verify_api_key
from rag_hybrid import fts_query
from structured_log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_DEFAULT_LIMIT = int(os.getenv("WORLDBASE_GLOBAL_SEARCH_LIMIT", "20"))

# Source weights — boost entities and briefings over RAG chunks
_SOURCE_WEIGHTS: dict[str, float] = {
    "entity": 1.3,
    "statement": 1.1,
    "briefing": 1.2,
    "rag_chunk": 1.0,
    "entity_store": 1.1,
}


def _enabled() -> bool:
    return os.getenv("WORLDBASE_GLOBAL_SEARCH", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema — FTS5 virtual table for global search
# ---------------------------------------------------------------------------


def init_global_search_db() -> None:
    """Create the global_search FTS5 table if it doesn't exist."""
    conn = _conn()
    try:
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS global_search_fts USING fts5(
                ref_id UNINDEXED,
                source_type UNINDEXED,
                title,
                body,
                meta_json UNINDEXED,
                tokenize='porter unicode61'
            );
        """)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Indexing — populate FTS5 from various sources
# ---------------------------------------------------------------------------


def _index_entities_sqlite(conn: sqlite3.Connection) -> int:
    """Index entities from the SQLite entity_store."""
    try:
        rows = conn.execute("SELECT id, type, label FROM entities").fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for row in rows:
        ref_id = row["id"]
        title = row["label"] or ""
        body = f"{row['type']} {row['label'] or ''}"
        conn.execute(
            "INSERT INTO global_search_fts (ref_id, source_type, title, body, meta_json) VALUES (?, ?, ?, ?, ?)",
            (ref_id, "entity_store", title, body, json.dumps({"type": row["type"]})),
        )
        n += 1
    return n


def _index_rag_chunks(conn: sqlite3.Connection) -> int:
    """Index RAG chunks from SQLite."""
    try:
        rows = conn.execute(
            "SELECT id, source, source_id, text, meta_json FROM rag_chunks"
        ).fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for row in rows:
        ref_id = str(row["id"])
        title = (row["text"] or "")[:120]
        body = row["text"] or ""
        meta = {
            "source": row["source"],
            "source_id": row["source_id"],
            "original_meta": row["meta_json"],
        }
        conn.execute(
            "INSERT INTO global_search_fts (ref_id, source_type, title, body, meta_json) VALUES (?, ?, ?, ?, ?)",
            (ref_id, "rag_chunk", title, body, json.dumps(meta)),
        )
        n += 1
    return n


def _index_briefings(conn: sqlite3.Connection) -> int:
    """Index briefings from SQLite."""
    try:
        rows = conn.execute("SELECT id, created_at, text FROM briefings").fetchall()
    except sqlite3.OperationalError:
        return 0
    n = 0
    for row in rows:
        ref_id = str(row["id"])
        title = f"Briefing {row['created_at'] or ''}"
        body = row["text"] or ""
        conn.execute(
            "INSERT INTO global_search_fts (ref_id, source_type, title, body, meta_json) VALUES (?, ?, ?, ?, ?)",
            (
                ref_id,
                "briefing",
                title,
                body,
                json.dumps({"created_at": row["created_at"]}),
            ),
        )
        n += 1
    return n


def _index_ftm_entities(conn: sqlite3.Connection) -> int:
    """Index FtM entities from DuckDB into the SQLite FTS5 table."""
    try:
        import ftm_query

        entities = ftm_query.list_entities(limit=5000)
    except Exception as e:
        log.warning("global_search_ftm_failed", error=str(e))
        return 0
    n = 0
    for ent in entities:
        ref_id = ent["id"]
        title = ent.get("caption") or ent.get("schema", "")
        props = ent.get("properties", {})
        body_parts = [ent.get("schema", ""), ent.get("caption", "")]
        for key in (
            "name",
            "email",
            "phone",
            "address",
            "country",
            "notes",
            "wikipediaUrl",
        ):
            val = props.get(key)
            if val:
                if isinstance(val, list):
                    body_parts.extend(str(v) for v in val)
                else:
                    body_parts.append(str(val))
        body = " ".join(body_parts)
        meta = {
            "schema": ent.get("schema"),
            "datasets": ent.get("datasets", []),
        }
        conn.execute(
            "INSERT INTO global_search_fts (ref_id, source_type, title, body, meta_json) VALUES (?, ?, ?, ?, ?)",
            (ref_id, "entity", title, body, json.dumps(meta)),
        )
        n += 1
    return n


def _index_ftm_statements(conn: sqlite3.Connection) -> int:
    """Index FtM statements from DuckDB into the SQLite FTS5 table."""
    try:
        import duckdb
        from ftm_connection import _DB_PATH as DUCKDB_PATH

        dconn = duckdb.connect(DUCKDB_PATH, read_only=True)
        rows = dconn.execute(
            "SELECT entity_id, prop, value, dataset FROM statements LIMIT 10000"
        ).fetchall()
        dconn.close()
    except Exception as e:
        log.warning("global_search_statements_failed", error=str(e))
        return 0
    n = 0
    for row in rows:
        entity_id, prop, value, dataset = row
        ref_id = f"stmt:{entity_id}:{prop}"
        title = f"{prop}: {value[:80]}" if value else prop
        body = f"{prop} {value}"
        meta = {"entity_id": entity_id, "dataset": dataset}
        conn.execute(
            "INSERT INTO global_search_fts (ref_id, source_type, title, body, meta_json) VALUES (?, ?, ?, ?, ?)",
            (ref_id, "statement", title, body, json.dumps(meta)),
        )
        n += 1
    return n


def rebuild_index() -> dict[str, Any]:
    """Rebuild the global search FTS5 index from all sources.

    Returns summary stats.
    """
    t0 = time.perf_counter()
    init_global_search_db()
    conn = _conn()
    try:
        # Clear existing index
        conn.execute("DELETE FROM global_search_fts")
        conn.commit()

        counts: dict[str, int] = {}
        counts["entity_store"] = _index_entities_sqlite(conn)
        counts["rag_chunk"] = _index_rag_chunks(conn)
        counts["briefing"] = _index_briefings(conn)
        counts["entity"] = _index_ftm_entities(conn)
        counts["statement"] = _index_ftm_statements(conn)
        conn.commit()
    finally:
        conn.close()

    elapsed = round(time.perf_counter() - t0, 2)
    total = sum(counts.values())
    log.info("global_search_rebuilt", total=total, counts=counts, elapsed_s=elapsed)
    return {
        "ok": True,
        "total_indexed": total,
        "by_source": counts,
        "elapsed_s": elapsed,
    }


# ---------------------------------------------------------------------------
# Search — query FTS5 with BM25 ranking
# ---------------------------------------------------------------------------


def _search_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Execute FTS5 MATCH query and return ranked results."""
    fts_q = fts_query(query)
    if not fts_q:
        return []

    where_clause = "WHERE global_search_fts MATCH ?"
    params: list[Any] = [fts_q]

    if source_type:
        where_clause += " AND source_type = ?"
        params.append(source_type)

    rows: list[dict[str, Any]] = []
    try:
        for row in conn.execute(
            f"""
            SELECT ref_id, source_type, title, body, meta_json,
                   bm25(global_search_fts) AS rank
            FROM global_search_fts
            {where_clause}
            ORDER BY rank
            LIMIT ?
            """,
            (*params, limit),
        ):
            rank = float(row["rank"])
            weight = _SOURCE_WEIGHTS.get(row["source_type"], 1.0)
            weighted_score = abs(rank) * weight
            rows.append(
                {
                    "ref_id": row["ref_id"],
                    "source_type": row["source_type"],
                    "title": row["title"][:200] if row["title"] else "",
                    "snippet": (row["body"] or "")[:300],
                    "score": round(weighted_score, 4),
                    "meta": json.loads(row["meta_json"] or "{}"),
                }
            )
    except sqlite3.OperationalError:
        return []
    return rows


def global_search(
    query: str,
    *,
    limit: int | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    """Search across all indexed sources.

    Args:
        query: Natural language search query
        limit: Max results (default: 20)
        source_type: Filter by source type (entity, statement, rag_chunk, briefing, entity_store)

    Returns:
        List of search results sorted by weighted BM25 score.
    """
    if not query.strip():
        return []
    limit = limit or _DEFAULT_LIMIT
    init_global_search_db()
    conn = _conn()
    try:
        return _search_fts(conn, query, limit, source_type)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


class SearchResponse(BaseModel):
    query: str
    results: list[dict[str, Any]]
    total: int
    elapsed_ms: float


@router.get("/global")
async def search_global(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    source_type: str | None = Query(
        None, description="Filter: entity, statement, rag_chunk, briefing, entity_store"
    ),
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Global FTS5 search across entities, RAG memory, briefings, and statements."""
    if not _enabled():
        return {
            "error": "Global search disabled. Set WORLDBASE_GLOBAL_SEARCH=1 to enable."
        }
    t0 = time.perf_counter()
    results = global_search(q, limit=limit, source_type=source_type)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "query": q,
        "results": results,
        "total": len(results),
        "elapsed_ms": elapsed_ms,
    }


@router.post("/rebuild")
async def rebuild_search_index(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Rebuild the global search FTS5 index from all sources."""
    if not _enabled():
        return {
            "error": "Global search disabled. Set WORLDBASE_GLOBAL_SEARCH=1 to enable."
        }
    return rebuild_index()


@router.get("/status")
async def search_status(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Return global search index status."""
    if not _enabled():
        return {"enabled": False, "indexed_count": 0}
    init_global_search_db()
    try:
        conn = _conn()
        try:
            count = conn.execute("SELECT COUNT(*) FROM global_search_fts").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.OperationalError:
        count = 0
    return {
        "enabled": True,
        "indexed_count": count,
        "db_path": _DB_PATH,
    }
