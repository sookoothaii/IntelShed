"""Insight synthesis (Track A) — ranked so-what cards from existing intelligence.

Deterministic correlation + ranking over fusion hotspots and the FtM subgraph.
Each insight answers what / where / why it matters / since when / how confident.

A1 (this module) ships deterministic headlines and so-what templates. The local
LLM narrative layer (A2) only rewrites ``headline`` / ``so_what`` and flips
``narrative_source`` to ``ollama``. Fail-soft: returns ``{count: 0, insights: []}``
when no fusion grid cache is available.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter

import fusion_heatmap
import intel_subgraph

router = APIRouter(prefix="/api", tags=["insights"])

_CELL_DEG = 2.0
_DELTA_MIN = 0.12  # escalation threshold (matches build_watch_items)
_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None, "key": None}
_CACHE_TTL = 120.0

# --- A2: local LLM narrative layer (qwen3:8b by default) --------------------
_LLM_ENABLED = os.getenv("INSIGHTS_LLM", "1").strip().lower() in ("1", "true", "yes")
_LLM_TOP = int(os.getenv("INSIGHTS_LLM_TOP", "5"))
_LLM_TIMEOUT = float(os.getenv("INSIGHTS_LLM_TIMEOUT", "25"))
_OLLAMA_HOSTS = [
    h.strip()
    for h in os.getenv("OLLAMA_HOST", "127.0.0.1:11434").split(",")
    if h.strip()
]
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
# Narrative cache keyed by insight id + rounded score/delta — survives rebuilds.
_NARRATIVE_CACHE: dict[str, tuple[str, str]] = {}
_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s*(.+?)\s*::\s*(.+?)\s*$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _confidence(sources: list[str], delta: float, score: float) -> tuple[float, str]:
    """Confidence from independent source families + escalation + base score.

    When provenance (P4) is enabled, source reliability modulates confidence.
    """
    families = len({s for s in (sources or []) if s})
    conf = 0.30 + 0.15 * min(families, 3)
    conf += min(0.15, max(0.0, delta))
    conf += max(0.0, score) * 0.10

    # P4: provenance boost from source reliability
    try:
        from provenance import provenance_enabled, source_reliability

        if provenance_enabled() and sources:
            avg_reliability = sum(source_reliability(s) for s in sources) / len(sources)
            conf += (avg_reliability - 0.5) * 0.10  # ±0.05 around neutral
    except Exception:
        pass

    conf = round(min(0.95, conf), 2)
    basis = f"{families} source famil{'y' if families == 1 else 'ies'}"
    if delta >= _DELTA_MIN:
        basis += f", +{delta:.2f} since 24h"
    return conf, basis


def _bbox_around(lat: float, lon: float, deg: float = _CELL_DEG) -> list[float]:
    half = deg / 2.0
    return [
        round(lon - half, 3),
        round(lat - half, 3),
        round(lon + half, 3),
        round(lat + half, 3),
    ]


def _entities_for(bbox: list[float]) -> list[dict[str, Any]]:
    """Top linked FtM entities inside the hotspot bbox (fail-soft to empty)."""
    try:
        sg = intel_subgraph.build_subgraph(
            bbox=bbox, hops=1, node_limit=12, window_hours=24
        )
    except Exception:
        return []
    if not sg.get("available"):
        return []
    out: list[dict[str, Any]] = []
    for node in (sg.get("nodes") or [])[:5]:
        name = node.get("caption") or node.get("name") or node.get("id")
        if not name:
            continue
        out.append({"id": node.get("id"), "name": name, "schema": node.get("schema")})
    return out


def _first_sample(cell: dict) -> str:
    for s in cell.get("samples") or []:
        label = s.get("label")
        if label:
            return str(label)[:100]
    return ""


def _headline(rising: bool, place: str, sources: list[str], sample: str) -> str:
    families = sorted({s for s in (sources or []) if s})
    fam_label = ", ".join(families[:3]) or "multi-source"
    state = "Escalating" if rising else "Active"
    if sample:
        return f"{state} cluster — {place}: {sample[:60]}"
    return f"{state} {fam_label} cluster — {place}"


def _so_what(
    rising: bool, families: int, delta: float, score: float, entity_names: list[str]
) -> str:
    bits: list[str] = []
    if families >= 2:
        bits.append(f"{families} independent feed families converge here")
    else:
        bits.append("single-family signal — corroboration low")
    if rising:
        bits.append(f"intensity rose {delta:.2f} in the last 24h")
    if entity_names:
        bits.append("linked entities: " + ", ".join(entity_names[:3]))
    tail = (
        "worth a closer look before the next briefing."
        if (rising or families >= 2)
        else "monitor; not yet corroborated."
    )
    return "; ".join(bits) + " — " + tail


def synthesize_insights(
    hotspots: list[dict],
    deltas: list[dict] | None = None,
    *,
    top: int = 10,
    with_entities: bool = True,
) -> list[dict[str, Any]]:
    """Pure synthesis step — testable without network (fusion data passed in)."""
    delta_map = {
        c.get("cell_id"): float(c.get("delta_score") or 0)
        for c in (deltas or [])
        if c.get("cell_id")
    }

    insights: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cell in hotspots or []:
        lat, lon = cell.get("lat"), cell.get("lon")
        if lat is None or lon is None:
            continue
        cid = cell.get("cell_id") or f"{float(lat):.2f},{float(lon):.2f}"
        if cid in seen:
            continue
        seen.add(cid)

        score = float(cell.get("score") or 0)
        delta = float(cell.get("delta_score") or delta_map.get(cid) or 0)
        rising = delta >= _DELTA_MIN
        sources = [s for s in (cell.get("sources") or []) if s]
        families = len(set(sources))
        place = fusion_heatmap._lat_lon_label(float(lat), float(lon))
        bbox = _bbox_around(float(lat), float(lon))
        entities = _entities_for(bbox) if with_entities else []
        entity_names = [e["name"] for e in entities if e.get("name")]
        conf, basis = _confidence(sources, delta, score)
        sample = _first_sample(cell)
        since = (
            (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            if rising
            else None
        )

        # P4: provenance score per insight
        provenance_score: float | None = None
        try:
            from provenance import provenance_enabled, score_provenance

            if provenance_enabled():
                provenance_score = score_provenance(
                    source=sources[0] if sources else "unknown",
                    corroboration_count=max(0, families - 1),
                )
        except Exception:
            pass

        insights.append(
            {
                "id": f"insight:{cid}",
                "cell_id": cid,
                "center": {"lat": lat, "lon": lon, "place": place},
                "bbox": bbox,
                "score": round(score, 3),
                "delta_score": round(delta, 3),
                "rising": rising,
                "since": since,
                "sources": sources,
                "entities": entities,
                "confidence": conf,
                "confidence_basis": basis,
                "provenance": provenance_score,
                "headline": _headline(rising, place, sources, sample),
                "so_what": _so_what(rising, families, delta, score, entity_names),
                "narrative_source": "template",
                "samples": [
                    str(s.get("label"))[:80]
                    for s in (cell.get("samples") or [])
                    if s.get("label")
                ][:2],
            }
        )

    # Rising cells first, then by descending score.
    insights.sort(key=lambda x: (0 if x["rising"] else 1, -x["score"]))
    insights = insights[:top]
    for i, ins in enumerate(insights, 1):
        ins["rank"] = i
    return insights


def slim_insights(insights: list[dict[str, Any]], top: int = 5) -> list[dict[str, Any]]:
    """Compact insight rows for briefing JSON + Pi pull (drops bbox/entities/samples)."""
    out: list[dict[str, Any]] = []
    for ins in (insights or [])[:top]:
        out.append(
            {
                "id": ins.get("id"),
                "rank": ins.get("rank"),
                "headline": ins.get("headline"),
                "so_what": ins.get("so_what"),
                "center": ins.get("center"),
                "score": ins.get("score"),
                "delta_score": ins.get("delta_score"),
                "rising": ins.get("rising"),
                "confidence": ins.get("confidence"),
                "provenance": ins.get("provenance"),
                "sources": ins.get("sources") or [],
            }
        )
    return out


def format_insights_prompt_block(insights: list[dict[str, Any]], top: int = 5) -> str:
    """Compact INSIGHTS block for the briefing prompt (ranked synthesis, few tokens)."""
    items = (insights or [])[:top]
    if not items:
        return ""
    lines = [
        "INSIGHTS (ranked cross-source synthesis — place, escalation, why it matters):"
    ]
    for ins in items:
        place = (ins.get("center") or {}).get("place", "")
        delta = float(ins.get("delta_score") or 0)
        rise = f" +{delta:.2f}/24h" if ins.get("rising") else ""
        srcs = ",".join(ins.get("sources") or [])
        conf = int(round((ins.get("confidence") or 0) * 100))
        lines.append(
            f"- #{ins.get('rank')} {ins.get('headline')} ({place}{rise}; conf {conf}%; [{srcs}])"
        )
    return "\n".join(lines)


def _darkweb_insights(top: int = 3) -> list[dict[str, Any]]:
    """Create insight cards from already ingested dark web Mention entities."""
    try:
        from config import get_config

        if not get_config().darkweb_enabled or not get_config().briefing_darkweb:
            return []
    except Exception:
        return []

    try:
        import ftm_query

        rows = ftm_query.list_entities(limit=200)
        mentions = [
            r
            for r in rows
            if r.get("schema") == "Mention" and "darkweb" in (r.get("datasets") or [])
        ]
    except Exception:
        return []

    insights: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in mentions[:top]:
        props = m.get("properties", {})
        url = (props.get("url") or [""])[0]
        if url in seen:
            continue
        seen.add(url)
        title = (props.get("name") or ["Dark web mention"])[0]
        engine = (props.get("source") or ["darkweb"])[0]
        query = (props.get("query") or [""])[0]
        insights.append(
            {
                "id": f"darkweb:{m.get('id', url)}",
                "type": "darkweb_mention",
                "center": {"lat": None, "lon": None, "place": "dark web"},
                "score": 0.55,
                "delta_score": 0.0,
                "rising": False,
                "sources": [engine],
                "entities": [],
                "confidence": 0.45,
                "confidence_basis": "single low-reliability source",
                "headline": f"Dark web mention: {title[:60]}",
                "so_what": f"Low-reliability dark web reference ({engine}). Corroborate before acting; query: {query[:40]}",
                "narrative_source": "template",
            }
        )
    return insights


async def build_insights(top: int = 10, *, narrate: bool = True) -> dict[str, Any]:
    """Fetch fusion hotspots and synthesize ranked insight cards."""
    try:
        hotspots, _text, deltas = await fusion_heatmap.top_hotspots_for_llm(
            cell_deg=_CELL_DEG, top=top, compare_hours=24.0
        )
    except Exception as exc:
        return {
            "count": 0,
            "insights": [],
            "error": str(exc)[:200],
            "generated_at": _now_iso(),
        }

    insights: list[dict[str, Any]] = []
    if hotspots:
        insights = synthesize_insights(hotspots, deltas, top=top)

    # Append dark web insights (low-reliability, no spatial center) if enabled.
    try:
        insights.extend(_darkweb_insights(top=3))
    except Exception:
        pass

    if narrate:
        try:
            insights = await narrate_insights(insights)
        except Exception:
            pass  # deterministic templates already in place
    return {
        "count": len(insights),
        "insights": insights,
        "generated_at": _now_iso(),
        "cell_deg": _CELL_DEG,
        "narrated": narrate and _LLM_ENABLED,
    }


def _narrative_key(ins: dict[str, Any]) -> str:
    return f"{ins.get('id')}|{ins.get('score'):.2f}|{ins.get('delta_score'):.2f}"


def _narration_prompt(items: list[dict[str, Any]]) -> str:
    lines = [
        "You are an OSINT analyst writing for a solo operator. For each numbered",
        'hotspot, write a short headline (max 10 words) and a one-sentence "so what"',
        "(max 25 words, plain, decision-relevant). Use ONLY the given signals; do not",
        "invent facts or place names. Output EXACTLY one line per hotspot, nothing",
        "else, in this format:",
        "<number>| <headline> :: <so what>",
        "",
        "Hotspots:",
    ]
    for i, ins in enumerate(items, 1):
        sources = ",".join(ins.get("sources") or []) or "none"
        ents = ",".join(e.get("name", "") for e in (ins.get("entities") or [])[:3])
        sample = (ins.get("samples") or [""])[0]
        place = (ins.get("center") or {}).get("place", "")
        lines.append(
            f"{i}. {place} score={ins.get('score')} delta={ins.get('delta_score')}/24h "
            f"sources=[{sources}] sample=\"{sample}\" entities=[{ents}]"
        )
    return "\n".join(lines)


async def _ollama_complete(prompt: str) -> str:
    """Single-shot local LLM completion — bounded tokens, no Qwen3 thinking."""
    body: dict[str, Any] = {
        "model": _OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_predict": 600, "temperature": 0.3},
    }
    if "qwen3" in _OLLAMA_MODEL.lower():
        body["think"] = False
    for host in _OLLAMA_HOSTS:
        try:
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                r = await client.post(f"http://{host}/api/chat", json=body)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return ""


def _parse_narration(text: str) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for line in (text or "").splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1))
        headline = m.group(2).strip()[:120]
        so_what = m.group(3).strip()[:280]
        if headline and so_what:
            out[idx] = (headline, so_what)
    return out


async def narrate_insights(insights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite headline/so_what for the top insights via local LLM (fail-soft).

    Cached by insight id + rounded score/delta so unchanged hotspots reuse prior
    text. On any failure the deterministic template (A1) is kept unchanged.
    """
    if not _LLM_ENABLED or not insights:
        return insights

    targets = insights[: max(0, _LLM_TOP)]
    to_call: list[dict[str, Any]] = []
    for ins in targets:
        cached = _NARRATIVE_CACHE.get(_narrative_key(ins))
        if cached:
            ins["headline"], ins["so_what"] = cached
            ins["narrative_source"] = "ollama"
        else:
            to_call.append(ins)

    if not to_call:
        return insights

    text = await _ollama_complete(_narration_prompt(to_call))
    parsed = _parse_narration(text)
    for i, ins in enumerate(to_call, 1):
        pair = parsed.get(i)
        if not pair:
            continue
        ins["headline"], ins["so_what"] = pair
        ins["narrative_source"] = "ollama"
        _NARRATIVE_CACHE[_narrative_key(ins)] = pair
    return insights


@router.get("/insights")
async def get_insights(top: int = 10):
    """Ranked so-what insight cards (Track A). 120s cache; fail-soft to empty."""
    top = max(1, min(20, int(top)))
    now = time.time()
    cached = _CACHE["payload"]
    if cached and _CACHE["key"] == top and (now - _CACHE["ts"]) < _CACHE_TTL:
        return {**cached, "cached": True}
    payload = await build_insights(top=top)
    _CACHE.update(ts=now, payload=payload, key=top)
    return {**payload, "cached": False}
