"""Citable RAG memory — Ollama nomic-embed + SQLite (sqlite-vec + FTS5 hybrid RRF)."""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
import sqlite_vec

from rag_hybrid import (
    format_embed_text,
    format_prediction_watch_text,
    fts_query,
    row_to_hit,
    rrf_merge,
)
from rag_chunking import (
    chunk_record,
    get_source_profile,
    iter_chunk_ids,
    resolve_source_id,
)
from rag_rerank import rerank_enabled, rerank_hits, search_mode_label
from rag_spatial import (
    apply_spatial_postfilter,
    enrich_meta_spatial,
    operator_search_bbox,
    spatial_enabled,
    spatial_sql_clause,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_OLLAMA = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")[0].strip()
_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
_HYBRID_CANDIDATES = int(os.getenv("RAG_HYBRID_CANDIDATES", "24"))
_RERANK_POOL = int(os.getenv("RAG_RERANK_POOL", "24"))


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

            CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                tokenize='porter unicode61'
            );
        """)

        chunk_count = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        vec_count = conn.execute("SELECT COUNT(*) FROM rag_vec").fetchone()[0]
        fts_count = conn.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0]

        if vec_count == 0 and chunk_count > 0:
            print(f"[RAG] Migrating {chunk_count} existing chunks to sqlite-vec...", flush=True)
            chunks = conn.execute("SELECT id, embedding_json FROM rag_chunks").fetchall()
            for chunk in chunks:
                try:
                    emb = json.loads(chunk["embedding_json"])
                    if len(emb) == 768:
                        conn.execute(
                            "INSERT INTO rag_vec(id, embedding) VALUES (?, ?)",
                            (chunk["id"], serialize_f32(emb)),
                        )
                except Exception:
                    pass
            print("[RAG] vec migration complete.", flush=True)

        if fts_count == 0 and chunk_count > 0:
            print(f"[RAG] Backfilling FTS5 for {chunk_count} chunks...", flush=True)
            for row in conn.execute("SELECT id, text FROM rag_chunks").fetchall():
                conn.execute(
                    "INSERT INTO rag_fts(chunk_id, text) VALUES (?, ?)",
                    (row["id"], row["text"]),
                )
            print("[RAG] FTS5 backfill complete.", flush=True)

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
            (row_id, serialize_f32(embedding)),
        )
        conn.execute("DELETE FROM rag_fts WHERE chunk_id = ?", (row_id,))
        conn.execute(
            "INSERT INTO rag_fts(chunk_id, text) VALUES (?, ?)",
            (row_id, text[:12000]),
        )

        old_rows = conn.execute("SELECT id FROM rag_chunks ORDER BY id DESC LIMIT -1 OFFSET 2000").fetchall()
        if old_rows:
            old_ids = [r[0] for r in old_rows]
            marks = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM rag_chunks WHERE id IN ({marks})", old_ids)
            conn.execute(f"DELETE FROM rag_vec WHERE id IN ({marks})", old_ids)
            conn.execute(f"DELETE FROM rag_fts WHERE chunk_id IN ({marks})", old_ids)

        conn.commit()


async def index_text(source: str, source_id: str, text: str, meta: dict | None = None) -> dict:
    meta = enrich_meta_spatial(dict(meta or {}))
    embed_text_body = format_embed_text(source, text, meta)
    emb = await embed_text(embed_text_body)
    upsert_chunk(source, source_id, embed_text_body, emb, meta)
    return {"ok": True, "source": source, "source_id": source_id, "dims": len(emb)}


async def index_chunk_entries(
    entries: list[tuple[str, str, str, dict]],
) -> dict:
    """Index pre-chunked tuples ``(source, source_id, text, meta)``."""
    n = 0
    for source, source_id, text, meta in entries:
        if not (text or "").strip():
            continue
        try:
            await index_text(source, source_id, text, meta=meta)
            n += 1
        except Exception:
            pass
    return {"indexed": n}


async def index_with_profile(
    source: str,
    record: dict,
    *,
    preformatted: str | None = None,
    mapping_name: str | None = None,
    meta: dict | None = None,
) -> dict:
    """Index one logical record using adaptive chunk profile (Track R1.3)."""
    profile = get_source_profile(source, mapping_name)
    base_id = resolve_source_id(record, profile, source)
    parts = chunk_record(record, profile, preformatted=preformatted)
    if not parts:
        return {"indexed": 0, "reason": "empty"}
    meta_base = enrich_meta_spatial(dict(meta or record))
    entries = [
        (source, sid, part, meta_base)
        for sid, part in zip(iter_chunk_ids(base_id, len(parts)), parts)
    ]
    out = await index_chunk_entries(entries)
    out["source"] = source
    out["chunks"] = len(parts)
    return out


def _search_vector(
    conn: sqlite3.Connection,
    q_bin: bytes,
    limit: int,
    bbox: list[float] | None = None,
) -> list[dict]:
    spatial_clause, spatial_params = spatial_sql_clause(bbox)
    rows: list[dict] = []
    for row in conn.execute(
        f"""
        SELECT c.id, c.source, c.source_id, c.text, c.meta_json, c.created_at,
               vec_distance_cosine(v.embedding, ?) AS dist
        FROM rag_vec v
        JOIN rag_chunks c ON v.id = c.id
        WHERE 1=1
        {spatial_clause}
        ORDER BY dist ASC
        LIMIT ?
        """,
        (q_bin, *spatial_params, limit),
    ):
        dist = float(row["dist"])
        rows.append(row_to_hit(row, score=1.0 - dist, rank_source="vector"))
    return rows


def _search_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    bbox: list[float] | None = None,
) -> list[dict]:
    fts_q = fts_query(query)
    if not fts_q:
        return []
    spatial_clause, spatial_params = spatial_sql_clause(bbox)
    rows: list[dict] = []
    try:
        for row in conn.execute(
            f"""
            SELECT c.id, c.source, c.source_id, c.text, c.meta_json, c.created_at,
                   bm25(rag_fts) AS rank
            FROM rag_fts
            JOIN rag_chunks c ON c.id = rag_fts.chunk_id
            WHERE rag_fts MATCH ?
            {spatial_clause}
            ORDER BY rank
            LIMIT ?
            """,
            (fts_q, *spatial_params, limit),
        ):
            rank = float(row["rank"])
            rows.append(row_to_hit(row, score=abs(rank), rank_source="fts"))
    except sqlite3.OperationalError:
        return []
    return rows


def _finalize_hits(query: str, hits: list[dict], k: int) -> list[dict]:
    pool_k = _RERANK_POOL if rerank_enabled() else k
    pool = hits[:pool_k]
    if rerank_enabled() and pool:
        return rerank_hits(query, pool, top_k=k)
    return pool[:k]


async def search(
    query: str,
    k: int | None = None,
    bbox: list[float] | None = None,
) -> list[dict]:
    """Hybrid search: sqlite-vec cosine + FTS5 BM25 fused via reciprocal rank fusion."""
    k = k or _TOP_K
    candidate_k = max(k * 2, _HYBRID_CANDIDATES, _RERANK_POOL if rerank_enabled() else 0)
    if spatial_enabled():
        candidate_k = max(candidate_k, k * 4)
    search_bbox = bbox if bbox is not None else (operator_search_bbox() if spatial_enabled() else None)
    q_emb = await embed_text(query)
    q_bin = serialize_f32(q_emb)

    with _conn() as conn:
        vec_hits = _search_vector(conn, q_bin, candidate_k, search_bbox)
        fts_hits = _search_fts(conn, query, candidate_k, search_bbox)
        if not fts_hits:
            merged = _finalize_hits(query, vec_hits, k)
        elif not vec_hits:
            merged = _finalize_hits(query, fts_hits, k)
        else:
            pool_k = _RERANK_POOL if rerank_enabled() else k
            merged = _finalize_hits(
                query,
                rrf_merge(vec_hits, fts_hits, k=_RRF_K, top_k=pool_k),
                k,
            )
        return apply_spatial_postfilter(merged, search_bbox, min_keep=k)


async def _ingest_gdelt_articles(
    source: str,
    articles: list[dict],
    *,
    region: str | None = None,
) -> int:
    n = 0
    mapping_name = "gdelt_events"
    for i, art in enumerate(articles):
        title = art.get("title") or ""
        if not title:
            continue
        record = {
            "id": f"{source}:{art.get('url') or i}",
            "title": title,
            "snippet": title,
            "url": art.get("url") or "",
            "country": art.get("sourcecountry") or art.get("country") or "",
            "place": "",
            "themes": art.get("domain") or "",
            "lat": art.get("lat"),
            "lon": art.get("lon"),
        }
        meta = dict(art)
        if region:
            meta["region"] = region
        try:
            out = await index_with_profile(source, record, mapping_name=mapping_name, meta=meta)
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return n


async def ingest_pulse() -> dict:
    """Index latest GDELT global pulse headlines (legacy source key gdelt_pulse)."""
    import gdelt_bridge

    data = await gdelt_bridge.gdelt_pulse()
    n = await _ingest_gdelt_articles("gdelt_pulse", data.get("articles") or [])
    return {"indexed": n, "source": "gdelt_pulse"}


async def ingest_gdelt_local() -> dict:
    """Index operator-region GDELT pulse headlines."""
    import gdelt_bridge

    region = os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()
    data = await gdelt_bridge.gdelt_pulse_local_data(region, refresh=False)
    n = await _ingest_gdelt_articles(
        "gdelt_pulse_local",
        data.get("articles") or [],
        region=region,
    )
    return {"indexed": n, "source": "gdelt_pulse_local", "region": region}


async def ingest_gdelt_global() -> dict:
    """Index GDELT global pulse headlines (distinct source key)."""
    import gdelt_bridge

    data = await gdelt_bridge.gdelt_pulse()
    n = await _ingest_gdelt_articles("gdelt_pulse_global", data.get("articles") or [])
    return {"indexed": n, "source": "gdelt_pulse_global"}


async def ingest_newsdata_headlines(*, limit: int = 25) -> dict:
    """Index NewsData.io headlines when API key is configured."""
    import newsdata_bridge

    if not newsdata_bridge.api_key_configured():
        return {"indexed": 0, "source": "newsdata", "reason": "no_api_key"}
    data = await newsdata_bridge.get_newsdata(limit=max(1, min(limit, 30)), refresh=False)
    n = 0
    for i, art in enumerate(data.get("articles") or []):
        title = (art.get("title") or "").strip()
        if not title:
            continue
        sid = f"newsdata:{art.get('article_id') or art.get('link') or i}"
        desc = (art.get("description") or "").strip()
        record = {
            "article_id": sid,
            "title": title,
            "snippet": desc or title,
            "country": art.get("country"),
            "url": art.get("link") or "",
        }
        meta = dict(art)
        country = art.get("country")
        if isinstance(country, list):
            meta["country"] = ",".join(str(c) for c in country[:4])
            record["country"] = meta["country"]
        try:
            out = await index_with_profile("newsdata", record, meta=meta)
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return {"indexed": n, "source": "newsdata"}


async def ingest_news_sources() -> dict:
    """GDELT local/global + NewsData headlines (Track R0.4)."""
    parts: dict[str, Any] = {}
    for name, coro in (
        ("gdelt_global", ingest_gdelt_global()),
        ("gdelt_local", ingest_gdelt_local()),
        ("newsdata", ingest_newsdata_headlines()),
        ("gdelt_pulse", ingest_pulse()),
    ):
        try:
            parts[name] = await coro
        except Exception as e:
            parts[name] = {"indexed": 0, "error": str(e)}
    total = sum(int(v.get("indexed") or 0) for v in parts.values() if isinstance(v, dict))
    return {"indexed": total, "sources": parts}


async def ingest_prediction_watches(*, limit: int = 150) -> dict:
    """Index pending and resolved prediction-ledger watches (Track R0.3)."""
    import prediction_ledger

    items = prediction_ledger.list_watches_for_rag(limit=limit)
    n = 0
    for item in items:
        watch_id = item.get("watch_id") or ""
        issued_at = item.get("issued_at") or ""
        if not watch_id or not issued_at:
            continue
        sid = f"{watch_id}:{issued_at}"
        status = "pending" if item.get("hit") is None else ("hit" if item.get("hit") else "miss")
        meta = {
            **item,
            "status": status,
            "prefix": item.get("prefix") or "",
            "bucket": item.get("bucket") or "",
        }
        record = {**item, "watch_id": sid, "status": status}
        try:
            out = await index_with_profile(
                "prediction_watch",
                record,
                preformatted=format_prediction_watch_text(item),
                meta=meta,
            )
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return {"indexed": n, "source": "prediction_watch", "pool": len(items)}


async def ingest_hazards() -> dict:
    import cap_bridge
    data = await cap_bridge.hazards_active(limit=120)
    n = 0
    for a in data.get("alerts") or []:
        sid = f"hazard:{a.get('id', '') or n}"
        record = {
            "id": sid,
            "title": a.get("headline") or a.get("event") or "Hazard alert",
            "text": (
                f"HAZARD: {a.get('event', '')} in {a.get('area_desc', '')}. "
                f"{a.get('headline', '')} Severity: {a.get('severity', '')}"
            ),
        }
        try:
            out = await index_with_profile("hazards", record, preformatted=record["text"], meta=a)
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return {"indexed": n, "source": "hazards"}


async def ingest_volcanoes() -> dict:
    import volcano_bridge
    data = await volcano_bridge.holocene_volcanoes(active_only=True, limit=300)
    n = 0
    for v in data.get("volcanoes") or []:
        sid = f"volcano:{v.get('id', '') or v.get('name', '')}"
        record = {
            "id": sid,
            "title": v.get("name") or "Volcano",
            "text": (
                f"ACTIVE VOLCANO: {v.get('name', '')} in {v.get('country', '')}. "
                f"Type: {v.get('type', '')}. Last eruption: {v.get('last_eruption', '')}"
            ),
        }
        try:
            out = await index_with_profile("volcanoes", record, preformatted=record["text"], meta=v)
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return {"indexed": n, "source": "volcanoes"}


async def ingest_situations() -> dict:
    import situations
    data = await situations.unified_situations()
    n = 0
    for s in data.get("items") or []:
        sid = f"situation:{s.get('id', '') or n}"
        record = {
            "id": sid,
            "title": s.get("title") or "Situation",
            "text": (
                f"SITUATION [{s.get('severity', '')}]: {s.get('title', '')} "
                f"({s.get('type', '')}). Details: {s.get('details', '')}"
            ),
        }
        meta = dict(s)
        loc = s.get("location") or {}
        if loc.get("lat") is not None and loc.get("lon") is not None:
            meta["lat"] = loc["lat"]
            meta["lon"] = loc["lon"]
            record["lat"] = loc["lat"]
            record["lon"] = loc["lon"]
        try:
            out = await index_with_profile("situations", record, preformatted=record["text"], meta=meta)
            n += int(out.get("indexed") or 0)
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
        record = {
            "entity_id": ent_id,
            "title": h.get("caption") or ent_id,
            "text": (
                f"SANCTIONED {h.get('schema', 'Entity')}: {h.get('caption', '')} — "
                f"datasets: {', '.join(h.get('datasets', []) or [])}. "
                f"Topics: {', '.join(h.get('topics', []) or [])}. Score: {h.get('score', 0):.2f}"
            ),
        }
        try:
            out = await index_with_profile("sanctions", record, preformatted=record["text"], meta=h)
            n += int(out.get("indexed") or 0)
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
        record = {
            "id": it.get("id"),
            "title": f"{it.get('collection', '')} {it.get('id', '')}",
            "text": (
                f"SAT IMAGE: {it.get('collection', '')} {it.get('id', '')} "
                f"({it.get('datetime', '')}) bbox={bbox} cloud_cover={it.get('cloud_cover', '')}%"
            ),
        }
        try:
            out = await index_with_profile(
                "stac",
                record,
                preformatted=record["text"],
                meta={k: it.get(k) for k in ("id", "collection", "datetime", "bbox", "cloud_cover", "thumbnail")},
            )
            n += int(out.get("indexed") or 0)
        except Exception:
            pass
    return {"indexed": n, "source": "stac"}


async def ingest_briefing(text: str, created_at: str) -> dict:
    if not text or len(text) < 40:
        return {"indexed": 0, "reason": "empty"}
    sid = created_at or str(time.time())
    record = {"created_at": sid, "title": "Operator briefing", "text": text}
    out = await index_with_profile(
        "briefing",
        record,
        preformatted=text,
        meta={"created_at": created_at},
    )
    out["source"] = "briefing"
    out["source_id"] = sid
    return out


@router.get("/search")
async def memory_search(q: str, k: int = 6, spatial: bool | None = None):
    """Semantic search over indexed briefings and feed snippets."""
    if not q.strip():
        return {"query": q, "results": [], "error": "empty query"}
    use_spatial = spatial_enabled() if spatial is None else bool(spatial)
    search_bbox = operator_search_bbox() if use_spatial else None
    try:
        results = await search(q.strip(), k=min(k, 20), bbox=search_bbox)
        return {
            "query": q,
            "model": _EMBED_MODEL,
            "count": len(results),
            "search_mode": search_mode_label(),
            "spatial": use_spatial,
            "bbox": search_bbox,
            "results": results,
        }
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
        fts_total = conn.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS n FROM rag_chunks GROUP BY source ORDER BY n DESC"
        ).fetchall()
    return {
        "chunks": total,
        "vec_chunks": vec_total,
        "fts_chunks": fts_total,
        "by_source": [{"source": r[0], "count": r[1]} for r in by_source],
        "embed_model": _EMBED_MODEL,
        "vector_engine": "sqlite-vec",
        "search_mode": search_mode_label(),
        "rerank_enabled": rerank_enabled(),
        "spatial_enabled": spatial_enabled(),
        "adaptive_chunking": True,
    }
