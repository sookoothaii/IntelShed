"""Generic CKAN Harvester — data portal integration for any CKAN instance.

Supports multiple CKAN portals via YAML config (``backend/ingest/ckan_sources.yml``).
Each portal defines base URL, optional API key, filter groups, and TTL.

Feature flag: WORLDBASE_CKAN_HARVESTER=1 (default off)

Endpoints:
  GET  /api/ckan/portals           — list configured portals
  GET  /api/ckan/{portal_id}/search — search datasets
  POST /api/ckan/{portal_id}/harvest — harvest datasets into feed_cache + FtM
  GET  /api/ckan/harvest/log       — recent harvest runs
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Query

from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector

logger = logging.getLogger("worldbase.ckan_harvester")

router = APIRouter(prefix="/api/ckan", tags=["ckan-harvester"])

_SOURCES_FILE = Path(__file__).resolve().parent / "ingest" / "ckan_sources.yml"
_HARVEST_LOG_TABLE = "ckan_harvest_log"
_UA = {"User-Agent": "WorldBase/1.0 (CKAN harvester)"}


def _enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_CKAN_HARVESTER", "0"))


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------


def load_sources() -> dict[str, dict[str, Any]]:
    """Load CKAN portal definitions from YAML. Returns portal_id → config."""
    if not _SOURCES_FILE.is_file():
        return {}
    with open(_SOURCES_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    portals: dict[str, dict[str, Any]] = {}
    for entry in data.get("portals", []):
        pid = entry.get("id")
        if not pid:
            continue
        portals[pid] = entry
    return portals


def list_portals() -> list[dict[str, Any]]:
    """Return portal metadata for API consumption."""
    sources = load_sources()
    out: list[dict[str, Any]] = []
    for pid, cfg in sorted(sources.items()):
        out.append(
            {
                "id": pid,
                "name": cfg.get("name", pid),
                "url": cfg.get("url", ""),
                "region": cfg.get("region", "global"),
                "groups": cfg.get("groups", []),
                "ttl_sec": cfg.get("ttl_sec", 3600),
                "has_api_key": bool(cfg.get("api_key_env")),
                "enabled": cfg.get("enabled", True),
            }
        )
    return out


# ---------------------------------------------------------------------------
# CKAN API client
# ---------------------------------------------------------------------------


def _resolve_api_key(portal_cfg: dict[str, Any]) -> str | None:
    env_name = portal_cfg.get("api_key_env")
    if not env_name:
        return None
    return os.getenv(env_name)


async def _ckan_request(
    base_url: str,
    action: str,
    params: dict[str, Any],
    *,
    api_key: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Execute a CKAN API action. Fail-soft."""
    url = f"{base_url.rstrip('/')}/api/3/action/{action}"
    headers = dict(_UA)
    if api_key:
        headers["Authorization"] = api_key
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
            if not data.get("success"):
                err = data.get("error", {})
                return {"error": err.get("message", "CKAN error"), "results": []}
            return data.get("result", {})
    except Exception as exc:
        logger.warning("CKAN %s failed: %s", action, exc)
        return {"error": str(exc)[:300], "results": []}


def _normalize_dataset(pkg: dict[str, Any]) -> dict[str, Any]:
    """Extract a normalized dataset record from a CKAN package."""
    resources = []
    for res in pkg.get("resources", []):
        resources.append(
            {
                "id": res.get("id"),
                "name": res.get("name"),
                "format": res.get("format"),
                "url": res.get("url"),
                "size": res.get("size"),
                "mimetype": res.get("mimetype"),
            }
        )
    org = pkg.get("organization", {}) or {}
    extras = {}
    for ex in pkg.get("extras", []):
        if isinstance(ex, dict) and ex.get("key"):
            extras[ex["key"]] = ex.get("value")
    return {
        "id": pkg.get("id"),
        "title": pkg.get("title"),
        "name": pkg.get("name"),
        "notes": (pkg.get("notes") or "")[:800],
        "groups": [g.get("name") for g in pkg.get("groups", [])],
        "org": org.get("title"),
        "org_id": org.get("id"),
        "resources": resources,
        "tags": [t.get("name") for t in pkg.get("tags", [])],
        "metadata_created": pkg.get("metadata_created"),
        "metadata_modified": pkg.get("metadata_modified"),
        "extras": extras,
        "license": pkg.get("license_id"),
    }


# ---------------------------------------------------------------------------
# Harvest log (SQLite)
# ---------------------------------------------------------------------------


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def init_harvest_log() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_HARVEST_LOG_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portal_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                datasets_found INTEGER DEFAULT 0,
                datasets_harvested INTEGER DEFAULT 0,
                error TEXT,
                duration_ms REAL
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _log_harvest_start(portal_id: str) -> int:
    conn = sqlite3.connect(_db_path(), timeout=5.0)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        f"INSERT INTO {_HARVEST_LOG_TABLE} (portal_id, started_at, status) VALUES (?, ?, 'running')",
        (portal_id, now),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id or 0


