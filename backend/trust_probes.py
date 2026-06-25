"""Synthetic trust probes — aggregate field-ops readiness (score 0–4)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import httpx

_OLLAMA = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not _OLLAMA.startswith(("http://", "https://")):
    _OLLAMA = f"http://{_OLLAMA}"
_BRIEFING_MAX_AGE_H = float(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "21600")) / 3600.0
_GDELT_MAX_AGE_H = float(os.getenv("WORLDBASE_TRUST_GDELT_MAX_AGE_H", "4"))
_PI_MAX_AGE_S = int(os.getenv("WORLDBASE_TRUST_PI_MAX_AGE_S", "600"))


def _probe_result(name: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, **extra}


async def probe_briefing_fresh() -> dict[str, Any]:
    from node_sync import latest_briefing

    brief = await latest_briefing()
    created = brief.get("created_at")
    if not created:
        return _probe_result("briefing_fresh", False, "no briefing stored")
    try:
        ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    except Exception as exc:
        return _probe_result("briefing_fresh", False, f"bad timestamp: {exc}")
    ok = age_h <= _BRIEFING_MAX_AGE_H
    q = (brief.get("quality") or {}).get("score")
    return _probe_result(
        "briefing_fresh",
        ok,
        f"age {age_h:.1f}h (max {_BRIEFING_MAX_AGE_H:.1f}h)",
        age_hours=round(age_h, 2),
        quality_score=q,
    )


async def probe_gdelt_local() -> dict[str, Any]:
    try:
        import gdelt_bridge

        data = await gdelt_bridge.gdelt_pulse_local_data(refresh=False)
    except Exception as exc:
        return _probe_result("gdelt_local", False, str(exc)[:120])
    count = int(data.get("count") or 0)
    stale = bool(data.get("stale"))
    err = data.get("error")
    # Cached local pulse during GDELT backoff / SWR still counts as operational.
    ok = count > 0
    detail = f"count={count}"
    if err:
        detail += f" error={str(err)[:80]}"
    if stale:
        detail += " stale=true"
    return _probe_result("gdelt_local", ok, detail, count=count, stale=stale)


async def probe_ollama() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_OLLAMA}/api/tags")
            if r.status_code != 200:
                return _probe_result("ollama", False, f"HTTP {r.status_code}")
            models = r.json().get("models") or []
            if not models:
                return _probe_result("ollama", False, "no models")
            return _probe_result("ollama", True, f"{len(models)} model(s)")
    except Exception as exc:
        return _probe_result("ollama", False, str(exc)[:120])


async def probe_pi_edge() -> dict[str, Any]:
    try:
        from node_sync import list_nodes

        data = await list_nodes()
        nodes = data.get("nodes") or []
        pi = next((n for n in nodes if n.get("node_id") == "offgrid-pi"), None)
        if not pi:
            pi = nodes[0] if len(nodes) == 1 else None
        if not pi:
            return _probe_result("pi_edge", False, "no nodes registered")
        online = bool(pi.get("online"))
        age = pi.get("age_seconds")
        ok = online and age is not None and int(age) <= _PI_MAX_AGE_S
        return _probe_result(
            "pi_edge",
            ok,
            f"{pi.get('node_id')} online={online} age={age}s",
            node_id=pi.get("node_id"),
            online=online,
            age_seconds=age,
        )
    except Exception as exc:
        return _probe_result("pi_edge", False, str(exc)[:120])


async def run_trust_probes() -> dict[str, Any]:
    briefing, gdelt, ollama, pi = await asyncio.gather(
        probe_briefing_fresh(),
        probe_gdelt_local(),
        probe_ollama(),
        probe_pi_edge(),
    )
    probes = [briefing, gdelt, ollama, pi]
    score = sum(1 for p in probes if p.get("ok"))
    status = "ok" if score >= 3 else ("warn" if score >= 2 else "critical")
    failed_probes = [p["name"] for p in probes if not p.get("ok")]

    feed_drift: dict[str, Any] = {
        "ok": True,
        "detail": "skipped",
        "drifting": [],
        "freshness": [],
        "degradation": {},
    }
    try:
        import feed_drift as _feed_drift

        feed_drift = await asyncio.to_thread(_feed_drift.check_feed_drift)
    except Exception as exc:
        feed_drift = {
            "ok": False,
            "detail": str(exc)[:120],
            "drifting": [],
            "freshness": [],
        }

    briefing_pipeline: dict[str, Any] = {}
    try:
        from node_sync import latest_briefing

        brief = await latest_briefing()
        meta = (brief.get("quality") or {}).get("meta") or {}
        briefing_pipeline = {
            "gdelt_collected": meta.get("gdelt_collected"),
            "gdelt_digest_lines": meta.get("gdelt_digest_lines"),
            "pipeline_ok": meta.get("gdelt_pipeline_ok"),
            "pipeline_placed_ok": meta.get("gdelt_pipeline_placed_ok"),
            "pipeline_blocker": meta.get("gdelt_pipeline_blocker")
            or meta.get("corroboration_blocker"),
            "pipeline_yield": meta.get("gdelt_pipeline_yield"),
            "watch_count": meta.get("watch_count"),
            "corroboration_avg_local": meta.get("corroboration_avg_local"),
            "corroboration_blocker": meta.get("corroboration_blocker"),
            "prediction_accuracy_30d": meta.get("prediction_accuracy_30d"),
            "prediction_sample_30d": meta.get("prediction_sample_30d"),
            "prediction_pending": meta.get("prediction_pending"),
        }
    except Exception:
        pass

    fusion_compare: dict[str, Any] = {"available": False, "detail": "skipped"}
    try:
        import fusion_heatmap as _fusion

        fusion_compare = await asyncio.to_thread(
            _fusion.fusion_compare_summary, 2.0, 24.0
        )
    except Exception as exc:
        fusion_compare = {"available": False, "detail": str(exc)[:120]}

    degradation = feed_drift.get("degradation") or {}
    field_warn = score < 2
    feed_warn = bool(degradation.get("warn"))

    mapping_drift: dict[str, Any] = {"ok": True, "statuses": {}, "detail": "skipped"}
    try:
        import mapping_validator as _mv
        mapping_drift = {
            "ok": True,
            "statuses": await asyncio.to_thread(_mv.get_mapping_drift_status),
            "detail": "ok",
        }
        if any(v == "error" for v in mapping_drift["statuses"].values()):
            mapping_drift["ok"] = False
            mapping_drift["detail"] = "mapping validation error"
    except Exception as exc:
        mapping_drift = {"ok": False, "statuses": {}, "detail": str(exc)[:120]}

    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "max_score": 4,
        "status": status,
        "probes": probes,
        "failed_probes": failed_probes,
        "field_warn": field_warn,
        "feed_warn": feed_warn,
        "degraded": field_warn or feed_warn,
        "feed_drift": feed_drift,
        "mapping_drift": mapping_drift,
        "fusion_compare": fusion_compare,
        "briefing_pipeline": briefing_pipeline,
    }
