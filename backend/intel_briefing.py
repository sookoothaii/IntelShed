"""FtM graph → operator 24h briefing bridge.

Pulls ranked, geolocated entities from the canonical DuckDB store and formats
them for LOCAL / REGION / GLOBAL digest buckets. Keeps aircraft noise out by
default and surfaces sameAs resolution links when present.
"""

from __future__ import annotations

import os
from typing import Any

import ftm_store
from operator_briefing import (
    OPERATOR_REGION,
    _ASEAN_BBOX,
    _region_bbox,
    classify_item,
)

# Lower rank = higher briefing priority.
_DATASET_PRIORITY: dict[str, int] = {
    "gdacs": 0,
    "gdelt-geo": 1,
    "gdelt-pulse": 2,
    "eonet": 3,
    "intel-ingest": 4,
    "osint": 5,
    "entity-resolution": 6,
    "correlations": 7,
    "ais": 8,
    "anomalies": 9,
}

_SCHEMA_PRIORITY: dict[str, int] = {
    "Event": 0,
    "Vessel": 1,
    "Person": 2,
    "Organization": 3,
    "Company": 4,
    "Address": 5,
    "Document": 6,
}

_DEFAULT_EXCLUDE = ("Airplane", "Thing")


def _truthy(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def briefing_intel_enabled() -> bool:
    return _truthy("WORLDBASE_BRIEFING_INTEL", "1")


def _exclude_schemas() -> set[str]:
    raw = os.getenv(
        "WORLDBASE_BRIEFING_INTEL_EXCLUDE_SCHEMAS", ",".join(_DEFAULT_EXCLUDE)
    )
    return {s.strip() for s in raw.split(",") if s.strip()}


def _dataset_rank(datasets: list[str]) -> int:
    best = 99
    for ds in datasets or []:
        best = min(best, _DATASET_PRIORITY.get(str(ds), 50))
    return best


def _schema_rank(schema: str) -> int:
    return _SCHEMA_PRIORITY.get(schema or "", 50)


def _entity_severity(entity: dict) -> str:
    schema = entity.get("schema") or ""
    datasets = entity.get("datasets") or []
    ds_rank = _dataset_rank(datasets)
    if schema == "Event" and ds_rank <= 0:
        return "high"
    if schema == "Event" and ds_rank <= 2:
        return "medium"
    if schema in ("Vessel", "Event"):
        return "medium"
    if schema in ("Person", "Organization", "Company") and "intel-ingest" in datasets:
        return "medium"
    if entity.get("same_as"):
        return "medium"
    return "low"


def _primary_dataset(datasets: list[str]) -> str:
    if not datasets:
        return "unknown"
    return min(datasets, key=lambda d: _DATASET_PRIORITY.get(str(d), 50))


def _score_entity(entity: dict) -> tuple:
    """Sort key: lower tuple = higher priority in digest."""
    ds_rank = _dataset_rank(entity.get("datasets") or [])
    schema_rank = _schema_rank(entity.get("schema") or "")
    same_as_bonus = 0 if entity.get("same_as") else 1
    last_seen = entity.get("last_seen") or ""
    return (schema_rank, ds_rank, same_as_bonus, last_seen)


def format_entity_line(entity: dict) -> str:
    """Human-readable digest line for one FtM entity."""
    schema = entity.get("schema") or "Entity"
    caption = (entity.get("caption") or entity.get("id") or "Unknown")[:140]
    primary = _primary_dataset(entity.get("datasets") or [])
    parts = [f"[FtM {schema}/{primary}] {caption}"]
    links = entity.get("same_as") or []
    if links:
        linked = ", ".join(
            f"{n.get('caption', '?')} ({n.get('schema', '?')})" for n in links[:2]
        )
        parts.append(f"linked: {linked}")
    return " — ".join(parts)


def rank_entities_for_briefing(entities: list[dict]) -> list[dict]:
    """Stable priority sort for briefing candidates."""
    return sorted(entities, key=_score_entity)


def entities_to_digest_items(
    entities: list[dict],
    *,
    per_bucket: int = 4,
    existing_text_keys: set[str] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Classify ranked FtM entities into digest bucket items + slim metadata."""
    local_bbox = _region_bbox(OPERATOR_REGION)
    regional_bbox = _ASEAN_BBOX if OPERATOR_REGION == "thailand" else local_bbox
    if regional_bbox is None and local_bbox:
        w, s, e, n = local_bbox
        regional_bbox = [w - 8, s - 6, e + 8, n + 4]

    seen_captions = set(existing_text_keys or [])
    bucket_counts = {"local": 0, "regional": 0, "global": 0}
    items: list[dict] = []
    slim: list[dict] = []

    for entity in rank_entities_for_briefing(entities):
        caption_key = (entity.get("caption") or "")[:80].lower()
        if caption_key and caption_key in seen_captions:
            continue

        lat = entity.get("lat")
        lon = entity.get("lon")
        text = entity.get("caption") or ""
        bucket = classify_item(lat, lon, text, local_bbox, regional_bbox)
        if bucket_counts.get(bucket, 0) >= per_bucket:
            continue

        line_text = format_entity_line(entity)
        from digest_timestamps import apply_observed_at

        primary = _primary_dataset(entity.get("datasets") or [])
        body, iso = apply_observed_at(line_text, entity.get("last_seen"))
        items.append(
            {
                "severity": _entity_severity(entity),
                "text": body,
                "bucket": bucket,
                "source": "ftm",
                "sources": ["ftm", primary],
                "entity_id": entity.get("id"),
                "schema": entity.get("schema"),
                "datasets": entity.get("datasets") or [],
                "observed_at": iso,
            }
        )
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if caption_key:
            seen_captions.add(caption_key)
        slim.append(
            {
                "id": entity.get("id"),
                "schema": entity.get("schema"),
                "caption": entity.get("caption"),
                "bucket": bucket,
                "lat": lat,
                "lon": lon,
                "datasets": entity.get("datasets") or [],
                "same_as_count": len(entity.get("same_as") or []),
            }
        )

    meta = {
        "enabled": True,
        "count": len(slim),
        "by_bucket": bucket_counts,
        "candidates": len(entities),
        "entities": slim,
    }
    return items, meta


def gather_for_briefing() -> dict[str, Any]:
    """Load FtM entities for the current briefing window (fail-soft)."""
    if not briefing_intel_enabled():
        return {
            "enabled": False,
            "count": 0,
            "by_bucket": {},
            "entities": [],
            "candidates": [],
            "items": [],
        }

    window_hours = _env_int("WORLDBASE_BRIEFING_INTEL_WINDOW_HOURS", 24)
    fetch_limit = _env_int("WORLDBASE_BRIEFING_INTEL_FETCH_LIMIT", 200)
    per_bucket = _env_int("WORLDBASE_BRIEFING_INTEL_PER_BUCKET", 4)

    try:
        ftm_store.init_store()
        candidates = ftm_store.entities_for_briefing(
            window_hours=window_hours,
            fetch_limit=fetch_limit,
            exclude_schemas=_exclude_schemas(),
            include_same_as=True,
            same_as_per_entity=2,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "error": str(exc),
            "count": 0,
            "by_bucket": {},
            "entities": [],
            "candidates": [],
            "items": [],
            "window_hours": window_hours,
        }

    return {
        "enabled": True,
        "candidates": candidates,
        "window_hours": window_hours,
        "fetch_limit": fetch_limit,
        "per_bucket": per_bucket,
    }


def finalize_intel_for_digest(
    intel_meta: dict[str, Any] | None,
    *,
    existing_text_keys: set[str],
) -> dict[str, Any]:
    """Rank/classify FtM candidates after feed items are known (dedup against feeds)."""
    if not intel_meta or not intel_meta.get("enabled"):
        return {
            "enabled": False,
            "count": 0,
            "by_bucket": {},
            "entities": [],
            "items": [],
        }
    if intel_meta.get("error"):
        return intel_meta

    candidates = intel_meta.get("candidates") or []
    per_bucket = int(
        intel_meta.get("per_bucket")
        or _env_int("WORLDBASE_BRIEFING_INTEL_PER_BUCKET", 4)
    )
    items, slim = entities_to_digest_items(
        candidates,
        per_bucket=per_bucket,
        existing_text_keys=existing_text_keys,
    )
    return {
        **intel_meta,
        **slim,
        "items": items,
    }


def _format_flat_intel_block(intel_meta: dict[str, Any], lang: str = "en") -> str:
    """Flat entity list block (legacy prompt shape)."""
    items = intel_meta.get("items") or []
    if not items:
        if lang.startswith("de"):
            return "- Keine FtM-Entitäten im 24h-Fenster (Graph leer oder nur ausgeschlossene Schemas)."
        return "- No FtM entities in the 24h window (graph empty or only excluded schemas)."

    buckets: dict[str, list[str]] = {"local": [], "regional": [], "global": []}
    for item in items:
        bucket = item.get("bucket") or "global"
        buckets.setdefault(bucket, []).append(f"- {item.get('text', '')}")

    if lang.startswith("de"):
        header = "INTEL ENTITIES (FtM-Graph — wer/was, aus Feeds + Ingest):"
        labels = {
            "local": "LOCAL Entitäten:",
            "regional": "REGION Entitäten:",
            "global": "GLOBAL Entitäten:",
        }
    else:
        header = "INTEL ENTITIES (FtM graph — who/what from feeds + ingest):"
        labels = {
            "local": "LOCAL entities:",
            "regional": "REGION entities:",
            "global": "GLOBAL entities:",
        }

    parts = [header]
    for key in ("local", "regional", "global"):
        lines = buckets.get(key) or []
        if lines:
            parts.append(f"{labels[key]}\n" + "\n".join(lines))
    if len(parts) == 1:
        parts.append(buckets.get("global") and "\n".join(buckets["global"]) or "- none")
    return "\n\n".join(parts)


def intel_prompt_metrics(
    intel_meta: dict[str, Any] | None, lang: str = "en"
) -> dict[str, Any]:
    """Token proxy for flat vs subgraph intel blocks (Track 3+ Sprint 3)."""
    intel_meta = intel_meta or {}
    flat_block = _format_flat_intel_block(intel_meta, lang=lang)
    subgraph_block = ""
    mode = "flat"
    subgraph_available = False
    try:
        import intel_subgraph

        if intel_subgraph.subgraph_enabled() and briefing_intel_enabled():
            window = int(
                intel_meta.get("window_hours")
                or _env_int("WORLDBASE_BRIEFING_INTEL_WINDOW_HOURS", 24)
            )
            sg = intel_subgraph.build_subgraph(window_hours=window)
            if sg.get("available") and sg.get("nodes"):
                subgraph_block = intel_subgraph.format_subgraph_prompt_block(
                    sg, lang=lang
                )
                subgraph_available = True
                mode = "subgraph"
    except Exception:
        pass

    active_block = subgraph_block if mode == "subgraph" else flat_block
    return {
        "prompt_mode": mode,
        "intel_flat_chars": len(flat_block),
        "intel_subgraph_chars": len(subgraph_block),
        "intel_active_chars": len(active_block),
        "subgraph_available": subgraph_available,
    }


def format_intel_prompt_block(intel_meta: dict[str, Any], lang: str = "en") -> str:
    """Dedicated INTEL section for the LLM prompt (subgraph when enabled)."""
    metrics = intel_prompt_metrics(intel_meta, lang=lang)
    if metrics["prompt_mode"] == "subgraph":
        try:
            import intel_subgraph

            window = int(
                intel_meta.get("window_hours")
                or _env_int("WORLDBASE_BRIEFING_INTEL_WINDOW_HOURS", 24)
            )
            sg = intel_subgraph.build_subgraph(window_hours=window)
            if sg.get("available") and sg.get("nodes"):
                return intel_subgraph.format_subgraph_prompt_block(sg, lang=lang)
        except Exception:
            pass

    return _format_flat_intel_block(intel_meta, lang=lang)


def format_intel_chat_context(intel_meta: dict[str, Any]) -> str:
    """Compact FtM entity block for chat system context."""
    items = intel_meta.get("items") or []
    if not items:
        return ""
    lines = ["INTEL ENTITIES (FtM, ranked):"]
    for item in items[:8]:
        lines.append(f"  {item.get('text', '')}")
    return "\n".join(lines)
