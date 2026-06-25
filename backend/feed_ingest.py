"""T2 live-feed ingest -> FollowTheMoney graph (YAML mappings)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

import config
import ftm_store
import intel_graph_export
import intel_proximity
import intel_semantic_links
from ingest.mapping_runner import apply_mapping, iter_rag_chunk_entries, list_mappings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_cfg = config.get_config

_LAST_RUN: dict[str, Any] | None = None
_LAST_ERROR: str | None = None


def autopilot_on() -> bool:
    return _cfg().feed_ingest_autopilot


def resolve_after_feeds() -> bool:
    return _cfg().entity_resolution_after_feeds


def rag_feed_ingest_on() -> bool:
    return _cfg().rag_feed_ingest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_key(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts if p)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


# ---------------------------------------------------------------------------
# Record normalizers (flat dicts -> YAML column names)
# ---------------------------------------------------------------------------


def normalize_gdacs_alert(alert: dict, idx: int) -> dict:
    title = (alert.get("title") or "GDACS alert").strip()
    published = alert.get("published") or alert.get("date") or ""
    return {
        "eventid": f"gdacs-{_hash_key(title, published, str(idx))}",
        "title": title,
        "description": (alert.get("description") or "")[:2000],
        "fromdate": published,
        "todate": published,
        "country": alert.get("eventtype") or "",
        "iso3": "",
        "link": alert.get("link") or "",
        "eventtype": alert.get("eventtype") or "",
        "alertlevel": alert.get("alertlevel") or "",
        "lat": alert.get("lat"),
        "lon": alert.get("lon"),
    }


def normalize_gdelt_geo(event: dict, idx: int) -> dict:
    name = (event.get("name") or event.get("title") or "GDELT signal")[:300]
    url = event.get("url") or ""
    return {
        "id": f"gdelt-geo-{_hash_key(url, name, str(event.get('lat')), str(event.get('lon')))}",
        "title": name,
        "snippet": name,
        "seen_date": event.get("date") or "",
        "url": url,
        "country": "",
        "place": "",
        "themes": "",
        "lat": event.get("lat"),
        "lon": event.get("lon"),
    }


def normalize_gdelt_article(article: dict) -> dict:
    url = article.get("url") or ""
    title = (article.get("title") or "Headline")[:300]
    return {
        "id": f"gdelt-doc-{_hash_key(url)}",
        "title": title,
        "snippet": title,
        "seen_date": article.get("seendate") or "",
        "url": url,
        "country": article.get("sourcecountry") or "",
        "place": "",
        "themes": article.get("domain") or "",
        "lat": None,
        "lon": None,
    }


def normalize_eonet_event(ev: dict) -> dict:
    return {
        "id": f"eonet-{ev.get('id')}",
        "title": ev.get("title") or "EONET event",
        "description": ev.get("category") or "",
        "date": ev.get("date") or "",
        "link": ev.get("link") or "",
        "category": ev.get("category") or "",
        "lat": ev.get("lat"),
        "lon": ev.get("lon"),
    }


def normalize_ais_vessel(v: dict) -> dict:
    return {
        "mmsi": str(v.get("mmsi") or ""),
        "name": v.get("name") or "Unknown",
        "imo": str(v.get("imo") or ""),
        "flag": v.get("flag") or "",
        "type": v.get("type") or "",
        "callsign": v.get("callsign") or "",
        "lat": v.get("lat"),
        "lon": v.get("lon"),
    }


def ingest_aircraft_anomalies(anomalies: list[dict]) -> dict:
    written = 0
    for a in anomalies:
        icao = (a.get("icao24") or "").lower()
        if not icao:
            continue
        ftm_store.upsert_legacy(
            f"aircraft:{icao}",
            "aircraft",
            label=a.get("callsign") or icao,
            lat=a.get("lat"),
            lon=a.get("lon"),
            source_feed="anomalies",
            external_id=icao,
            meta={"reasons": a.get("reasons"), "squawk": a.get("squawk")},
        )
        written += 1
    return {"dataset": "anomalies", "entities_written": written, "edges_written": 0}


# ---------------------------------------------------------------------------
# Async fetchers (reuse existing bridges — no HTTP self-call)
# ---------------------------------------------------------------------------


async def _fetch_gdacs_records() -> list[dict]:
    import feeds_extra

    data = await feeds_extra.gdacs_alerts()
    return [normalize_gdacs_alert(a, i) for i, a in enumerate(data.get("alerts") or [])]


async def _fetch_gdelt_geo_records() -> list[dict]:
    import gdelt_bridge

    data = await gdelt_bridge.gdelt_geo_local(region=_cfg().operator_region)
    return [normalize_gdelt_geo(e, i) for i, e in enumerate(data.get("events") or [])]


async def _fetch_gdelt_pulse_records() -> list[dict]:
    import gdelt_bridge

    data = await gdelt_bridge.gdelt_pulse_local(region=_cfg().operator_region)
    return [normalize_gdelt_article(a) for a in data.get("articles") or []]


async def _fetch_eonet_records(limit: int = 80) -> list[dict]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://eonet.gsfc.nasa.gov/api/v3/events?status=open&limit=200"
        )
        r.raise_for_status()
        data = r.json()
    out: list[dict] = []
    for ev in data.get("events", [])[:limit]:
        cats = [c.get("title") for c in ev.get("categories", []) if c.get("title")]
        geo = ev.get("geometry") or []
        if not geo:
            continue
        last = geo[-1]
        coords = last.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        sources = [s.get("url") for s in ev.get("sources", []) if s.get("url")]
        out.append(
            normalize_eonet_event(
                {
                    "id": ev.get("id"),
                    "title": ev.get("title"),
                    "category": cats[0] if cats else "Unknown",
                    "date": last.get("date"),
                    "lon": coords[0],
                    "lat": coords[1],
                    "link": sources[0] if sources else ev.get("link"),
                }
            )
        )
    return out


async def _fetch_maritime_records(limit: int = 120) -> list[dict]:
    import ais_bridge

    data = await ais_bridge.get_maritime()
    vessels = (data.get("vessels") or [])[:limit]
    return [normalize_ais_vessel(v) for v in vessels if v.get("mmsi")]


async def _fetch_anomaly_records() -> list[dict]:
    import feeds_extra

    data = await feeds_extra.aircraft_anomalies()
    return list(data.get("anomalies") or [])


FEED_SOURCES: dict[str, dict[str, Any]] = {
    "gdacs": {
        "mapping": "gdacs_alerts",
        "fetch": _fetch_gdacs_records,
        "dataset": "gdacs",
        "rag_source": "gdacs",
    },
    "gdelt_geo": {
        "mapping": "gdelt_events",
        "fetch": _fetch_gdelt_geo_records,
        "dataset": "gdelt-geo",
        "rag_source": "gdelt_geo",
    },
    "gdelt_pulse": {
        "mapping": "gdelt_events",
        "fetch": _fetch_gdelt_pulse_records,
        "dataset": "gdelt-pulse",
        "rag_source": "gdelt_pulse_local",
    },
    "eonet": {
        "mapping": "eonet_events",
        "fetch": _fetch_eonet_records,
        "dataset": "eonet",
        "rag_source": "eonet",
    },
    "maritime": {
        "mapping": "ais_vessels",
        "fetch": _fetch_maritime_records,
        "dataset": "ais",
        "rag_source": "maritime",
    },
}


async def _index_mapping_records_to_rag(
    records: list[dict],
    mapping_name: str,
    *,
    rag_source: str,
) -> dict:
    """Index feed records into RAG using YAML ``rag:`` chunk profiles (Track R1.3)."""
    import rag_memory

    entries = iter_rag_chunk_entries(records, mapping_name, rag_source=rag_source)
    if not entries:
        return {"indexed": 0, "reason": "no_rag_profile_or_records"}
    return await rag_memory.index_chunk_entries(entries)


async def run_feed_ingest(*, sources: list[str] | None = None) -> dict:
    global _LAST_RUN, _LAST_ERROR
    started = _now()
    _t0 = time.monotonic()
    chosen = sources or list(FEED_SOURCES.keys())
    per_source: dict[str, dict] = {}
    totals = {"entities": 0, "edges": 0, "records": 0}
    errors: list[str] = []

    for name in chosen:
        spec = FEED_SOURCES.get(name)
        if not spec:
            errors.append(f"unknown source: {name}")
            continue
        try:
            records = await spec["fetch"]()
            if name == "anomalies":
                result = ingest_aircraft_anomalies(records)
            else:
                result = apply_mapping(
                    records,
                    spec["mapping"],
                    dataset=spec.get("dataset") or name,
                )
                if rag_feed_ingest_on() and records:
                    try:
                        rag_src = spec.get("rag_source") or name
                        rag_out = await _index_mapping_records_to_rag(
                            records,
                            spec["mapping"],
                            rag_source=rag_src,
                        )
                        result["rag_indexed"] = rag_out.get("indexed", 0)
                    except Exception:
                        if len(errors) < 8:
                            errors.append(f"{name} rag: indexing failed")
                        logger.exception("rag indexing failed for %s", name)
            per_source[name] = result
            totals["records"] += result.get("records", len(records))
            totals["entities"] += result.get("entities_written", 0)
            totals["edges"] += result.get("edges_written", 0)
            if result.get("errors"):
                errors.extend(result["errors"][:2])
        except Exception:
            errors.append(f"{name}: ingest failed")
            per_source[name] = {"error": "ingest failed"}
            logger.exception("feed ingest failed for %s", name)

    # Aircraft anomalies (legacy mirror, no YAML)
    if "anomalies" in chosen or sources is None:
        try:
            anomalies = await _fetch_anomaly_records()
            ac = ingest_aircraft_anomalies(anomalies)
            per_source["anomalies"] = ac
            totals["entities"] += ac.get("entities_written", 0)
        except Exception:
            if len(errors) < 8:
                errors.append("anomalies: ingest failed")
            logger.exception("anomalies ingest failed")

    out = {
        "ok": not errors or totals["entities"] > 0,
        "started_at": started,
        "finished_at": _now(),
        "sources": chosen,
        "per_source": per_source,
        "totals": totals,
        "ftm_stats": ftm_store.stats(),
        "errors": errors[:10],
    }

    if resolve_after_feeds() and out["ok"]:
        try:
            import entity_resolution

            resolution = await asyncio.to_thread(entity_resolution.run_resolution)
            out["resolution"] = {
                "edges_added": resolution.get("edges_added", 0),
                "exact_edges": resolution.get("exact_edges", 0),
                "subset_edges": resolution.get("subset_edges", 0),
                "splink_edges": resolution.get("splink_edges", 0),
                "resolution_edges_total": resolution.get("resolution_edges_total", 0),
            }
        except Exception:
            out["errors"] = list(out["errors"]) + ["resolution: failed"]
            logger.exception("post-feed resolution failed")

    if out["ok"]:
        try:
            import intel_proximity

            if intel_proximity.enabled():
                spatial = await asyncio.to_thread(
                    intel_proximity.link_proximity_edges,
                    window_hours=24,
                )
                out["spatial_edges"] = spatial
                totals["edges"] += spatial.get("edges_added", 0)
        except Exception:
            out["errors"] = list(out["errors"]) + ["spatial: failed"]
            logger.exception("spatial proximity failed")

        try:
            import intel_semantic_links

            if intel_semantic_links.enabled():
                semantic = await asyncio.to_thread(
                    intel_semantic_links.link_semantic_edges,
                    window_hours=24,
                )
                out["semantic_edges"] = semantic
                totals["edges"] += semantic.get("edges_added", 0)
            if intel_semantic_links.sanctions_enabled():
                sanction = await intel_semantic_links.link_sanction_edges(window_hours=24)
                out["sanction_edges"] = sanction
                totals["edges"] += sanction.get("edges_added", 0)
        except Exception:
            out["errors"] = list(out["errors"]) + ["semantic: failed"]
            logger.exception("semantic links failed")

        try:
            import intel_graph_export

            if intel_graph_export.enabled():
                exported = await asyncio.to_thread(intel_graph_export.export_operator_subgraph)
                out["subgraph_export"] = {
                    "node_count": exported.get("node_count"),
                    "edge_count": exported.get("edge_count"),
                    "export_path": exported.get("export_path"),
                }
        except Exception:
            out["errors"] = list(out["errors"]) + ["subgraph_export: failed"]
            logger.exception("subgraph export failed")

    _elapsed = time.monotonic() - _t0
    out["duration_sec"] = round(_elapsed, 2)
    logger.info(
        "feed ingest: %.1fs, +%d entities, +%d edges, sources=%s",
        _elapsed, totals["entities"], totals["edges"], chosen,
    )
    _LAST_RUN = out
    _LAST_ERROR = errors[0] if errors else None
    return out


def status() -> dict:
    cfg = _cfg()
    return {
        "autopilot": autopilot_on(),
        "interval_sec": cfg.feed_ingest_interval,
        "operator_region": cfg.operator_region,
        "sources": list(FEED_SOURCES.keys()) + ["anomalies"],
        "mappings": list_mappings(),
        "last_run": _LAST_RUN,
        "last_error": _LAST_ERROR,
        "ftm_stats": ftm_store.stats(),
        "resolve_after_feeds": resolve_after_feeds(),
        "rag_feed_ingest": rag_feed_ingest_on(),
        "spatial_edges": intel_proximity.enabled(),
        "semantic_edges": intel_semantic_links.enabled(),
        "subgraph_export": intel_graph_export.enabled(),
    }


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: E402

from auth.security import verify_lan_auth  # noqa: E402

router = APIRouter(prefix="/api/intel/feeds", tags=["intel"])


@router.get("/status")
async def feeds_status():
    return status()


@router.post("/run")
async def feeds_run(
    sources: str | None = Query(None, description="Comma-separated source ids"),
    _auth: str | None = Depends(verify_lan_auth),
):
    src_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    try:
        return await run_feed_ingest(sources=src_list)
    except Exception as exc:
        logger.exception("feed ingest failed")
        raise HTTPException(status_code=503, detail="feed ingest failed") from exc
