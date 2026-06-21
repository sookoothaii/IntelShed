"""Humanitarian datasets — HDX (UN OCHA) CKAN search, no API key."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query

import feed_registry

router = APIRouter(prefix="/api/humanitarian", tags=["humanitarian"])

_HDX_SEARCH = "https://data.humdata.org/api/3/action/package_search"
_UA = {"User-Agent": "WorldBase/1.0 (HDX humanitarian research)"}
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = float(os.getenv("WORLDBASE_HDX_CACHE_SEC", "3600"))
_REFRESH_LOCK = asyncio.Lock()

# Southeast Asia / operator focus — OR-joined for HDX full-text search
_DEFAULT_QUERIES: tuple[str, ...] = (
    "thailand humanitarian",
    "myanmar refugee thailand border",
    "rohingya bangladesh",
    "southeast asia displacement",
)


def _parse_dataset(row: dict[str, Any]) -> dict[str, Any]:
    org = row.get("organization") or {}
    org_title = org.get("title") if isinstance(org, dict) else None
    tags = [t.get("name") for t in (row.get("tags") or []) if isinstance(t, dict) and t.get("name")]
    resources = row.get("resources") or []
    return {
        "id": row.get("id") or row.get("name"),
        "name": row.get("name"),
        "title": row.get("title") or row.get("name") or "Dataset",
        "organization": org_title,
        "modified": row.get("metadata_modified") or row.get("metadata_created"),
        "tags": tags[:8],
        "resource_count": len(resources),
        "url": f"https://data.humdata.org/dataset/{row.get('name')}" if row.get("name") else None,
    }


async def _search_hdx(client: httpx.AsyncClient, query: str, rows: int) -> list[dict]:
    try:
        r = await client.get(
            _HDX_SEARCH,
            params={"q": query, "rows": rows, "sort": "metadata_modified desc"},
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return []
    if not payload.get("success"):
        return []
    results = (payload.get("result") or {}).get("results") or []
    return [_parse_dataset(row) for row in results if isinstance(row, dict)]


async def fetch_humanitarian_datasets(
    *,
    queries: tuple[str, ...] | None = None,
    limit: int = 20,
) -> dict:
    queries = queries or _DEFAULT_QUERIES
    per_query = max(3, limit // len(queries))
    seen: set[str] = set()
    datasets: list[dict] = []

    async with httpx.AsyncClient(timeout=20.0, headers=_UA) as client:
        batches = await asyncio.gather(
            *(_search_hdx(client, q, per_query) for q in queries)
        )

    for batch in batches:
        for ds in batch:
            key = (ds.get("id") or ds.get("title") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            datasets.append(ds)

    datasets.sort(key=lambda d: d.get("modified") or "", reverse=True)
    datasets = datasets[:limit]
    return {
        "count": len(datasets),
        "datasets": datasets,
        "queries": list(queries),
        "source": "hdx",
        "updated": datetime.now(timezone.utc).isoformat(),
    }


async def get_humanitarian(*, limit: int = 20, refresh: bool = False) -> dict:
    cache_key = f"humanitarian:{limit}"
    if not refresh:
        hit = _CACHE.get(cache_key)
        if hit and (time.time() - hit[0]) < _TTL:
            return hit[1]

    async with _REFRESH_LOCK:
        hit = _CACHE.get(cache_key)
        if not refresh and hit and (time.time() - hit[0]) < _TTL:
            return hit[1]

        stale = hit[1] if hit else None
        try:
            out = await fetch_humanitarian_datasets(limit=limit)
        except Exception as exc:
            if stale:
                s = dict(stale)
                s["stale"] = True
                s["error"] = str(exc)[:120]
                return s
            return {"count": 0, "datasets": [], "error": str(exc)[:120]}

        if out.get("datasets"):
            feed_registry.write_auto("humanitarian", out)
            _CACHE[cache_key] = (time.time(), out)
        elif stale:
            s = dict(stale)
            s["stale"] = True
            return s
        else:
            _CACHE[cache_key] = (time.time(), out)
        return out


@router.get("")
async def humanitarian_datasets(
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = False,
):
    """Recent HDX humanitarian datasets for Southeast Asia / Thailand context."""
    return await get_humanitarian(limit=limit, refresh=refresh)
