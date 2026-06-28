"""Onion directory feed — curated legitimate .onion services for OSINT/Threat-Intelligence.

Pulls from two CSV files in the **real-world-onion-sites** repo (Alec Muffett, GitHub):
1. ``master.csv`` — curated onion services categorised by news, tech, government, etc.
2. ``securedrop-api.csv`` — SecureDrop directory of newsroom whistle-blowing instances.

Both are plain CSV files served via ``raw.githubusercontent.com`` — no auth required.

No illegal marketplaces, no drug/weapon sites.  All entries are publicly documented
and verified by their respective maintainers.

Data is cached in-memory with TTL, optionally ingested as FtM ``Domain`` entities,
and surfaced in the briefing digest when ``WORLDBASE_BRIEFING_ONION_DIR=1``.

Env:
  WORLDBASE_ONION_DIR=1              (default off, opt-in)
  WORLDBASE_ONION_DIR_CACHE_SEC=7200 (2h default — curated lists change slowly)
  WORLDBASE_BRIEFING_ONION_DIR=0     (opt-in briefing block)
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query

from config import get_config
from feeds.envelope import utc_now_iso
from feeds.runner import FeedConnector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/onion-directory", tags=["onion-directory"])

_UA = {"User-Agent": "WorldBase/1.0 (OSINT research; onion directory)"}
_TIMEOUT = 30.0

_CONNECTOR = FeedConnector(
    "onion_directory",
    ttl_sec=7200.0,
    default_source="real-world-onion-sites+securedrop",
)

# Source URLs (raw GitHub CSV — no auth required)
_RWOS_BASE = (
    "https://raw.githubusercontent.com/alecmuffett/real-world-onion-sites/master"
)
_RWOS_MASTER_CSV = f"{_RWOS_BASE}/master.csv"
_RWOS_SECUREDROP_CSV = f"{_RWOS_BASE}/securedrop-api.csv"

# Source reliability for provenance (curated, verified lists)
SOURCE_RELIABILITY: dict[str, float] = {
    "real-world-onion-sites": 0.7,
    "securedrop": 0.8,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = asyncio.Lock()


def _enabled() -> bool:
    return get_config().onion_dir_enabled


def _cache_ttl() -> int:
    return max(300, getattr(get_config(), "onion_dir_cache_sec", 7200))


async def _get_cached(key: str) -> dict[str, Any] | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry.get("_ts", 0)) < _cache_ttl():
            return entry.get("data")
        return None


async def _set_cached(key: str, data: dict[str, Any]) -> None:
    async with _cache_lock:
        _cache[key] = {"data": data, "_ts": time.time()}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

# Extract hostname from URL: https://xxx.onion/path -> xxx.onion
_ONION_HOST_RE = re.compile(r"([a-z0-9.-]{16,80}\.onion)", re.IGNORECASE)


def _extract_onion_host(url: str) -> str:
    """Extract the .onion hostname from a URL or bare address."""
    m = _ONION_HOST_RE.search(url or "")
    if m:
        return m.group(1).lower()
    # Maybe it's already a bare hostname
    s = (url or "").strip().lower()
    if s.endswith(".onion"):
        return s
    return ""


def _parse_rwos_csv(
    csv_text: str, source: str = "real-world-onion-sites"
) -> list[dict[str, Any]]:
    """Parse master.csv from real-world-onion-sites repo.

    Columns: category,flaky,site_name,onion_url,onion_name,proof_url,comment
    """
    sites: list[dict[str, Any]] = []
    if not csv_text or not csv_text.strip():
        return sites
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        onion_url = (row.get("onion_url") or "").strip()
        onion = _extract_onion_host(onion_url)
        if not onion:
            continue
        name = (row.get("site_name") or "").strip()
        if not name:
            name = onion
        category = (row.get("category") or "unknown").strip()
        proof = (row.get("proof_url") or "").strip()
        comment = (row.get("comment") or "").strip()
        sites.append(
            {
                "name": name,
                "onion": onion,
                "category": category,
                "source": source,
                "proof_url": proof,
                "comment": comment,
            }
        )
    return sites


def _parse_securedrop_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse securedrop-api.csv from real-world-onion-sites repo.

    Columns: flaky,category,site_name,onion_name,onion_url,proof_url,comment
    """
    return _parse_rwos_csv(csv_text, source="securedrop")


