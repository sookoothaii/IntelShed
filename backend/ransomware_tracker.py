"""Ransomware leak-site intelligence (P8.6) — Ransomware.live + RansomLook API clients.

Two clearnet JSON APIs are used as primary sources (no Tor required):
- Ransomware.live  — https://api.ransomware.live/v2  (public, no auth)
- RansomLook       — https://www.ransomlook.io/api   (public read, CC BY 4.0)

Both aggregate victim postings from ransomware gang leak sites.  Only public
metadata is collected (victim name, group, date, country, description, post
URL).  Leaked files are never downloaded or stored.

Data is normalised to a common schema, cached in-memory with TTL, optionally
ingested as FtM ``Event`` entities (type: ransomware), and surfaced in the
briefing digest when ``WORLDBASE_BRIEFING_RANSOMWARE=1``.

Env:
  WORLDBASE_RANSOMWARE=1            (default off, opt-in)
  WORLDBASE_RANSOMWARE_CACHE_SEC=3600
  WORLDBASE_BRIEFING_RANSOMWARE=0   (opt-in, requires WORLDBASE_RANSOMWARE=1)
  RANSOMLOOK_API_KEY=               (optional, for export endpoint only)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query

from config import get_config

router = APIRouter(prefix="/api/darkweb/ransomware", tags=["darkweb"])

_RL_BASE = "https://api.ransomware.live/v2"
_RLOOK_BASE = "https://www.ransomlook.io/api"
_UA = {"User-Agent": "WorldBase/1.0 (OSINT research; ransomware tracker)"}

# Source reliability for provenance scoring (unverified criminal claims).
SOURCE_RELIABILITY: dict[str, float] = {
    "ransomware.live": 0.25,
    "ransomlook": 0.25,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = asyncio.Lock()


def _cache_ttl() -> int:
    return max(60, get_config().ransomware_cache_sec)


def _is_fresh(key: str) -> bool:
    entry = _cache.get(key)
    if not entry:
        return False
    return (time.time() - entry.get("_ts", 0)) < _cache_ttl()


async def _get_cached(key: str) -> dict[str, Any] | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and _is_fresh(key):
            return entry.get("data")
        return None


async def _set_cached(key: str, data: dict[str, Any]) -> None:
    async with _cache_lock:
        _cache[key] = {"data": data, "_ts": time.time()}


# ---------------------------------------------------------------------------
# API clients
# ---------------------------------------------------------------------------


async def _fetch_ransomware_live_victims(limit: int = 100) -> list[dict[str, Any]]:
    """Fetch recent victims from Ransomware.live v2 API."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), headers=_UA
        ) as client:
            resp = await client.get(f"{_RL_BASE}/recentvictims")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data[:limit]
            return []
    except Exception:
        return []


async def _fetch_ransomware_live_groups() -> list[dict[str, Any]]:
    """Fetch active groups from Ransomware.live v2 API."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), headers=_UA
        ) as client:
            resp = await client.get(f"{_RL_BASE}/groups")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


async def _fetch_ransomlook_posts(days: int = 30) -> list[dict[str, Any]]:
    """Fetch recent posts from RansomLook API.

    The API returns ``{"posts": [...]}`` (dict), but older versions returned
    a bare list.  Both shapes are handled.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), headers=_UA
        ) as client:
            resp = await client.get(f"{_RLOOK_BASE}/posts", params={"days": days})
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("posts", [])
            return []
    except Exception:
        return []


