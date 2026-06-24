"""GDELT DOC API — global news pulse (no key; respect 5s rate limit via cache)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Query

import feed_registry

from stac_bridge import REGION_PRESETS

router = APIRouter(prefix="/api/gdelt", tags=["gdelt"])

# GDELT DOC/GEO: one request per ~5s globally; serialize + adaptive backoff on 429.
_GDELT_LOCK = asyncio.Lock()
_GDELT_LAST_CALL = 0.0
_GDELT_BACKOFF_UNTIL = 0.0
_GDELT_CONSECUTIVE_429 = 0
_GDELT_MIN_INTERVAL = float(os.getenv("WORLDBASE_GDELT_MIN_INTERVAL", "5.5"))
_GDELT_BACKOFF_BASE = float(os.getenv("WORLDBASE_GDELT_BACKOFF_SEC", "45"))
_GDELT_BACKOFF_MAX = float(os.getenv("WORLDBASE_GDELT_BACKOFF_MAX_SEC", "300"))
_GDELT_LOCAL_MAX_RETRIES = int(os.getenv("WORLDBASE_GDELT_LOCAL_RETRIES", "2"))
_GDELT_LOCAL_RETRY_MAX_SEC = float(os.getenv("WORLDBASE_GDELT_LOCAL_RETRY_MAX_SEC", "20"))
_GDELT_CACHE_LOCAL_SEC = int(os.getenv("WORLDBASE_GDELT_CACHE_LOCAL_SEC", "600"))
_GDELT_CACHE_GLOBAL_SEC = int(os.getenv("WORLDBASE_GDELT_CACHE_GLOBAL_SEC", "900"))
_GDELT_HTTP_LOCAL_SEC = float(os.getenv("WORLDBASE_GDELT_HTTP_LOCAL_SEC", "20"))
_GDELT_HTTP_GLOBAL_SEC = float(os.getenv("WORLDBASE_GDELT_HTTP_GLOBAL_SEC", "30"))
_GDELT_COLD_START_SEC = float(os.getenv("WORLDBASE_GDELT_COLD_START_SEC", "18"))
_LOCAL_DOC_TIMESPAN = (os.getenv("WORLDBASE_GDELT_LOCAL_TIMESPAN", "24h") or "24h").strip()
_LOCAL_DOC_MAX_AGE_H = float(os.getenv("WORLDBASE_GDELT_LOCAL_MAX_AGE_H", "24"))

Priority = Literal["local", "global"]

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT)"}
_CACHE: dict[str, tuple[float, dict]] = {}
_INFLIGHT: dict[str, asyncio.Task] = {}
_LOG = logging.getLogger(__name__)

# httpx logs every request at INFO — noisy when GDELT returns 429 (handled fail-soft).
logging.getLogger("httpx").setLevel(logging.WARNING)

# Rotating civic queries — one per cache refresh (global pulse)
_QUERIES = [
    "(earthquake OR flood OR wildfire)",
    "(protest OR conflict OR violence)",
    "(cyberattack OR outage OR blackout)",
]

# Operator-home DOC queries for briefing LOCAL block (GDELT DOC 2.0 syntax)
_REGION_DOC_QUERIES: dict[str, str] = {
    "thailand": (
        '(thailand OR bangkok OR phuket OR chiangmai OR "chiang mai" OR thai OR andaman)'
    ),
    "bangkok": '(bangkok OR "greater bangkok" OR thailand) sourcecountry:TH',
    "phuket": '(phuket OR andaman OR krabi OR thailand)',
    "mekong-delta": '(mekong OR "mekong delta" OR vietnam OR cambodia OR laos OR thailand)',
    "germany": '(germany OR deutschland OR berlin OR munich OR hamburg OR rhein)',
    "rhein": '(rhein OR rhine OR germany OR deutschland OR "north rhine")',
}

_REGION_GEO_QUERIES: dict[str, str] = {
    "thailand": "(thailand OR bangkok OR myanmar OR cambodia) (conflict OR protest OR earthquake OR flood OR storm)",
    "bangkok": "(bangkok OR thailand) (flood OR protest OR earthquake OR fire)",
    "germany": "(germany OR deutschland) (flood OR protest OR earthquake OR storm)",
    "rhein": "(germany OR rhein OR rhine) (flood OR storm OR earthquake)",
}


def _operator_region() -> str:
    return os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()


def _resolve_region(region: str | None) -> str:
    if not region:
        return _operator_region()
    return region.strip().lower()


def parse_gdelt_seendate(raw: str | None) -> datetime | None:
    """Parse GDELT DOC seendate (``20260430T204500Z``)."""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw).strip(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_gdelt_article_fresh(article: dict, *, max_age_hours: float | None = None) -> bool:
    """True when article seendate is within the briefing window."""
    max_h = _LOCAL_DOC_MAX_AGE_H if max_age_hours is None else max_age_hours
    seen = parse_gdelt_seendate(article.get("seendate"))
    if seen is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_h)
    return seen >= cutoff


def filter_local_pulse_articles(
    articles: list[dict] | None,
    *,
    apply_freshness: bool = True,
) -> list[dict]:
    """Drop sports/tourism-promo headlines; optionally enforce the 24h freshness window."""
    from newsdata_bridge import is_sports_content, is_tourism_promo_content

    kept: list[dict] = []
    for art in articles or []:
        title = art.get("title") or ""
        desc = art.get("description") or ""
        if is_sports_content(title=title, description=desc):
            continue
        if is_tourism_promo_content(title=title, description=desc):
            continue
        if apply_freshness and not is_gdelt_article_fresh(art):
            continue
        kept.append(art)
    return kept


def finalize_local_pulse(out: dict | None, *, apply_freshness: bool | None = None) -> dict:
    """Apply briefing filters and refresh count on a local pulse payload."""
    if not out:
        return {"count": 0, "articles": []}
    if apply_freshness is None:
        # Stale-while-revalidate / disk fallback: keep aged headlines so trust
        # probes and HUD do not report count=0 while GDELT backoff refreshes.
        apply_freshness = not bool(out.get("stale"))
    articles = filter_local_pulse_articles(out.get("articles"), apply_freshness=apply_freshness)
    result = dict(out)
    result["articles"] = articles
    result["count"] = len(articles)
    return result


def _region_bbox(region: str) -> list[float] | None:
    preset = REGION_PRESETS.get(region)
    if not preset:
        return None
    return list(preset["bbox"])


def _in_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


def _backoff_seconds() -> float:
    if _GDELT_CONSECUTIVE_429 <= 0:
        return _GDELT_BACKOFF_BASE
    exp = min(_GDELT_CONSECUTIVE_429 - 1, 8)
    return min(_GDELT_BACKOFF_BASE * (1.5**exp), _GDELT_BACKOFF_MAX)


def _in_backoff() -> bool:
    return time.monotonic() < _GDELT_BACKOFF_UNTIL


def _backoff_remaining_sec() -> int:
    if not _in_backoff():
        return 0
    return max(1, int(_GDELT_BACKOFF_UNTIL - time.monotonic()))


def _gdelt_rate_limited() -> None:
    global _GDELT_BACKOFF_UNTIL, _GDELT_CONSECUTIVE_429
    _GDELT_CONSECUTIVE_429 = min(_GDELT_CONSECUTIVE_429 + 1, 10)
    _GDELT_BACKOFF_UNTIL = time.monotonic() + _backoff_seconds()


def _gdelt_success() -> None:
    global _GDELT_CONSECUTIVE_429, _GDELT_BACKOFF_UNTIL
    if _GDELT_CONSECUTIVE_429 > 0:
        _GDELT_CONSECUTIVE_429 -= 1
    if _GDELT_CONSECUTIVE_429 == 0:
        _GDELT_BACKOFF_UNTIL = 0.0


async def _gdelt_wait_retry(attempt: int) -> None:
    # In-request spacing aligned with GDELT ~5s limit (not full backoff window).
    base = min(6.0 * (2**attempt), 30.0)
    jitter = random.uniform(0, base * 0.15)
    await asyncio.sleep(base + jitter)


async def _gdelt_throttle(*, priority: Priority = "global") -> str | None:
    """Serialize GDELT HTTP calls. Local priority waits out backoff; global skips."""
    global _GDELT_LAST_CALL

    while True:
        now = time.monotonic()
        if now < _GDELT_BACKOFF_UNTIL:
            if priority == "global":
                return f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
            await asyncio.sleep(min(_GDELT_BACKOFF_UNTIL - now, 30.0))
            continue

        async with _GDELT_LOCK:
            now = time.monotonic()
            gap = _GDELT_MIN_INTERVAL - (now - _GDELT_LAST_CALL)
            if gap <= 0:
                _GDELT_LAST_CALL = time.monotonic()
                return None

        await asyncio.sleep(gap)


def _cache_fresh(key: str, ttl_sec: int) -> dict | None:
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < ttl_sec:
        return cached[1]
    return None


def _cache_any(key: str) -> dict | None:
    cached = _CACHE.get(key)
    return cached[1] if cached else None


def _stale_response(key: str, *, error: str | None = None, extra: dict | None = None) -> dict | None:
    stale = _CACHE.get(key)
    if not stale:
        return None
    out = stale[1].copy()
    out["stale"] = True
    if error:
        out["error"] = error
    if extra:
        out.update(extra)
    return out


def _http_timeout(priority: Priority, *, geo: bool = False) -> float:
    if priority == "local":
        return _GDELT_HTTP_LOCAL_SEC + (5.0 if geo else 0.0)
    return _GDELT_HTTP_GLOBAL_SEC + (10.0 if geo else 0.0)


async def _single_flight(key: str, factory):
    task = _INFLIGHT.get(key)
    if task is not None and not task.done():
        return await asyncio.shield(task)
    task = asyncio.create_task(factory())
    _INFLIGHT[key] = task
    try:
        return await task
    finally:
        if _INFLIGHT.get(key) is task:
            _INFLIGHT.pop(key, None)


def _kick_refresh(key: str, factory) -> None:
    task = _INFLIGHT.get(key)
    if task is not None and not task.done():
        return

    async def _run():
        try:
            await factory()
        except Exception:
            _LOG.debug("GDELT background refresh failed for %s", key, exc_info=True)

    task = asyncio.create_task(_run())
    _INFLIGHT[key] = task

    def _done(done_task: asyncio.Task) -> None:
        if _INFLIGHT.get(key) is done_task:
            _INFLIGHT.pop(key, None)

    task.add_done_callback(_done)


async def _cold_start_or_swr(
    key: str,
    *,
    reg: str,
    query: str,
    refresh: bool,
    refresh_factory,
    empty: dict,
) -> dict:
    cached = _cache_any(key)
    if not refresh:
        if cached:
            out = cached.copy()
            out["stale"] = True
            return out
        return empty

    if cached:
        out = cached.copy()
        out["stale"] = True
        _kick_refresh(key, refresh_factory)
        return out

    async def _cold_fetch():
        try:
            return await asyncio.wait_for(refresh_factory(), timeout=_GDELT_COLD_START_SEC)
        except asyncio.TimeoutError:
            _kick_refresh(key, refresh_factory)
            warming = empty.copy()
            warming["warming"] = True
            warming["error"] = "GDELT fetch slow; warming cache in background"
            return warming

    return await _single_flight(key, _cold_fetch)


async def _fetch_doc_articles(
    query: str,
    maxrecords: int = 40,
    *,
    priority: Priority = "global",
    timespan: str | None = None,
) -> tuple[list[dict], str | None]:
    max_retries = _GDELT_LOCAL_MAX_RETRIES if priority == "local" else 1
    last_err: str | None = None
    retry_started = time.monotonic()

    for attempt in range(max_retries):
        if priority == "local" and (time.monotonic() - retry_started) > _GDELT_LOCAL_RETRY_MAX_SEC:
            return [], last_err or "GDELT local retry budget exceeded"

        throttle_err = await _gdelt_throttle(priority=priority)
        if throttle_err:
            last_err = throttle_err
            if priority == "local" and attempt < max_retries - 1:
                await _gdelt_wait_retry(attempt)
                continue
            return [], last_err

        try:
            async with httpx.AsyncClient(timeout=_http_timeout(priority), headers=_UA) as client:
                r = await client.get(
                    "https://api.gdeltproject.org/api/v2/doc/doc",
                    params={
                        "query": query,
                        "mode": "ArtList",
                        "maxrecords": maxrecords,
                        "format": "json",
                        **({"timespan": timespan} if timespan else {}),
                    },
                )
                if r.status_code == 429:
                    _gdelt_rate_limited()
                    last_err = f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
                    if priority == "local" and attempt < max_retries - 1:
                        await _gdelt_wait_retry(attempt)
                        continue
                    return [], last_err
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            last_err = str(e)
            if priority == "local" and attempt < max_retries - 1:
                await _gdelt_wait_retry(attempt)
                continue
            return [], last_err

        articles = []
        for art in data.get("articles") or []:
            articles.append({
                "title": art.get("title"),
                "url": art.get("url"),
                "seendate": art.get("seendate"),
                "domain": art.get("domain"),
                "language": art.get("language"),
                "sourcecountry": art.get("sourcecountry"),
            })
        _gdelt_success()
        return articles, None

    return [], last_err


async def _fetch_geo_events(
    query: str,
    timespan: str,
    maxrecords: int,
    bbox: list[float] | None = None,
    *,
    priority: Priority = "global",
) -> tuple[list[dict], str | None]:
    max_retries = _GDELT_LOCAL_MAX_RETRIES if priority == "local" else 1
    last_err: str | None = None
    retry_started = time.monotonic()

    for attempt in range(max_retries):
        if priority == "local" and (time.monotonic() - retry_started) > _GDELT_LOCAL_RETRY_MAX_SEC:
            return [], last_err or "GDELT local retry budget exceeded"

        throttle_err = await _gdelt_throttle(priority=priority)
        if throttle_err:
            last_err = throttle_err
            if priority == "local" and attempt < max_retries - 1:
                await _gdelt_wait_retry(attempt)
                continue
            return [], last_err

        try:
            async with httpx.AsyncClient(timeout=_http_timeout(priority, geo=True), headers=_UA) as client:
                r = await client.get(
                    "https://api.gdeltproject.org/api/v2/geo/geo",
                    params={
                        "query": query,
                        "mode": "PointData",
                        "format": "GeoJSON",
                        "timespan": timespan,
                        "maxrecords": min(maxrecords, 120),
                    },
                )
                if r.status_code == 429:
                    _gdelt_rate_limited()
                    last_err = f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
                    if priority == "local" and attempt < max_retries - 1:
                        await _gdelt_wait_retry(attempt)
                        continue
                    return [], last_err
                r.raise_for_status()
                gj = r.json()
        except Exception as e:
            last_err = str(e)
            if priority == "local" and attempt < max_retries - 1:
                await _gdelt_wait_retry(attempt)
                continue
            return [], last_err

        events = []
        for f in gj.get("features") or []:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None]
            lon, lat = coords[0], coords[1]
            if lat is None or lon is None:
                continue
            lat_f, lon_f = float(lat), float(lon)
            if bbox and not _in_bbox(lat_f, lon_f, bbox):
                continue
            events.append({
                "name": (props.get("name") or props.get("html") or "")[:200],
                "url": props.get("url") or props.get("shareimage"),
                "count": props.get("count"),
                "lat": lat_f,
                "lon": lon_f,
                "date": props.get("date"),
            })
        _gdelt_success()
        return events, None

    return [], last_err


def _current_global_query() -> str:
    slot = int(time.time() // _GDELT_CACHE_GLOBAL_SEC) % len(_QUERIES)
    return _QUERIES[slot]


async def _refresh_pulse_global(*, priority: Priority = "global") -> dict:
    query = _current_global_query()
    key = "pulse"
    articles, err = await _fetch_doc_articles(query, maxrecords=40, priority=priority)
    if err and not articles:
        stale = _stale_response(key, error=err, extra={"query": query})
        if stale:
            return stale
        disk = _load_pulse_global_registry()
        if disk:
            _CACHE[key] = (time.time(), disk)
            out = disk.copy()
            out["stale"] = True
            out["error"] = err
            return out
        return {"count": 0, "articles": [], "query": query, "error": err}

    out = {
        "count": len(articles),
        "query": query,
        "articles": articles,
        "cached_at": time.time(),
        "hint": "Headlines for Situation Board / chat context — geo layer uses GDACS + crises",
    }
    if err:
        out["error"] = err
        out["stale"] = True
    out.setdefault("stale", False)
    _CACHE[key] = (time.time(), out)
    try:
        feed_registry.write_auto("gdelt_pulse_global", out)
    except Exception:
        pass
    return out


@router.get("/pulse")
async def gdelt_pulse():
    """
    Recent global news themes with source countries (GDELT DOC 2.0).
    Cached 15 minutes to stay under GDELT rate limits.
    """
    key = "pulse"
    fresh = _cache_fresh(key, _GDELT_CACHE_GLOBAL_SEC)
    if fresh:
        return fresh

    query = _current_global_query()

    if _in_backoff():
        backoff_err = f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
        stale = _stale_response(key, error=backoff_err, extra={"query": query})
        if stale:
            return stale
        disk = _load_pulse_global_registry()
        if disk:
            _CACHE[key] = (time.time(), disk)
            out = disk.copy()
            out["stale"] = True
            out["error"] = backoff_err
            return out
        _kick_refresh("pulse", lambda: _refresh_pulse_global(priority="local"))
        return {"count": 0, "articles": [], "query": query, "error": backoff_err}

    out = await _refresh_pulse_global(priority="global")
    if int(out.get("count") or 0) == 0 and not _load_pulse_global_registry():
        _kick_refresh("pulse", lambda: _refresh_pulse_global(priority="local"))
    return out


async def _refresh_pulse_local(reg: str) -> dict:
    query = _REGION_DOC_QUERIES.get(reg) or f"({reg.replace('_', ' ')})"
    key = f"pulse:local:{reg}"
    articles, err = await _fetch_doc_articles(
        query,
        maxrecords=25,
        priority="local",
        timespan=_LOCAL_DOC_TIMESPAN,
    )
    articles = filter_local_pulse_articles(articles)
    if err and not articles:
        stale = _stale_response(key, error=err, extra={"region": reg, "query": query})
        if stale:
            return finalize_local_pulse(stale)
        return {
            "count": 0,
            "articles": [],
            "query": query,
            "region": reg,
            "error": err,
        }

    out = {
        "count": len(articles),
        "query": query,
        "region": reg,
        "articles": articles,
        "cached_at": time.time(),
        "hint": "Region-scoped headlines for security digest LOCAL section",
    }
    if err:
        out["error"] = err
        out["stale"] = True
    out.setdefault("stale", False)
    _CACHE[key] = (time.time(), out)
    try:
        feed_registry.write_auto(f"gdelt_pulse_local:{reg}", out)
    except Exception:
        pass
    return finalize_local_pulse(out)


def _load_pulse_local_registry(reg: str) -> dict | None:
    try:
        data = feed_registry.read(f"gdelt_pulse_local:{reg}")
        if not data:
            return None
        articles = data.get("articles") or []
        if not articles and int(data.get("count") or 0) <= 0:
            return None
        out = dict(data)
        out["stale"] = True
        return finalize_local_pulse(out)
    except Exception:
        pass
    return None


def _load_pulse_global_registry() -> dict | None:
    try:
        data = feed_registry.read("gdelt_pulse_global")
        if data and int(data.get("count") or 0) > 0:
            return data
    except Exception:
        pass
    return None


async def warmup_local_pulse(region: str | None = None) -> dict | None:
    """Startup / manual warm — populate local DOC pulse cache."""
    reg = _resolve_region(region)
    try:
        return await _refresh_pulse_local(reg)
    except Exception:
        _LOG.debug("GDELT local warmup failed for %s", reg, exc_info=True)
        return _load_pulse_local_registry(reg)


async def warmup_global_pulse() -> dict | None:
    """Startup warm — populate global DOC pulse cache (waits through GDELT backoff)."""
    last: dict | None = None
    for attempt in range(3):
        try:
            last = await _refresh_pulse_global(priority="local")
            if int((last or {}).get("count") or 0) > 0:
                return last
        except Exception:
            _LOG.debug("GDELT global warmup attempt %s failed", attempt + 1, exc_info=True)
        if attempt < 2:
            await asyncio.sleep(_GDELT_MIN_INTERVAL + 1.0)
    if last and int(last.get("count") or 0) > 0:
        return last
    disk = _load_pulse_global_registry()
    if disk:
        return disk
    return last


async def touch_local_pulse_cache() -> bool:
    """Keep feed_cache.cached_at fresh from memory/disk; refresh GDELT when TTL expired."""
    reg = _resolve_region(None)
    key = f"pulse:local:{reg}"
    reg_key = f"gdelt_pulse_local:{reg}"
    data = _cache_fresh(key, _GDELT_CACHE_LOCAL_SEC) or _cache_any(key)
    if not data or int(data.get("count") or 0) == 0:
        data = _load_pulse_local_registry(reg)
    if (not data or int(data.get("count") or 0) == 0) and not _in_backoff():
        try:
            data = await _refresh_pulse_local(reg)
        except Exception:
            _LOG.debug("GDELT local touch refresh failed for %s", reg, exc_info=True)
    if data and int(data.get("count") or 0) > 0:
        feed_registry.write_auto(reg_key, finalize_local_pulse(data))
        return True
    return False


async def gdelt_pulse_local_data(
    region: str | None = None,
    *,
    refresh: bool = True,
) -> dict:
    """
    Region-scoped GDELT DOC pulse. Set refresh=False for fast trust probes (cache only).
    """
    reg = _resolve_region(region)
    query = _REGION_DOC_QUERIES.get(reg) or f"({reg.replace('_', ' ')})"
    key = f"pulse:local:{reg}"
    fresh = _cache_fresh(key, _GDELT_CACHE_LOCAL_SEC)
    if fresh:
        return finalize_local_pulse(fresh)

    backoff_err = f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
    if _in_backoff():
        stale = _stale_response(key, error=backoff_err, extra={"region": reg, "query": query})
        if stale:
            return finalize_local_pulse(stale)
        cached = _cache_any(key)
        if cached:
            out = cached.copy()
            out["stale"] = True
            out["error"] = backoff_err
            return finalize_local_pulse(out)
        return {
            "count": 0,
            "articles": [],
            "query": query,
            "region": reg,
            "error": backoff_err,
        }

    empty = {
        "count": 0,
        "articles": [],
        "query": query,
        "region": reg,
        "error": "no cached local pulse yet",
    }

    if not refresh:
        cached = _cache_any(key)
        if cached and (cached.get("articles") or int(cached.get("count") or 0) > 0):
            out = cached.copy()
            out["stale"] = True
            return finalize_local_pulse(out)
        disk = _load_pulse_local_registry(reg)
        if disk:
            _CACHE[key] = (time.time(), disk)
            out = disk.copy()
            out["stale"] = True
            _kick_refresh(key, lambda: _refresh_pulse_local(reg))
            return finalize_local_pulse(out)
        _kick_refresh(key, lambda: _refresh_pulse_local(reg))
        return empty

    out = await _cold_start_or_swr(
        key,
        reg=reg,
        query=query,
        refresh=refresh,
        refresh_factory=lambda: _refresh_pulse_local(reg),
        empty=empty,
    )
    return finalize_local_pulse(out)


@router.get("/pulse/local")
async def gdelt_pulse_local(
    region: Annotated[str | None, Query(description="Operator region preset")] = None,
):
    """
    Headlines scoped to the operator home region (for briefing LOCAL block).
    Cached 10 minutes. Uses WORLDBASE_OPERATOR_REGION when region is omitted.
    """
    return await gdelt_pulse_local_data(region, refresh=True)


@router.get("/geo")
async def gdelt_geo(timespan: str = "1d", maxrecords: int = 60):
    """
    GDELT GEO 2.0 — geocoded event points (conflict/disaster themes).
    Cached 15 minutes. No API key.
    """
    key = f"geo:{timespan}"
    fresh = _cache_fresh(key, _GDELT_CACHE_GLOBAL_SEC)
    if fresh:
        return fresh

    if _in_backoff():
        stale = _stale_response(
            key,
            error=f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)",
        )
        if stale:
            return stale

    query = "(conflict OR protest OR earthquake OR flood OR explosion)"
    events, err = await _fetch_geo_events(
        query, timespan, maxrecords, None, priority="global"
    )
    if err and not events:
        stale = _stale_response(key, error=err)
        if stale:
            return stale
        return {"count": 0, "events": [], "error": err}

    out = {
        "count": len(events),
        "query": query,
        "timespan": timespan,
        "events": events,
        "cached_at": time.time(),
    }
    if err:
        out["error"] = err
        out["stale"] = True
    out.setdefault("stale", False)
    _CACHE[key] = (time.time(), out)
    return out


async def _refresh_geo_local(reg: str, timespan: str, maxrecords: int) -> dict:
    bbox = _region_bbox(reg)
    query = _REGION_GEO_QUERIES.get(reg) or "(conflict OR protest OR earthquake OR flood)"
    key = f"geo:local:{reg}:{timespan}"
    events, err = await _fetch_geo_events(
        query, timespan, maxrecords, bbox, priority="local"
    )
    if err and not events:
        stale = _stale_response(
            key,
            error=err,
            extra={"region": reg, "query": query, "bbox": bbox},
        )
        if stale:
            return stale
        return {"count": 0, "events": [], "region": reg, "query": query, "error": err}

    out = {
        "count": len(events),
        "query": query,
        "region": reg,
        "timespan": timespan,
        "events": events,
        "cached_at": time.time(),
        "bbox": bbox,
    }
    if err:
        out["error"] = err
        out["stale"] = True
    out.setdefault("stale", False)
    _CACHE[key] = (time.time(), out)
    return out


async def gdelt_geo_local_data(
    region: str | None = None,
    *,
    timespan: str = "1d",
    maxrecords: int = 50,
    refresh: bool = True,
) -> dict:
    reg = _resolve_region(region)
    bbox = _region_bbox(reg)
    query = _REGION_GEO_QUERIES.get(reg) or "(conflict OR protest OR earthquake OR flood)"
    key = f"geo:local:{reg}:{timespan}"
    fresh = _cache_fresh(key, _GDELT_CACHE_LOCAL_SEC)
    if fresh:
        return fresh

    backoff_err = f"GDELT rate limit (backoff {_backoff_remaining_sec()}s)"
    if _in_backoff():
        stale = _stale_response(
            key,
            error=backoff_err,
            extra={"region": reg, "query": query, "bbox": bbox},
        )
        if stale:
            return stale
        cached = _cache_any(key)
        if cached:
            out = cached.copy()
            out["stale"] = True
            out["error"] = backoff_err
            return out
        return {"count": 0, "events": [], "region": reg, "query": query, "error": backoff_err}

    empty = {
        "count": 0,
        "events": [],
        "region": reg,
        "query": query,
        "error": "no cached geo local yet",
    }
    return await _cold_start_or_swr(
        key,
        reg=reg,
        query=query,
        refresh=refresh,
        refresh_factory=lambda: _refresh_geo_local(reg, timespan, maxrecords),
        empty=empty,
    )


@router.get("/geo/local")
async def gdelt_geo_local(
    region: Annotated[str | None, Query()] = None,
    timespan: str = "1d",
    maxrecords: int = 50,
):
    """
    GDELT GEO points filtered to the operator region bbox.
    Cached 10 minutes. For briefing LOCAL / REGION buckets.
    """
    return await gdelt_geo_local_data(
        region,
        timespan=timespan,
        maxrecords=maxrecords,
        refresh=True,
    )
