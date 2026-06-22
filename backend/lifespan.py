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
from sqlite_bootstrap import init_db, prune_feed_cache
from routes import aircraft as aircraft_routes

_BRIEFING_AUTOPILOT_TASK: asyncio.Task | None = None
_BRIEFING_INTERVAL = int(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "21600"))


async def _phase1_background_tasks() -> None:
    """River anomaly scan + GDELT/RAG indexing (best-effort, no crash on missing Ollama)."""
    from ollama_config import rag_autopilot_on

    await asyncio.sleep(90)
    while True:
        try:
            await anomaly_river.scan_feeds()
        except Exception as e:
            print(f"[PHASE1] River scan failed: {e}", flush=True)
        if rag_autopilot_on():
            try:
                await rag_memory.ingest_pulse()
                await rag_memory.ingest_hazards()
                await rag_memory.ingest_situations()
                await rag_memory.ingest_volcanoes()
            except Exception as e:
                print(f"[PHASE1] RAG pulse index failed: {e}", flush=True)
        try:
            items = await stac_bridge.fetch_recent_thailand_items(limit=6)
            await rag_memory.ingest_stac_items(items)
        except Exception as e:
            print(f"[PHASE2] STAC ingest failed: {e}", flush=True)
        try:
            screen = await sanctions_bridge.sanctions_screen_vessels(min_score=0.85, limit=200)
            hits = [m.get("sanction") for m in (screen.get("matches") or []) if m.get("sanction")]
            if hits:
                await rag_memory.ingest_sanctions_hits(hits)
        except Exception as e:
            print(f"[PHASE2] Sanctions ingest failed: {e}", flush=True)
        if feed_ingest.autopilot_on():
            try:
                result = await feed_ingest.run_feed_ingest()
                t = result.get("totals") or {}
                print(
                    f"[PHASE2] Feed ingest: +{t.get('entities', 0)} entities "
                    f"({t.get('records', 0)} records)",
                    flush=True,
                )
            except Exception as e:
                print(f"[PHASE2] Feed ingest failed: {e}", flush=True)
        await asyncio.sleep(600)


async def _aircraft_trail_loop() -> None:
    await asyncio.sleep(45)
    while True:
        try:
            await aircraft_trails.snapshot_now()
        except Exception as e:
            print(f"[TRAIL] aircraft snapshot failed: {e}", flush=True)
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
        print(f"[WARMUP] GDELT local pulse: {n} articles", flush=True)
        await asyncio.sleep(gdelt_bridge._GDELT_MIN_INTERVAL + 1.0)
        out = await gdelt_bridge.warmup_global_pulse()
        n = int((out or {}).get("count") or 0)
        print(f"[WARMUP] GDELT global pulse: {n} articles", flush=True)
    except Exception as e:
        print(f"[WARMUP] GDELT local failed: {e}", flush=True)
    try:
        from traffic_bridge import warm_traffic_cams

        await warm_traffic_cams(force=True)
        print("[WARMUP] Traffic cams refreshed (regional/global/all)", flush=True)
    except Exception as e:
        print(f"[WARMUP] Traffic cams failed: {e}", flush=True)
    try:
        import ais_bridge

        m = await ais_bridge.warm_maritime()
        if m:
            print(f"[WARMUP] Maritime: {m.get('count')} vessels demo={m.get('demo_mode')}", flush=True)
    except Exception as e:
        print(f"[WARMUP] Maritime failed: {e}", flush=True)
    try:
        import cams_bridge

        h = await cams_bridge.get_haze(refresh=True)
        print(f"[WARMUP] CAMS haze: {h.get('count')} cities", flush=True)
    except Exception as e:
        print(f"[WARMUP] CAMS haze failed: {e}", flush=True)
    try:
        from feeds_extra import air_quality

        await air_quality()
        print("[WARMUP] Air quality refreshed", flush=True)
    except Exception as e:
        print(f"[WARMUP] Air quality failed: {e}", flush=True)
    try:
        import feed_registry
        from windy_bridge import fetch_point_weather

        pt = await fetch_point_weather(13.75, 100.5)
        if pt.get("current"):
            feed_registry.write_auto("weather:13.75:100.5", pt)
            print(f"[WARMUP] Bangkok weather: source={pt.get('source')}", flush=True)
    except Exception as e:
        print(f"[WARMUP] Weather failed: {e}", flush=True)
    try:
        snap = await node_sync.warm_snapshot_cache()
        n = sum(1 for k in snap if snap.get(k))
        print(f"[WARMUP] Briefing snapshot cache: {n} feeds", flush=True)
    except Exception as e:
        print(f"[WARMUP] Snapshot cache failed: {e}", flush=True)


async def _entity_resolution_autopilot() -> None:
    await asyncio.sleep(120)
    interval = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_INTERVAL", "86400"))
    while True:
        try:
            result = await asyncio.to_thread(entity_resolution.run_resolution)
            print(
                f"[AUTOPILOT] Entity resolution: +{result.get('edges_added', 0)} edges "
                f"({result.get('exact_edges', 0)} exact, {result.get('splink_edges', 0)} splink)",
                flush=True,
            )
        except Exception as e:
            print(f"[AUTOPILOT] Entity resolution failed: {e}", flush=True)
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
                print(
                    "[AUTOPILOT] Prediction ledger: "
                    f"resolved={result.get('resolved')} "
                    f"hits={result.get('hits')} misses={result.get('misses')} "
                    f"30d={stats.get('accuracy')} n={stats.get('sample_size')}",
                    flush=True,
                )
        except Exception as e:
            print(f"[AUTOPILOT] Prediction ledger failed: {e}", flush=True)
        await asyncio.sleep(prediction_ledger.resolve_interval_s())


async def _briefing_autopilot() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await node_sync.generate_briefing_internal()
            print(f"[AUTOPILOT] Briefing generated at {datetime.now(timezone.utc).isoformat()}")
        except Exception as e:
            print(f"[AUTOPILOT] Briefing generation failed: {e}")
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
            print(
                "[FTM] Intel graph offline — DuckDB locked or missing. "
                "/api/intel/* and briefing FtM block may be empty until restart.",
                flush=True,
            )
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
            print("[AUTOPILOT] Briefing autopilot disabled (WORLDBASE_BRIEFING_AUTOPILOT=0)", flush=True)
        if entity_resolution.autopilot_on():
            asyncio.create_task(_entity_resolution_autopilot())
        else:
            print(
                "[AUTOPILOT] Entity resolution autopilot disabled "
                "(WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT=0)",
                flush=True,
            )
        import prediction_ledger

        if prediction_ledger.autopilot_on():
            asyncio.create_task(_prediction_ledger_autopilot())
        else:
            print(
                "[AUTOPILOT] Prediction ledger disabled (WORLDBASE_PREDICTION_LEDGER=0)",
                flush=True,
            )
        asyncio.create_task(aircraft_routes.aircraft_warmup())
        asyncio.create_task(_phase1_background_tasks())
        asyncio.create_task(_aircraft_trail_loop())
        asyncio.create_task(_situations_prewarm())
        asyncio.create_task(_stack_warmup())
        import ais_bridge

        ais_bridge.start_aisstream_collector()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        if _BRIEFING_AUTOPILOT_TASK:
            _BRIEFING_AUTOPILOT_TASK.cancel()
        import ais_bridge

        ais_bridge.stop_aisstream_collector()
