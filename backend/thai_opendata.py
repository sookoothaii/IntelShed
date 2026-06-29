"""Thailand Open Data Connector — data.go.th (CKAN-based).

Provides population, economic, and environmental datasets from the Thai
government open data portal. Uses the standard CKAN package_search API.

Feature flag: WORLDBASE_THAI_OPENDATA=0 (default off)
Briefing: WORLDBASE_BRIEFING_THAI=0 (opt-in)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Query

from config import get_config
from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector

logger = logging.getLogger("worldbase.thai_opendata")

router = APIRouter(prefix="/api/thai", tags=["thai-opendata"])

_CKAN_BASE = "https://data.go.th/api/3/action"
_UA = {"User-Agent": "WorldBase/1.0 (research; thai-opendata)"}
_TTL = float(os.getenv("WORLDBASE_THAI_OPENDATA_CACHE_SEC", "3600"))
_CONNECTOR = FeedConnector("thai_opendata", ttl_sec=_TTL, default_source="data.go.th")
_REFRESH_LOCK = asyncio.Lock()

# Curated dataset groups for briefing relevance
_DATASET_GROUPS = {
    "environment": "environment",
    "population": "population",
    "economy": "economy",
    "health": "health",
    "transport": "transport",
}

# Thailand major cities for geo-coding (English + Thai names)
_TH_CITIES = {
    "bangkok": (13.7563, 100.5018),
    "กรุงเทพ": (13.7563, 100.5018),
    "chiang mai": (18.7883, 98.9853),
    "เชียงใหม่": (18.7883, 98.9853),
    "phuket": (7.8804, 98.3923),
    "ภูเก็ต": (7.8804, 98.3923),
    "khon kaen": (16.4419, 102.8360),
    "ขอนแก่น": (16.4419, 102.8360),
    "songkhla": (7.1898, 100.5950),
    "สงขลา": (7.1898, 100.5950),
    "nakhon ratchasima": (14.9799, 102.0978),
    "นครราชสีมา": (14.9799, 102.0978),
    "rayong": (12.6816, 101.2813),
    "ระยอง": (12.6816, 101.2813),
    "chonburi": (13.3611, 100.9847),
    "ชลบุรี": (13.3611, 100.9847),
    "chumphon": (10.4933, 99.1800),
    "ชุมพร": (10.4933, 99.1800),
    "chiang rai": (19.9105, 99.8406),
    "เชียงราย": (19.9105, 99.8406),
}


def _enabled() -> bool:
    return get_config().thai_opendata_enabled


async def _fetch_ckan(
    action: str,
    params: dict[str, Any],
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Fetch from CKAN API. Fail-soft."""
    url = f"{_CKAN_BASE}/{action}"
    try:
        r = await client.get(url, params=params, headers=_UA, timeout=20.0)
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            return {
                "error": data.get("error", {}).get("message", "CKAN error"),
                "results": [],
            }
        return data.get("result", {})
    except Exception as exc:
        logger.warning("CKAN %s failed: %s", action, exc)
        return {"error": str(exc), "results": []}


