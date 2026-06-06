"""Citable RAG memory — Ollama nomic-embed + SQLite (optional sqlite-vec)."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/memory", tags=["memory"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_OLLAMA = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")[0].strip()
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_TOP_K = int(os.getenv("RAG_TOP_K", "6"))


def _conn():
    conn = sqlite3.connect(_DB_PATH)
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
        """)
        conn.commit()


async def embed_text(text: str) -> list[float]:
    host = _OLLAMA
    url = f"http://{host}/api/embeddings"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json={"model": _EMBED_MODEL, "prompt": text[:8000]})
        r.raise_for_status()
        data = r.json()
        emb = data.get("embedding")
        if not emb:
            raise RuntimeError("Ollama returned no embedding — run: ollama pull nomic-embed-text")
        return [float(x) for x in emb]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return dot / (na * nb)


def upsert_chunk(source: str, source_id: str, text: str, embedding: list[float], meta: dict | None = None):
    now = datetime.now(timezone.utc).isoformat()
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
        conn.commit()


async def index_text(source: str, source_id: str, text: str, meta: dict | None = None) -> dict:
    emb = await embed_text(text)
    upsert_chunk(source, source_id, text, emb, meta)
    return {"ok": True, "source": source, "source_id": source_id, "dims": len(emb)}


async def search(query: str, k: int | None = None) -> list[dict]:
    k = k or _TOP_K
    q_emb = await embed_text(query)
    rows = []
    with _conn() as conn:
        for row in conn.execute(
            "SELECT id, source, source_id, text, embedding_json, meta_json, created_at FROM rag_chunks ORDER BY id DESC LIMIT 500"
        ):
            emb = json.loads(row["embedding_json"])
            score = _cosine(q_emb, emb)
            rows.append({
                "id": row["id"],
                "source": row["source"],
                "source_id": row["source_id"],
                "text": row["text"][:600],
                "score": round(score, 4),
                "meta": json.loads(row["meta_json"] or "{}"),
                "created_at": row["created_at"],
            })
    rows.sort(key=lambda x: -x["score"])
    return rows[:k]


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
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS n FROM rag_chunks GROUP BY source ORDER BY n DESC"
        ).fetchall()
    return {
        "chunks": total,
        "by_source": [{"source": r[0], "count": r[1]} for r in by_source],
        "embed_model": _EMBED_MODEL,
    }
