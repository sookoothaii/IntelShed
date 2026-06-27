"""WorldBase — node briefing layer (snapshot, alerts, LLM briefing, Pi pull).

Extracted from node_sync.py (Phase 2). Handles:
- Feed snapshot gathering (parallel, cached)
- Critical alert compilation from raw feeds
- LLM situation briefing generation via Ollama
- Pi pull endpoint (briefing + alerts + fusion hotspots)
- Prediction ledger status endpoint
"""

from __future__ import annotations

import os
import json
import hashlib
import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Header, Query, Request, Depends
from fastapi.responses import JSONResponse, Response

from auth.security import verify_api_key, verify_lan_auth
from middleware.rate_limit import rate_limit_general, rate_limit_node_pull

from node_ingest import _db, _verify_node_secret

router = APIRouter(prefix="/api", tags=["node-sync"])

SELF_URL = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
OLLAMA_HOSTS = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

_BRIEFING_LOCK = asyncio.Lock()

_SNAPSHOT_CACHE: dict | None = None
_SNAPSHOT_CACHE_AT: float = 0.0
_SNAPSHOT_CACHE_LOCK = asyncio.Lock()


def _snapshot_cache_ttl_sec() -> float:
    try:
        return max(
            30.0,
            min(300.0, float(os.getenv("WORLDBASE_SNAPSHOT_CACHE_SEC", "90") or "90")),
        )
    except ValueError:
        return 90.0


def invalidate_snapshot_cache() -> None:
    """Drop cached feed snapshot (tests, forced refresh)."""
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    _SNAPSHOT_CACHE = None
    _SNAPSHOT_CACHE_AT = 0.0


def snapshot_cache_age_sec() -> float | None:
    """Seconds since last snapshot cache fill, or None if empty."""
    if _SNAPSHOT_CACHE is None or not _SNAPSHOT_CACHE_AT:
        return None
    return max(0.0, time.monotonic() - _SNAPSHOT_CACHE_AT)


async def warm_snapshot_cache(*, force: bool = False) -> dict:
    """Pre-fill snapshot cache after stack warmup (shared by briefing generate)."""
    return await _gather_snapshot(force=force)


def _gdelt_snapshot_meta(snap: dict) -> dict:
    """Compact GDELT feed counts for briefing quality scoring."""
    local = snap.get("gdelt_pulse_local") or {}
    geo_local = snap.get("gdelt_geo_local") or {}
    pulse = snap.get("gdelt_pulse") or {}
    geo = snap.get("gdelt_geo") or {}
    from briefing_quality import _gdelt_block_volume

    return {
        "local_pulse_count": _gdelt_block_volume(local, list_key="articles"),
        "geo_local_count": _gdelt_block_volume(geo_local, list_key="events"),
        "pulse_count": _gdelt_block_volume(pulse, list_key="articles"),
        "geo_count": _gdelt_block_volume(geo, list_key="events"),
        "feed_operator_available": _gdelt_block_volume(local, list_key="articles")
        + _gdelt_block_volume(geo_local, list_key="events"),
        "stale": bool(local.get("stale") or geo_local.get("stale")),
        "error": local.get("error") or geo_local.get("error"),
    }


