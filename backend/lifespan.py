"""Background autopilot loops and FastAPI startup/shutdown hooks.

Extracted from main.py (Phase 1 decortication). Schedules briefing, RAG, trails,
stack warmups, AISstream collector, and aircraft cache refresh.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable

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
import snapshot_archiver
import situations
import stac_bridge
from config import get_config as _cfg
from sqlite_bootstrap import init_db, prune_feed_cache
from routes import aircraft as aircraft_routes
from structured_log import get_logger

log = get_logger(__name__)

_BRIEFING_AUTOPILOT_TASK: asyncio.Task | None = None
_BRIEFING_INTERVAL = _cfg().briefing_interval


# ---------------------------------------------------------------------------
# Task watchdog — strong references, heartbeat tracking, restart on crash
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    """Metadata for a supervised background task."""

    name: str
    coro_factory: Callable[[], Awaitable]
    interval_sec: float
    task: asyncio.Task | None = None
    last_heartbeat: float = 0.0
    error_count: int = 0
    restart_count: int = 0
    last_error: str | None = None
    last_restart: str | None = None


class TaskWatchdog:
    """Holds strong references to background tasks, monitors heartbeats,
    and restarts crashed or silent tasks.

    Fail-soft: if restart fails, logs a warning and continues monitoring.
    """

    def __init__(self, timeout_multiplier: float = 2.5) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._timeout_multiplier = timeout_multiplier
        self._watchdog_task: asyncio.Task | None = None
        self._loop_lag_ms: float = 0.0
        self._rss_mb: float = 0.0

    def register(
        self,
        name: str,
        coro_factory: Callable[[], Awaitable],
        interval_sec: float,
    ) -> None:
        """Register a task for supervision. Call before starting the task."""
        rec = TaskRecord(
            name=name,
            coro_factory=coro_factory,
            interval_sec=interval_sec,
        )
        self._tasks[name] = rec

    def start(self, name: str) -> asyncio.Task:
        """Create and start the asyncio task, holding a strong reference."""
        rec = self._tasks.get(name)
        if rec is None:
            raise KeyError(f"Task {name!r} not registered")
        rec.task = asyncio.create_task(rec.coro_factory(), name=name)
        rec.last_heartbeat = time.monotonic()
        return rec.task

    def heartbeat(self, name: str) -> None:
        """Update the last-seen timestamp for a task."""
        rec = self._tasks.get(name)
        if rec:
            rec.last_heartbeat = time.monotonic()

    def record_error(self, name: str, error: str) -> None:
        """Record an error for a task."""
        rec = self._tasks.get(name)
        if rec:
            rec.error_count += 1
            rec.last_error = error

    def status(self) -> dict:
        """Return a snapshot of all supervised tasks + resource pressure."""
        now = time.monotonic()
        tasks_status = {}
        for name, rec in self._tasks.items():
            is_alive = rec.task is not None and not rec.task.done()
            silent_for = (
                round(now - rec.last_heartbeat, 1) if rec.last_heartbeat else None
            )
            timeout_sec = rec.interval_sec * self._timeout_multiplier
            tasks_status[name] = {
                "alive": is_alive,
                "silent_for_sec": silent_for,
                "timeout_sec": round(timeout_sec, 1),
                "error_count": rec.error_count,
                "restart_count": rec.restart_count,
                "last_error": rec.last_error,
                "last_restart": rec.last_restart,
                "interval_sec": rec.interval_sec,
            }
        return {
            "tasks": tasks_status,
            "loop_lag_ms": round(self._loop_lag_ms, 2),
            "rss_mb": round(self._rss_mb, 1),
            "watchdog_enabled": self._watchdog_task is not None,
        }

    async def _monitor(self) -> None:
        """Watchdog loop: check task health, restart if needed, sample resources."""
        await asyncio.sleep(60)
        while True:
            try:
                now = time.monotonic()
                for name, rec in list(self._tasks.items()):
                    # Check if task crashed or completed
                    if rec.task is not None and rec.task.done():
                        exc = rec.task.exception()
                        if exc:
                            rec.error_count += 1
                            rec.last_error = str(exc)
                            log.warning(
                                "task_crashed",
                                task=name,
                                error=str(exc),
                                error_count=rec.error_count,
                            )
                        # Restart if enabled, but respect interval_sec as
                        # cooldown — one-shot tasks (warmup, prewarm) should
                        # not restart faster than their declared interval.
                        if rec.error_count < 5:
                            elapsed = now - rec.last_heartbeat
                            if elapsed < rec.interval_sec:
                                continue  # too soon, wait for next cycle
                            try:
                                rec.task = asyncio.create_task(
                                    rec.coro_factory(), name=name
                                )
                                rec.restart_count += 1
                                rec.last_heartbeat = now
                                ts = datetime.now(timezone.utc).isoformat()
                                rec.last_restart = ts
                                log.info(
                                    "task_restarted",
                                    task=name,
                                    restart_count=rec.restart_count,
                                )
                            except Exception as e:
                                log.warning(
                                    "task_restart_failed", task=name, error=str(e)
                                )
                        else:
                            log.error(
                                "task_restart_limit_exceeded",
                                task=name,
                                error_count=rec.error_count,
                            )

                    # Check if task is silent (heartbeat stale)
                    elif rec.task is not None and not rec.task.done():
                        timeout_sec = rec.interval_sec * self._timeout_multiplier
                        if (
                            rec.last_heartbeat
                            and (now - rec.last_heartbeat) > timeout_sec
                        ):
                            log.warning(
                                "task_silent",
                                task=name,
                                silent_for_sec=round(now - rec.last_heartbeat, 1),
                                timeout_sec=round(timeout_sec, 1),
                            )
                            # Don't cancel — just warn. The task may be in a long blocking call.

                # Sample resource pressure (fail-soft)
                await self._sample_resources()
            except Exception as e:
                log.debug("watchdog_monitor_failed", error=str(e))
            await asyncio.sleep(30)

    async def _sample_resources(self) -> None:
        """Sample RSS memory and event-loop lag. Fail-soft if psutil missing."""
        try:
            import psutil

            proc = psutil.Process()
            self._rss_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            await asyncio.sleep(1)
            self._loop_lag_ms = (loop.time() - t0 - 1.0) * 1000
        except Exception:
            pass

    def start_watchdog(self) -> None:
        """Start the monitoring loop."""
        if self._watchdog_task is None:
            self._watchdog_task = asyncio.create_task(
                self._monitor(), name="task_watchdog"
            )

    def stop_watchdog(self) -> None:
        """Stop the monitoring loop and cancel all supervised tasks."""
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        for rec in self._tasks.values():
            if rec.task is not None and not rec.task.done():
                rec.task.cancel()


# Module-level singleton
_watchdog: TaskWatchdog | None = None


def get_watchdog() -> TaskWatchdog | None:
    """Return the global TaskWatchdog instance, or None if disabled."""
    return _watchdog


async def _news_feeds_autopilot() -> None:
    """Refresh ReliefWeb + RSS headlines for chat context (10 min TTL)."""
    await asyncio.sleep(30)
    interval = float(os.getenv("WORLDBASE_NEWS_REFRESH_INTERVAL", "600"))
    while True:
        try:
            import news_feeds

            result = await news_feeds.refresh_news_feeds()
            log.info(
                "news_feeds_refreshed",
                reliefweb=result.get("reliefweb", {}).get("count", 0),
                rss=result.get("rss", {}).get("count", 0),
            )
        except Exception as exc:
            log.debug("news_feeds_refresh_failed", error=str(exc))
        await asyncio.sleep(interval)


async def _maritime_trajectory_maintenance() -> None:
    """P7: Periodic AIS trajectory ringbuffer flush + position pruning (every 5 min)."""
    await asyncio.sleep(60)
    while True:
        try:
            import ais_trajectory

            if ais_trajectory.trajectory_enabled():
                ais_trajectory.flush_buffer()
                pruned = ais_trajectory.prune_old_positions()
                if pruned:
                    log.debug("ais_trajectory_pruned", removed=pruned)
        except Exception as exc:
            log.debug("ais_trajectory_maintenance_failed", error=str(exc))
        await asyncio.sleep(300)


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
                log.info("rag_news_indexed", chunks=news.get("indexed", 0))
                await rag_memory.ingest_hazards()
                await rag_memory.ingest_situations()
                await rag_memory.ingest_volcanoes()
                watches = await rag_memory.ingest_prediction_watches()
                if watches.get("indexed"):
                    log.info("rag_watches_indexed", indexed=watches.get("indexed"))
            except Exception as e:
                log.warning("rag_index_failed", error=str(e))
        try:
            items = await stac_bridge.fetch_recent_thailand_items(limit=6)
            await rag_memory.ingest_stac_items(items)
        except Exception as e:
            log.warning("stac_ingest_failed", error=str(e))
        try:
            screen = await sanctions_bridge.sanctions_screen_vessels(
                min_score=0.85, limit=200
            )
            hits = [
                m.get("sanction")
                for m in (screen.get("matches") or [])
                if m.get("sanction")
            ]
            if hits:
                await rag_memory.ingest_sanctions_hits(hits)
        except Exception as e:
            log.warning("sanctions_ingest_failed", error=str(e))
        if feed_ingest.autopilot_on() and _cfg().task_queue != "celery":
            try:
                result = await feed_ingest.run_feed_ingest()
                t = result.get("totals") or {}
                log.info(
                    "feed_ingest_done",
                    entities=t.get("entities", 0),
                    records=t.get("records", 0),
                )
            except Exception as e:
                log.warning("feed_ingest_failed", error=str(e))
        elif feed_ingest.autopilot_on() and _cfg().task_queue == "celery":
            log.debug("feed_ingest_delegated_to_celery")
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
            log.info("warmup_maritime", vessels=m.get("count"))
    except Exception as e:
        log.warning("warmup_maritime_failed", error=str(e))
    try:
        import cams_bridge

        h = await cams_bridge.get_haze(refresh=True)
        log.info("warmup_cams_haze", cities=h.get("count"))
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
            log.info("warmup_weather", source=pt.get("source"))
    except Exception as e:
        log.warning("warmup_weather_failed", error=str(e))
    try:
        snap = await node_sync.warm_snapshot_cache()
        n = sum(1 for k in snap if snap.get(k))
        log.info("warmup_snapshot_cache", feeds=n)
    except Exception as e:
        log.warning("warmup_snapshot_cache_failed", error=str(e))
    # I7: RAG reranker warmup (ONNX int8 or Torch fallback)
    try:
        import rag_rerank

        if rag_rerank.rerank_enabled():
            result = await rag_rerank.warmup_reranker()
            log.info(
                "warmup_reranker",
                state=result.get("state"),
                backend=result.get("backend"),
                elapsed_s=result.get("elapsed_s"),
            )
    except Exception as e:
        log.warning("warmup_reranker_failed", error=str(e))
    # V4-15: BLIP image captioning warmup (ONNX or NVIDIA VLM)
    try:
        import blip_bridge

        if blip_bridge._enabled():
            result = await blip_bridge.warmup_blip()
            log.info(
                "warmup_blip",
                state=result.get("state"),
                backend=result.get("backend"),
                elapsed_s=result.get("elapsed_s"),
            )
    except Exception as e:
        log.warning("warmup_blip_failed", error=str(e))


async def _entity_resolution_autopilot() -> None:
    await asyncio.sleep(120)
    interval = _cfg().entity_resolution_interval
    while True:
        try:
            result = await asyncio.to_thread(entity_resolution.run_resolution)
            log.info(
                "entity_resolution_done",
                edges_added=result.get("edges_added", 0),
                exact_edges=result.get("exact_edges", 0),
                splink_edges=result.get("splink_edges", 0),
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
                grid = await fusion_heatmap.fusion_heatmap(
                    cell_deg=2.0, top=60, include_geojson=0
                )
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
                    resolved=result.get("resolved"),
                    hits=result.get("hits"),
                    misses=result.get("misses"),
                    accuracy_30d=stats.get("accuracy"),
                    sample_size=stats.get("sample_size"),
                )
        except Exception as e:
            log.warning("prediction_ledger_failed", error=str(e))
        await asyncio.sleep(prediction_ledger.resolve_interval_s())


async def _feed_cache_autopilot() -> None:
    """Keep feed_cache.cached_at fresh for background-collected feeds (no HTTP poll required)."""
    await asyncio.sleep(45)
    maritime_interval = float(os.getenv("WORLDBASE_MARITIME_TOUCH_INTERVAL_S", "30"))
    gdelt_interval = float(os.getenv("WORLDBASE_GDELT_TOUCH_INTERVAL_S", "600"))
    airquality_interval = float(
        os.getenv("WORLDBASE_AIRQUALITY_TOUCH_INTERVAL_S", "2700")
    )
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
    _celery_mode = _cfg().task_queue == "celery"
    while True:
        if _celery_mode:
            log.debug("briefing_delegated_to_celery")
        else:
            try:
                await node_sync.generate_briefing_internal()
                log.info(
                    "briefing_generated", ts=datetime.now(timezone.utc).isoformat()
                )
            except Exception as e:
                log.warning("briefing_generation_failed", error=str(e))
        # I4: webhook alerting after briefing
        try:
            import alerting
            import metrics as _metrics

            m = _metrics.collect_all()
            alerts = alerting.check_and_alert(
                trust_score=int(
                    m.get("ollama_reachable", 0)
                    + m.get("pi_edge_online", 0)
                    + (1 if m.get("briefing_age_seconds", 999) < 21600 else 0)
                    + (1 if m.get("feed_fresh_count", 0) > 0 else 0)
                ),
                feed_fresh=int(m.get("feed_fresh_count", 0)),
                feed_stale=int(m.get("feed_stale_count", 0)),
                duckdb_queue_backlog=int(m.get("duckdb_queue_backlog", 0)),
            )
            for a in alerts:
                log.warning("alert_fired", **a)
        except Exception as exc:
            log.debug("alert_check_failed", error=str(exc))
        # J5: quota alerting
        try:
            import quota_monitor

            quota_alerts = quota_monitor.check_alerts()
            for qa in quota_alerts:
                log.warning("quota_alert", **qa)
        except Exception as exc:
            log.debug("quota_alert_check_failed", error=str(exc))
        # 3.4: trigger-response engine evaluation
        try:
            import fusion_heatmap
            import trigger_engine

            grid = await fusion_heatmap.fusion_heatmap(
                cell_deg=2.0, top=60, include_geojson=0
            )
            cells = list(grid.get("cells") or [])
            # Get watch items from latest briefing digest
            watches: list[dict] = []
            try:
                import prediction_ledger

                preds = prediction_ledger.list_predictions(
                    pending_limit=20, resolved_limit=0
                )
                watches = [
                    {
                        "id": p.get("watch_id"),
                        "prefix": p.get("prefix"),
                        "title": p.get("claim"),
                        "confidence": 0.5,
                        "bucket": p.get("bucket"),
                        "cell_id": p.get("cell_id"),
                        "sources": p.get("sources", []),
                    }
                    for p in (preds.get("pending") or [])
                ]
            except Exception:
                pass
            fired = trigger_engine.evaluate_triggers(cells, watches)
            for t in fired:
                log.warning("trigger_fired", **t)
                # Post webhook
                try:
                    import alerting

                    alerting._post_webhook(
                        {
                            "alert": t["rule_name"],
                            "severity": t["severity"],
                            "message": t["context"],
                            "confidence": t["confidence"],
                            "source": "worldbase-pc",
                            "timestamp": t["fired_at"],
                        }
                    )
                except Exception:
                    pass
            # Push to Pi nodes via command queue + SSE
            try:
                pushed = trigger_engine.push_trigger_to_nodes(fired)
                if pushed:
                    log.info("trigger_pushed_to_nodes", count=pushed)
            except Exception:
                pass
        except Exception as exc:
            log.debug("trigger_eval_failed", error=str(exc))
        # I6: tiered storage maintenance (every 24h — runs when briefing interval >= 6h, otherwise every loop)
        try:
            import ftm_archive
            import sqlite_bootstrap

            # Prune stale feed cache
            pruned = sqlite_bootstrap.prune_feed_cache()
            if pruned:
                log.info("feed_cache_pruned", removed=pruned)
            # VACUUM SQLite
            import sqlite3

            conn = sqlite3.connect(sqlite_bootstrap.DB_PATH, timeout=10.0)
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("VACUUM")
            conn.close()
            # FtM archival (no-op when WORLDBASE_FTM_ARCHIVE_DAYS=0)
            result = ftm_archive.archive_stale_entities()
            if result.get("enabled") and result.get("archived", 0) > 0:
                log.info("ftm_archived", **result)
        except Exception as exc:
            log.debug("tiered_storage_maintenance_failed", error=str(exc))
        await asyncio.sleep(_BRIEFING_INTERVAL)


def register_lifecycle(app) -> None:
    """Attach startup/shutdown handlers to the FastAPI app."""

    @app.on_event("startup")
    def on_startup() -> None:
        global _BRIEFING_AUTOPILOT_TASK, _watchdog
        init_db()
        prune_feed_cache()
        # Session 7 — apply operator-set credentials from JSON store
        try:
            from credentials.store import apply_credentials_to_env

            n = apply_credentials_to_env()
            if n:
                log.info("credentials_loaded", count=n)
        except Exception as e:
            log.warning("credentials_load_failed", error=str(e))
        entity_store.init_entity_db()
        if not ftm_store.init_store():
            log.error("ftm_store_offline", detail="DuckDB locked or missing")
        if _cfg().duckdb_queue_enabled:
            import duckdb_queue

            duckdb_queue.get_queue().enable()
        node_sync.init_node_db()
        node_sync.init_command_db()
        anomaly_river.init_river_db()
        import anomaly_detector

        anomaly_detector.init_anomaly_db()
        rag_memory.init_memory_db()
        import feed_drift

        feed_drift.init_drift_db()
        import prediction_ledger

        prediction_ledger.init_prediction_db()
        import route_ledger

        route_ledger.init_route_ledger_db()
        aircraft_trails.init_trail_db()
        import briefing_pipeline

        briefing_pipeline.init_pipeline_db()
        import ckan_harvester

        ckan_harvester.init_harvest_log()
        import features

        features.init_feature_flags_db()
        import quota_monitor

        quota_monitor.init_quota_db()
        from ollama_config import briefing_autopilot_on

        # Initialize task watchdog
        cfg = _cfg()
        if cfg.task_watchdog_enabled:
            _watchdog = TaskWatchdog(
                timeout_multiplier=cfg.task_watchdog_timeout_multiplier
            )

        wd = _watchdog

        if cfg.task_queue == "celery":
            log.info(
                "task_queue_celery",
                broker=cfg.celery_broker_url,
                backend_url=cfg.celery_backend_url,
                feeds_delegated=True,
                briefing_delegated=True,
            )

        if briefing_autopilot_on():
            if wd:
                wd.register(
                    "briefing_autopilot", _briefing_autopilot, float(_BRIEFING_INTERVAL)
                )
                _BRIEFING_AUTOPILOT_TASK = wd.start("briefing_autopilot")
            else:
                _BRIEFING_AUTOPILOT_TASK = asyncio.create_task(_briefing_autopilot())
        else:
            log.info("briefing_autopilot_disabled")
        if entity_resolution.autopilot_on():
            if wd:
                wd.register(
                    "entity_resolution",
                    _entity_resolution_autopilot,
                    float(cfg.entity_resolution_interval),
                )
                wd.start("entity_resolution")
            else:
                asyncio.create_task(_entity_resolution_autopilot())
        else:
            log.info("entity_resolution_autopilot_disabled")
        import prediction_ledger

        if prediction_ledger.autopilot_on():
            if wd:
                wd.register(
                    "prediction_ledger",
                    _prediction_ledger_autopilot,
                    float(prediction_ledger.resolve_interval_s()),
                )
                wd.start("prediction_ledger")
            else:
                asyncio.create_task(_prediction_ledger_autopilot())
        else:
            log.info("prediction_ledger_disabled")
        if wd:
            wd.register("aircraft_warmup", aircraft_routes.aircraft_warmup, 300.0)
            wd.start("aircraft_warmup")
            wd.register("phase1_background", _phase1_background_tasks, 600.0)
            wd.start("phase1_background")
            wd.register("aircraft_trail_loop", _aircraft_trail_loop, 30.0)
            wd.start("aircraft_trail_loop")
            wd.register("situations_prewarm", _situations_prewarm, 600.0)
            wd.start("situations_prewarm")
            wd.register("stack_warmup", _stack_warmup, 3600.0)
            wd.start("stack_warmup")
            wd.register("feed_cache_autopilot", _feed_cache_autopilot, 30.0)
            wd.start("feed_cache_autopilot")
            wd.register("maritime_trajectory", _maritime_trajectory_maintenance, 300.0)
            wd.start("maritime_trajectory")
            wd.register("news_feeds_autopilot", _news_feeds_autopilot, 600.0)
            wd.start("news_feeds_autopilot")
            # V4-09: Daily snapshot archiver (opt-in)
            if snapshot_archiver._enabled():
                wd.register(
                    "snapshot_archiver",
                    snapshot_archiver.snapshot_autopilot,
                    float(snapshot_archiver._INTERVAL_HOURS * 3600),
                )
                wd.start("snapshot_archiver")
            wd.start_watchdog()
        else:
            asyncio.create_task(aircraft_routes.aircraft_warmup())
            asyncio.create_task(_phase1_background_tasks())
            asyncio.create_task(_aircraft_trail_loop())
            asyncio.create_task(_situations_prewarm())
            asyncio.create_task(_stack_warmup())
            asyncio.create_task(_feed_cache_autopilot())
            asyncio.create_task(_maritime_trajectory_maintenance())
            asyncio.create_task(_news_feeds_autopilot())
            # V4-09: Daily snapshot archiver (opt-in)
            if snapshot_archiver._enabled():
                asyncio.create_task(snapshot_archiver.snapshot_autopilot())
            # V4-23: Anomaly detection autopilot (opt-in)
            if anomaly_detector._enabled():
                asyncio.create_task(anomaly_detector.anomaly_autopilot())
        import ais_bridge

        ais_bridge.start_aisstream_collector()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        if _BRIEFING_AUTOPILOT_TASK:
            _BRIEFING_AUTOPILOT_TASK.cancel()
        if _watchdog is not None:
            _watchdog.stop_watchdog()
        import duckdb_queue

        if duckdb_queue.is_enabled():
            duckdb_queue.get_queue().disable()
        import ais_bridge

        ais_bridge.stop_aisstream_collector()