def _log_harvest_finish(
    row_id: int,
    *,
    status: str,
    datasets_found: int,
    datasets_harvested: int,
    error: str | None,
    duration_ms: float,
) -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"UPDATE {_HARVEST_LOG_TABLE} SET finished_at=?, status=?, datasets_found=?, datasets_harvested=?, error=?, duration_ms=? WHERE id=?",
            (
                now,
                status,
                datasets_found,
                datasets_harvested,
                error,
                duration_ms,
                row_id,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_harvest_log(limit: int = 20) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT * FROM {_HARVEST_LOG_TABLE} ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Core harvest logic
# ---------------------------------------------------------------------------


async def search_portal(
    portal_id: str,
    *,
    query: str | None = None,
    group: str | None = None,
    limit: int = 20,
    refresh: bool = False,
) -> dict[str, Any]:
    """Search datasets on a CKAN portal."""
    sources = load_sources()
    portal = sources.get(portal_id)
    if not portal:
        return {"error": f"Unknown portal: {portal_id}", "datasets": [], "count": 0}
    if not portal.get("enabled", True):
        return {"error": f"Portal disabled: {portal_id}", "datasets": [], "count": 0}

    cache_key = f"ckan:{portal_id}"
    connector = FeedConnector(
        cache_key,
        ttl_sec=float(portal.get("ttl_sec", 3600)),
        default_source=portal.get("name", portal_id),
    )
    subkey = f"search:{query or 'all'}:{group or 'all'}:{limit}"
    if not refresh:
        hit = connector.get_cached(subkey)
        if hit is not None:
            return hit

    params: dict[str, Any] = {"rows": min(limit, 200)}
    if query:
        params["q"] = query
    if group:
        params["groups"] = group

    api_key = _resolve_api_key(portal)
    result = await _ckan_request(
        portal["url"], "package_search", params, api_key=api_key
    )

    if result.get("error"):
        return connector.build(
            FeedEnvelope(
                count=0, source=portal.get("name", portal_id), error=result["error"]
            ),
            persist=False,
            subkey=subkey,
            datasets=[],
            total=0,
        )

    datasets = [_normalize_dataset(pkg) for pkg in result.get("results", [])[:limit]]
    total = result.get("count", len(datasets))
    return connector.build(
        FeedEnvelope(count=len(datasets), source=portal.get("name", portal_id)),
        subkey=subkey,
        datasets=datasets,
        total=total,
    )


async def harvest_portal(
    portal_id: str,
    *,
    limit: int = 50,
    group: str | None = None,
) -> dict[str, Any]:
    """Full harvest: fetch datasets, persist to feed_cache, optionally FtM ingest."""
    sources = load_sources()
    portal = sources.get(portal_id)
    if not portal:
        return {"error": f"Unknown portal: {portal_id}", "harvested": 0}

    log_id = _log_harvest_start(portal_id)
    t0 = time.monotonic()

    search_result = await search_portal(
        portal_id, group=group, limit=limit, refresh=True
    )

    datasets = search_result.get("datasets", [])
    found = len(datasets)

    # Persist to feed_cache
    cache_key = f"ckan:{portal_id}"
    try:
        import feed_registry

        feed_registry.write(
            cache_key,
            {
                "count": found,
                "source": portal.get("name", portal_id),
                "updated": datetime.now(timezone.utc).isoformat(),
                "datasets": datasets,
            },
        )
    except Exception as exc:
        logger.warning("feed_cache write failed for %s: %s", portal_id, exc)

    # Optional FtM ingest if mapping is configured
    ingested = 0
    mapping_name = portal.get("ingest_mapping")
    if mapping_name and datasets:
        try:
            from ingest.mapping_runner import load_mapping, run_mapping

            mapping = load_mapping(mapping_name)
            run_mapping(datasets, mapping, dataset=f"ckan_{portal_id}")
            ingested = found
        except Exception as exc:
            logger.warning("FtM ingest failed for %s: %s", portal_id, exc)

    duration_ms = (time.monotonic() - t0) * 1000
    status = "ok" if not search_result.get("error") else "error"
    _log_harvest_finish(
        log_id,
        status=status,
        datasets_found=found,
        datasets_harvested=ingested,
        error=search_result.get("error"),
        duration_ms=duration_ms,
    )

    return {
        "portal_id": portal_id,
        "status": status,
        "datasets_found": found,
        "datasets_harvested": ingested,
        "error": search_result.get("error"),
        "duration_ms": round(duration_ms, 1),
    }


async def harvest_all_portals(*, limit: int = 50) -> list[dict[str, Any]]:
    """Harvest all enabled portals sequentially."""
    sources = load_sources()
    results: list[dict[str, Any]] = []
    for pid in sorted(sources):
        if not sources[pid].get("enabled", True):
            continue
        result = await harvest_portal(pid, limit=limit)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("/portals")
async def api_list_portals():
    """List configured CKAN portals."""
    return {
        "enabled": _enabled(),
        "portals": list_portals(),
        "count": len(list_portals()),
    }


@router.get("/{portal_id}/search")
async def api_search_portal(
    portal_id: str,
    q: str | None = Query(None, description="Full-text search"),
    group: str | None = Query(None, description="CKAN group filter"),
    limit: int = Query(20, ge=1, le=200),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Search datasets on a CKAN portal."""
    return await search_portal(
        portal_id, query=q, group=group, limit=limit, refresh=refresh
    )


@router.post("/{portal_id}/harvest")
async def api_harvest_portal(
    portal_id: str,
    limit: int = Query(50, ge=1, le=500),
    group: str | None = Query(None),
):
    """Harvest datasets from a CKAN portal into feed_cache + FtM."""
    if not _enabled():
        return {
            "error": "CKAN harvester disabled (WORLDBASE_CKAN_HARVESTER=0)",
            "harvested": 0,
        }
    return await harvest_portal(portal_id, limit=limit, group=group)


@router.post("/harvest-all")
async def api_harvest_all(
    limit: int = Query(50, ge=1, le=500),
):
    """Harvest all enabled CKAN portals."""
    if not _enabled():
        return {
            "error": "CKAN harvester disabled (WORLDBASE_CKAN_HARVESTER=0)",
            "results": [],
        }
    results = await harvest_all_portals(limit=limit)
    return {"results": results, "count": len(results)}


@router.get("/harvest/log")
async def api_harvest_log(limit: int = Query(20, ge=1, le=100)):
    """Recent harvest runs."""
    return {"logs": get_harvest_log(limit=limit)}
