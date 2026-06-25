"""Background autopilot loops and FastAPI startup/shutdown hooks.

Extracted from main.py (Phase 1 decortication). Schedules briefing, RAG, trails,
stack warmups, AISstream collector, and aircraft cache refresh.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import aircraft_trails
import anomaly_river
import entity_resolution
import entity_store
import feed_ingest
import ftm_store
import fusion_heatmap
import node_sync
import rag_memory
import sanctions_bridge
import situations
import stac_bridge
from config import get_config as _cfg
from sqlite_bootstrap import init_db, prune_feed_cache
from routes import aircraft as aircraft_routes
from structured_log import get_logger

log = get_logger(__name__)

_BRIEFING_AUTOPILOT_TASK: asyncio.Task | None = None
_BRIEFING_INTERVAL = _cfg().briefing_interval


async def _phase1_background_tasks() -> None:
    """River anomaly scan + GDELT/RAG indexing (best-effort, no crash on missing Ollama)."""
    from ollama_config import rag_autopilot_on

    await asyncio.sleep(90)
    while True:
        try:
            await anomaly_river.scan_feeds()
        except Exception as e:
            log.warning("river_scan_failed", error=str(e))
        if rag_autopilot_on():
            try:
                news = await rag_memory.ingest_news_sources()
                log.info("rag_news_indexed", chunks=news.get('indexed', 0))
                await rag_memory.ingest_hazards()
                await rag_memory.ingest_situations()
                await rag_memory.ingest_volcanoes()
                watches = await rag_memory.ingest_prediction_watches()
                if watches.get("indexed"):
                    log.info("rag_watches_indexed", indexed=watches.get('indexed'))
            except Exception as e:
                log.warning("rag_index_failed", error=str(e))
        try:
            items = await stac_bridge.fetch_recent_thailand_items(limit=6)
            await rag_memory.ingest_stac_items(items)
        except Exception as e:
            log.warning("stac_ingest_failed", error=str(e))
        try:
            screen = await sanctions_bridge.sanctions_screen_vessels(min_score=0.85, limit=200)
            hits = [m.get("sanction") for m in (screen.get("matches") or []) if m.get("sanction")]
            if hits:
                await rag_memory.ingest_sanctions_hits(hits)
        except Exception as e:
            log.warning("sanctions_ingest_failed", error=str(e))
        if feed_ingest.autopilot_on():
            try:
                result = await feed_ingest.run_feed_ingest()
                t = result.get("totals") or {}
                log.info("feed_ingest_done", entities=t.get('entities', 0), records=t.get('records', 0))
            except Exception as e:
                log.warning("feed_ingest_failed", error=str(e))
        await asyncio.sleep(600)


async def _aircraft_trail_loop() -> None:
    await asyncio.sleep(45)
    while True:
        try:
            await aircraft_trails.snapshot_now()
        except Exception as e:
            log.warning("aircraft_snapshot_failed", error=str(e))
        await asyncio.sleep(30)


async def _situations_prewarm() -> None:
    await asyncio.sleep(20)
    try:
        await anomaly_river.scan_feeds()
    except Exception:
        pass
    try:
        await situations.unified_situations()
    except Exception:
        pass
    try:
        await fusion_heatmap.fusion_heatmap(cell_deg=2.0, top=60, include_geojson=0)
    except Exception:
        pass


async def _stack_warmup() -> None:
    """Warm operator-critical feeds after boot (GDELT local, maritime, traffic, haze)."""
    await asyncio.sleep(6)
    try:
        import gdelt_bridge

        out = await gdelt_bridge.warmup_local_pulse()
        n = int((out or {}).get("count") or 0)
        log.info("warmup_gdelt_local", articles=n)
        await asyncio.sleep(gdelt_bridge._GDELT_MIN_INTERVAL + 1.0)
        out = await gdelt_bridge.warmup_global_pulse()
        n = int((out or {}).get("count") or 0)
        log.info("warmup_gdelt_global", articles=n)
    except Exception as e:
        log.warning("warmup_gdelt_failed", error=str(e))
    try:
        from traffic_bridge import warm_traffic_cams

        await warm_traffic_cams(force=True)
        log.info("warmup_traffic_cams")
    except Exception as e:
        log.warning("warmup_traffic_cams_failed", error=str(e))
    try:
        import ais_bridge

        m = await ais_bridge.warm_maritime()
        if m:
            log.info("warmup_maritime", vessels=m.get('count'))
    except Exception as e:
        log.warning("warmup_maritime_failed", error=str(e))
    try:
        import cams_bridge

        h = await cams_bridge.get_haze(refresh=True)
        log.info("warmup_cams_haze", cities=h.get('count'))
    except Exception as e:
        log.warning("warmup_cams_haze_failed", error=str(e))
    try:
        from feeds_extra import air_quality

        await air_quality()
        log.info("warmup_air_quality")
    except Exception as e:
        log.warning("warmup_air_quality_failed", error=str(e))
    try:
        import feed_registry
        from windy_bridge import fetch_point_weather

        pt = await fetch_point_weather(13.75, 100.5)
        if pt.get("current"):
            feed_registry.write_auto("weather:13.75:100.5", pt)
            log.info("warmup_weather", source=pt.get('source'))
    except Exception as e:
        log.warning("warmup_weather_failed", error=str(e))
    try:
        snap = await node_sync.warm_snapshot_cache()
        n = sum(1 for k in snap if snap.get(k))
        log.info("warmup_snapshot_cache", feeds=n)
    except Exception as e:
        log.warning("warmup_snapshot_cache_failed", error=str(e))


async def _entity_resolution_autopilot() -> None:
    await asyncio.sleep(120)
    interval = _cfg().entity_resolution_interval
    while True:
        try:
            result = await asyncio.to_thread(entity_resolution.run_resolution)
            log.info(
                "entity_resolution_done",
                edges_added=result.get('edges_added', 0),
                exact_edges=result.get('exact_edges', 0),
                splink_edges=result.get('splink_edges', 0),
            )
        except Exception as e:
            log.warning("entity_resolution_failed", error=str(e))
        await asyncio.sleep(interval)


async def _prediction_ledger_autopilot() -> None:
    await asyncio.sleep(180)
    import prediction_ledger

    while True:
        try:
            snap = await node_sync.warm_snapshot_cache()
            fusion_cells: list[dict] = []
            try:
                grid = await fusion_heatmap.fusion_heatmap(cell_deg=2.0, top=60, include_geojson=0)
                fusion_cells = list(grid.get("cells") or [])
            except Exception:
                fusion_cells = []
            result = await asyncio.to_thread(
                prediction_ledger.resolve_pending,
                snap,
                fusion_cells,
            )
            if result.get("resolved"):
                stats = prediction_ledger.accuracy_30d()
                log.info(
                    "prediction_ledger_resolved",
                    resolved=result.get('resolved'),
                    hits=result.get('hits'),
                    misses=result.get('misses'),
                    accuracy_30d=stats.get('accuracy'),
                    sample_size=stats.get('sample_size'),
                )
        except Exception as e:
            log.warning("prediction_ledger_failed", error=str(e))
        await asyncio.sleep(prediction_ledger.resolve_interval_s())


async def _feed_cache_autopilot() -> None:
    """Keep feed_cache.cached_at fresh for background-collected feeds (no HTTP poll required)."""
    await asyncio.sleep(45)
    maritime_interval = float(os.getenv("WORLDBASE_MARITIME_TOUCH_INTERVAL_S", "30"))
    gdelt_interval = float(os.getenv("WORLDBASE_GDELT_TOUCH_INTERVAL_S", "600"))
    airquality_interval = float(os.getenv("WORLDBASE_AIRQUALITY_TOUCH_INTERVAL_S", "2700"))
    next_gdelt = 0.0
    next_airquality = 0.0
    while True:
        now = asyncio.get_event_loop().time()
        try:
            import ais_bridge

            if await ais_bridge.touch_maritime_cache():
                pass  # best-effort; silence when buffer empty
        except Exception as e:
            log.warning("maritime_cache_touch_failed", error=str(e))
        if now >= next_gdelt:
            next_gdelt = now + gdelt_interval
            try:
                import gdelt_bridge

                await gdelt_bridge.touch_local_pulse_cache()
            except Exception as e:
                log.warning("gdelt_touch_failed", error=str(e))
        if now >= next_airquality:
            next_airquality = now + airquality_interval
            try:
                from feeds_extra import air_quality

                await air_quality()
            except Exception as e:
                log.warning("air_quality_touch_failed", error=str(e))
        await asyncio.sleep(maritime_interval)


async def _briefing_autopilot() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await node_sync.generate_briefing_internal()
            log.info("briefing_generated", ts=datetime.now(timezone.utc).isoformat())
        except Exception as e:
            log.warning("briefing_generation_failed", error=str(e))
        await asyncio.sleep(_BRIEFING_INTERVAL)


def register_lifecycle(app) -> None:
    """Attach startup/shutdown handlers to the FastAPI app."""

    @app.on_event("startup")
    def on_startup() -> None:
        global _BRIEFING_AUTOPILOT_TASK
        init_db()
        prune_feed_cache()
        entity_store.init_entity_db()
        if not ftm_store.init_store():
            log.error("ftm_store_offline", detail="DuckDB locked or missing")
        node_sync.init_node_db()
        node_sync.init_command_db()
        anomaly_river.init_river_db()
        rag_memory.init_memory_db()
        import feed_drift

        feed_drift.init_drift_db()
        import prediction_ledger

        prediction_ledger.init_prediction_db()
        aircraft_trails.init_trail_db()
        from ollama_config import briefing_autopilot_on

        if briefing_autopilot_on():
            _BRIEFING_AUTOPILOT_TASK = asyncio.create_task(_briefing_autopilot())
        else:
            log.info("briefing_autopilot_disabled")
        if entity_resolution.autopilot_on():
            asyncio.create_task(_entity_resolution_autopilot())
        else:
            log.info("entity_resolution_autopilot_disabled")
        import prediction_ledger

        if prediction_ledger.autopilot_on():
            asyncio.create_task(_prediction_ledger_autopilot())
        else:
            log.info("prediction_ledger_disabled")
        asyncio.create_task(aircraft_routes.aircraft_warmup())
        asyncio.create_task(_phase1_background_tasks())
        asyncio.create_task(_aircraft_trail_loop())
        asyncio.create_task(_situations_prewarm())
        asyncio.create_task(_stack_warmup())
        asyncio.create_task(_feed_cache_autopilot())
        import ais_bridge

        ais_bridge.start_aisstream_collector()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        if _BRIEFING_AUTOPILOT_TASK:
            _BRIEFING_AUTOPILOT_TASK.cancel()
        import ais_bridge

        ais_bridge.stop_aisstream_collector()
