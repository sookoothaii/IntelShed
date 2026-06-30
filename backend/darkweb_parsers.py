"""V4-58 Engine-specific HTML parsers for Tor dark-web search engines.

Replaces the generic _parse_tor_html() heuristic with dedicated parsers for:
Torch, Tor66, TorDex, Haystak, Not Evil.

Each parser extracts title, URL, and snippet from engine-specific HTML layouts
using BeautifulSoup4. All parsers are synchronous (the HTTP fetch is already
handled by darkweb_bridge._search_tor_engine via httpx async).

Parser interface:
    parse(html: str, limit: int) -> list[dict[str, Any]]

Returns dicts matching the darkweb_bridge result format:
    {"title", "url", "snippet", "engine", "first_seen"}
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

_ONION_URL_RE = re.compile(r"https?://[a-z2-7]{16,56}\.onion[^\s\"'<>]*", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    return html_mod.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _result(title: str, url: str, snippet: str, engine: str) -> dict[str, Any]:
    return {
        "title": title or f"{engine} result",
        "url": url,
        "snippet": snippet[:300],
        "engine": engine,
        "first_seen": _now(),
    }


# ─────────────────────────────────────────────────────────────
# Tor66 Parser
# ─────────────────────────────────────────────────────────────


def parse_tor66(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse Tor66 search results (table-based layout).

    Tor66 uses <tr class="result"> rows with <a href> links and text snippets.
    URL pattern: /search.php?q={query}&sorttype=rel&page={page}
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in soup.find_all("tr", class_=re.compile("result", re.I)):
        link = row.find("a", href=True)
        if not link:
            continue
        title = link.get_text(strip=True)
        raw_url = link["href"]
        if not raw_url.startswith("http"):
            raw_url = f"http://{raw_url}"
        if raw_url in seen or not _ONION_URL_RE.match(raw_url):
            continue
        seen.add(raw_url)

        # Snippet: text nodes in the row that aren't the title or URL
        snippet = ""
        for text_node in row.find_all(string=True):
            t = text_node.strip()
            if t and t != title and len(t) > 15:
                snippet = t
                break

        results.append(_result(title, raw_url, snippet, "tor66"))
        if len(results) >= limit:
            break

    # Fallback: generic onion link extraction
    if not results:
        results = _fallback_link_parse(soup, "tor66", limit)

    return results


# ─────────────────────────────────────────────────────────────
# TorDex Parser
# ─────────────────────────────────────────────────────────────


def parse_tordex(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse TorDex search results (card-based layout).

    TorDex uses <div class="result"> or <div class="search-result"> containers.
    URL pattern: /search?query={query}&page={page}
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    containers = soup.find_all(
        "div", class_=re.compile("result|search-result", re.I)
    ) or soup.find_all("div", class_=re.compile("result|item", re.I))

    for container in containers:
        title_elem = (
            container.find("h3")
            or container.find("a", class_=re.compile("title|link", re.I))
            or container.find("a", href=True)
        )
        if not title_elem:
            continue

        title = title_elem.get_text(strip=True)
        url = title_elem.get("href", "") if title_elem.name == "a" else ""
        if not url:
            link = container.find("a", href=True)
            if not link:
                continue
            url = link["href"]
            title = link.get_text(strip=True) or title

        # Handle redirect wrappers
        if url.startswith("/redirect"):
            match = re.search(r"[?&]url=([^&]+)", url)
            if match:
                url = match.group(1)
        if not url.startswith("http"):
            url = f"http://{url}"
        if url in seen or not _ONION_URL_RE.match(url):
            continue
        seen.add(url)

        snippet_elem = (
            container.find("p", class_=re.compile("desc|snippet|summary", re.I))
            or container.find("div", class_=re.compile("desc|snippet", re.I))
            or container.find("span", class_=re.compile("desc", re.I))
        )
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        results.append(_result(title, url, snippet, "tordex"))
        if len(results) >= limit:
            break

    if not results:
        results = _fallback_link_parse(soup, "tordex", limit)

    return results


# ─────────────────────────────────────────────────────────────
# Haystak Parser
# ─────────────────────────────────────────────────────────────


def parse_haystak(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse Haystak search results.

    Haystak uses <div class="result"> with <h4><a>Title</a></h4>,
    <p class="url"> for display URL, <p class="summary"> for snippet.
    URL pattern: /?q={query}&offset={offset}  (offset-based pagination)
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for container in soup.find_all("div", class_=re.compile("result|item", re.I)):
        heading = container.find(["h2", "h3", "h4"])
        link = heading.find("a", href=True) if heading else None
        if not link:
            link = container.find("a", href=re.compile(r"\.onion|/url\?", re.I))
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get("href", "")

        # Handle /url?u=... redirects
        if "/url?" in url or "/url?" in str(link):
            match = re.search(r"[?&]u=([^&]+)", url)
            if match:
                url = match.group(1)
        if not url.startswith("http"):
            url = f"http://{url}"
        if url in seen or not _ONION_URL_RE.match(url):
            continue
        seen.add(url)

        snippet_elem = container.find(
            "p", class_=re.compile("summary|snippet|desc|content", re.I)
        ) or container.find("div", class_=re.compile("summary|snippet", re.I))
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        results.append(_result(title, url, snippet, "haystak"))
        if len(results) >= limit:
            break

    if not results:
        results = _fallback_link_parse(soup, "haystak", limit)

    return results


# ─────────────────────────────────────────────────────────────
# Not Evil Parser
# ─────────────────────────────────────────────────────────────


def parse_notevil(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse Not Evil search results.

    Not Evil has a simple Google-like layout with <div class="result"> or
    <div class="g"> containers. Often unstable, layout changes frequently.
    URL pattern: /index.php?q={query}&start={start}  (start-based pagination)
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Try multiple selectors — Not Evil changes layouts often
    containers: list[Tag] = []
    for selector in [
        ("div", "result"),
        ("div", "g"),
        ("li", "result"),
        ("div", re.compile("result|res|item", re.I)),
    ]:
        containers = soup.find_all(selector[0], class_=selector[1])
        if containers:
            break

    for container in containers:
        link = container.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link["href"]

        # Handle redirect URLs
        if url.startswith("/url?"):
            match = re.search(r"[?&]q=([^&]+)", url)
            if match:
                url = match.group(1)
        if not url.startswith("http"):
            url = f"http://{url}"
        if url in seen or not _ONION_URL_RE.match(url):
            continue
        seen.add(url)

        snippet_elem = (
            container.find("div", class_=re.compile("snippet|summary|content", re.I))
            or container.find("span", class_=re.compile("snippet", re.I))
            or container.find("p")
        )
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        # Fallback: use cite/display URL as snippet
        if not snippet:
            cite = container.find("cite") or container.find(
                "span", class_=re.compile("url|address", re.I)
            )
            if cite:
                snippet = cite.get_text(strip=True)

        results.append(_result(title, url, snippet, "notevil"))
        if len(results) >= limit:
            break

    if not results:
        results = _fallback_link_parse(soup, "notevil", limit)

    return results


# ─────────────────────────────────────────────────────────────
# Torch Parser
# ─────────────────────────────────────────────────────────────


def parse_torch(html_text: str, limit: int) -> list[dict[str, Any]]:
    """Parse Torch search results.

    Torch is one of the oldest Tor search engines. Uses <div class="result">
    with <h3><a>Title</a></h3>, <div class="url">, <div class="snippet">.
    URL pattern: /search?q={query}&page={page}
    """
    soup = BeautifulSoup(html_text, "html.parser")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for container in soup.find_all(
        "div", class_=re.compile("result|search-result|item", re.I)
    ):
        heading = container.find(["h2", "h3", "h4"])
        link = heading.find("a", href=True) if heading else None
        if not link:
            link = container.find("a", href=True)
        if not link:
            continue

        title = link.get_text(strip=True)
        url = link.get("href", "")

        # Handle relative URLs
        if url.startswith("/"):
            # Build absolute URL from the engine's base
            base = _ENGINE_BASE_URLS.get("torch", "")
            if base:
                url = f"{base}{url}"
        if not url.startswith("http"):
            url = f"http://{url}"
        if url in seen or not _ONION_URL_RE.match(url):
            continue
        seen.add(url)

        snippet_elem = (
            container.find("div", class_=re.compile("snippet|desc|summary", re.I))
            or container.find("p", class_=re.compile("snippet|desc", re.I))
            or container.find("span", class_=re.compile("snippet", re.I))
        )
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        results.append(_result(title, url, snippet, "torch"))
        if len(results) >= limit:
            break

    # Fallback: generic onion link extraction
    if not results:
        results = _fallback_link_parse(soup, "torch", limit)

    return results


# ─────────────────────────────────────────────────────────────
# Fallback parser (used when structured extraction fails)
# ─────────────────────────────────────────────────────────────


def _fallback_link_parse(
    soup: BeautifulSoup, engine: str, limit: int
) -> list[dict[str, Any]]:
    """Generic fallback: extract all .onion links with surrounding text."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("http"):
            href = f"http://{href}"
        if not _ONION_URL_RE.match(href) or href in seen:
            continue
        seen.add(href)

        title = link.get_text(strip=True)
        if len(title) < 3:
            title = f"{engine} result"

        # Try to find snippet in parent container
        snippet = ""
        parent = link.parent
        if parent:
            snippet = _clean(parent.get_text(separator=" ", strip=True))[:200]

        results.append(_result(title, href, snippet, engine))
        if len(results) >= limit:
            break

    return results