async def _fetch_datasets(
    group: str | None = None,
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch dataset catalog from data.go.th."""
    subkey = f"datasets:{group or 'all'}:{limit}"
    if not refresh:
        hit = _CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    async with _REFRESH_LOCK:
        if not refresh:
            hit = _CONNECTOR.get_cached(subkey)
            if hit is not None:
                return hit

        params: dict[str, Any] = {"rows": min(limit, 100)}
        if group:
            params["groups"] = group

        async with httpx.AsyncClient() as client:
            result = await _fetch_ckan("package_search", params, client)

        if result.get("error"):
            return _CONNECTOR.build(
                FeedEnvelope(count=0, source="data.go.th", error=result["error"]),
                persist=False,
                subkey=subkey,
                datasets=[],
                configured=True,
            )

        datasets = []
        for pkg in result.get("results", [])[:limit]:
            resources = []
            for res in pkg.get("resources", []):
                resources.append(
                    {
                        "id": res.get("id"),
                        "name": res.get("name"),
                        "format": res.get("format"),
                        "url": res.get("url"),
                        "size": res.get("size"),
                    }
                )
            org = pkg.get("organization", {})
            datasets.append(
                {
                    "id": pkg.get("id"),
                    "title": pkg.get("title"),
                    "name": pkg.get("name"),
                    "notes": (pkg.get("notes") or "")[:500],
                    "groups": [g.get("name") for g in pkg.get("groups", [])],
                    "org": org.get("title"),
                    "org_id": org.get("id"),
                    "resources": resources,
                    "metadata_created": pkg.get("metadata_created"),
                    "metadata_modified": pkg.get("metadata_modified"),
                    "tags": [t.get("name") for t in pkg.get("tags", [])],
                }
            )

        return _CONNECTOR.build(
            FeedEnvelope(count=len(datasets), source="data.go.th"),
            subkey=subkey,
            datasets=datasets,
            configured=True,
            total=result.get("count", len(datasets)),
        )


async def _fetch_environmental(
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch environmental datasets (AQI, water quality) with geo-coding."""
    subkey = f"env:{limit}"
    if not refresh:
        hit = _CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    # data.go.th has no CKAN groups; use keyword search instead
    params = {
        "rows": min(limit, 100),
        "q": "environment OR air quality OR water quality OR pollution OR AQI OR PM2.5",
    }
    async with httpx.AsyncClient() as client:
        result = await _fetch_ckan("package_search", params, client)

    if result.get("error"):
        return _CONNECTOR.build(
            FeedEnvelope(count=0, source="data.go.th", error=result["error"]),
            persist=False,
            subkey=subkey,
            stations=[],
            configured=True,
        )

    stations = []
    for pkg in result.get("results", [])[:limit]:
        title = pkg.get("title", "")
        notes = pkg.get("notes", "") or ""
        # Try to extract location from tags/notes
        lat, lon = None, None
        text = (title + " " + notes).lower()
        for city_key, (clat, clon) in _TH_CITIES.items():
            if city_key in text:
                lat, lon = clat, clon
                break
        stations.append(
            {
                "id": pkg.get("id"),
                "title": title,
                "notes": notes[:300],
                "lat": lat,
                "lon": lon,
                "tags": [t.get("name") for t in pkg.get("tags", [])],
                "modified": pkg.get("metadata_modified"),
                "resource_count": len(pkg.get("resources", [])),
            }
        )

    geocoded = sum(1 for s in stations if s["lat"] is not None)
    return _CONNECTOR.build(
        FeedEnvelope(count=len(stations), source="data.go.th", geocoded=geocoded),
        subkey=subkey,
        stations=stations,
        configured=True,
    )


def _enrich_ftm(datasets: list[dict[str, Any]]) -> dict[str, Any]:
    """Create FtM Event entities from environmental datasets. Fail-soft."""
    try:
        import entity_store

        ids: list[str] = []
        for ds in datasets:
            if not ds.get("lat"):
                continue
            entity_id = f"thai-env-{ds['id'][:12]}"
            entity_store.upsert_entity(
                entity_id,
                "Event",
                label=ds.get("title", "Thai environmental dataset"),
                lat=ds["lat"],
                lon=ds["lon"],
                source_feed="thai_opendata",
                meta={
                    "notes": ds.get("notes", "")[:500],
                    "tags": ds.get("tags", []),
                    "modified": ds.get("modified"),
                },
            )
            ids.append(entity_id)
        return {"count": len(ids), "ids": ids, "error": None}
    except Exception as exc:
        logger.warning("Thai FtM enrichment failed: %s", exc)
        return {"count": 0, "ids": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Briefing digest
# ---------------------------------------------------------------------------


async def gather_thai_digest() -> dict[str, Any]:
    """Gather Thai open data for briefing LOCAL bucket. Fail-soft."""
    cfg = get_config()
    if not cfg.thai_opendata_enabled or not cfg.briefing_thai:
        return {"enabled": False, "count": 0, "lines": []}

    try:
        lines: list[str] = []
        env_data = await _fetch_environmental(limit=10)
        stations = env_data.get("stations", [])
        for st in stations[:5]:
            title = st.get("title", "Unknown")
            tags = ", ".join(st.get("tags", [])[:3])
            geo = f"({st['lat']:.2f}, {st['lon']:.2f})" if st.get("lat") else "no geo"
            lines.append(f"- {title} — tags: {tags} — {geo}")

        catalog = await _fetch_datasets(limit=5)
        total = catalog.get("total", 0)
        if total:
            lines.append(f"- Catalog: {total} datasets available on data.go.th")

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines[:5],
            "stations_geocoded": sum(1 for s in stations if s.get("lat")),
        }
    except Exception as exc:
        logger.warning("Thai digest failed: %s", exc)
        return {"enabled": False, "count": 0, "lines": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/opendata")
async def thai_opendata(
    group: str | None = Query(None, description="Dataset group filter"),
    limit: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Browse Thai government open data catalog (data.go.th CKAN API)."""
    if not _enabled():
        return {
            "count": 0,
            "source": "data.go.th",
            "error": "Thai Open Data connector disabled (WORLDBASE_THAI_OPENDATA=0)",
            "configured": False,
        }
    return await _fetch_datasets(group=group, limit=limit, refresh=refresh)


@router.get("/environmental")
async def thai_environmental(
    limit: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Environmental monitoring datasets from data.go.th with geo-coding."""
    if not _enabled():
        return {
            "count": 0,
            "source": "data.go.th",
            "error": "Thai Open Data connector disabled (WORLDBASE_THAI_OPENDATA=0)",
            "configured": False,
        }
    return await _fetch_environmental(limit=limit, refresh=refresh)


@router.post("/ingest")
async def thai_ingest(
    limit: int = Query(20, ge=1, le=100),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Ingest environmental datasets as FtM Event entities."""
    if not _enabled():
        return {
            "count": 0,
            "source": "data.go.th",
            "error": "Thai Open Data connector disabled (WORLDBASE_THAI_OPENDATA=0)",
            "configured": False,
        }
    env_data = await _fetch_environmental(limit=limit, refresh=refresh)
    stations = env_data.get("stations", [])
    enrich_result = _enrich_ftm(stations)
    return {
        "source": "data.go.th",
        "stations_found": len(stations),
        "ingested": enrich_result["count"],
        "ids": enrich_result["ids"],
        "error": enrich_result["error"],
    }