# ---------------------------------------------------------------------------
# Fusion : gather feeds -> compile critical alerts
# ---------------------------------------------------------------------------
async def _gather_snapshot_uncached() -> dict:
    """Pull key feeds from our own API into one compact snapshot (parallel)."""
    snap: dict = {}
    feeds = (
        ("earthquakes", "/api/earthquakes?period=day&magnitude=4.5"),
        ("spaceweather", "/api/spaceweather"),
        ("events", "/api/events?limit=40"),
        ("markets", "/api/markets"),
        ("markets_crypto", "/api/markets/crypto"),
        ("markets_stocks", "/api/markets/stocks"),
        ("geopolitics", "/api/geopolitics?limit=20"),
        ("military", "/api/military"),
        ("gdacs", "/api/gdacs"),
        ("hazards", "/api/hazards?limit=40"),
        ("gdelt_pulse_local", "/api/gdelt/pulse/local"),
        ("gdelt_geo_local", "/api/gdelt/geo/local?timespan=1d&maxrecords=40"),
        ("gdelt_geo", "/api/gdelt/geo?timespan=1d&maxrecords=30"),
        ("river", "/api/anomalies/river"),
        ("outages", "/api/outages?limit=20"),
        ("volcanoes", "/api/volcanoes?active_only=true&limit=30"),
        ("cve", "/api/cve?limit=15"),
        ("nodes", "/api/nodes"),
        ("gdelt_pulse", "/api/gdelt/pulse"),
        ("airquality", "/api/airquality"),
        ("cams_haze", "/api/cams/haze"),
        ("humanitarian", "/api/humanitarian?limit=15"),
        ("newsdata", "/api/newsdata?limit=10"),
        ("maritime", "/api/maritime"),
    )

    async with httpx.AsyncClient(timeout=45.0) as client:

        async def grab(name: str, path: str) -> tuple[str, dict | None]:
            try:
                r = await client.get(f"{SELF_URL}{path}")
                if r.status_code == 200:
                    return name, r.json()
            except Exception:
                pass
            return name, None

        results = await asyncio.gather(*(grab(n, p) for n, p in feeds))
        for name, data in results:
            if data is not None:
                snap[name] = data
    return snap


async def _gather_snapshot(*, force: bool = False) -> dict:
    """Cached wrapper — TTL WORLDBASE_SNAPSHOT_CACHE_SEC (default 90s)."""
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    ttl = _snapshot_cache_ttl_sec()
    async with _SNAPSHOT_CACHE_LOCK:
        now = time.monotonic()
        if (
            not force
            and _SNAPSHOT_CACHE is not None
            and _SNAPSHOT_CACHE_AT
            and (now - _SNAPSHOT_CACHE_AT) < ttl
        ):
            return _SNAPSHOT_CACHE
        snap = await _gather_snapshot_uncached()
        _SNAPSHOT_CACHE = snap
        _SNAPSHOT_CACHE_AT = now
        return snap


