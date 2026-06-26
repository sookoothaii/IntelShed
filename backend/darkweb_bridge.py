"""Dark Web Monitor Bridge (P8) — .onion search + entity mention matching.

Passive clearnet APIs by default (no Tor relay required):
- Ahmia (HTML scrape)
- darksearch.io (JSON API) — **dead since Jan 2022**, kept in registry for backward compat

Optional Tor-proxy engines (requires WORLDBASE_DARKWEB_TOR_PROXY):
- Torch, Tor66, OnionLand, TorDex, Haystak, Not Evil

Results are matched against FtM entity names, optionally deep-scraped for
public identifiers (crypto wallets, PGP keys, emails, IOCs), and ingested as
`Mention` schema entities. Fail-soft when engines are down or rate-limited.

Env:
  WORLDBASE_DARKWEB=1 (default off, opt-in)
  WORLDBASE_DARKWEB_ENGINES=ahmia
  WORLDBASE_DARKWEB_CACHE_SEC=3600
  WORLDBASE_DARKWEB_MAX_RESULTS=50
  WORLDBASE_DARKWEB_TOR_PROXY=socks5://127.0.0.1:9050  (optional)
  WORLDBASE_DARKWEB_TIMEOUT_SEC=15
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel

from config import get_config
from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/darkweb", tags=["darkweb"])

_AHMIA_BASE = "https://ahmia.fi/search/"
_DARKSEARCH_BASE = "https://darksearch.io/api/search"
_UA = {"User-Agent": "WorldBase/1.0 (private research; darkweb)"}

# Strip .onion URLs, HTML tags, and excessive whitespace.
_AHMIARE_RESULT = re.compile(
    r'<li class="result">\s*<h4>\s*<a href="([^"]+)"[^>]*>([^<]+)</a>\s*</h4>\s*<p>(.*?)</p>',
    re.S | re.I,
)
_DARKSEARCH_URL = re.compile(r"https?://[a-z2-7]{16,56}\.onion(?:/[\S]*)?", re.I)

# Entity extraction patterns (public identifiers only).
_EXTRACT_PATTERNS: dict[str, re.Pattern] = {
    "btc_wallet": re.compile(
        r"\b(1[a-zA-Z0-9]{25,34}|3[a-zA-Z0-9]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{11,71})\b"
    ),
    "eth_wallet": re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
    "xmr_wallet": re.compile(r"\b4[0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b"),
    "ltc_wallet": re.compile(r"\b(L|M|ltc1)[a-zA-HJ-NP-Z0-9]{25,62}\b"),
    "pgp_fingerprint": re.compile(r"\b([a-fA-F0-9]{4}\s?){10}\b"),
    "pgp_block": re.compile(
        r"-----BEGIN PGP PUBLIC KEY BLOCK-----.*?-----END PGP PUBLIC KEY BLOCK-----",
        re.S,
    ),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "sha256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
    "md5": re.compile(r"\b[a-fA-F0-9]{32}\b"),
    "cve": re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I),
    "onion": re.compile(r"[a-z2-7]{16,56}\.onion(?:/[\S]*)?"),
}

# Static reliability for provenance scoring.
SOURCE_RELIABILITY: dict[str, float] = {"ahmia": 0.3, "darksearch": 0.3}

# Engine registry: base URL and whether Tor proxy is required.
_ENGINE_REGISTRY: dict[str, dict[str, Any]] = {
    "ahmia": {
        "url": "https://ahmia.fi/search/",
        "tor_required": False,
        "type": "html",
    },
    "darksearch": {
        "url": "https://darksearch.io/api/search",
        "tor_required": False,
        "type": "json",
        "deprecated": True,
    },
    "torch": {
        "url": "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygth47de6krkb7pfqd.onion",
        "tor_required": True,
        "type": "html",
    },
    "tor66": {
        "url": "http://tor66sezptlr2hdqzw4ceh3n66xlsqft3koxo2y72vpfz4z6hdq3d3ad.onion/search.php",
        "tor_required": True,
        "type": "html",
    },
    "onionland": {
        "url": "https://onionlandsearchengine.com/search",
        "tor_required": False,
        "type": "html",
    },
    "tordex": {
        "url": "http://tordex7iiepec2wl.onion/search",
        "tor_required": True,
        "type": "html",
    },
    "haystak": {
        "url": "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64j3oo5ts5i6lhifuvfqd.onion",
        "tor_required": True,
        "type": "html",
    },
    "notevil": {
        "url": "http://hss3uro2hsxfogfq.onion/index.php",
        "tor_required": True,
        "type": "html",
    },
}

_REFRESH_LOCK = asyncio.Lock()
_CONNECTOR = FeedConnector("darkweb", ttl_sec=3600, default_source="darksearch.io")


def darkweb_enabled() -> bool:
    return get_config().darkweb_enabled


def _engines() -> list[str]:
    engines = get_config().darkweb_engines
    return [e.strip() for e in engines.split(",") if e.strip()]


def _max_results() -> int:
    return max(1, min(200, get_config().darkweb_max_results))


def _tor_proxy() -> str | None:
    proxy = get_config().darkweb_tor_proxy.strip()
    return proxy if proxy else None


def _timeout_sec() -> float:
    return max(5.0, min(60.0, get_config().darkweb_timeout_sec))


def _http_client(proxy: str | None = None) -> httpx.AsyncClient:
    """Return httpx client with optional SOCKS5 proxy.

    Passing a fresh client per Tor engine request isolates circuits and avoids
    sharing the same Tor exit node across concurrent requests.
    """
    proxy = (proxy or _tor_proxy() or "").strip()
    mounts = None
    if proxy:
        mounts = {
            "http://": httpx.AsyncHTTPTransport(proxy=proxy),
            "https://": httpx.AsyncHTTPTransport(proxy=proxy),
        }
    return httpx.AsyncClient(
        timeout=httpx.Timeout(_timeout_sec()),
        headers=_UA,
        mounts=mounts,  # type: ignore[arg-type]
    )


def _tor_client() -> httpx.AsyncClient:
    """Return a fresh httpx client bound to the configured Tor SOCKS5 proxy."""
    proxy = _tor_proxy()
    if not proxy:
        raise RuntimeError("no Tor proxy configured")
    return _http_client(proxy=proxy)


def _extract_entities(text: str) -> dict[str, list[str]]:
    """Extract public identifiers from dark web content."""
    found: dict[str, list[str]] = {}
    for label, pattern in _EXTRACT_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            # Flatten tuple groups if necessary.
            flat: list[str] = []
            for m in matches:
                if isinstance(m, tuple):
                    flat.extend([x for x in m if x])
                else:
                    flat.append(m)
            # Deduplicate while preserving order.
            seen: set[str] = set()
            unique: list[str] = []
            for item in flat:
                item = item.strip()
                if item and item not in seen:
                    seen.add(item)
                    unique.append(item)
            if unique:
                found[label] = unique[:20]
    return found


async def _search_ahmia(
    query: str, limit: int, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Scrape Ahmia HTML search results."""
    results: list[dict[str, Any]] = []
    try:
        if client is None:
            async with _http_client() as client:
                resp = await client.get(_AHMIA_BASE, params={"q": query, "pages": 1})
                resp.raise_for_status()
                text = resp.text
        else:
            resp = await client.get(_AHMIA_BASE, params={"q": query, "pages": 1})
            resp.raise_for_status()
            text = resp.text
    except Exception:
        return results

    for match in _AHMIARE_RESULT.finditer(text):
        url, title, snippet = match.groups()
        title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet)).strip()
        url = html.unescape(url).strip()
        if not url or not _DARKSEARCH_URL.match(url):
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": "ahmia",
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(results) >= limit:
            break
    return results