async def _fetch_ransomlook_groups() -> list[dict[str, Any]]:
    """Fetch group list from RansomLook API."""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), headers=_UA
        ) as client:
            resp = await client.get(f"{_RLOOK_BASE}/groups")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return list(data.values())
            return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise_victim_rl(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Ransomware.live victim record."""
    return {
        "victim": row.get("post_title") or row.get("victim") or "",
        "group": row.get("group_name") or row.get("group") or "",
        "discovered": row.get("discovered") or "",
        "published": row.get("published") or "",
        "country": row.get("country") or "",
        "activity": row.get("activity") or "",
        "description": row.get("description") or "",
        "post_url": row.get("post_url") or "",
        "website": row.get("website") or "",
        "screenshot": row.get("screenshot") or "",
        "source": "ransomware.live",
    }


def _normalise_victim_rlook(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a RansomLook post record."""
    return {
        "victim": row.get("post_title") or "",
        "group": row.get("group_name") or "",
        "discovered": row.get("discovered") or "",
        "published": "",
        "country": row.get("country") or "",
        "activity": "",
        "description": row.get("description") or "",
        "post_url": row.get("post_url") or "",
        "website": "",
        "screenshot": "",
        "source": "ransomlook",
    }


def _normalise_group_rl(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Ransomware.live group record."""
    return {
        "name": row.get("name") or row.get("group_name") or "",
        "url": row.get("url") or row.get("onion_url") or "",
        "tor_url": row.get("tor_url") or "",
        "description": row.get("description") or "",
        "source": "ransomware.live",
        "active": row.get("active", True),
    }


def _normalise_group_rlook(row: dict[str, Any] | str) -> dict[str, Any]:
    """Normalise a RansomLook group record (may be a plain string name)."""
    if isinstance(row, str):
        return {
            "name": row,
            "url": "",
            "tor_url": "",
            "description": "",
            "source": "ransomlook",
            "active": True,
        }
    name = row.get("name") or row.get("group_name") or ""
    return {
        "name": name,
        "url": row.get("url") or "",
        "tor_url": row.get("onion_url") or "",
        "description": row.get("description") or "",
        "source": "ransomlook",
        "active": True,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_recent_victims(
    limit: int = 100, group: str | None = None, refresh: bool = False
) -> dict[str, Any]:
    """Fetch recent ransomware victims from both APIs.

    Returns a dict with ``count``, ``victims``, ``sources``, and optional ``error``.
    """
    if not get_config().ransomware_enabled:
        return {
            "count": 0,
            "victims": [],
            "sources": [],
            "error": "ransomware disabled",
        }

    cache_key = f"victims:{limit}:{group or 'all'}"
    if not refresh:
        cached = await _get_cached(cache_key)
        if cached:
            return cached

    rl_task = _fetch_ransomware_live_victims(limit=limit)
    rlook_task = _fetch_ransomlook_posts(days=30)
    rl_data, rlook_data = await asyncio.gather(rl_task, rlook_task)

    victims: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rl_data:
        v = _normalise_victim_rl(row)
        key = f"{v['group']}|{v['victim']}|{v['discovered']}"
        if key not in seen and v["victim"]:
            seen.add(key)
            victims.append(v)

    for row in rlook_data:
        v = _normalise_victim_rlook(row)
        key = f"{v['group']}|{v['victim']}|{v['discovered']}"
        if key not in seen and v["victim"]:
            seen.add(key)
            victims.append(v)

    if group:
        group_l = group.lower().replace("_", " ").strip()
        victims = [
            v
            for v in victims
            if v["group"].lower().replace("_", " ").strip() == group_l
        ]

    victims = victims[:limit]
    sources = sorted({v["source"] for v in victims})

    result = {
        "count": len(victims),
        "victims": victims,
        "sources": sources,
        "error": None,
    }
    await _set_cached(cache_key, result)
    return result


async def get_tracked_groups(refresh: bool = False) -> dict[str, Any]:
    """Fetch tracked ransomware groups from both APIs.

    Returns a dict with ``count``, ``groups``, ``sources``, and optional ``error``.
    """
    if not get_config().ransomware_enabled:
        return {"count": 0, "groups": [], "sources": [], "error": "ransomware disabled"}

    cache_key = "groups"
    if not refresh:
        cached = await _get_cached(cache_key)
        if cached:
            return cached

    rl_task = _fetch_ransomware_live_groups()
    rlook_task = _fetch_ransomlook_groups()
    rl_data, rlook_data = await asyncio.gather(rl_task, rlook_task)

    groups: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in rl_data:
        g = _normalise_group_rl(row)
        if g["name"] and g["name"].lower() not in seen:
            seen.add(g["name"].lower())
            groups.append(g)

    for row in rlook_data:
        g = _normalise_group_rlook(row)
        if g["name"] and g["name"].lower() not in seen:
            seen.add(g["name"].lower())
            groups.append(g)

    sources = sorted({g["source"] for g in groups})

    result = {
        "count": len(groups),
        "groups": groups,
        "sources": sources,
        "error": None,
    }
    await _set_cached(cache_key, result)
    return result


def ingest_victims_as_events(victims: list[dict[str, Any]]) -> dict[str, Any]:
    """Ingest ransomware victims as FtM Event entities.

    Each victim becomes an ``Event`` entity with ``type=ransomware``,
    ``startDate``, ``summary``, and provenance metadata.  Fail-soft.
    """
    if not victims:
        return {"count": 0, "ids": [], "error": None}
    try:
        import ftm_query

        ids: list[str] = []
        seen_at = datetime.now(timezone.utc).isoformat()
        for v in victims:
            group = v.get("group") or "unknown"
            victim_name = v.get("victim") or "unknown"
            discovered = v.get("discovered") or ""
            entity_id = ftm_query.make_entity_id(
                f"ransomware:{group}:{victim_name}:{discovered}"
            )
            props: dict[str, list[str]] = {
                "name": [f"Ransomware: {group} → {victim_name}"],
                "summary": [v.get("description") or f"{group} claims {victim_name}"],
                "type": ["ransomware"],
            }
            if discovered:
                props["startDate"] = [discovered]
            if v.get("country"):
                props["country"] = [v["country"]]
            if v.get("post_url"):
                props["sourceUrl"] = [v["post_url"]]
            props["source"] = [v.get("source", "ransomware.tracker")]
            props["confidence"] = ["0.25"]

            ent = ftm_query._proxy_with_id(entity_id, "Event", props)
            ftm_query.upsert(ent, dataset="ransomware", seen_at=seen_at)
            ids.append(entity_id)

        return {"count": len(ids), "ids": ids, "error": None}
    except Exception as exc:
        return {"count": 0, "ids": [], "error": str(exc)}


async def gather_ransomware_digest(limit: int = 10) -> dict[str, Any]:
    """Gather ransomware victim lines for the briefing digest.

    Returns a dict with ``enabled``, ``count``, ``lines``, ``victims``, ``sources``.
    Fail-soft when disabled or no data.
    """
    cfg = get_config()
    if not cfg.ransomware_enabled or not cfg.briefing_ransomware:
        return {"enabled": False, "count": 0, "lines": [], "victims": [], "sources": []}

    try:
        data = await get_recent_victims(limit=limit)
        victims = data.get("victims", [])
        lines: list[str] = []
        for v in victims[:limit]:
            group = v.get("group") or "?"
            victim_name = v.get("victim") or "?"
            country = v.get("country") or ""
            country_str = f" [{country}]" if country else ""
            discovered = v.get("discovered") or ""
            date_str = f" ({discovered[:10]})" if discovered else ""
            lines.append(f"- {group} → {victim_name}{country_str}{date_str}")

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "victims": victims[:limit],
            "sources": data.get("sources", []),
        }
    except Exception:
        return {"enabled": True, "count": 0, "lines": [], "victims": [], "sources": []}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/groups")
async def api_ransomware_groups(refresh: bool = Query(False)):
    """List tracked ransomware groups and their last known URLs."""
    return await get_tracked_groups(refresh=refresh)


@router.get("/victims")
async def api_ransomware_victims(
    group: str = Query("", description="Filter by group name"),
    limit: int = Query(100, ge=1, le=500),
    refresh: bool = Query(False),
):
    """Query parsed ransomware victims (live fetch + cached)."""
    return await get_recent_victims(limit=limit, group=group or None, refresh=refresh)


@router.post("/refresh")
async def api_ransomware_refresh():
    """Force refresh of ransomware tracker data from both APIs."""
    groups = await get_tracked_groups(refresh=True)
    victims = await get_recent_victims(limit=100, refresh=True)
    return {
        "groups_count": groups.get("count", 0),
        "victims_count": victims.get("count", 0),
        "sources": sorted(set(groups.get("sources", []) + victims.get("sources", []))),
        "error": groups.get("error") or victims.get("error"),
    }


@router.post("/ingest")
async def api_ransomware_ingest(
    group: str = Query("", description="Filter by group name"),
    limit: int = Query(50, ge=1, le=500),
):
    """Fetch recent victims and ingest them as FtM Event entities."""
    if not get_config().ransomware_enabled:
        return {"count": 0, "ids": [], "error": "ransomware disabled"}

    data = await get_recent_victims(limit=limit, group=group or None)
    victims = data.get("victims", [])
    summary = ingest_victims_as_events(victims)
    summary["victims_fetched"] = len(victims)
    summary["sources"] = data.get("sources", [])
    return summary