def _compile_alerts(snap: dict) -> list:
    """Turn raw feeds into a ranked list of human-readable critical alerts."""
    alerts = []

    sw = snap.get("spaceweather", {})
    if sw.get("kp_index") is not None and sw["kp_index"] >= 5:
        alerts.append(
            {
                "severity": "high" if sw["kp_index"] >= 7 else "medium",
                "kind": "space_weather",
                "text": f"Geomagnetic {sw.get('scale', 'storm')} (Kp={sw['kp_index']}). "
                f"HF radio/GPS may degrade.",
            }
        )
    dst = sw.get("dst")
    if dst is not None and dst <= -100:
        alerts.append(
            {
                "severity": "high" if dst <= -150 else "medium",
                "kind": "space_weather_dst",
                "text": f"Geomagnetic storm (Dst={dst:.0f} nT). Power grid/GPS risk elevated.",
            }
        )
    solar = sw.get("solar_wind") or {}
    sw_speed = solar.get("speed_km_s")
    if sw_speed is not None and sw_speed >= 600:
        alerts.append(
            {
                "severity": "medium",
                "kind": "solar_wind",
                "text": f"High-speed solar wind {sw_speed:.0f} km/s. Aurora/HF propagation impact likely.",
            }
        )
    protons = sw.get("protons") or {}
    p10 = protons.get("gt_10_mev")
    if p10 is not None and p10 >= 10:
        alerts.append(
            {
                "severity": "high" if p10 >= 100 else "medium",
                "kind": "proton_event",
                "text": f"Elevated proton flux >10 MeV ({p10:.1f} pfu). Radiation storm risk.",
            }
        )
    for a in (sw.get("alerts") or [])[:3]:
        msg = (a.get("message") or "").strip()
        if not msg:
            continue
        asev = a.get("severity", "").lower()
        alerts.append(
            {
                "severity": "high" if asev in ("extreme", "severe") else "medium",
                "kind": "swpc_alert",
                "text": f"SWPC: {msg[:160]}",
            }
        )

    try:
        import markets_bridge

        stress = markets_bridge.summarize_market_stress(
            snap.get("markets_crypto"), snap.get("markets_stocks")
        )
        if (
            stress
            and markets_bridge._LEVEL_ORDER.get(stress.get("overall_level"), 0) >= 2
        ):
            line = markets_bridge.format_market_stress_line(stress)
            if line:
                alerts.append(
                    {
                        "severity": markets_bridge.market_stress_severity(
                            stress["overall_level"]
                        ),
                        "kind": "market_stress",
                        "text": line,
                    }
                )
    except Exception:
        pass

    quakes = (snap.get("earthquakes", {}) or {}).get("earthquakes", [])
    big = sorted(
        [q for q in quakes if (q.get("mag") or 0) >= 5.5],
        key=lambda q: q.get("mag") or 0,
        reverse=True,
    )[:5]
    for q in big:
        alerts.append(
            {
                "severity": "high" if (q.get("mag") or 0) >= 6.5 else "medium",
                "kind": "earthquake",
                "text": f"M{q.get('mag')} earthquake — {q.get('place')}",
                "lat": q.get("lat"),
                "lon": q.get("lon"),
            }
        )

    events = (snap.get("events", {}) or {}).get("events", [])
    for ev in events[:6]:
        alerts.append(
            {
                "severity": "low",
                "kind": "natural_event",
                "text": f"{ev.get('category')}: {ev.get('title')}",
                "lat": ev.get("lat"),
                "lon": ev.get("lon"),
            }
        )

    mil = (snap.get("military", {}) or {}).get("count")
    if mil:
        alerts.append(
            {
                "severity": "low",
                "kind": "military_air",
                "text": f"{mil} military/interesting aircraft currently tracked.",
            }
        )

    gdacs_n = (snap.get("gdacs", {}) or {}).get("count") or 0
    if gdacs_n:
        alerts.append(
            {
                "severity": "medium",
                "kind": "gdacs",
                "text": f"{gdacs_n} GDACS humanitarian alerts active.",
            }
        )

    haz_n = (snap.get("hazards", {}) or {}).get("count") or 0
    if haz_n:
        top = ((snap.get("hazards", {}) or {}).get("alerts") or [])[:3]
        sample = "; ".join((a.get("event") or "")[:50] for a in top if a.get("event"))
        alerts.append(
            {
                "severity": "medium",
                "kind": "weather_hazard",
                "text": f"{haz_n} NWS/Meteoalarm alerts active. {sample}".strip(),
            }
        )

    for sig in (snap.get("river", {}) or {}).get("anomalies") or []:
        alerts.append(
            {
                "severity": "high",
                "kind": "feed_anomaly",
                "text": f"River anomaly: {sig.get('feed')} value={sig.get('value')} score={sig.get('score')}",
            }
        )

    out_n = (snap.get("outages", {}) or {}).get("count") or 0
    if out_n:
        top = ((snap.get("outages", {}) or {}).get("items") or [])[:2]
        sample = "; ".join((i.get("title") or "")[:40] for i in top)
        alerts.append(
            {
                "severity": "medium",
                "kind": "internet_outage",
                "text": f"{out_n} IODA/CF outage signals. {sample}".strip(),
            }
        )

    act_v = (snap.get("volcanoes", {}) or {}).get("active_count") or 0
    if act_v:
        alerts.append(
            {
                "severity": "low",
                "kind": "volcano",
                "text": f"{act_v} volcanoes with recent/observed activity (Smithsonian GVP).",
            }
        )

    cve_items = (snap.get("cve", {}) or {}).get("vulnerabilities", [])[:5]
    for v in cve_items:
        sev = "high" if v.get("ransomware") == "Known" else "medium"
        alerts.append(
            {
                "severity": sev,
                "kind": "cve",
                "text": f"KEV {v.get('cve_id')}: {v.get('vendor')} {v.get('product')}",
            }
        )

    nodes = (snap.get("nodes", {}) or {}).get("nodes", [])
    for n in nodes:
        disk = (n.get("health") or {}).get("disk_pct")
        if disk is not None and disk >= 85:
            alerts.append(
                {
                    "severity": "critical" if disk >= 92 else "warning",
                    "kind": "disk_space",
                    "text": f"{n.get('name', n.get('node_id'))}: root disk {disk}% full — run pi-disk-maintenance.sh on Pi",
                    "lat": n.get("lat"),
                    "lon": n.get("lon"),
                }
            )
    offline = [n for n in nodes if not n.get("online")]
    for n in offline[:2]:
        alerts.append(
            {
                "severity": "medium",
                "kind": "node_offline",
                "text": f"Edge node {n.get('name', n.get('node_id'))} offline ({int(n.get('age_seconds') or 0)}s stale).",
                "lat": n.get("lat"),
                "lon": n.get("lon"),
            }
        )

    return alerts


