"""Citable RAG memory — Ollama nomic-embed + SQLite (optional sqlite-vec)."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
import sqlite_vec

router = APIRouter(prefix="/api/memory", tags=["memory"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_OLLAMA = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")[0].strip()
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_TOP_K = int(os.getenv("RAG_TOP_K", "6"))


def serialize_f32(vector: list[float]) -> bytes:
    """Serializes a list of floats into a compact format sqlite-vec can understand."""
    return struct.pack("%sf" % len(vector), *vector)


def _conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT,
                text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(source, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_rag_source ON rag_chunks(source);
            
            CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(
                id INTEGER PRIMARY KEY,
                embedding float[768]
            );
        """)
        
        # Migration: Backfill rag_vec if empty but rag_chunks has data
        vec_count = conn.execute("SELECT COUNT(*) FROM rag_vec").fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        
        if vec_count == 0 and chunk_count > 0:
            print(f"[RAG] Migrating {chunk_count} existing chunks to sqlite-vec...", flush=True)
            chunks = conn.execute("SELECT id, embedding_json FROM rag_chunks").fetchall()
            for chunk in chunks:
                try:
                    emb = json.loads(chunk["embedding_json"])
                    if len(emb) == 768:
                        conn.execute("INSERT INTO rag_vec(id, embedding) VALUES (?, ?)", (chunk["id"], serialize_f32(emb)))
                except Exception:
                    pass
            print("[RAG] Migration complete.", flush=True)
            
        conn.commit()


async def embed_text(text: str) -> list[float]:
    host = _OLLAMA
    url = f"http://{host}/api/embeddings"
    async with httpx.AsyncClient(timeout=60.0) as client:
        from ollama_config import keep_alive
        r = await client.post(
            url,
            json={"model": _EMBED_MODEL, "prompt": text[:8000], "keep_alive": keep_alive()},
        )
        r.raise_for_status()
        data = r.json()
        emb = data.get("embedding")
        if not emb:
            raise RuntimeError("Ollama returned no embedding — run: ollama pull nomic-embed-text")
        return [float(x) for x in emb]


