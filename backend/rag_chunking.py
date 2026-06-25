"""Adaptive RAG chunking profiles (Track R1.3).

Profiles load from ``ingest/mappings/*.yml`` ``rag:`` blocks or built-in defaults
for sources that bypass YAML feed mappings (briefing, situations, …).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChunkProfile:
    strategy: str = "record"
    max_chars: int = 600
    overlap: int = 0
    min_chars: int = 24
    source_key: str = "id"
    rag_source: str | None = None
    body: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def effective_rag_source(self, fallback: str) -> str:
        return self.rag_source or fallback


# Built-in profiles for RAG ingest paths that do not use feed YAML mappings.
SOURCE_DEFAULTS: dict[str, ChunkProfile] = {
    "briefing": ChunkProfile(
        strategy="paragraph", max_chars=800, overlap=100, source_key="created_at"
    ),
    "situations": ChunkProfile(strategy="record", max_chars=640, source_key="id"),
    "volcanoes": ChunkProfile(strategy="single", max_chars=420, source_key="id"),
    "hazards": ChunkProfile(strategy="single", max_chars=520, source_key="id"),
    "prediction_watch": ChunkProfile(
        strategy="single", max_chars=720, source_key="watch_id"
    ),
    "newsdata": ChunkProfile(
        strategy="headline", max_chars=480, source_key="article_id"
    ),
    "stac": ChunkProfile(strategy="single", max_chars=420, source_key="id"),
    "sanctions": ChunkProfile(strategy="single", max_chars=520, source_key="entity_id"),
    "gdelt_pulse": ChunkProfile(strategy="headline", max_chars=480, source_key="url"),
    "gdelt_pulse_local": ChunkProfile(
        strategy="headline", max_chars=480, source_key="url"
    ),
    "gdelt_pulse_global": ChunkProfile(
        strategy="headline", max_chars=480, source_key="url"
    ),
}


def profile_from_yaml(raw: dict[str, Any] | None) -> ChunkProfile | None:
    if not raw or not isinstance(raw, dict):
        return None
    body = raw.get("body") or []
    if not isinstance(body, list):
        body = []
    return ChunkProfile(
        strategy=str(raw.get("strategy") or "record").strip().lower(),
        max_chars=int(raw.get("max_chars") or 600),
        overlap=max(0, int(raw.get("overlap") or 0)),
        min_chars=max(1, int(raw.get("min_chars") or 24)),
        source_key=str(raw.get("source_key") or "id"),
        rag_source=(str(raw["rag_source"]).strip() if raw.get("rag_source") else None),
        body=tuple(dict(part) for part in body if isinstance(part, dict)),
    )


def get_source_profile(source: str, mapping_name: str | None = None) -> ChunkProfile:
    if mapping_name:
        from ingest.mapping_runner import load_rag_profile

        mapped = load_rag_profile(mapping_name)
        if mapped is not None:
            return mapped
    return SOURCE_DEFAULTS.get(source, ChunkProfile())


def _field_line(record: dict[str, Any], spec: dict[str, Any]) -> str:
    if "template" in spec:
        try:
            return str(spec["template"]).format(**record).strip()
        except (KeyError, ValueError):
            return str(spec["template"]).strip()
    if "column" in spec:
        val = record.get(spec["column"])
        if val in (None, ""):
            return ""
        text = str(val).strip()
        max_field = spec.get("max_chars")
        if max_field is not None:
            text = text[: int(max_field)]
        prefix = spec.get("prefix") or ""
        return f"{prefix}{text}".strip()
    cols = spec.get("columns") or []
    parts = [
        str(record.get(c)).strip() for c in cols if record.get(c) not in (None, "")
    ]
    if not parts:
        return ""
    joiner = spec.get("join") or " | "
    text = joiner.join(parts)
    prefix = spec.get("prefix") or ""
    return f"{prefix}{text}".strip()


def format_record_body(record: dict[str, Any], profile: ChunkProfile) -> str:
    lines: list[str] = []
    for spec in profile.body:
        line = _field_line(record, spec)
        if line:
            lines.append(line)
    if lines:
        return "\n".join(lines)
    title = (
        record.get("title") or record.get("name") or record.get("text") or ""
    ).strip()
    return title


def split_text(text: str, max_chars: int, overlap: int = 0) -> list[str]:
    """Split *text* at paragraph / sentence boundaries with optional overlap."""
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= max_chars:
        return [body]

    chunks: list[str] = []
    pos = 0
    n = len(body)
    while pos < n:
        end = min(pos + max_chars, n)
        if end < n:
            window = body[pos:end]
            cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "))
            if cut > max_chars // 3:
                end = pos + cut + (2 if window[cut : cut + 1] == ". " else 1)
        piece = body[pos:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        pos = max(end - overlap, pos + 1) if overlap else end
    return chunks


def chunk_text(text: str, profile: ChunkProfile) -> list[str]:
    body = (text or "").strip()
    if not body or len(body) < profile.min_chars:
        return []
    strategy = profile.strategy
    if strategy in ("headline", "single", "record"):
        if len(body) <= profile.max_chars:
            return [body]
        if strategy == "headline":
            return [body[: profile.max_chars].rstrip()]
        if strategy == "single":
            return [body[: profile.max_chars]]
    return split_text(body, profile.max_chars, profile.overlap)


def chunk_record(
    record: dict[str, Any],
    profile: ChunkProfile,
    *,
    preformatted: str | None = None,
) -> list[str]:
    text = (preformatted or format_record_body(record, profile)).strip()
    return chunk_text(text, profile)


def resolve_source_id(
    record: dict[str, Any], profile: ChunkProfile, fallback: str
) -> str:
    for key in (
        profile.source_key,
        "id",
        "eventid",
        "mmsi",
        "url",
        "article_id",
        "watch_id",
    ):
        val = record.get(key)
        if val not in (None, ""):
            return str(val)
    return fallback


def iter_chunk_ids(base_id: str, count: int) -> list[str]:
    if count <= 1:
        return [base_id]
    return [f"{base_id}:c{i}" for i in range(count)]