# ---------------------------------------------------------------------------
# PC -> Pi : LLM situation briefing
# ---------------------------------------------------------------------------
async def _ollama_briefing(prompt: str) -> str:
    """Single-shot briefing via local Ollama — capped tokens, no Qwen3 thinking."""
    options: dict = {"num_predict": 420, "temperature": 0.35}
    try:
        from ollama_config import context_length_for

        ctx = context_length_for(OLLAMA_MODEL)
        if ctx is not None:
            options["num_ctx"] = ctx
    except Exception:
        pass
    body: dict = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": __import__("ollama_config").keep_alive(),
        "options": options,
    }
    if "qwen3" in OLLAMA_MODEL.lower():
        body["think"] = False
    for host in OLLAMA_HOSTS:
        host = host.strip()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"http://{host}/api/chat", json=body)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return ""


@router.post("/briefing/generate")
@rate_limit_general()
async def generate_briefing(
    request: Request,
    lang: str | None = None,
    api_key: str = Depends(verify_api_key),
):
    """Fuse all feeds and have the local LLM write a world-situation report.

    Optional ``lang`` query parameter (``en`` or ``de``) overrides the
    ``WORLDBASE_BRIEFING_LANG`` env default for this request only. Result is
    stored in SQLite; the Pi pulls it via /api/node/pull for offline display.
    Open on the LAN — local Ollama only; destructive node commands stay admin-gated.
    Set ``force=1`` to bypass the snapshot cache (default uses TTL cache).
    """
    force_snap = request.query_params.get("force", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return await generate_briefing_internal(lang=lang, force_snapshot=force_snap)


async def generate_briefing_internal(
    lang: str | None = None, *, force_snapshot: bool = False
):
    """Actual briefing generation logic (no auth). Used by route + autopilot."""
    async with _BRIEFING_LOCK:
        return await _generate_briefing_unlocked(
            lang=lang, force_snapshot=force_snapshot
        )


async def _generate_briefing_unlocked(
    lang: str | None = None, *, force_snapshot: bool = False
):
    import fusion_heatmap
    import intel_briefing
    from operator_briefing import (
        build_security_advisor_prompt,
        format_digest_sections,
        format_fallback_protocol,
    )

    snap = await _gather_snapshot(force=force_snapshot)
    alerts = _compile_alerts(snap)
    (
        fusion_hotspots,
        fusion_lines,
        fusion_deltas,
    ) = await fusion_heatmap.top_hotspots_for_llm(top=3)
    intel_meta = await asyncio.to_thread(intel_briefing.gather_for_briefing)

    darkweb_digest: dict = {"enabled": False, "count": 0, "lines": []}
    ransomware_digest: dict = {"enabled": False, "count": 0, "lines": []}
    telegram_digest: dict = {"enabled": False, "count": 0, "lines": []}
    maritime_anomaly_digest: dict = {"enabled": False, "count": 0, "lines": []}
    spaceweather_digest: dict = {"enabled": False, "count": 0, "lines": []}
    identity_digest: dict = {"enabled": False, "count": 0, "lines": []}
    try:
        import darkweb_bridge

        darkweb_digest = await darkweb_bridge.gather_darkweb_digest()
    except Exception:
        pass
    try:
        from darkweb_briefing import gather_ransomware_briefing

        ransomware_digest = await gather_ransomware_briefing()
    except Exception:
        pass
    try:
        from telegram_briefing import gather_telegram_briefing

        telegram_digest = await gather_telegram_briefing()
    except Exception:
        pass
    try:
        from maritime_briefing import gather_maritime_anomaly_digest

        maritime_anomaly_digest = await gather_maritime_anomaly_digest()
    except Exception:
        pass
    try:
        from spaceweather_briefing import gather_spaceweather_digest

        spaceweather_digest = gather_spaceweather_digest(snap)
    except Exception:
        pass

    if ransomware_digest:
        snap["ransomware_digest"] = ransomware_digest
    if telegram_digest:
        snap["telegram_digest"] = telegram_digest
    if maritime_anomaly_digest:
        snap["maritime_anomaly_digest"] = maritime_anomaly_digest
    if spaceweather_digest:
        snap["spaceweather_digest"] = spaceweather_digest
    try:
        from identity_osint import gather_identity_digest

        identity_digest = await gather_identity_digest()
    except Exception:
        pass
    if identity_digest:
        snap["identity_digest"] = identity_digest
    digest = format_digest_sections(
        snap,
        alerts,
        fusion_lines,
        fusion_hotspots,
        fusion_deltas=fusion_deltas,
        intel_meta=intel_meta,
        lang=lang,
        darkweb_digest=darkweb_digest,
        ransomware_digest=ransomware_digest,
        telegram_digest=telegram_digest,
        maritime_anomaly_digest=maritime_anomaly_digest,
        spaceweather_digest=spaceweather_digest,
        identity_digest=identity_digest,
    )
    from briefing_agentic import run_briefing_agentic_loop

    digest, agentic_meta = await run_briefing_agentic_loop(digest, snap=snap)

    insight_list: list = []
    try:
        import insights as insights_mod

        insight_payload = await insights_mod.build_insights(top=10, narrate=False)
        insight_list = insight_payload.get("insights") or []
    except Exception:
        insights_mod = None

    prompt = build_security_advisor_prompt(digest, lang=lang)
    if insights_mod and insight_list:
        ins_block = insights_mod.format_insights_prompt_block(insight_list)
        if ins_block:
            prompt = f"{prompt}\n\n{ins_block}"
    text = await _ollama_briefing(prompt)
    if not text:
        text = format_fallback_protocol(digest, lang=lang)

    now = datetime.now(timezone.utc).isoformat()
    intel_src = digest.get("intel") or {}
    from briefing_quality import gdelt_digest_pipeline_meta

    gdelt_meta = _gdelt_snapshot_meta(snap)
    gdelt_meta.update(gdelt_digest_pipeline_meta(snap, digest))
    sources_payload = {
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "intel": {
            "enabled": intel_src.get("enabled"),
            "count": intel_src.get("count", 0),
            "by_bucket": intel_src.get("by_bucket") or {},
            "window_hours": intel_src.get("window_hours"),
            "entities": intel_src.get("entities") or [],
            "prompt_metrics": intel_src.get("prompt_metrics") or {},
        },
        "digest": {
            "region": digest.get("region"),
            "region_label": digest.get("region_label"),
            "window": digest.get("window"),
            "lang": digest.get("lang"),
            "local_count": len(digest.get("local") or []),
            "regional_count": len(digest.get("regional") or []),
            "global_count": len(digest.get("global") or []),
            "intel_count": intel_src.get("count", 0),
            "maritime": digest.get("maritime")
            or {"enabled": False, "count": 0, "lines": []},
            "spaceweather": digest.get("spaceweather")
            or {"enabled": False, "count": 0, "lines": []},
        },
        "_digest_sections": {
            "local": digest.get("local") or [],
            "regional": digest.get("regional") or [],
            "global": digest.get("global") or [],
        },
        "gdelt": gdelt_meta,
        "style": "security_advisor_24h",
        "watch_items": digest.get("watch_items") or [],
        "digest_line_meta": digest.get("digest_line_meta") or [],
        "agentic": agentic_meta,
        "insights": insights_mod.slim_insights(insight_list) if insights_mod else [],
    }
    from briefing_quality import attach_quality_to_sources

    sources_payload = attach_quality_to_sources(
        sources_payload, text=text, created_at=now
    )
    with _db() as conn:
        conn.execute(
            "INSERT INTO briefings (created_at, text, sources) VALUES (?,?,?)",
            (now, text, json.dumps(sources_payload)),
        )
        conn.commit()
    try:
        import rag_memory

        await rag_memory.ingest_briefing(text, now)
    except Exception:
        pass
    try:
        import prediction_ledger

        if prediction_ledger.autopilot_on():
            await asyncio.to_thread(
                prediction_ledger.record_watch_items,
                digest.get("watch_items") or [],
                now,
            )
    except Exception:
        pass
    try:
        import intel_graph_export

        if intel_graph_export.enabled():
            await asyncio.to_thread(intel_graph_export.export_operator_subgraph)
    except Exception:
        pass
    return {
        "created_at": now,
        "text": text,
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "digest": sources_payload.get("digest"),
        "quality": sources_payload.get("quality"),
        "watch_items": digest.get("watch_items") or [],
        "digest_line_meta": digest.get("digest_line_meta")
        or sources_payload.get("digest_line_meta")
        or [],
        "agentic": agentic_meta,
        "insights": sources_payload.get("insights") or [],
    }


@router.get("/briefing")
async def latest_briefing(_auth: str | None = Depends(verify_lan_auth)):
    """Latest stored situation briefing."""
    with _db() as conn:
        row = conn.execute(
            "SELECT created_at, text, sources FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {
            "created_at": None,
            "text": "No briefing yet. POST /api/briefing/generate.",
            "alerts": [],
        }
    sources = {}
    try:
        sources = json.loads(row["sources"]) if row["sources"] else {}
    except Exception:
        pass
    quality = sources.get("quality")
    if not quality and row["text"]:
        try:
            from briefing_quality import score_briefing

            quality = score_briefing(
                text=row["text"],
                sources=sources,
                created_at=row["created_at"],
            )
        except Exception:
            quality = None
    try:
        import prediction_ledger

        quality = prediction_ledger.enrich_quality_meta(quality)
    except Exception:
        pass
    from operator_briefing import enrich_watch_items_coords

    watch_items = enrich_watch_items_coords(sources.get("watch_items") or [])
    return {
        "created_at": row["created_at"],
        "text": row["text"],
        "alerts": sources.get("alerts", []),
        "fusion_hotspots": sources.get("fusion_hotspots", []),
        "intel": sources.get("intel"),
        "digest": sources.get("digest"),
        "quality": quality,
        "style": sources.get("style"),
        "watch_items": watch_items,
        "digest_line_meta": sources.get("digest_line_meta") or [],
        "agentic": sources.get("agentic"),
        "insights": sources.get("insights") or [],
    }


@router.get("/briefing/export")
async def export_briefing(
    format: str = Query("pdf", regex="^(pdf|docx|pptx)$"),
    _auth: str | None = Depends(verify_lan_auth),
):
    """Export the latest briefing as a downloadable PDF or DOCX document."""
    with _db() as conn:
        row = conn.execute(
            "SELECT created_at, text, sources FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return JSONResponse(
            status_code=404,
            content={
                "error": "No briefing available. POST /api/briefing/generate first."
            },
        )
    import doc_export

    briefing = doc_export._briefing_from_db_row(row)
    if format == "pdf":
        data = doc_export.briefing_to_pdf(briefing)
        return Response(
            content=data,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="worldbase-briefing-{briefing["created_at"][:10] if briefing["created_at"] else "latest"}.pdf"',
            },
        )
    elif format == "docx":
        data = doc_export.briefing_to_docx(briefing)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="worldbase-briefing-{briefing["created_at"][:10] if briefing["created_at"] else "latest"}.docx"',
            },
        )
    elif format == "pptx":
        data = doc_export.briefing_to_pptx(briefing)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Content-Disposition": f'attachment; filename="worldbase-briefing-{briefing["created_at"][:10] if briefing["created_at"] else "latest"}.pptx"',
            },
        )