# ─────────────────────────────────────────────────────────────
# Engine registry & dispatcher
# ─────────────────────────────────────────────────────────────

# Base URLs for relative-URL resolution (from darkweb_bridge._ENGINE_REGISTRY)
_ENGINE_BASE_URLS: dict[str, str] = {
    "torch": "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion",
    "tor66": "http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion",
    "tordex": "http://tordex7iiepec2wl.onion",
    "haystak": "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64j3oo5ts5i6lhifuvfqd.onion",
    "notevil": "http://hss3uro2hsxfogfq.onion",
}

_PARSER_REGISTRY: dict[str, Any] = {
    "torch": parse_torch,
    "tor66": parse_tor66,
    "tordex": parse_tordex,
    "haystak": parse_haystak,
    "notevil": parse_notevil,
}


def has_engine_parser(engine: str) -> bool:
    """Check if a dedicated parser exists for this engine."""
    return engine.lower().strip() in _PARSER_REGISTRY


def parse_engine_html(engine: str, html_text: str, limit: int) -> list[dict[str, Any]]:
    """Dispatch to the engine-specific parser.

    Falls back to None if no dedicated parser exists (caller should use
    _parse_tor_html generic heuristic in that case).
    """
    engine = engine.lower().strip()
    parser = _PARSER_REGISTRY.get(engine)
    if not parser:
        return []
    try:
        return parser(html_text, limit)
    except Exception as exc:
        logger.warning("Parser %s failed: %s", engine, exc)
        return []


def list_parser_engines() -> list[str]:
    """Return all engine names with dedicated parsers."""
    return list(_PARSER_REGISTRY.keys())