def _normalise_site(site: dict[str, Any]) -> dict[str, Any]:
    """Normalise a parsed site into an FtM-ready dict."""
    return {
        "name": site["name"],
        "onion": site["onion"],
        "category": site.get("category", "unknown"),
        "source": site.get("source", "unknown"),
        "schema": "Domain",
        "first_seen": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# FtM ingestion
# ---------------------------------------------------------------------------


def _ingest_ftm(sites: list[dict[str, Any]]) -> dict[str, Any]:
    """Ingest onion sites as FtM Domain entities.

    Each site becomes a ``Domain`` entity with provenance metadata.  Fail-soft.
    """
    if not sites:
        return {"count": 0, "ids": [], "error": None}
    try:
        import ftm_query

        ids: list[str] = []
        seen_at = datetime.now(timezone.utc).isoformat()
        dataset = "onion_directory"

        for site in sites:
            onion = site["onion"]
            name = site["name"]
            category = site.get("category", "unknown")
            source = site.get("source", "unknown")

            props: dict[str, Any] = {
                "name": [onion],
            }
            # Store the organisation name as a statement
            props["summary"] = [f"{name} ({category}) — onion service via {source}"]
            props["source"] = [source]
            props["confidence"] = [str(SOURCE_RELIABILITY.get(source, 0.5))]

            entity = ftm_query.make_entity("Domain", [onion], props)
            ftm_query.upsert(entity, dataset=dataset, seen_at=seen_at)
            ids.append(entity.id)

        return {"count": len(ids), "ids": ids, "error": None}
    except Exception as exc:
        logger.warning("onion directory FtM ingest failed: %s", exc)
        return {"count": 0, "ids": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------


async def _gather_directory() -> dict[str, Any]:
    """Fetch all sources in parallel and merge into a unified directory."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
        master_task = client.get(_RWOS_MASTER_CSV)
        sd_task = client.get(_RWOS_SECUREDROP_CSV)

        errors: list[str] = []
        master_text = ""
        sd_text = ""

        try:
            resp = await master_task
            resp.raise_for_status()
            master_text = resp.text
        except Exception as e:
            errors.append(f"master.csv: {e}")

        try:
            resp = await sd_task
            resp.raise_for_status()
            sd_text = resp.text
        except Exception as e:
            errors.append(f"securedrop-api.csv: {e}")

    # Parse all sources
    sites: list[dict[str, Any]] = []
    if master_text:
        sites.extend(_parse_rwos_csv(master_text))
    if sd_text:
        sites.extend(_parse_securedrop_csv(sd_text))

    # Deduplicate by onion address
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for site in sites:
        onion = site["onion"]
        if onion not in seen:
            seen.add(onion)
            deduped.append(_normalise_site(site))

    # Categorise
    by_category: dict[str, int] = {}
    for s in deduped:
        cat = s["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    return {
        "count": len(deduped),
        "sites": deduped,
        "categories": by_category,
        "sources": sorted({s["source"] for s in deduped}),
        "updated": utc_now_iso(),
        "error": "; ".join(errors) if errors else None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_directory(refresh: bool = False) -> dict[str, Any]:
    """Get the onion directory. Cached with TTL."""
    if not _enabled():
        return {
            "count": 0,
            "sites": [],
            "sources": [],
            "error": "onion_directory disabled",
        }

    cache_key = "directory"
    if not refresh:
        cached = await _get_cached(cache_key)
        if cached:
            return cached

    try:
        result = await _gather_directory()
        result["stale"] = False
        await _set_cached(cache_key, result)
        return result
    except Exception as exc:
        stale = _cache.get(cache_key, {}).get("data")
        if stale:
            stale = dict(stale)
            stale["stale"] = True
            stale["error"] = str(exc)
            return stale
        return {
            "count": 0,
            "sites": [],
            "sources": [],
            "error": str(exc),
            "stale": True,
        }


async def gather_onion_directory_digest(limit: int = 20) -> dict[str, Any]:
    """Gather onion directory summary for the briefing digest.

    Returns a dict with ``enabled``, ``count``, ``lines``, ``categories``.
    Fail-soft when disabled or no data.
    """
    cfg = get_config()
    if not _enabled() or not getattr(cfg, "briefing_onion_dir", False):
        return {
            "enabled": False,
            "count": 0,
            "lines": [],
            "categories": {},
        }

    try:
        data = await get_directory()
        sites = data.get("sites", [])
        lines: list[str] = []
        for s in sites[:limit]:
            name = s.get("name", "?")
            cat = s.get("category", "?")
            lines.append(f"- {name} ({cat}) — {s['onion'][:20]}…")

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "categories": data.get("categories", {}),
            "sources": data.get("sources", []),
        }
    except Exception:
        return {
            "enabled": True,
            "count": 0,
            "lines": [],
            "categories": {},
        }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def directory_endpoint(
    refresh: bool = Query(False, description="Bypass cache"),
    ingest: bool = Query(False, description="Ingest results as FtM Domain entities"),
):
    """Curated onion directory: real-world-onion-sites + SecureDrop. Cached 2h."""
    if not _enabled():
        return _CONNECTOR.empty_payload("onion_directory disabled")

    result = await get_directory(refresh=refresh)

    if ingest and result.get("count", 0) > 0:
        enrich = _ingest_ftm(result["sites"])
        result["ingested"] = enrich.get("count", 0)
        result["ingest_ids"] = enrich.get("ids", [])
        result["ingest_error"] = enrich.get("error")

    return result


@router.post("/ingest")
async def ingest_endpoint(
    refresh: bool = Query(False, description="Bypass cache before ingesting"),
):
    """Fetch onion directory and ingest all sites as FtM Domain entities."""
    if not _enabled():
        return {"count": 0, "ids": [], "error": "onion_directory disabled"}

    result = await get_directory(refresh=refresh)
    sites = result.get("sites", [])
    enrich = _ingest_ftm(sites)

    return {
        "total_sites": len(sites),
        "ingested": enrich.get("count", 0),
        "ids": enrich.get("ids", []),
        "error": enrich.get("error"),
        "sources": result.get("sources", []),
    }


@router.get("/status")
async def status_endpoint():
    """Onion directory feed status: sources, cache age, enabled state."""
    return {
        "enabled": _enabled(),
        "sources": ["master.csv", "securedrop-api.csv"],
        "cache_ttl_sec": _cache_ttl(),
        "cached": "directory" in _cache,
        "cache_age_sec": (
            time.time() - _cache["directory"]["_ts"] if "directory" in _cache else None
        ),
        "tor_proxy": bool(get_config().darkweb_tor_proxy),
    }
