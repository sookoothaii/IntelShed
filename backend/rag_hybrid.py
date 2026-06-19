"""Pure helpers for hybrid RAG search (FTS5 query + RRF merge)."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


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
