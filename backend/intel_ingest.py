"""GLiNER + GLiREL document ingest -> FollowTheMoney graph (PC-only, GPU).

This module turns free text (paste / PDF / e-mail) into canonical FtM entities
and relations stored in :mod:`ftm_store`:

* **GLiNER** (``urchade/gliner_multi-v2.1``, multilingual, Apache-2.0) performs
  zero-shot Named Entity Recognition.
* **GLiREL** (``jackboyla/glirel-large-v0``, zero-shot Relation Extraction)
  classifies relations between the entities GLiNER found. (CC BY-NC-SA 4.0 -
  non-commercial; fine for local operator use.)

Heavy ML deps (torch / gliner / glirel) are imported lazily on first use, so the
FastAPI startup stays fast and the Raspberry Pi edge node is never burdened: it
only ever pulls the finished graph, it does not run this module.

Every entity and edge carries provenance (``dataset`` + ``seen_at``; edges also
``confidence``), matching the WorldBase non-negotiables.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

import ftm_store

# ---------------------------------------------------------------------------
# Config (env-overridable)
# ---------------------------------------------------------------------------

GLINER_MODEL = os.getenv("WORLDBASE_GLINER_MODEL", "urchade/gliner_multi-v2.1")
GLIREL_MODEL = os.getenv("WORLDBASE_GLIREL_MODEL", "jackboyla/glirel-large-v0")
_DEVICE_PREF = os.getenv("WORLDBASE_INTEL_DEVICE", "auto").lower()
_ENT_THRESHOLD = float(os.getenv("WORLDBASE_GLINER_THRESHOLD", "0.45"))
_REL_THRESHOLD = float(os.getenv("WORLDBASE_GLIREL_THRESHOLD", "0.50"))
_MAX_CHARS = int(os.getenv("WORLDBASE_INTEL_MAX_CHARS", "60000"))
_CHUNK_CHARS = int(os.getenv("WORLDBASE_INTEL_CHUNK_CHARS", "1400"))

# Zero-shot entity labels GLiNER searches for.
ENTITY_LABELS = [
    "person", "organization", "company", "government agency", "location",
    "address", "vessel", "aircraft", "event", "facility", "email", "phone number",
]

# GLiNER label -> FtM schema.
_FTM_SCHEMA: dict[str, str] = {
    "person": "Person",
    "organization": "Organization",
    "company": "Company",
    "government agency": "Organization",
    "location": "Address",
    "address": "Address",
    "facility": "Address",
    "vessel": "Vessel",
    "aircraft": "Airplane",
    "event": "Event",
    "email": "Person",
    "phone number": "Person",
}

# FtM schema -> coarse GLiREL head/tail type (used for allowed_head / allowed_tail).
_GLIREL_TYPE: dict[str, str] = {
    "Person": "PERSON",
    "Organization": "ORG",
    "Company": "ORG",
    "Vessel": "ORG",
    "Airplane": "ORG",
    "Address": "LOC",
    "Event": "EVENT",
    "Thing": "MISC",
}

# Zero-shot relation labels (edge ``kind``) + coarse head/tail type constraints.
# GLiREL's raw ``predict_relations`` API takes a flat label list and does NOT
# enforce head/tail types, so we constrain results ourselves by FtM schema.
RELATION_CONSTRAINTS: dict[str, tuple[set[str], set[str]]] = {
    "works for": ({"PERSON"}, {"ORG"}),
    "founder of": ({"PERSON"}, {"ORG"}),
    "owner of": ({"PERSON", "ORG"}, {"ORG"}),
    "member of": ({"PERSON"}, {"ORG"}),
    "subsidiary of": ({"ORG"}, {"ORG"}),
    "located in": ({"PERSON", "ORG", "LOC"}, {"LOC"}),
    "headquartered in": ({"ORG"}, {"LOC"}),
    "family of": ({"PERSON"}, {"PERSON"}),
    "associate of": ({"PERSON"}, {"PERSON"}),
    "participated in": ({"PERSON", "ORG"}, {"EVENT"}),
}
RELATION_LABELS: list[str] = list(RELATION_CONSTRAINTS.keys())

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

# ---------------------------------------------------------------------------
# Lazy model singletons
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_GLINER = None
_GLIREL = None
_DEVICE: str | None = None
_LOAD_ERROR: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_device() -> str:
    import torch

    if _DEVICE_PREF in ("cuda", "gpu"):
        return "cuda" if torch.cuda.is_available() else "cpu"
    if _DEVICE_PREF == "cpu":
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load() -> tuple[Any, Any, str]:
    """Load GLiNER + GLiREL once. Raises on failure (caller maps to HTTP 503)."""
    global _GLINER, _GLIREL, _DEVICE, _LOAD_ERROR
    if _GLINER is not None and _GLIREL is not None:
        return _GLINER, _GLIREL, _DEVICE  # type: ignore[return-value]
    with _LOCK:
        if _GLINER is not None and _GLIREL is not None:
            return _GLINER, _GLIREL, _DEVICE  # type: ignore[return-value]
        try:
            # Windows: torch and pyarrow ship clashing native libs; importing
            # pyarrow before torch (gliner pulls torch + datasets/pyarrow) avoids
            # an access-violation crash. Must happen before the gliner import.
            try:
                import pyarrow.dataset  # noqa: F401
            except Exception:
                pass

            from gliner import GLiNER
            from glirel import GLiREL

            device = _resolve_device()
            gliner = GLiNER.from_pretrained(GLINER_MODEL)
            glirel = GLiREL.from_pretrained(GLIREL_MODEL)
            try:
                gliner = gliner.to(device)
                glirel = glirel.to(device)
            except Exception:
                device = "cpu"
            try:
                gliner.eval()
                glirel.eval()
            except Exception:
                pass
            _GLINER, _GLIREL, _DEVICE, _LOAD_ERROR = gliner, glirel, device, None
        except Exception as exc:  # pragma: no cover - depends on optional deps
            _LOAD_ERROR = f"{type(exc).__name__}: {exc}"
            raise
    return _GLINER, _GLIREL, _DEVICE  # type: ignore[return-value]


def status() -> dict:
    """Report model / device state without forcing a load."""
    info: dict[str, Any] = {
        "loaded": _GLINER is not None and _GLIREL is not None,
        "device": _DEVICE,
        "gliner_model": GLINER_MODEL,
        "glirel_model": GLIREL_MODEL,
        "load_error": _LOAD_ERROR,
        "entity_labels": ENTITY_LABELS,
        "relation_labels": RELATION_LABELS,
    }
    try:
        import torch

        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            info["cuda_device"] = torch.cuda.get_device_name(0)
    except Exception:
        info["torch_version"] = None
        info["cuda_available"] = False
    return info


# ---------------------------------------------------------------------------
# Tokenization + char-span -> token-span alignment (GLiREL needs token indices)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[tuple[str, int, int]]:
    """Return [(token, char_start, char_end_exclusive), ...]."""
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]


def _char_span_to_tokens(tokens: list[tuple[str, int, int]], cs: int, ce: int) -> tuple[int, int] | None:
    """Map a [cs, ce) char span to inclusive [first_tok, last_tok] indices."""
    first = last = None
    for i, (_t, ts, te) in enumerate(tokens):
        if te > cs and ts < ce:
            if first is None:
                first = i
            last = i
    if first is None:
        return None
    return first, last


# ---------------------------------------------------------------------------
# Entity normalization + FtM persistence
# ---------------------------------------------------------------------------


def _norm_key(schema: str, surface: str) -> str:
    return f"{schema}\u0001{re.sub(r'\s+', ' ', surface).strip().casefold()}"


def _entity_id(schema: str, surface: str) -> str:
    proxy = ftm_store.make_entity(schema, [schema, _norm_key(schema, surface)], {"name": [surface]})
    return proxy.id


def _chunk_text(text: str, max_chars: int) -> list[tuple[str, int]]:
    """Split text into chunks under ``max_chars`` at paragraph/line boundaries.

    Returns [(chunk_text, char_offset_in_original), ...].
    """
    chunks: list[tuple[str, int]] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + max_chars, n)
        if end < n:
            window = text[pos:end]
            cut = max(window.rfind("\n"), window.rfind(". "))
            if cut > max_chars // 2:
                end = pos + cut + 1
        chunks.append((text[pos:end], pos))
        pos = end
    return chunks


# ---------------------------------------------------------------------------
# Core extraction + ingest
# ---------------------------------------------------------------------------


def ingest_text(
    text: str,
    *,
    dataset: str = "intel-ingest",
    source_ref: str | None = None,
    threshold: float | None = None,
    relation_threshold: float | None = None,
) -> dict:
    """Extract entities + relations from ``text`` and persist them into ftm_store."""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    truncated = len(text) > _MAX_CHARS
    if truncated:
        text = text[:_MAX_CHARS]

    gliner, glirel, device = _load()
    ent_thr = _ENT_THRESHOLD if threshold is None else float(threshold)
    rel_thr = _REL_THRESHOLD if relation_threshold is None else float(relation_threshold)
    seen = _now()

    # Source/document hub so the graph is connected even without semantic edges.
    src_label = source_ref or f"Ingest {seen}"
    doc_proxy = ftm_store.make_entity(
        "Document",
        ["intel-ingest", source_ref or hashlib.sha256(text.encode()).hexdigest()[:16]],
        {"title": [src_label], "fileName": [source_ref] if source_ref else None},
    )
    ftm_store.upsert(doc_proxy, dataset=dataset, seen_at=seen)
    doc_id = doc_proxy.id

    entities: dict[str, dict] = {}  # ftm_id -> {schema, name}
    edges: list[dict] = []
    edge_keys: set[tuple] = set()

    def _record_edge(src: str, tgt: str, kind: str, conf: float):
        key = (src, tgt, kind)
        if src == tgt or key in edge_keys:
            return
        edge_keys.add(key)
        ftm_store.add_edge(src, tgt, kind, dataset=dataset, confidence=conf, seen_at=seen)
        edges.append({"source": src, "target": tgt, "kind": kind, "confidence": round(conf, 3)})

    for chunk, _offset in _chunk_text(text, _CHUNK_CHARS):
        if not chunk.strip():
            continue
        try:
            found = gliner.predict_entities(chunk, ENTITY_LABELS, threshold=ent_thr)
        except Exception:
            continue

        tokens = _tokenize(chunk)
        token_texts = [t[0] for t in tokens]
        ner: list[list] = []
        ner_ids: list[str] = []
        ner_types: list[str] = []
        start_to_ner: dict[int, int] = {}

        for ent in found:
            label = (ent.get("label") or "").lower()
            surface = (ent.get("text") or "").strip()
            if not surface:
                continue
            schema = _FTM_SCHEMA.get(label, "Thing")
            eid = _entity_id(schema, surface)
            proxy = ftm_store.make_entity(schema, [schema, _norm_key(schema, surface)], {"name": [surface]})
            ftm_store.upsert(proxy, dataset=dataset, seen_at=seen)
            entities[eid] = {"schema": schema, "name": surface}
            _record_edge(doc_id, eid, "mentions", 1.0)

            span = _char_span_to_tokens(tokens, ent.get("start", 0), ent.get("end", 0))
            if span is not None:
                ti0, ti1 = span
                start_to_ner[ti0] = len(ner)
                ner.append([ti0, ti1, _GLIREL_TYPE.get(schema, "MISC"), surface])
                ner_ids.append(eid)
                ner_types.append(_GLIREL_TYPE.get(schema, "MISC"))

        if len(ner) >= 2:
            try:
                rels = glirel.predict_relations(
                    token_texts, RELATION_LABELS, threshold=0.0, ner=ner, top_k=1
                )
            except Exception:
                rels = []
            for r in rels or []:
                label = r.get("label")
                score = float(r.get("score", 0.0))
                constraint = RELATION_CONSTRAINTS.get(label or "")
                if constraint is None or score < rel_thr:
                    continue
                hp = r.get("head_pos") or []
                tp = r.get("tail_pos") or []
                if not hp or not tp:
                    continue
                h_idx = start_to_ner.get(hp[0])
                t_idx = start_to_ner.get(tp[0])
                if h_idx is None or t_idx is None or h_idx == t_idx:
                    continue
                allowed_head, allowed_tail = constraint
                if ner_types[h_idx] not in allowed_head or ner_types[t_idx] not in allowed_tail:
                    continue
                _record_edge(ner_ids[h_idx], ner_ids[t_idx], label, score)

    return {
        "ok": True,
        "device": device,
        "dataset": dataset,
        "source": src_label,
        "root_id": doc_id,
        "truncated": truncated,
        "counts": {
            "entities": len(entities),
            "edges": len(edges),
            "mentions": sum(1 for e in edges if e["kind"] == "mentions"),
            "relations": sum(1 for e in edges if e["kind"] != "mentions"),
        },
        "entities": [{"id": k, **v} for k, v in entities.items()],
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Document text extraction (PDF / e-mail / plain)
# ---------------------------------------------------------------------------


def extract_text_from_pdf(data: bytes) -> str:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io_bytes(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def extract_text_from_email(data: bytes) -> str:
    import mailparser

    mail = mailparser.parse_from_bytes(data)
    header = " ".join(
        x for x in [
            f"From: {mail.from_}" if mail.from_ else "",
            f"To: {mail.to}" if mail.to else "",
            f"Subject: {mail.subject}" if mail.subject else "",
        ] if x
    )
    body = mail.text_plain[0] if mail.text_plain else (mail.body or "")
    return f"{header}\n\n{body}".strip()


def io_bytes(data: bytes):
    import io

    return io.BytesIO(data)


def extract_document(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return extract_text_from_pdf(data)
    if name.endswith(".eml") or name.endswith(".msg"):
        return extract_text_from_email(data)
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# FastAPI routes (heavy deps stay lazy; load failures map to HTTP 503)
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile  # noqa: E402

router = APIRouter(prefix="/api/intel/ingest", tags=["intel"])


@router.get("/status")
async def ingest_status(load: bool = False):
    """Model + device state. ``?load=1`` forces a (slow) first-time model load."""
    if load:
        try:
            await _to_thread(_load)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"model load failed: {exc}")
    return status()


@router.post("/text")
async def ingest_text_route(payload: dict = Body(...)):
    text = payload.get("text") or ""
    if not text.strip():
        raise HTTPException(status_code=400, detail="field 'text' is required")
    try:
        return await _to_thread(
            ingest_text,
            text,
            dataset=payload.get("dataset") or "intel-ingest",
            source_ref=payload.get("source_ref"),
            threshold=payload.get("threshold"),
            relation_threshold=payload.get("relation_threshold"),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ingest failed: {exc}")


@router.post("/document")
async def ingest_document_route(
    file: UploadFile = File(...),
    dataset: str = Form("intel-ingest"),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        text = await _to_thread(extract_document, file.filename or "", data)
    except Exception as exc:
        raise HTTPException(status_code=415, detail=f"could not parse document: {exc}")
    if not text.strip():
        raise HTTPException(status_code=422, detail="no extractable text in document")
    try:
        return await _to_thread(
            ingest_text, text, dataset=dataset, source_ref=file.filename
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ingest failed: {exc}")


async def _to_thread(fn, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(fn, *args, **kwargs)
