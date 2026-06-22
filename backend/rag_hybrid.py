"""Pure helpers for hybrid RAG search (FTS5 query + RRF merge)."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


_SOURCE_PREFIX: dict[str, str] = {
    "briefing": "SOURCE: operator security briefing",
    "gdelt_pulse": "SOURCE: GDELT news pulse",
    "gdelt_pulse_local": "SOURCE: GDELT local news pulse",
    "gdelt_pulse_global": "SOURCE: GDELT global news pulse",
    "newsdata": "SOURCE: NewsData.io headline",
    "prediction_watch": "SOURCE: briefing prediction watch item",
    "hazards": "SOURCE: active hazard alert",
    "situations": "SOURCE: unified situation board",
    "volcanoes": "SOURCE: active volcano registry",
    "sanctions": "SOURCE: sanctions screening match",
    "stac": "SOURCE: satellite imagery scene",
}


def format_embed_text(source: str, text: str, meta: dict | None = None) -> str:
    """Contextual prefix for embedding + FTS (Track R0.2)."""
    meta = meta or {}
    prefix = _SOURCE_PREFIX.get(source, f"SOURCE: {source.replace('_', ' ')}")
    extras: list[str] = []
    for key in ("region", "country", "bucket", "status", "prefix"):
        val = meta.get(key)
        if val:
            extras.append(f"{key}: {val}")
    if extras:
        prefix = f"{prefix} | {' | '.join(extras)}"
    body = (text or "").strip()
    if not body:
        return prefix[:12000]
    return f"{prefix}\n{body}"[:12000]


def format_prediction_watch_text(item: dict[str, Any]) -> str:
    """Human-readable watch item body for RAG indexing."""
    if item.get("hit") is True:
        status = "hit"
    elif item.get("hit") is False:
        status = "miss"
    else:
        status = "pending"
    lines = [
        f"Watch claim: {item.get('claim') or ''}",
        f"Signal prefix: {item.get('prefix') or ''} | Bucket: {item.get('bucket') or ''}",
        f"Horizon: {item.get('horizon_h', 48)}h | Status: {status}",
        f"Issued: {item.get('issued_at') or ''} | Due: {item.get('due_at') or ''}",
    ]
    if item.get("outcome"):
        lines.append(f"Outcome: {item['outcome']}")
    sources = item.get("sources") or []
    if sources:
        lines.append(f"Signal sources: {', '.join(str(s) for s in sources)}")
    if item.get("cell_id"):
        lines.append(f"Grid cell: {item['cell_id']}")
    return "\n".join(lines)


def fts_query(raw: str) -> str | None:
    tokens = re.findall(r"\w+", raw.strip(), flags=re.UNICODE)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in tokens[:12])


def row_to_hit(row: sqlite3.Row, *, score: float, rank_source: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source": row["source"],
        "source_id": row["source_id"],
        "text": row["text"][:600],
        "score": round(score, 4),
        "meta": json.loads(row["meta_json"] or "{}"),
        "created_at": row["created_at"],
        "rank_source": rank_source,
    }


def rrf_merge(
    vec_hits: list[dict],
    fts_hits: list[dict],
    *,
    k: int,
    top_k: int,
) -> list[dict]:
    scores: dict[int, float] = {}
    hits: dict[int, dict] = {}
    for rank, hit in enumerate(vec_hits):
        cid = int(hit["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        hits[cid] = hit
    for rank, hit in enumerate(fts_hits):
        cid = int(hit["id"])
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        hits.setdefault(cid, hit)
    merged = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    out: list[dict] = []
    for cid, rrf_score in merged:
        row = dict(hits[cid])
        row["score"] = round(rrf_score, 4)
        row["rank_source"] = "hybrid_rrf"
        out.append(row)
    return out