@router.get("/predictions")
async def predictions_status(
    pending_limit: int = Query(8, ge=1, le=50),
    resolved_limit: int = Query(5, ge=1, le=30),
):
    """Track 4 — pending watch outcomes and recent resolved samples."""
    import prediction_ledger

    if not prediction_ledger.autopilot_on():
        return {
            "enabled": False,
            "stats": {},
            "pending": [],
            "resolved_recent": [],
            "overdue_count": 0,
            "due_next": None,
        }
    out = prediction_ledger.list_predictions(
        pending_limit=pending_limit,
        resolved_limit=resolved_limit,
    )
    out["enabled"] = True
    return out


def _compress_briefing(text: str, alerts: list) -> str:
    """Shrink briefing to <230 bytes for Meshtastic/LoRa TX.
    Format: [SEV]alert1|[SEV]alert2|...|brief_snippet
    """
    parts = []
    for a in alerts[:3]:
        sev = a.get("severity", "low")[0].upper()
        txt = a.get("text", "")[:40]
        parts.append(f"[{sev}]{txt}")
    alert_str = "|".join(parts)
    remaining = 230 - len(alert_str) - 2
    brief_snippet = text[: max(remaining, 60)] if remaining > 0 else ""
    return f"{alert_str}|{brief_snippet}" if brief_snippet else alert_str