def upsert_chunk(source: str, source_id: str, text: str, embedding: list[float], meta: dict | None = None):
    now = datetime.now(timezone.utc).isoformat()
    if len(embedding) != 768:
        raise ValueError("sqlite-vec currently expects exactly 768 dimensions for nomic-embed-text")
        
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO rag_chunks (source, source_id, text, embedding_json, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, source_id) DO UPDATE SET
                text=excluded.text,
                embedding_json=excluded.embedding_json,
                meta_json=excluded.meta_json,
                created_at=excluded.created_at
            """,
            (
                source,
                source_id,
                text[:12000],
                json.dumps(embedding),
                json.dumps(meta or {}),
                now,
            ),
        )
        row_id = conn.execute("SELECT id FROM rag_chunks WHERE source=? AND source_id=?", (source, source_id)).fetchone()[0]
        
        # Sync with high-performance vector index
        conn.execute(
            "INSERT OR REPLACE INTO rag_vec(id, embedding) VALUES (?, ?)",
            (row_id, serialize_f32(embedding))
        )

        # Professional Ring buffer cap — explicit sync between both tables
        old_rows = conn.execute("SELECT id FROM rag_chunks ORDER BY id DESC LIMIT -1 OFFSET 2000").fetchall()
        if old_rows:
            old_ids = [r[0] for r in old_rows]
            marks = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM rag_chunks WHERE id IN ({marks})", old_ids)
            conn.execute(f"DELETE FROM rag_vec WHERE id IN ({marks})", old_ids)
            
        conn.commit()


async def index_text(source: str, source_id: str, text: str, meta: dict | None = None) -> dict:
    emb = await embed_text(text)
    upsert_chunk(source, source_id, text, emb, meta)
    return {"ok": True, "source": source, "source_id": source_id, "dims": len(emb)}


async def search(query: str, k: int | None = None) -> list[dict]:
    k = k or _TOP_K
    q_emb = await embed_text(query)
    q_bin = serialize_f32(q_emb)
    
    rows = []
    with _conn() as conn:
        for row in conn.execute(
            """
            SELECT c.id, c.source, c.source_id, c.text, c.meta_json, c.created_at, vec_distance_cosine(v.embedding, ?) as dist 
            FROM rag_vec v
            JOIN rag_chunks c ON v.id = c.id
            ORDER BY dist ASC
            LIMIT ?
            """,
            (q_bin, k)
        ):
            dist = float(row["dist"])
            rows.append({
                "id": row["id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "text": row["text"][:600],
                "score": round(1.0 - dist, 4),
                "meta": json.loads(row["meta_json"] or "{}"),
                "created_at": row["created_at"],
            })
    return rows


async def ingest_pulse() -> dict:
    """Index latest GDELT pulse headlines into memory."""
    import gdelt_bridge

    data = await gdelt_bridge.gdelt_pulse()
    n = 0
    for i, art in enumerate(data.get("articles") or []):
        title = art.get("title") or ""
        if not title:
            continue
        sid = f"pulse:{art.get('url') or i}"
        text = f"{title}\n{art.get('domain', '')} {art.get('sourcecountry', '')}"
        try:
            await index_text("gdelt_pulse", sid, text, meta=art)
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "gdelt_pulse"}


async def ingest_hazards() -> dict:
    import cap_bridge
    data = await cap_bridge.hazards_active(limit=120)
    n = 0
    for a in data.get("alerts") or []:
        sid = f"hazard:{a.get('id', '') or n}"
        text = f"HAZARD: {a.get('event', '')} in {a.get('area_desc', '')}. {a.get('headline', '')} Severity: {a.get('severity', '')}"
        try:
            await index_text("hazards", sid, text, meta=a)
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "hazards"}


async def ingest_volcanoes() -> dict:
    import volcano_bridge
    data = await volcano_bridge.holocene_volcanoes(active_only=True, limit=300)
    n = 0
    for v in data.get("volcanoes") or []:
        sid = f"volcano:{v.get('id', '') or v.get('name', '')}"
        text = f"ACTIVE VOLCANO: {v.get('name', '')} in {v.get('country', '')}. Type: {v.get('type', '')}. Last eruption: {v.get('last_eruption', '')}"
        try:
            await index_text("volcanoes", sid, text, meta=v)
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "volcanoes"}


async def ingest_situations() -> dict:
    import situations
    data = await situations.unified_situations()
    n = 0
    for s in data.get("items") or []:
        sid = f"situation:{s.get('id', '') or n}"
        text = f"SITUATION [{s.get('severity', '')}]: {s.get('title', '')} ({s.get('type', '')}). Details: {s.get('details', '')}"
        try:
            await index_text("situations", sid, text, meta=s)
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "situations"}


async def ingest_sanctions_hits(hits: list[dict]) -> dict:
    """Index sanctions matches (vessels, individuals, entities) for citable recall."""
    n = 0
    for h in hits or []:
        ent_id = h.get("entity_id") or h.get("id") or h.get("caption") or ""
        if not ent_id:
            continue
        sid = f"sanctions:{ent_id}"
        text = (
            f"SANCTIONED {h.get('schema', 'Entity')}: {h.get('caption', '')} — "
            f"datasets: {', '.join(h.get('datasets', []) or [])}. "
            f"Topics: {', '.join(h.get('topics', []) or [])}. Score: {h.get('score', 0):.2f}"
        )
        try:
            await index_text("sanctions", sid, text, meta=h)
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "sanctions"}


async def ingest_stac_items(items: list[dict]) -> dict:
    """Index recent STAC/Sentinel-2 scenes so the LLM can cite imagery coverage."""
    n = 0
    for it in items or []:
        sid = f"stac:{it.get('id', '')}"
        if not it.get("id"):
            continue
        bbox = it.get("bbox") or []
        text = (
            f"SAT IMAGE: {it.get('collection', '')} {it.get('id', '')} "
            f"({it.get('datetime', '')}) bbox={bbox} cloud_cover={it.get('cloud_cover', '')}%"
        )
        try:
            await index_text("stac", sid, text, meta={k: it.get(k) for k in ("id", "collection", "datetime", "bbox", "cloud_cover", "thumbnail")})
            n += 1
        except Exception:
            pass
    return {"indexed": n, "source": "stac"}


async def ingest_briefing(text: str, created_at: str) -> dict:
    if not text or len(text) < 40:
        return {"indexed": 0, "reason": "empty"}
    sid = created_at or str(time.time())
    await index_text("briefing", sid, text[:8000], meta={"created_at": created_at})
    return {"indexed": 1, "source": "briefing", "source_id": sid}


@router.get("/search")
async def memory_search(q: str, k: int = 6):
    """Semantic search over indexed briefings and feed snippets."""
    if not q.strip():
        return {"query": q, "results": [], "error": "empty query"}
    try:
        results = await search(q.strip(), k=min(k, 20))
        return {"query": q, "model": _EMBED_MODEL, "count": len(results), "results": results}
    except Exception as e:
        return {"query": q, "results": [], "error": str(e), "hint": "ollama pull nomic-embed-text"}


@router.post("/index/pulse")
async def index_gdelt_pulse():
    try:
        return await ingest_pulse()
    except Exception as e:
        return {"indexed": 0, "error": str(e)}


@router.get("/stats")
async def memory_stats():
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        # Querying vec table explicitly to ensure it matches
        vec_total = conn.execute("SELECT COUNT(*) FROM rag_vec").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS n FROM rag_chunks GROUP BY source ORDER BY n DESC"
        ).fetchall()
    return {
        "chunks": total,
        "vec_chunks": vec_total,
        "by_source": [{"source": r[0], "count": r[1]} for r in by_source],
        "embed_model": _EMBED_MODEL,
        "vector_engine": "sqlite-vec"
    }