async def _search_darksearch(
    query: str, limit: int, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Query darksearch.io JSON API."""
    results: list[dict[str, Any]] = []
    try:
        if client is None:
            async with _http_client() as client:
                resp = await client.get(
                    _DARKSEARCH_BASE, params={"query": query, "page": 1, "limit": limit}
                )
                resp.raise_for_status()
                payload = resp.json()
        else:
            resp = await client.get(
                _DARKSEARCH_BASE, params={"query": query, "page": 1, "limit": limit}
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return results

    data = payload if isinstance(payload, list) else payload.get("data", [])
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "").strip()
        url = str(item.get("link") or item.get("url") or "").strip()
        snippet = str(item.get("snippet") or item.get("description") or "").strip()
        if not url or not _DARKSEARCH_URL.match(url):
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": "darksearch",
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(results) >= limit:
            break
    return results


async def _search_onionland(
    query: str, limit: int, client: httpx.AsyncClient | None = None
) -> list[dict[str, Any]]:
    """Scrape OnionLand HTML search results (clearnet, Tor not required)."""
    results: list[dict[str, Any]] = []
    cfg = _ENGINE_REGISTRY.get("onionland")
    if not cfg:
        return results
    try:
        if client is None:
            async with _http_client() as client:
                resp = await client.get(cfg["url"], params={"q": query, "page": 1})
                resp.raise_for_status()
                text = resp.text
        else:
            resp = await client.get(cfg["url"], params={"q": query, "page": 1})
            resp.raise_for_status()
            text = resp.text
    except Exception:
        return results

    # Heuristic: look for title + onion link + snippet patterns.
    for match in re.finditer(
        r"<a[^>]+href\s*=\s*\"(https?://[a-z2-7]{16,56}\.onion[^\"]*)\"[^>]*>([^<]+)</a>.*?<p[^>]*>(.*?)</p>",
        text,
        re.S | re.I,
    ):
        url, title, snippet = match.groups()
        title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet)).strip()
        url = html.unescape(url).strip()
        if not _DARKSEARCH_URL.match(url):
            continue
        results.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": "onionland",
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(results) >= limit:
            break
    return results


def _parse_tor_html(text: str, engine: str, limit: int) -> list[dict[str, Any]]:
    """Generic heuristic parser for Tor-only engine HTML.

    Looks for result blocks containing a .onion link and extracts the nearest
    title and snippet. Engines change their markup often, so this is intentionally
    conservative and fail-soft.
    """
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _DARKSEARCH_URL.finditer(text):
        url = match.group(0)
        if url in seen:
            continue
        seen.add(url)
        start = max(0, match.start() - 180)
        end = min(len(text), match.end() + 260)
        window = text[start:end]
        title = ""
        snippet = ""
        anchor = re.search(
            r'<a[^>]+href\s*=\s*"{}"[^>]*>(.*?)</a>'.format(re.escape(url)),
            window,
            re.S | re.I,
        )
        if anchor:
            title = html.unescape(re.sub(r"<[^>]+>", "", anchor.group(1))).strip()
        if not title:
            title_match = re.search(r"<title>([^<]+)</title>", window, re.I)
            title = html.unescape(title_match.group(1).strip()) if title_match else ""
        snippet = re.sub(r"<[^>]+>", " ", window)
        snippet = re.sub(r"\s+", " ", snippet).strip()[:250]
        results.append(
            {
                "title": title or f"{engine} result",
                "url": url,
                "snippet": snippet,
                "engine": engine,
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        )
        if len(results) >= limit:
            break
    return results


async def _search_tor_engine(
    engine: str, query: str, limit: int
) -> list[dict[str, Any]]:
    """Run a Tor-only engine through the SOCKS5 proxy with a fresh client.

    Each Tor engine request uses its own httpx client to isolate Tor circuits.
    The caller is responsible for spacing requests to avoid exit-node rate limits.
    """
    results: list[dict[str, Any]] = []
    cfg = _ENGINE_REGISTRY.get(engine)
    if not cfg:
        return results
    if not _tor_proxy():
        return results
    try:
        async with _tor_client() as client:
            resp = await client.get(
                cfg["url"],
                params={"q": query, "query": query, "search": query, "page": 1},
            )
            resp.raise_for_status()
            text = resp.text
    except Exception:
        return results

    return _parse_tor_html(text, engine, limit)


async def _scrape_onion_page(url: str, *, extract: bool = True) -> dict[str, Any]:
    """Scrape a single .onion page through the Tor proxy.

    Returns a dict with page text, status, and extracted entities. Fail-soft:
    missing Tor proxy or network errors return an empty result instead of
    raising.
    """
    url = url.strip()
    if not _DARKSEARCH_URL.match(url):
        return {
            "url": url,
            "ok": False,
            "error": "not an onion URL",
            "text": "",
            "entities": {},
        }
    if not _tor_proxy():
        return {
            "url": url,
            "ok": False,
            "error": "no Tor proxy",
            "text": "",
            "entities": {},
        }

    try:
        async with _tor_client() as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text
    except Exception as exc:
        return {"url": url, "ok": False, "error": str(exc), "text": "", "entities": {}}

    entities = _extract_entities(text) if extract else {}
    return {
        "url": url,
        "ok": True,
        "error": None,
        "text": text[:2000],
        "entities": entities,
    }


async def _deep_search(
    query: str,
    engines: list[str] | None = None,
    limit: int = 20,
    scrape_limit: int = 3,
    match_entities: bool = True,
    mode: str = "auto",
) -> dict[str, Any]:
    """Search dark web engines and deep-scrape the top .onion results.

    Each scraped page gets its extracted entities attached to the original
    search result. Results are optionally matched against FtM entities and
    can be ingested as Mention entities.
    """
    raw = await search_darkweb(query, engines, limit, mode=mode)
    results = raw.get("results", [])[:scrape_limit]
    scraped: list[dict[str, Any]] = []
    for r in results:
        url = r.get("url", "")
        if not _DARKSEARCH_URL.match(url):
            scraped.append({**r, "scrape": {"ok": False, "error": "not an onion URL"}})
            continue
        page = await _scrape_onion_page(url)
        scraped.append({**r, "scrape": page})

    if match_entities:
        entities = _list_fts_entities()
        matches = match_entities_to_darkweb(scraped, entities)
    else:
        matches = [
            {"result": r, "matched_names": [], "entity_ids": []} for r in scraped
        ]

    return {
        "query": query,
        "engines": raw.get("engines", []),
        "sources": raw.get("sources", []),
        "count": len(matches),
        "matches": matches,
        "error": raw.get("error"),
    }


async def search_darkweb(
    query: str,
    engines: list[str] | None = None,
    limit: int | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """Search dark web engines for a query.

    Args:
        query: Search term.
        engines: Comma-separated or list of engine names. Defaults to configured engines.
        limit: Max results to return.
        mode: "auto" (clearnet engines over clearnet, Tor engines over Tor),
              "clear" (clearnet engines only, Tor engines skipped),
              "tor" (all engines routed through Tor proxy).

    Returns:
        {
            "query": str,
            "engines": list[str],
            "results": list[dict],
            "count": int,
            "sources": list[str],
            "mode": str,
            "tor_proxy": bool,
            "error": str | None,
        }
    """
    if not darkweb_enabled():
        return {
            "query": query,
            "engines": [],
            "results": [],
            "count": 0,
            "sources": [],
            "mode": mode,
            "tor_proxy": bool(_tor_proxy()),
            "error": "darkweb disabled",
        }

    mode = (mode or "auto").lower().strip()
    if mode not in {"auto", "clear", "tor"}:
        mode = "auto"

    engines = engines or _engines()
    limit = limit if limit is not None else _max_results()
    sources: list[str] = []
    errors: list[str] = []
    all_results: list[dict[str, Any]] = []

    clearnet: list[str] = []
    tor: list[str] = []
    for engine in engines:
        engine = engine.strip().lower()
        if engine not in _ENGINE_REGISTRY:
            errors.append(f"{engine}: unknown engine")
            continue
        cfg = _ENGINE_REGISTRY[engine]
        if mode == "clear":
            if cfg.get("tor_required"):
                errors.append(f"{engine}: skipped in clear mode")
                continue
            clearnet.append(engine)
        elif cfg.get("tor_required") or mode == "tor":
            if not _tor_proxy():
                errors.append(f"{engine}: requires Tor proxy")
                continue
            tor.append(engine)
        else:
            clearnet.append(engine)

    if not clearnet and not tor:
        return {
            "query": query,
            "engines": engines,
            "results": [],
            "count": 0,
            "sources": [],
            "mode": mode,
            "tor_proxy": bool(_tor_proxy()),
            "error": "no valid engines" if not errors else "; ".join(errors),
        }

    # Clearnet engines share one client and run in parallel.
    if clearnet:
        try:
            async with _http_client() as client:
                coros = []
                names = []
                for engine in clearnet:
                    if engine == "ahmia":
                        coros.append(_search_ahmia(query, limit, client))
                    elif engine == "darksearch":
                        coros.append(_search_darksearch(query, limit, client))
                    elif engine == "onionland":
                        coros.append(_search_onionland(query, limit, client))
                    else:
                        continue
                    names.append(engine)
                gathered = await asyncio.gather(*coros, return_exceptions=True)
                for name, result in zip(names, gathered):
                    if isinstance(result, Exception):
                        errors.append(f"{name}: {result}")
                        continue
                    all_results.extend(result)
                    if result:
                        sources.append(name)
        except Exception as exc:
            errors.append(f"clearnet: {exc}")

    # Tor engines use a fresh client per engine and run sequentially.
    # This isolates circuits and respects Tor exit-node rate limits.
    for engine in tor:
        try:
            result = await _search_tor_engine(engine, query, limit)
            all_results.extend(result)
            if result:
                sources.append(engine)
        except Exception as exc:
            errors.append(f"{engine}: {exc}")
        if engine != tor[-1]:
            await asyncio.sleep(10.0)

    # Deduplicate by URL, keep first (title/snippet from first engine).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in sorted(all_results, key=lambda x: len(x.get("snippet", "")), reverse=True):
        url = r.get("url", "")
        if url and url not in seen:
            seen.add(url)
            r["query"] = query
            r["extracted_entities"] = _extract_entities(
                " ".join(filter(None, [r.get("title", ""), r.get("snippet", ""), url]))
            )
            deduped.append(r)
        if len(deduped) >= limit:
            break

    return {
        "query": query,
        "engines": engines,
        "results": deduped,
        "count": len(deduped),
        "sources": sources,
        "mode": mode,
        "tor_proxy": bool(_tor_proxy()),
        "error": "; ".join(errors) if errors else None,
    }


def match_entities_to_darkweb(
    results: list[dict[str, Any]], entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Match dark web results against FtM entity names.

    Returns a list of {result, entity_ids, matched_names}.
    """
    matches: list[dict[str, Any]] = []
    for result in results:
        text = " ".join(
            filter(None, [result.get("title", ""), result.get("snippet", "")])
        ).lower()
        matched_ids: list[str] = []
        matched_names: list[str] = []
        for ent in entities:
            name = (ent.get("name") or ent.get("caption") or "").strip()
            if not name:
                continue
            aliases = [name] + [a.strip() for a in ent.get("aliases", []) if a.strip()]
            for alias in aliases:
                if alias.lower() in text:
                    matched_ids.append(ent.get("id", ""))
                    matched_names.append(alias)
                    break
        if matched_ids:
            matches.append(
                {
                    "result": result,
                    "entity_ids": list(set(matched_ids)),
                    "matched_names": list(set(matched_names)),
                }
            )
    return matches


def _to_mention(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a dark web result into a FtM Mention-shaped dict."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema": "Mention",
        "id": f"darkweb-{_hash_url(result.get('url', ''))}",
        "properties": {
            "name": [result.get("title", "") or "Dark web mention"],
            "source": [result.get("engine", "")],
            "url": [result.get("url", "")],
            "snippet": [result.get("snippet", "")],
            "query": [result.get("query", "")],
            "publishedAt": [result.get("first_seen", now)],
        },
        "datasets": ["darkweb"],
    }


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _list_fts_entities(
    schema: str | None = None, limit: int = 1000
) -> list[dict[str, Any]]:
    """Load FtM entities for matching."""
    try:
        import ftm_query

        rows = ftm_query.list_entities(limit=limit)
        if schema:
            rows = [r for r in rows if r.get("schema") == schema]
        return rows
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Pydantic models for HTTP endpoints
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    q: str | None = None
    engines: str = ""
    limit: int = 50
    match_entities: bool = True
    mode: str = "auto"


class MatchRequest(BaseModel):
    results: list[dict[str, Any]]
    entity_ids: list[str] | None = None


class ScrapeRequest(BaseModel):
    url: str
    extract: bool = True


class DeepSearchRequest(BaseModel):
    q: str | None = None
    engines: str = ""
    limit: int = 20
    scrape_limit: int = 3
    match_entities: bool = True
    mode: str = "auto"


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


async def get_darkweb_search(
    q: str,
    engines: str = "",
    limit: int = 50,
    refresh: bool = False,
    mode: str = "auto",
) -> dict[str, Any]:
    """Cached dark web search via FeedConnector."""
    engine_list = engines.split(",") if engines else None
    subkey = f"darkweb:q={q}:engines={','.join(engine_list or _engines())}:limit={limit}:mode={mode}"
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
        raw = await search_darkweb(q, engine_list, limit, mode=mode)

        if raw.get("error") and not raw.get("results"):
            if stale_hit:
                return _CONNECTOR.build(
                    FeedEnvelope(
                        count=stale_hit.get("count", 0),
                        stale=True,
                        error=raw.get("error"),
                    ),
                    persist=False,
                    subkey=subkey,
                    results=stale_hit.get("results") or [],
                    query=q,
                    engines=raw.get("engines", []),
                    sources=stale_hit.get("sources") or [],
                )
            return _CONNECTOR.build(
                FeedEnvelope(
                    count=0,
                    error=raw.get("error"),
                    sources=raw.get("sources", []),
                ),
                persist=False,
                subkey=subkey,
                results=[],
                query=q,
                engines=raw.get("engines", []),
            )

        return _CONNECTOR.build(
            FeedEnvelope(
                count=raw["count"],
                sources=raw.get("sources", []),
                updated=datetime.now(timezone.utc).isoformat(),
                error=raw.get("error"),
            ),
            subkey=subkey,
            results=raw.get("results") or [],
            query=q,
            engines=raw.get("engines", []),
        )


@router.get("")
async def api_darkweb_search(
    q: str = Query(..., description="Search query"),
    engines: str = Query("", description="Comma-separated engines (ahmia,darksearch)"),
    limit: int = Query(50, ge=1, le=200),
    refresh: bool = False,
    mode: str = Query("auto", description="Routing mode: auto | clear | tor"),
):
    """Search dark web engines."""
    return await get_darkweb_search(
        q, engines=engines, limit=limit, refresh=refresh, mode=mode
    )


@router.get("/search")
async def api_darkweb_search_raw(
    q: str = Query(..., description="Search query"),
    engines: str = Query("", description="Comma-separated engines (ahmia,darksearch)"),
    limit: int = Query(50, ge=1, le=200),
    mode: str = Query("auto", description="Routing mode: auto | clear | tor"),
):
    """Raw dark web search without caching envelope."""
    return await search_darkweb(
        q, engines.split(",") if engines else None, limit, mode=mode
    )


@router.get("/status")
async def api_darkweb_status():
    """Show dark web bridge status and configured engines."""
    cfg = get_config()
    return {
        "enabled": darkweb_enabled(),
        "engines": _engines(),
        "modes": ["auto", "clear", "tor"],
        "max_results": _max_results(),
        "cache_sec": cfg.darkweb_cache_sec,
        "timeout_sec": cfg.darkweb_timeout_sec,
        "tor_proxy": cfg.darkweb_tor_proxy or None,
        "engine_registry": {
            name: {"tor_required": info["tor_required"], "type": info["type"]}
            for name, info in _ENGINE_REGISTRY.items()
        },
    }


@router.get("/engines")
async def api_darkweb_engines():
    """List available engines and their requirements."""
    return {
        "engines": [
            {
                "name": name,
                "tor_required": info["tor_required"],
                "type": info["type"],
                "url": info["url"],
            }
            for name, info in _ENGINE_REGISTRY.items()
        ],
        "configured": _engines(),
        "tor_proxy": _tor_proxy() or None,
    }


@router.post("/ingest")
async def api_darkweb_ingest(req: IngestRequest):
    """Run a dark web search and ingest the results as FtM Mention entities."""
    if not darkweb_enabled():
        return {"count": 0, "ids": [], "error": "darkweb disabled"}

    engine_list = req.engines.split(",") if req.engines else None
    raw = await search_darkweb(req.q or "", engine_list, req.limit, mode=req.mode)
    results = raw.get("results", [])

    matches = []
    if req.match_entities:
        entities = _list_fts_entities()
        matches = match_entities_to_darkweb(results, entities)
        results = [m["result"] for m in matches]

    summary = ingest_results(results)
    summary["query"] = req.q
    summary["engines"] = raw.get("engines", [])
    summary["sources"] = raw.get("sources", [])
    summary["mode"] = raw.get("mode", "auto")
    summary["matched_count"] = len(matches) if req.match_entities else 0
    return summary


@router.post("/match")
async def api_darkweb_match(req: MatchRequest):
    """Match a list of dark web results against FtM entities."""
    entities = _list_fts_entities()
    if req.entity_ids:
        entities = [e for e in entities if e.get("id") in req.entity_ids]
    return {
        "matches": match_entities_to_darkweb(req.results, entities),
        "entity_count": len(entities),
        "result_count": len(req.results),
    }


@router.get("/entities")
async def api_darkweb_entities(
    q: str = Query(..., description="Search query"),
    engines: str = Query("", description="Comma-separated engines"),
    limit: int = Query(50, ge=1, le=200),
    mode: str = Query("auto", description="Routing mode: auto | clear | tor"),
):
    """Search dark web and return results with matched entity IDs."""
    raw = await search_darkweb(
        q, engines.split(",") if engines else None, limit, mode=mode
    )
    entities = _list_fts_entities()
    matches = match_entities_to_darkweb(raw.get("results", []), entities)
    return {
        "query": q,
        "engines": raw.get("engines", []),
        "sources": raw.get("sources", []),
        "mode": raw.get("mode", "auto"),
        "count": len(matches),
        "matches": matches,
        "error": raw.get("error"),
    }


@router.get("/mentions")
async def api_darkweb_mentions(
    limit: int = Query(50, ge=1, le=500),
    schema: str = Query("", description="Filter by entity schema"),
):
    """List already ingested dark web `Mention` entities."""
    try:
        import ftm_query

        rows = ftm_query.list_entities(limit=limit * 2)
        mentions = [
            r
            for r in rows
            if r.get("schema") == "Mention" and "darkweb" in (r.get("datasets") or [])
        ]
        if schema:
            mentions = [m for m in mentions if m.get("schema") == schema]
        return {
            "count": len(mentions[:limit]),
            "mentions": mentions[:limit],
        }
    except Exception as exc:
        return {"count": 0, "mentions": [], "error": str(exc)}


@router.post("/scrape")
async def api_darkweb_scrape(req: ScrapeRequest):
    """Scrape a single .onion URL through the configured Tor proxy.

    Requires `WORLDBASE_DARKWEB=1` and a Tor proxy (`WORLDBASE_DARKWEB_TOR_PROXY`).
    """
    if not darkweb_enabled():
        return {
            "url": req.url,
            "ok": False,
            "error": "darkweb disabled",
            "text": "",
            "entities": {},
        }
    return await _scrape_onion_page(req.url, extract=req.extract)


@router.post("/deep_search")
async def api_darkweb_deep_search(req: DeepSearchRequest):
    """Search dark web engines and deep-scrape the top .onion results."""
    if not darkweb_enabled():
        return {
            "query": req.q,
            "engines": [],
            "sources": [],
            "count": 0,
            "matches": [],
            "error": "darkweb disabled",
        }
    engine_list = req.engines.split(",") if req.engines else None
    return await _deep_search(
        req.q or "",
        engines=engine_list,
        limit=req.limit,
        scrape_limit=req.scrape_limit,
        match_entities=req.match_entities,
        mode=req.mode,
    )


def ingest_results(
    results: list[dict[str, Any]], dataset: str = "darkweb"
) -> dict[str, Any]:
    """Convert dark web results into FtM Mention entities and ingest.

    Returns a summary dict with count/ids/error.
    """
    if not results:
        return {"count": 0, "ids": [], "error": None}
    try:
        import ftm_query

        mentions = [_to_mention(r) for r in results]
        ids: list[str] = []
        seen_at = datetime.now(timezone.utc).isoformat()
        for m in mentions:
            ent = ftm_query._proxy_with_id(m["id"], m["schema"], m["properties"])
            ftm_query.upsert(ent, dataset=dataset, seen_at=seen_at)
            ids.append(m["id"])
        return {"count": len(ids), "ids": ids, "error": None}
    except Exception as exc:
        return {"count": 0, "ids": [], "error": str(exc)}


async def gather_darkweb_digest(
    queries: list[str] | None = None, limit: int = 10
) -> dict[str, Any]:
    """Gather dark web mentions for the briefing digest.

    Searches configured engines for a set of default / operator queries and
    returns matched FtM entities. Fail-soft when disabled or no matches.
    """
    if not darkweb_enabled() or not get_config().briefing_darkweb:
        return {"enabled": False, "count": 0, "lines": [], "mentions": []}

    queries = queries or ["WorldBase", "operator region", "darknet"]
    all_mentions: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        try:
            raw = await search_darkweb(q, limit=limit)
            for r in raw.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_mentions.append(r)
        except Exception:
            continue

    entities = _list_fts_entities(limit=500)
    matches = match_entities_to_darkweb(all_mentions, entities)
    lines: list[str] = []
    for m in matches[:5]:
        result = m["result"]
        names = ", ".join(m["matched_names"][:3])
        lines.append(
            f"- [{result.get('engine', 'darkweb')}] {names}: {result.get('title', 'Mention')} "
            f"({result.get('url', '')})"
        )

    return {
        "enabled": True,
        "count": len(lines),
        "lines": lines,
        "mentions": matches,
        "sources": list({r.get("engine", "") for r in all_mentions if r.get("engine")}),
    }