def _pull_payload_digest(payload: dict) -> str:
    """SHA-256 of canonical JSON — excludes volatile keys and content_sha256."""
    skip = frozenset({"content_sha256", "generated_at"})
    base = {k: v for k, v in payload.items() if k not in skip}
    canonical = json.dumps(
        base, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _briefing_hash(text: str | None) -> str:
    """SHA-256 of briefing text — used for briefing diff (X-Briefing-Hash)."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _node_pull_delta_enabled() -> bool:
    """Check if delta sync is enabled via config or env."""
    try:
        from config import get_config

        return get_config().node_pull_delta
    except Exception:
        return os.getenv("WORLDBASE_NODE_PULL_DELTA", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }


@router.get("/node/pull")
@rate_limit_node_pull()
async def node_pull(
    request: Request,
    mesh: bool = False,
    since: str | None = Query(
        default=None, description="ISO 8601 timestamp for delta sync"
    ),
    x_node_token: str = Header(default=""),
):
    """Single payload the Pi pulls: latest briefing + live critical alerts.

    Designed so the off-grid portal can show global situational awareness even
    when the Pi itself has no upstream internet — the PC did the heavy lifting.
    Set ?mesh=1 for a <230 byte payload suitable for Meshtatic/LoRa relay.

    When NODE_INGEST_TOKEN is set, send the same value as header X-Node-Token.

    **I8 Delta Sync (v3):** When ``?since=<ISO8601>`` is provided and delta
    sync is enabled, the response uses ``payload_version: 3`` with:
    - Briefing diff: if briefing text unchanged (SHA-256 match with
      ``X-Briefing-Hash`` header), response body is ``{"briefing_unchanged": true}``
    - Intel delta: only entities/edges with ``last_seen``/``seen_at`` after
      ``since`` are included in ``intel_delta`` (instead of full ``intel_subgraph``)
    - Full refresh forced when ``since`` > 7d old or missing
    """
    _verify_node_secret(x_node_token)
    brief = await latest_briefing()
    alerts = brief.get("alerts") or []
    fusion_hotspots = brief.get("fusion_hotspots") or []

    if mesh:
        compressed = _compress_briefing(brief.get("text", ""), alerts)
        return {
            "t": datetime.now(timezone.utc).strftime("%H:%M"),
            "b": compressed,
            "a": len(alerts),
            "s": len(compressed),
        }

    briefing_text = brief.get("text")
    b_hash = _briefing_hash(briefing_text)
    delta_enabled = _node_pull_delta_enabled()
    use_delta = bool(since) and delta_enabled

    # --- Briefing diff: check if client already has this briefing ---
    client_briefing_hash = request.headers.get("x-briefing-hash", "").strip()
    if use_delta and client_briefing_hash and client_briefing_hash == b_hash:
        # Briefing unchanged — send minimal payload with intel delta only
        payload: dict = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "worldbase-pc",
            "payload_version": 3,
            "briefing_unchanged": True,
            "briefing_at": brief.get("created_at"),
            "briefing_hash": b_hash,
            "since": since,
        }
        try:
            import intel_graph_export

            if intel_graph_export.enabled():
                payload["intel_delta"] = await asyncio.to_thread(
                    intel_graph_export.compact_delta_for_pull, since
                )
        except Exception:
            payload["intel_delta"] = {"available": False}
        digest = _pull_payload_digest(payload)
        payload["content_sha256"] = digest

        inm = request.headers.get("if-none-match", "").strip().strip('"')
        if inm and inm == digest:
            return Response(
                status_code=304,
                headers={"ETag": f'"{digest}"', "X-Content-SHA256": digest},
            )
        return JSONResponse(
            payload,
            headers={
                "ETag": f'"{digest}"',
                "X-Content-SHA256": digest,
                "X-Briefing-Hash": b_hash,
            },
        )

    # --- Full or delta payload with briefing text ---
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "worldbase-pc",
        "payload_version": 3 if use_delta else 2,
        "briefing": briefing_text,
        "briefing_at": brief.get("created_at"),
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "quality": brief.get("quality"),
        "digest": brief.get("digest"),
        "watch_items": brief.get("watch_items") or [],
        "insights": brief.get("insights") or [],
    }
    if use_delta:
        payload["briefing_hash"] = b_hash
        payload["since"] = since

    try:
        import intel_graph_export

        if intel_graph_export.enabled():
            if use_delta:
                payload["intel_delta"] = await asyncio.to_thread(
                    intel_graph_export.compact_delta_for_pull, since
                )
            else:
                payload["intel_subgraph"] = await asyncio.to_thread(
                    intel_graph_export.compact_for_pull
                )
    except Exception:
        if use_delta:
            payload["intel_delta"] = {"available": False}
        else:
            payload["intel_subgraph"] = {"available": False}

    digest = _pull_payload_digest(payload)
    payload["content_sha256"] = digest

    inm = request.headers.get("if-none-match", "").strip().strip('"')
    if inm and inm == digest:
        return Response(
            status_code=304, headers={"ETag": f'"{digest}"', "X-Content-SHA256": digest}
        )

    return JSONResponse(
        payload,
        headers={
            "ETag": f'"{digest}"',
            "X-Content-SHA256": digest,
            **({"X-Briefing-Hash": b_hash} if use_delta else {}),
        },
    )


@router.get("/node/pull/mesh")
@rate_limit_node_pull()
async def node_pull_mesh(request: Request, x_node_token: str = Header(default="")):
    """Dedicated endpoint: always returns compressed <230 byte briefing for LoRa."""
    return await node_pull(request=request, mesh=True, x_node_token=x_node_token)
