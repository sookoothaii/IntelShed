"""V4-45 Bootstrap Hydration Endpoint — aggregated frontend data in 2 tiers.

Reduces Time-to-Interactive by replacing 20+ individual endpoint polls on
page load with 2 parallel bootstrap fetches (fast + slow), then switching
to individual SmartPollLoop for updates.

Each sub-section fails independently — one feed down doesn't break bootstrap.
Negative caching: ``__WM_NEG__`` sentinel for missing data.

Feature flag: ``WORLDBASE_BOOTSTRAP=0`` (default off, opt-in).

Endpoints:
    GET /api/bootstrap?tier=fast  — critical real-time data (TTL 1200s)
    GET /api/bootstrap?tier=slow  — less time-sensitive data (TTL 7200s)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api", tags=["bootstrap"])
logger = logging.getLogger("worldbase.bootstrap")

NEG = "__WM_NEG__"
_FAST_TTL = 1200  # 20 min
_SLOW_TTL = 7200  # 2 hours

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def bootstrap_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_BOOTSTRAP", "0"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Individual data gatherers — each fail-soft
# ---------------------------------------------------------------------------


async def _gather_briefing() -> dict[str, Any]:
    try:
        import node_sync

        brief = await node_sync.latest_briefing()
        return {
            "created_at": brief.get("created_at"),
            "style": brief.get("style"),
            "alert_count": len(brief.get("alerts") or []),
            "fusion_hotspot_count": len(brief.get("fusion_hotspots") or []),
            "digest": brief.get("digest") or {},
            "insights": brief.get("insights") or [],
            "watch_items": brief.get("watch_items") or [],
            "quality": brief.get("quality"),
            "text_preview": (brief.get("text") or "")[:500],
        }
    except Exception as exc:
        logger.warning(f"bootstrap briefing failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_fusion_hotspots() -> dict[str, Any]:
    try:
        import fusion_heatmap

        hotspots, summary, _ = await fusion_heatmap.top_hotspots_for_llm(top=10)
        return {"hotspots": hotspots, "summary": summary}
    except Exception as exc:
        logger.warning(f"bootstrap fusion_hotspots failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_feed_status() -> dict[str, Any]:
    try:
        import sqlite3

        from connector_registry import feed_ttl_sec

        db_path = os.getenv("WORLDBASE_DB_PATH", "")
        if not db_path:
            db_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
            )
        conn = sqlite3.connect(db_path, timeout=3.0)
        rows = conn.execute(
            "SELECT key, cached_at FROM feed_cache ORDER BY key"
        ).fetchall()
        conn.close()

        now = datetime.now(timezone.utc)
        fresh_n = stale_n = error_n = 0
        for key, cached_at in rows:
            try:
                age = (now - datetime.fromisoformat(cached_at)).total_seconds()
                ttl = feed_ttl_sec(key)
                if age < ttl:
                    fresh_n += 1
                else:
                    stale_n += 1
            except Exception:
                stale_n += 1
        return {
            "feed_count": len(rows),
            "feeds_fresh": fresh_n,
            "feeds_stale": stale_n,
            "feeds_error": error_n,
        }
    except Exception as exc:
        logger.warning(f"bootstrap feed_status failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_situations() -> dict[str, Any]:
    try:
        from situations import unified_situations

        result = await unified_situations()
        items = (result.get("items") or [])[:20]
        return {
            "count": result.get("count"),
            "returned": len(items),
            "items": items,
        }
    except Exception as exc:
        logger.warning(f"bootstrap situations failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_ais_snapshot() -> dict[str, Any]:
    try:
        import ais_bridge

        data = await ais_bridge.get_ais_positions(limit=500)
        positions = data.get("vessels") or data.get("positions") or []
        return {
            "count": len(positions),
            "positions": positions[:500],
        }
    except Exception as exc:
        logger.warning(f"bootstrap ais failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_anomalies() -> dict[str, Any]:
    try:
        if not _truthy(os.getenv("WORLDBASE_ANOMALY_DETECTION", "0")):
            return NEG
        import anomaly_detector

        anomalies = anomaly_detector.list_anomalies(limit=10)
        return {"anomalies": anomalies[:10], "count": len(anomalies)}
    except Exception as exc:
        logger.warning(f"bootstrap anomalies failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_ftm_stats() -> dict[str, Any]:
    try:
        import ftm_query

        return ftm_query.stats()
    except Exception as exc:
        logger.warning(f"bootstrap ftm_stats failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_gdelt_pulse() -> dict[str, Any]:
    try:
        import gdelt_bridge

        data = await gdelt_bridge.gdelt_pulse_local_data(refresh=False)
        articles = data.get("articles") or []
        return {
            "count": len(articles),
            "articles": articles[:10],
            "region": data.get("region"),
        }
    except Exception as exc:
        logger.warning(f"bootstrap gdelt_pulse failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_cams() -> dict[str, Any]:
    try:
        import cams_bridge

        data = await cams_bridge.get_haze(refresh=False)
        stations = data.get("stations") or []
        return {"count": len(stations), "stations": stations[:8]}
    except Exception as exc:
        logger.warning(f"bootstrap cams failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_earthquakes() -> dict[str, Any]:
    try:
        from routes.core_feeds import get_earthquakes

        data = await get_earthquakes(period="day", magnitude="2.5")
        quakes = data.get("earthquakes") or []
        return {"count": len(quakes), "earthquakes": quakes[:20]}
    except Exception as exc:
        logger.warning(f"bootstrap earthquakes failed: {exc}")
        return {"error": str(exc)[:200]}


async def _gather_darkweb_digest() -> dict[str, Any]:
    try:
        if not _truthy(os.getenv("WORLDBASE_DARKWEB", "0")):
            return NEG
        import darkweb_bridge

        return await darkweb_bridge.get_darkweb_digest()
    except Exception:
        return NEG


async def _gather_ransomware_digest() -> dict[str, Any]:
    try:
        if not _truthy(os.getenv("WORLDBASE_RANSOMWARE", "0")):
            return NEG
        import ransomware_tracker

        return await ransomware_tracker.get_ransomware_digest()
    except Exception:
        return NEG


async def _gather_prediction() -> dict[str, Any]:
    try:
        if not _truthy(os.getenv("WORLDBASE_PREDICTIVE", "0")):
            return NEG
        import predictive_analytics

        return await predictive_analytics.get_forecast_summary()
    except Exception:
        return NEG


# ---------------------------------------------------------------------------
# Tier assembly
# ---------------------------------------------------------------------------


async def _assemble_fast() -> dict[str, Any]:
    """Critical real-time data — s-maxage=1200, stale-while-revalidate=300."""
    results = await asyncio.gather(
        _gather_briefing(),
        _gather_fusion_hotspots(),
        _gather_feed_status(),
        _gather_situations(),
        _gather_ais_snapshot(),
        _gather_anomalies(),
        return_exceptions=True,
    )
    sections = [
        "briefing",
        "fusion_hotspots",
        "feed_status",
        "situations",
        "ais",
        "anomalies",
    ]
    out: dict[str, Any] = {
        "tier": "fast",
        "generated_at": _utc_now(),
        "ttl_sec": _FAST_TTL,
    }
    for section, result in zip(sections, results):
        if isinstance(result, Exception):
            out[section] = {"error": str(result)[:200]}
        else:
            out[section] = result
    return out


async def _assemble_slow() -> dict[str, Any]:
    """Less time-sensitive data — s-maxage=7200, stale-while-revalidate=1800."""
    results = await asyncio.gather(
        _gather_ftm_stats(),
        _gather_gdelt_pulse(),
        _gather_cams(),
        _gather_earthquakes(),
        _gather_darkweb_digest(),
        _gather_ransomware_digest(),
        _gather_prediction(),
        return_exceptions=True,
    )
    sections = [
        "ftm_stats",
        "gdelt_pulse",
        "cams",
        "earthquakes",
        "darkweb_digest",
        "ransomware_digest",
        "prediction",
    ]
    out: dict[str, Any] = {
        "tier": "slow",
        "generated_at": _utc_now(),
        "ttl_sec": _SLOW_TTL,
    }
    for section, result in zip(sections, results):
        if isinstance(result, Exception):
            out[section] = {"error": str(result)[:200]}
        else:
            out[section] = result
    return out


# ---------------------------------------------------------------------------
# Cache + endpoint
# ---------------------------------------------------------------------------


async def _get_cached_or_assemble(tier: str) -> dict[str, Any]:
    ttl = _FAST_TTL if tier == "fast" else _SLOW_TTL
    cache_key = f"bootstrap:{tier}"

    async with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < ttl:
            return cached[1]

    if tier == "fast":
        data = await _assemble_fast()
    else:
        data = await _assemble_slow()

    async with _CACHE_LOCK:
        _CACHE[cache_key] = (time.time(), data)
    return data


@router.get("/bootstrap")
async def get_bootstrap(
    tier: str = Query("fast", pattern="^(fast|slow)$"),
):
    """Aggregated bootstrap endpoint for frontend hydration.

    tier=fast: briefing, fusion hotspots, feed status, situations, AIS, anomalies
    tier=slow: FtM stats, GDELT pulse, CAMS, earthquakes, darkweb, ransomware, prediction

    Each sub-section fails independently. Cached in-memory with TTL matching s-maxage.
    """
    if not bootstrap_enabled():
        return JSONResponse(
            status_code=503,
            content={
                "error": "Bootstrap endpoint disabled (set WORLDBASE_BOOTSTRAP=1)"
            },
        )

    data = await _get_cached_or_assemble(tier)
    s_maxage = _FAST_TTL if tier == "fast" else _SLOW_TTL
    swr = 300 if tier == "fast" else 1800

    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": f"s-maxage={s_maxage}, stale-while-revalidate={swr}",
        },
    )
