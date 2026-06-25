"""Briefing agentic loop — coverage → retrieve → corroboration (Track R1.4).

Lightweight state machine (no LangGraph). Enriches the digest before the single
Ollama protocol call. Max three phases; each phase runs at most once.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from typing import Any

from briefing_quality import build_digest_line_meta, corroboration_summary

_MAX_ROUNDS = 3
_MIN_BUCKET_LINES = 2
_RAG_LINES_PER_BUCKET = 2
_RAG_TOP_K = 4

_EMPTY_MARKERS = (
    "no local signals",
    "no regional signals",
    "no global",
    "keine lokalen signale",
    "keine regionalen signale",
    "keine globalen",
)


class AgenticPhase(str, Enum):
    COVERAGE = "coverage"
    RETRIEVE = "retrieve"
    CORROBORATION = "corroboration"
    DONE = "done"


def agentic_loop_enabled() -> bool:
    return os.getenv("BRIEFING_AGENTIC_LOOP", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _is_placeholder_line(line: str) -> bool:
    low = str(line or "").lower().lstrip("- ").strip()
    if not low:
        return True
    return any(marker in low for marker in _EMPTY_MARKERS)


def _count_real_lines(lines: list[str] | None) -> int:
    return sum(1 for ln in lines or [] if not _is_placeholder_line(ln))


def assess_coverage(digest: dict[str, Any]) -> dict[str, Any]:
    """Phase 1 — bucket line counts and gap list."""
    buckets = ("local", "regional", "global")
    counts = {b: _count_real_lines(digest.get(b)) for b in buckets}
    gaps = [b for b in buckets if counts[b] < _MIN_BUCKET_LINES]
    return {
        "phase": AgenticPhase.COVERAGE.value,
        "counts": counts,
        "gaps": gaps,
        "needs_retrieve": bool(gaps),
    }


def _bucket_query(bucket: str, digest: dict[str, Any]) -> str:
    region = digest.get("region_label") or digest.get("region") or "Thailand"
    if bucket == "local":
        return f"{region} security hazard flood air quality local news last 24 hours"
    if bucket == "regional":
        return (
            f"ASEAN Southeast Asia {region} border conflict humanitarian regional news"
        )
    return "global security conflict disaster cyber infrastructure news"


def _hit_to_line(hit: dict[str, Any], *, corroborated: bool = False) -> str:
    raw = str(hit.get("_body") or hit.get("text") or "")
    raw = re.sub(r"^RAG (recall|corroborated) \([^)]+\):\s*", "", raw, flags=re.I)
    body = re.sub(r"\s+", " ", raw).strip()[:420]
    tag = "corroborated" if corroborated else "recall"
    source = hit.get("source") or "memory"
    return f"RAG {tag} ({source}): {body}"


def _text_overlap(a: str, b: str) -> float:
    words_a = {w for w in re.findall(r"\w{4,}", a.lower())}
    words_b = {w for w in re.findall(r"\w{4,}", b.lower())}
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


async def _retrieve_for_gaps(
    digest: dict[str, Any],
    gaps: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Phase 2 — hybrid RAG search per weak bucket."""
    import rag_memory
    from rag_spatial import spatial_enabled

    recalls: list[dict[str, Any]] = []
    per_bucket: dict[str, int] = {}
    errors: list[str] = []

    for bucket in gaps:
        query = _bucket_query(bucket, digest)
        use_spatial = spatial_enabled() and bucket == "local"
        try:
            if use_spatial:
                from rag_spatial import operator_search_bbox

                hits = await rag_memory.search(
                    query,
                    k=_RAG_TOP_K,
                    bbox=operator_search_bbox(),
                )
            else:
                hits = await rag_memory.search(query, k=_RAG_TOP_K)
        except Exception as exc:
            errors.append(f"{bucket}: {exc}")
            continue

        added = 0
        seen: set[str] = set()
        for hit in hits or []:
            line = _hit_to_line({**hit, "_body": hit.get("text")})
            key = line[:80].lower()
            if key in seen:
                continue
            seen.add(key)
            recalls.append(
                {
                    "bucket": bucket,
                    "text": line,
                    "score": hit.get("score"),
                    "source": hit.get("source"),
                    "rank_source": hit.get("rank_source"),
                    "corroborated": False,
                }
            )
            added += 1
            if added >= _RAG_LINES_PER_BUCKET:
                break
        per_bucket[bucket] = added

    return recalls, {
        "phase": AgenticPhase.RETRIEVE.value,
        "queries": {b: _bucket_query(b, digest) for b in gaps},
        "per_bucket": per_bucket,
        "retrieved": len(recalls),
        "errors": errors[:4],
    }


