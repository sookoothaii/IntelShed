"""Chat context builder + web search endpoint.

Extracted from routes/chat.py (Phase 2). Builds live WorldBase context
(briefing, nodes, feeds, crises, headlines, CVE, river, fusion, intel)
for injection into LLM prompts, and provides the /api/search endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3

import httpx
from fastapi import APIRouter

import feed_registry
import fusion_heatmap
import node_sync
from runtime_cache import cache_get, cache_set

router = APIRouter(tags=["chat"])


def _ollama_hosts() -> list[str]:
    """Resolve Ollama host(s) with Windows-friendly loopback fallbacks."""
    raw = os.getenv("OLLAMA_HOST", "127.0.0.1:11434")
    hosts = [h.strip() for h in raw.split(",") if h.strip()]
    expanded: list[str] = []
    for h in hosts:
        expanded.append(h)
        if h.startswith("localhost:"):
            expanded.append(h.replace("localhost:", "127.0.0.1:", 1))
        elif h.startswith("127.0.0.1:"):
            port = h.split(":", 1)[1]
            expanded.append(f"localhost:{port}")
    seen: set[str] = set()
    out: list[str] = []
    for h in expanded:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out or ["127.0.0.1:11434"]


OLLAMA_HOSTS = _ollama_hosts()

_models_cache: dict = {"ts": 0.0, "data": None}
_MODELS_CACHE_TTL = 60.0


def _is_embed_model(name: str) -> bool:
    embed_base = (
        os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").split(":")[0].lower()
    )
    n = (name or "").lower()
    return n.startswith(embed_base) or "embed" in n


# ---------------------------------------------------------------------------
# Chat context: inject live world state into LLM prompts
# ---------------------------------------------------------------------------
async def build_chat_context() -> str:
    """Fuse briefing + nodes + feed counts into a concise system context."""
    parts = []

    # Briefing
    try:
        brief = node_sync.latest_briefing()
        if brief and brief.get("text"):
            parts.append(f"SITUATION BRIEFING ({brief.get('created_at', 'unknown')}):")
            parts.append(brief["text"][:500])
    except Exception:
        pass

    # Nodes (Pi status)
    try:
        conn = sqlite3.connect(feed_registry.db_path())
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT node_id, name, lat, lon, updated_at, payload FROM node_state"
        ).fetchall()
        conn.close()
        if rows:
            parts.append("\nNODES:")
            for r in rows:
                p = json.loads(r["payload"] or "{}")
                h = p.get("health", {})
                parts.append(
                    f"  {r['name']} ({r['node_id']}): "
                    f"lat={r['lat']}, lon={r['lon']}, "
                    f"temp={h.get('cpu_temp_c', '?')}C, "
                    f"services={len(h.get('services', {}))}, "
                    f"mesh={len(p.get('mesh', []))}"
                )
    except Exception:
        pass

    # Feed counts (from cache if available)
    ac = cache_get("aircraft", ttl=999999)
    qu = cache_get("quakes:day:2.5", ttl=999999)
    ev = cache_get("eonet", ttl=999999)
    if ac or qu or ev:
        parts.append("\nFEEDS:")
        if ac:
            parts.append(f"  Aircraft: {len(ac.get('states', []) or [])}")
        if qu:
            parts.append(f"  Earthquakes(24h): {len(qu.get('features', []) or [])}")
        if ev:
            parts.append(f"  Natural events: {len(ev.get('events', []) or [])}")

    # ReliefWeb humanitarian crises
    try:
        rw = cache_get("reliefweb", ttl=999999)
        if not rw:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://api.reliefweb.int/v1/disasters",
                    params={
                        "appname": "worldbase",
                        "profile": "list",
                        "preset": "latest",
                        "limit": 10,
                    },
                )
                rw = r.json()
                cache_set("reliefweb", rw)
        disasters = rw.get("data", [])
        if disasters:
            parts.append("\nACTIVE CRISES (ReliefWeb):")
            for d in disasters[:5]:
                f = d.get("fields", {})
                parts.append(
                    f"  {f.get('name', 'Unknown')} — {f.get('status', 'unknown')}"
                )
    except Exception:
        pass

    # RSS news headlines
    try:
        news = cache_get("rss_news", ttl=999999)
        if not news:
            headlines = []
            feeds = [
                ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
                (
                    "Reuters",
                    "https://www.reutersagency.com/feed/?best-topics=business-finance",
                ),
                ("Tagesschau", "https://www.tagesschau.de/xml/rss2/"),
            ]
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                for name, url in feeds:
                    try:
                        r = await client.get(
                            url, headers={"User-Agent": "WorldBase/1.0"}
                        )
                        text = r.text
                        # Simple regex extraction for <title> inside <item>
                        titles = re.findall(
                            r"<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?</item>",
                            text,
                            re.DOTALL,
                        )[:3]
                        for t in titles:
                            clean = re.sub(r"<[^>]+>", "", t).strip()
                            if clean and clean not in [h["text"] for h in headlines]:
                                headlines.append({"source": name, "text": clean})
                    except Exception:
                        continue
            news = headlines[:8]
            cache_set("rss_news", news)
        if news:
            parts.append("\nHEADLINES:")
            for h in news:
                parts.append(f"  [{h['source']}] {h['text']}")
    except Exception:
        pass

    # CISA KEV (exploited CVEs)
    try:
        base = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/api/cve?limit=8")
            if r.status_code == 200:
                cve = r.json()
                vulns = cve.get("vulnerabilities", [])[:5]
                if vulns:
                    parts.append("\nCISA KEV (actively exploited):")
                    for v in vulns:
                        parts.append(
                            f"  {v.get('cve_id')}: {v.get('vendor')} {v.get('product')} "
                            f"(due {v.get('due_date', '?')})"
                        )
    except Exception:
        pass

    # River gauges (Germany)
    try:
        base = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(f"{base}/api/pegel")
            if r.status_code == 200:
                peg = r.json()
                elevated = [
                    g
                    for g in (peg.get("gauges") or [])
                    if g.get("severity") in ("critical", "high")
                ]
                if elevated:
                    parts.append("\nRIVER GAUGES (elevated, DE):")
                    for g in elevated[:6]:
                        parts.append(
                            f"  {g.get('name')} / {g.get('water')}: {g.get('value')} {g.get('unit')} ({g.get('severity')})"
                        )
    except Exception:
        pass

    # Fusion heatmap top-3 (spatial situational awareness)
    try:
        (
            fusion_hotspots,
            fusion_lines,
            _fusion_deltas,
        ) = await fusion_heatmap.top_hotspots_for_llm(top=3)
        if fusion_hotspots:
            parts.append("\nFUSION HOTSPOTS (8-feed grid, top 3):")
            parts.append(fusion_lines)
    except Exception:
        pass

    # FtM graph entities (who/what from feeds + ingest)
    try:
        import intel_briefing

        intel_ctx = await asyncio.to_thread(intel_briefing.gather_for_briefing)
        if intel_ctx.get("enabled") and intel_ctx.get("candidates"):
            finalized = intel_briefing.finalize_intel_for_digest(
                intel_ctx, existing_text_keys=set()
            )
            block = intel_briefing.format_intel_chat_context(finalized)
            if block:
                parts.append(f"\n{block}")
    except Exception:
        pass

    return "\n".join(parts) if parts else "No live context available."


@router.get("/api/search")
async def search_web(q: str, n: int = 5):
    """Web search via DuckDuckGo HTML (no API key required).

    Returns top-n results with title, url, and snippet.
    """
    from bs4 import BeautifulSoup

    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.post(
                url,
                data={"q": q, "b": ""},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0",
                    "Accept": "text/html",
                },
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        return {"query": q, "count": 0, "results": [], "error": str(e)}

    results = []
    for row in soup.select(".result")[:n]:
        a = row.select_one(".result__a")
        snippet = row.select_one(".result__snippet")
        if a:
            results.append(
                {
                    "title": a.get_text(strip=True),
                    "url": a.get("href", ""),
                    "snippet": snippet.get_text(strip=True) if snippet else "",
                }
            )

    return {"query": q, "count": len(results), "results": results}
