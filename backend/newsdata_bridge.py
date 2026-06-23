"""NewsData.io — optional headlines and source catalog (API key).

Complements GDELT with a stable REST source and separate corroboration family
(``newsdata`` vs ``gdelt``). Fail-soft when ``NEWSDATA_API_KEY`` is unset.

Free tier: ~12 h article delay (NewsData.io plan note).

Docs: https://newsdata.io/documentation
Endpoints:
  ``GET /api/newsdata`` — latest headlines (``/api/1/latest``)
  ``GET /api/newsdata/sources`` — source catalog (``/api/1/sources``)
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query

from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/newsdata", tags=["newsdata"])

_LATEST_BASE = "https://newsdata.io/api/1/latest"
_SOURCES_BASE = "https://newsdata.io/api/1/sources"
_UA = {"User-Agent": "WorldBase/1.0 (private research; newsdata)"}
_TTL = float(os.getenv("WORLDBASE_NEWSDATA_CACHE_SEC", "900"))
_SOURCES_TTL = float(os.getenv("WORLDBASE_NEWSDATA_SOURCES_CACHE_SEC", "86400"))
_REFRESH_LOCK = asyncio.Lock()
_SOURCES_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector("newsdata", ttl_sec=_TTL, default_source="newsdata.io")
_SOURCES_CONNECTOR = FeedConnector("newsdata_sources", ttl_sec=_SOURCES_TTL, default_source="newsdata.io")

_OPERATOR_COUNTRY: dict[str, str] = {
    "thailand": "th",
    "bangkok": "th",
    "phuket": "th",
    "singapore": "sg",
    "germany": "de",
    "hamburg": "de",
}

# Live Query Preview defaults (Free plan — 12 h delayed news).
_DEFAULT_COUNTRIES = "al,de,us,ir,th"
_DEFAULT_LANGUAGES = "de,en"
_DEFAULT_CATEGORY = "breaking,domestic,politics,technology,world"
_DEFAULT_PRIORITYDOMAIN = "low"
_PAID_STUB = "ONLY AVAILABLE IN PAID PLANS"
_JAIL_PATH = re.compile(r"jail[_/-]?bookings?", re.I)
_JAIL_TITLE = re.compile(r"^\d{4,}\s+[A-Z][A-Z\s'.-]+$")
_AP_SUMMARY = re.compile(r"^AP News Summary at\b", re.I)
_SPORTS_CATEGORY = frozenset({"sports", "sport"})
_SPORTS_TEXT = re.compile(
    r"\b(?:"
    r"sports?|football|soccer|basketball|tennis|cricket|rugby|"
    r"golf|nfl|nba|mlb|nhl|mls|premier league|champions league|"
    r"world cup|olympics?|bundesliga|la liga|serie a|uefa|fifa|"
    r"grand prix|formula\s*1|\bf1\b|super\s+bowl|playoffs?"
    r")\b",
    re.I,
)
_TOURISM_PROMO_TEXT = re.compile(
    r"\b(?:"
    r"songkran|agoda|"
    r"must[\s-]*see\s+destinations?|best\s+places?\s+to\s+(?:visit|celebrate|see|explore)|"
    r"land\s+of\s+smiles|exploring\s+thailand|travel\s+guide|"
    r"water\s+festival|new\s+year\s+festival|thai\s+new\s+year|"
    r"special\s+(?:rates?|offers?)|hotel\s+bookings?\s+drop"
    r")\b",
    re.I,
)


def api_key_configured() -> bool:
    return bool(os.getenv("NEWSDATA_API_KEY", "").strip())


def _operator_country() -> str:
    region = os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()
    return _OPERATOR_COUNTRY.get(region, "th")


def _env_csv(name: str, default: str) -> str:
    return (os.getenv(name, default) or default).strip()


def _filter_params(
    *,
    country: str | None = None,
    language: str | None = None,
    category: str | None = None,
    prioritydomain: str | None = None,
    domainurl: str | None = None,
    q: str | None = None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "country": country or _env_csv("WORLDBASE_NEWSDATA_COUNTRIES", _DEFAULT_COUNTRIES),
        "language": language or _env_csv("WORLDBASE_NEWSDATA_LANGUAGE", _DEFAULT_LANGUAGES),
        "category": category or _env_csv("WORLDBASE_NEWSDATA_CATEGORY", _DEFAULT_CATEGORY),
        "prioritydomain": prioritydomain
        or _env_csv("WORLDBASE_NEWSDATA_PRIORITYDOMAIN", _DEFAULT_PRIORITYDOMAIN),
    }
    domain = (domainurl if domainurl is not None else os.getenv("WORLDBASE_NEWSDATA_DOMAINURL", "")).strip()
    if domain:
        params["domainurl"] = domain
    query = (q or os.getenv("WORLDBASE_NEWSDATA_QUERY", "")).strip()
    if query:
        params["q"] = query
    exclude = os.getenv("WORLDBASE_NEWSDATA_EXCLUDE_DOMAIN", "reflector.com").strip()
    if exclude:
        params["excludedomain"] = exclude
    return params


def _filter_subkey(params: dict[str, str]) -> str:
    parts = [f"{k}={params[k]}" for k in sorted(params)]
    return "|".join(parts)


def _parse_article(row: dict[str, Any]) -> dict[str, Any]:
    countries = row.get("country") or []
    if isinstance(countries, str):
        countries = [countries]
    categories = row.get("category") or []
    if isinstance(categories, str):
        categories = [categories]
    return {
        "title": (row.get("title") or "").strip(),
        "description": (row.get("description") or row.get("content") or "")[:400],
        "link": row.get("link") or row.get("source_url"),
        "pubDate": row.get("pubDate") or row.get("published_at"),
        "source_id": row.get("source_id") or row.get("source_name"),
        "category": categories[:5] if categories else None,
        "country": countries[:3] if countries else None,
        "language": row.get("language"),
    }


def _normalize_categories(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        raw = [raw]
    return [str(c).strip().lower() for c in raw if c]


def is_sports_content(
    *,
    title: str = "",
    description: str = "",
    categories: list | str | None = None,
) -> bool:
    """True when headline looks like sports / entertainment athletics (briefing skip)."""
    cats = _normalize_categories(categories)
    if any(c in _SPORTS_CATEGORY or c.startswith("sport") for c in cats):
        return True
    text = f"{title} {description}".strip()
    return bool(text and _SPORTS_TEXT.search(text))


def is_tourism_promo_content(*, title: str = "", description: str = "") -> bool:
    """True when headline looks like travel promos / stale festival tourism (briefing skip)."""
    text = f"{title} {description}".strip()
    return bool(text and _TOURISM_PROMO_TEXT.search(text))


def _is_briefing_article(article: dict[str, Any]) -> bool:
    title = (article.get("title") or "").strip()
    if not title or len(title) < 12:
        return False
    link = str(article.get("link") or "")
    if _JAIL_PATH.search(link):
        return False
    if _JAIL_TITLE.match(title):
        return False
    if _AP_SUMMARY.match(title):
        return False
    desc = (article.get("description") or "").strip()
    if desc.upper() == _PAID_STUB:
        return False
    if is_sports_content(
        title=title,
        description=desc,
        categories=article.get("category"),
    ):
        return False
    if is_tourism_promo_content(title=title, description=desc):
        return False
    if not desc and _JAIL_TITLE.match(title):
        return False
    return True


def _filter_articles(articles: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    kept: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    skipped = 0
    for article in articles:
        if not _is_briefing_article(article):
            skipped += 1
            continue
        norm = (article.get("title") or "").strip().lower()
        if norm in seen_titles:
            skipped += 1
            continue
        seen_titles.add(norm)
        kept.append(article)
        if len(kept) >= limit:
            break
    return kept, skipped


def _fetch_size(limit: int) -> int:
    cap = int(os.getenv("WORLDBASE_NEWSDATA_FETCH_SIZE", "10"))
    return min(cap, max(limit, limit + 3))


def _parse_source(row: dict[str, Any]) -> dict[str, Any]:
    countries = row.get("country") or []
    if isinstance(countries, str):
        countries = [countries]
    categories = row.get("category") or []
    if isinstance(categories, str):
        categories = [categories]
    langs = row.get("language") or []
    if isinstance(langs, str):
        langs = [langs]
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "url": row.get("url"),
        "description": (row.get("description") or "")[:300],
        "category": categories[:8] if categories else None,
        "country": countries[:5] if countries else None,
        "language": langs[:5] if langs else None,
    }


def _unconfigured() -> dict[str, Any]:
    return {
        "count": 0,
        "articles": [],
        "sources": [],
        "configured": False,
        "error": "NEWSDATA_API_KEY not set",
        "source": "newsdata.io",
    }


async def _request_newsdata(url: str, params: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str | None]:
    api_key = os.getenv("NEWSDATA_API_KEY", "").strip()
    if not api_key:
        return 0, None, "NEWSDATA_API_KEY not set"

    req_params = {**params, "apikey": api_key}
    try:
        async with httpx.AsyncClient(timeout=25.0, headers=_UA) as client:
            r = await client.get(url, params=req_params)
            if r.status_code == 401:
                return 401, None, "newsdata unauthorized (check API key)"
            if r.status_code == 429:
                return 429, None, "newsdata rate limit"
            payload = r.json()
            if r.status_code >= 400:
                err = payload
                if isinstance(err.get("results"), list) and err["results"]:
                    row = err["results"][0]
                    if isinstance(row, dict):
                        return r.status_code, None, str(row.get("message") or row)[:160]
                return r.status_code, None, str(err.get("message") or err)[:160]
            r.raise_for_status()
            return r.status_code, payload, None
    except Exception as exc:
        return 0, None, str(exc)[:160]


def _payload_error(payload: dict[str, Any]) -> str | None:
    status = str(payload.get("status", "")).lower()
    if status in ("success", "ok", ""):
        results = payload.get("results")
        if isinstance(results, dict) and results.get("message"):
            return str(results.get("message"))[:160]
        if isinstance(results, list) and results and isinstance(results[0], dict):
            if results[0].get("code") or results[0].get("message"):
                return str(results[0].get("message") or results[0])[:160]
        return None
    msg = payload.get("message")
    if not msg and isinstance(payload.get("results"), dict):
        msg = payload["results"].get("message")
    return str(msg or payload.get("results") or "newsdata error")[:160]


async def fetch_newsdata_latest(
    *,
    country: str | None = None,
    language: str | None = None,
    category: str | None = None,
    prioritydomain: str | None = None,
    domainurl: str | None = None,
    q: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    if not api_key_configured():
        return _unconfigured()

    params = _filter_params(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        q=q,
    )
    params["size"] = str(_fetch_size(limit))

    _status, payload, transport_err = await _request_newsdata(_LATEST_BASE, params)
    if transport_err and payload is None:
        return {
            "count": 0,
            "articles": [],
            "configured": True,
            "error": transport_err,
            "source": "newsdata.io",
            "filters": params,
        }

    assert payload is not None
    api_err = _payload_error(payload)
    if api_err:
        return {
            "count": 0,
            "articles": [],
            "configured": True,
            "error": api_err,
            "source": "newsdata.io",
            "filters": {k: v for k, v in params.items() if k != "size"},
        }

    raw_rows = payload.get("results") or []
    parsed = [_parse_article(row) for row in raw_rows if isinstance(row, dict)]
    parsed = [a for a in parsed if a.get("title")]
    articles, filtered_count = _filter_articles(parsed, max(1, min(limit, 50)))

    return {
        "count": len(articles),
        "articles": articles,
        "configured": True,
        "filters": {k: v for k, v in params.items() if k != "size"},
        "source": "newsdata.io",
        "updated": datetime.now(timezone.utc).isoformat(),
        "total_results": payload.get("totalResults"),
        "raw_count": len(parsed),
        "filtered_count": filtered_count,
        "plan_note": "Free plan: ~12h delayed news",
    }


async def fetch_newsdata_sources(
    *,
    country: str | None = None,
    language: str | None = None,
    category: str | None = None,
    prioritydomain: str | None = None,
    domainurl: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not api_key_configured():
        return _unconfigured()

    params = _filter_params(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        q=None,
    )

    _status, payload, transport_err = await _request_newsdata(_SOURCES_BASE, params)
    if transport_err and payload is None:
        return {
            "count": 0,
            "sources": [],
            "configured": True,
            "error": transport_err,
            "source": "newsdata.io",
            "filters": params,
        }

    assert payload is not None
    api_err = _payload_error(payload)
    if api_err:
        return {
            "count": 0,
            "sources": [],
            "configured": True,
            "error": api_err,
            "source": "newsdata.io",
            "filters": params,
        }

    raw_rows = payload.get("results") or []
    sources = [_parse_source(row) for row in raw_rows if isinstance(row, dict)]
    sources = [s for s in sources if s.get("id")][: max(1, min(limit, 100))]

    return {
        "count": len(sources),
        "sources": sources,
        "configured": True,
        "filters": params,
        "source": "newsdata.io",
        "updated": datetime.now(timezone.utc).isoformat(),
        "total_results": payload.get("totalResults"),
        "plan_note": "Free plan: ~12h delayed news",
    }


async def get_newsdata(
    *,
    country: str | None = None,
    language: str | None = None,
    category: str | None = None,
    prioritydomain: str | None = None,
    domainurl: str | None = None,
    q: str | None = None,
    limit: int = 10,
    refresh: bool = False,
) -> dict[str, Any]:
    filt = _filter_params(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        q=q,
    )
    subkey = f"newsdata:latest:{_filter_subkey(filt)}:{limit}"
    if not refresh:
        hit = _CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    async with _REFRESH_LOCK:
        if not refresh:
            hit = _CONNECTOR.get_cached(subkey)
            if hit is not None:
                return hit

        stale_hit = _CONNECTOR.peek_memory(subkey)
        raw = await fetch_newsdata_latest(
            country=country,
            language=language,
            category=category,
            prioritydomain=prioritydomain,
            domainurl=domainurl,
            q=q,
            limit=limit,
        )

        if not raw.get("configured"):
            return _CONNECTOR.build(
                FeedEnvelope(count=0, source="newsdata.io", error=raw.get("error")),
                persist=False,
                subkey=subkey,
                articles=[],
                configured=False,
            )

        if raw.get("error") and not raw.get("articles"):
            if stale_hit:
                return _CONNECTOR.build(
                    FeedEnvelope(count=stale_hit.get("count", 0), stale=True, error=raw.get("error")),
                    persist=False,
                    subkey=subkey,
                    articles=stale_hit.get("articles") or [],
                    configured=True,
                    filters=raw.get("filters") or filt,
                    plan_note=raw.get("plan_note"),
                )
            return _CONNECTOR.build(
                FeedEnvelope(count=0, source="newsdata.io", error=raw.get("error")),
                persist=False,
                subkey=subkey,
                articles=[],
                configured=True,
                filters=raw.get("filters") or filt,
                plan_note=raw.get("plan_note"),
            )

        return _CONNECTOR.build(
            FeedEnvelope(
                count=raw["count"],
                source="newsdata.io",
                updated=raw.get("updated"),
                error=raw.get("error"),
            ),
            subkey=subkey,
            articles=raw.get("articles") or [],
            configured=True,
            filters=raw.get("filters") or filt,
            total_results=raw.get("total_results"),
            plan_note=raw.get("plan_note"),
            raw_count=raw.get("raw_count"),
            filtered_count=raw.get("filtered_count"),
        )


async def get_newsdata_sources(
    *,
    country: str | None = None,
    language: str | None = None,
    category: str | None = None,
    prioritydomain: str | None = None,
    domainurl: str | None = None,
    limit: int = 50,
    refresh: bool = False,
) -> dict[str, Any]:
    filt = _filter_params(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        q=None,
    )
    subkey = f"newsdata:sources:{_filter_subkey(filt)}:{limit}"
    if not refresh:
        hit = _SOURCES_CONNECTOR.get_cached(subkey)
        if hit is not None:
            return hit

    async with _SOURCES_LOCK:
        if not refresh:
            hit = _SOURCES_CONNECTOR.get_cached(subkey)
            if hit is not None:
                return hit

        stale_hit = _SOURCES_CONNECTOR.peek_memory(subkey)
        raw = await fetch_newsdata_sources(
            country=country,
            language=language,
            category=category,
            prioritydomain=prioritydomain,
            domainurl=domainurl,
            limit=limit,
        )

        if not raw.get("configured"):
            return _SOURCES_CONNECTOR.build(
                FeedEnvelope(count=0, source="newsdata.io", error=raw.get("error")),
                persist=False,
                subkey=subkey,
                sources=[],
                configured=False,
            )

        if raw.get("error") and not raw.get("sources"):
            if stale_hit:
                return _SOURCES_CONNECTOR.build(
                    FeedEnvelope(count=stale_hit.get("count", 0), stale=True, error=raw.get("error")),
                    persist=False,
                    subkey=subkey,
                    sources=stale_hit.get("sources") or [],
                    configured=True,
                    filters=raw.get("filters") or filt,
                    plan_note=raw.get("plan_note"),
                )
            return _SOURCES_CONNECTOR.build(
                FeedEnvelope(count=0, source="newsdata.io", error=raw.get("error")),
                persist=False,
                subkey=subkey,
                sources=[],
                configured=True,
                filters=raw.get("filters") or filt,
                plan_note=raw.get("plan_note"),
            )

        return _SOURCES_CONNECTOR.build(
            FeedEnvelope(
                count=raw["count"],
                source="newsdata.io",
                updated=raw.get("updated"),
                error=raw.get("error"),
            ),
            subkey=subkey,
            sources=raw.get("sources") or [],
            configured=True,
            filters=raw.get("filters") or filt,
            total_results=raw.get("total_results"),
            plan_note=raw.get("plan_note"),
        )


@router.get("")
async def newsdata_latest(
    country: str | None = Query(None, description="ISO countries CSV — default WORLDBASE_NEWSDATA_COUNTRIES"),
    language: str | None = Query(None, description="Languages CSV — default de,en"),
    category: str | None = Query(None, description="Categories CSV"),
    prioritydomain: str | None = Query(None, description="top | medium | low"),
    domainurl: str | None = Query(None, description="Optional domain filter (must exist in NewsData DB)"),
    q: str | None = Query(None, description="Optional search query"),
    limit: int = Query(10, ge=1, le=30),
    refresh: bool = False,
):
    """Latest headlines — Live Query Preview filters by default (Free plan ~12h delay)."""
    return await get_newsdata(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        q=q,
        limit=limit,
        refresh=refresh,
    )


@router.get("/sources")
async def newsdata_sources(
    country: str | None = Query(None, description="ISO countries CSV — default WORLDBASE_NEWSDATA_COUNTRIES"),
    language: str | None = Query(None, description="Languages CSV — default de,en"),
    category: str | None = Query(None, description="Categories CSV"),
    prioritydomain: str | None = Query(None, description="top | medium | low"),
    domainurl: str | None = Query(None, description="Optional domain filter"),
    limit: int = Query(50, ge=1, le=100),
    refresh: bool = False,
):
    """News source catalog matching the same filter profile as latest."""
    return await get_newsdata_sources(
        country=country,
        language=language,
        category=category,
        prioritydomain=prioritydomain,
        domainurl=domainurl,
        limit=limit,
        refresh=refresh,
    )