def _merge_recalls_into_digest(
    digest: dict[str, Any],
    recalls: list[dict[str, Any]],
) -> None:
    for row in recalls:
        bucket = row.get("bucket") or "global"
        line = f"- {row.get('text', '')}"
        digest.setdefault(bucket, [])
        if _is_placeholder_line(
            (digest.get(bucket) or [""])[0] if digest.get(bucket) else ""
        ):
            digest[bucket] = []
        if line not in digest[bucket]:
            digest[bucket].append(line)
    digest["rag_recall"] = recalls


def apply_corroboration_pass(digest: dict[str, Any]) -> dict[str, Any]:
    """Phase 3 — score digest lines; mark RAG recalls that overlap weak rows."""
    all_items: list[dict[str, Any]] = []
    for bucket in ("local", "regional", "global"):
        for line in digest.get(bucket) or []:
            if _is_placeholder_line(line):
                continue
            text = str(line).lstrip("- ").strip()
            all_items.append(
                {"text": text, "bucket": bucket, "severity": "low", "sources": []}
            )

    picked_by_bucket: dict[str, list[dict[str, Any]]] = {
        b: [] for b in ("local", "regional", "global")
    }
    for item in all_items:
        picked_by_bucket.setdefault(item["bucket"], []).append(item)

    meta = build_digest_line_meta(all_items, picked_by_bucket)
    summary = corroboration_summary(meta)

    weak_texts = [
        row.get("text", "")
        for row in meta
        if float(row.get("corroboration") or 0) < 0.5 and row.get("bucket") == "local"
    ]

    recalls = list(digest.get("rag_recall") or [])
    corroborated_n = 0
    for row in recalls:
        body = str(row.get("text") or "")
        for weak in weak_texts:
            if _text_overlap(body, weak) >= 0.2:
                old_line = f"- {body}"
                row["corroborated"] = True
                row["text"] = _hit_to_line(row, corroborated=True)
                new_line = f"- {row['text']}"
                bucket = row.get("bucket") or "local"
                digest[bucket] = [
                    new_line if ln == old_line else ln
                    for ln in (digest.get(bucket) or [])
                ]
                corroborated_n += 1
                break

    if recalls:
        digest["rag_recall"] = recalls

    digest["digest_line_meta"] = meta

    return {
        "phase": AgenticPhase.CORROBORATION.value,
        "corroboration": summary,
        "weak_local_lines": len(weak_texts),
        "rag_corroborated": corroborated_n,
        "digest_lines_scored": len(meta),
    }


async def run_briefing_agentic_loop(
    digest: dict[str, Any],
    *,
    snap: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run up to three agentic phases; return enriched digest + trace metadata."""
    _ = snap  # reserved for future feed-aware coverage
    if not agentic_loop_enabled():
        return digest, {"enabled": False, "rounds": 0, "phases": []}

    trace: dict[str, Any] = {
        "enabled": True,
        "rounds": 0,
        "phases": [],
        "max_rounds": _MAX_ROUNDS,
    }
    recalls: list[dict[str, Any]] = []

    coverage = assess_coverage(digest)
    trace["phases"].append(coverage)
    trace["rounds"] += 1

    gaps = list(coverage.get("gaps") or [])
    if gaps and trace["rounds"] < _MAX_ROUNDS:
        recalls, retrieve_meta = await _retrieve_for_gaps(digest, gaps)
        trace["phases"].append(retrieve_meta)
        trace["rounds"] += 1
        if recalls:
            _merge_recalls_into_digest(digest, recalls)

    if trace["rounds"] < _MAX_ROUNDS:
        corro_meta = apply_corroboration_pass(digest)
        trace["phases"].append(corro_meta)
        trace["rounds"] += 1

    trace["final_counts"] = {
        b: _count_real_lines(digest.get(b)) for b in ("local", "regional", "global")
    }
    trace["status"] = AgenticPhase.DONE.value
    digest["agentic"] = trace
    return digest, trace


def format_rag_recall_block(
    recalls: list[dict[str, Any]] | None, lang: str | None = None
) -> str:
    """Plain-text block for the LLM prompt."""
    rows = recalls or []
    if not rows:
        return ""
    lang = (lang or "en").strip().lower()
    if lang.startswith("de"):
        header = "RAG-NACHSCHLAG (nur ergänzend; nicht erfinden):"
        empty = "- Kein RAG-Nachschlag."
    else:
        header = "SUPPLEMENTAL RAG RECALL (supporting context only — do not invent):"
        empty = "- No RAG recall."
    lines = [header]
    for row in rows:
        tag = "corroborated" if row.get("corroborated") else "recall"
        lines.append(f"- [{tag}] {row.get('text', '').lstrip('- ')}")
    return "\n".join(lines) if len(lines) > 1 else empty
