"""News feed fetchers for chat context (background autopilot, no request-path HTTP).

Moves ReliefWeb + RSS headline fetching out of the hot chat context path
so /api/chat never blocks on live HTTP. Results are written to runtime_cache
and refreshed by the background autopilot loop in lifespan.py.

Env:
  WORLDBASE_NEWS_REFRESH_INTERVAL=600 (default 10 min)
  WORLDBASE_NEWS_RSS_FEEDS= comma-separated list of "name|url" pairs
"""

from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from runtime_cache import cache_set

_UA = {"User-Agent": "WorldBase/1.0 (spatial intelligence dashboard)"}

_DEFAULT_RSS_FEEDS = [
    ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
    (
        "Reuters",
        "https://www.reutersagency.com/feed/?best-topics=business-finance",
    ),
    ("Tagesschau", "https://www.tagesschau.de/xml/rss2/"),
]


async def fetch_reliefweb_disasters(limit: int = 10) -> dict[str, Any]:
    """Fetch latest ReliefWeb disasters. Returns dict for cache storage."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                "https://api.reliefweb.int/v1/disasters",
                params={
                    "appname": "worldbase",
                    "profile": "list",
                    "preset": "latest",
                    "limit": limit,
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"error": str(e), "data": []}

    disasters = data.get("data", []) or []
    out = []
    for d in disasters:
        f = d.get("fields", {})
        out.append(
            {
                "name": f.get("name", "Unknown"),
                "status": f.get("status", "unknown"),
            }
        )
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(out),
        "data": out,
    }


def _parse_rss_items(text: str, name: str) -> list[dict[str, str]]:
    """Extract <item> titles from an RSS XML body."""
    try:
        items = re.findall(
            r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?</item>",
            text,
            re.DOTALL,
        )
        out: list[dict[str, str]] = []
        for t in items:
            clean = re.sub(r"<[^>]+>", "", html.unescape(t)).strip()
            if clean:
                out.append({"source": name, "text": clean})
        return out
    except Exception:
        return []


async def fetch_rss_headlines(
    feeds: list[tuple[str, str]] | None = None,
    items_per_feed: int = 3,
    total_limit: int = 8,
) -> dict[str, Any]:
    """Fetch headlines from configured RSS feeds. Returns dict for cache storage."""
    feeds = feeds or _DEFAULT_RSS_FEEDS
    headlines: list[dict[str, str]] = []

    async def _fetch_one(name: str, url: str) -> list[dict[str, str]]:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                r = await client.get(url, headers=_UA)
                r.raise_for_status()
                return _parse_rss_items(r.text, name)[:items_per_feed]
        except Exception:
            return []

    tasks = [asyncio.create_task(_fetch_one(name, url)) for name, url in feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, list):
            for h in res:
                if h["text"] not in [x["text"] for x in headlines]:
                    headlines.append(h)

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(headlines),
        "data": headlines[:total_limit],
    }


def _rss_feeds_from_env() -> list[tuple[str, str]]:
    """Parse WORLDBASE_NEWS_RSS_FEEDS into (name, url) tuples."""
    raw = os.getenv("WORLDBASE_NEWS_RSS_FEEDS", "").strip()
    if not raw:
        return _DEFAULT_RSS_FEEDS
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        if "|" in part:
            name, url = part.split("|", 1)
            out.append((name.strip(), url.strip()))
    return out or _DEFAULT_RSS_FEEDS


async def refresh_news_feeds() -> dict[str, Any]:
    """Fetch ReliefWeb + RSS and store in runtime_cache.

    Called by the background autopilot loop. Fail-soft: never raises.
    """
    reliefweb = await fetch_reliefweb_disasters()
    rss = await fetch_rss_headlines(feeds=_rss_feeds_from_env())

    cache_set("reliefweb", reliefweb)
    cache_set("rss_news", rss)

    return {
        "reliefweb": {"count": reliefweb.get("count", 0)},
        "rss": {"count": rss.get("count", 0)},
        "errors": [e for e in [reliefweb.get("error"), rss.get("error")] if e],
    }


def get_reliefweb_context() -> list[str]:
    """Return formatted ReliefWeb lines for chat_context.py (cache-backed)."""
    from runtime_cache import cache_get

    cached = cache_get("reliefweb", ttl=999999)
    if not cached:
        return []
    disasters = (cached.get("data") or [])[:5]
    if not disasters:
        return []
    lines = ["\nACTIVE CRISES (ReliefWeb):"]
    for d in disasters:
        lines.append(f"  {d.get('name', 'Unknown')} — {d.get('status', 'unknown')}")
    return lines


def get_rss_context() -> list[str]:
    """Return formatted RSS headline lines for chat_context.py (cache-backed)."""
    from runtime_cache import cache_get

    cached = cache_get("rss_news", ttl=999999)
    if not cached:
        return []
    news = cached.get("data") or []
    if not news:
        return []
    lines = ["\nHEADLINES:"]
    for h in news:
        lines.append(f"  [{h.get('source', '?')}] {h.get('text', '')}")
    return lines
