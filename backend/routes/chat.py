"""Chat + LLM proxy endpoints — /api/search, /api/models, /api/chat, /api/providers.

Extracted from main.py (Phase 1 decortication). Routing logic lives in
chat_routing.py; this module owns the HTTP surface, provider fan-out, SSE
streaming, firewall gate, and the live WorldBase chat-context builder.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

import chat_routing
import chat_tools
import feed_registry
import fusion_heatmap
import node_sync
from auth.security import verify_api_key, lan_exposed, API_KEY
from middleware.rate_limit import rate_limit_general
from runtime_cache import cache_get, cache_set

router = APIRouter(tags=["chat"])

_models_cache: dict = {"ts": 0.0, "data": None}
_MODELS_CACHE_TTL = 60.0


def _client_base_url_override_allowed() -> bool:
    """HUD ``api_base_urls`` only when loopback or WORLDBASE_API_KEY is configured."""
    return bool(API_KEY) or not lan_exposed()


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


def _is_embed_model(name: str) -> bool:
    embed_base = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").split(":")[0].lower()
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
                    params={"appname": "worldbase", "profile": "list", "preset": "latest", "limit": 10},
                )
                rw = r.json()
                cache_set("reliefweb", rw)
        disasters = rw.get("data", [])
        if disasters:
            parts.append("\nACTIVE CRISES (ReliefWeb):")
            for d in disasters[:5]:
                f = d.get("fields", {})
                parts.append(f"  {f.get('name', 'Unknown')} — {f.get('status', 'unknown')}")
    except Exception:
        pass

    # RSS news headlines
    try:
        news = cache_get("rss_news", ttl=999999)
        if not news:
            headlines = []
            feeds = [
                ("BBC World", "http://feeds.bbci.co.uk/news/world/rss.xml"),
                ("Reuters", "https://www.reutersagency.com/feed/?best-topics=business-finance"),
                ("Tagesschau", "https://www.tagesschau.de/xml/rss2/"),
            ]
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                for name, url in feeds:
                    try:
                        r = await client.get(url, headers={"User-Agent": "WorldBase/1.0"})
                        text = r.text
                        # Simple regex extraction for <title> inside <item>
                        titles = re.findall(r'<item>.*?<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>.*?</item>', text, re.DOTALL)[:3]
                        for t in titles:
                            clean = re.sub(r'<[^>]+>', '', t).strip()
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
                elevated = [g for g in (peg.get("gauges") or []) if g.get("severity") in ("critical", "high")]
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
        fusion_hotspots, fusion_lines, _fusion_deltas = await fusion_heatmap.top_hotspots_for_llm(top=3)
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
            finalized = intel_briefing.finalize_intel_for_digest(intel_ctx, existing_text_keys=set())
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
            results.append({
                "title": a.get_text(strip=True),
                "url": a.get("href", ""),
                "snippet": snippet.get_text(strip=True) if snippet else "",
            })

    return {"query": q, "count": len(results), "results": results}


@router.get("/api/models")
async def list_models():
    """List available Ollama chat models (embed models excluded from chat picker)."""
    now = time.time()
    if _models_cache["data"] and now - _models_cache["ts"] < _MODELS_CACHE_TTL:
        return _models_cache["data"]

    last_err = None
    for host in OLLAMA_HOSTS:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.get(f"http://{host}/api/tags")
                r.raise_for_status()
                data = r.json()
                all_models = data.get("models", [])
                chat_models = [m for m in all_models if not _is_embed_model(m.get("name", ""))]
                default_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
                chat_names = [m.get("name") for m in chat_models]
                all_names = [m.get("name") for m in all_models]
                if default_model not in chat_names:
                    for n in chat_names:
                        if n and n.split(":")[0] == default_model.split(":")[0]:
                            default_model = n
                            break
                payload = {
                    "host": host,
                    "count": len(chat_models),
                    "default": default_model if default_model in chat_names else (chat_names[0] if chat_names else None),
                    "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                    "embed_available": any(_is_embed_model(n or "") for n in all_names),
                    "models": [
                        {
                            "name": m.get("name"),
                            "size": m.get("size"),
                            "parameter_size": m.get("details", {}).get("parameter_size"),
                        }
                        for m in chat_models
                    ],
                }
                if not chat_models and all_models:
                    payload["warning"] = (
                        "Only embedding models found. Run: ollama pull qwen3:8b"
                    )
                _models_cache["ts"] = now
                _models_cache["data"] = payload
                return payload
        except Exception as e:
            last_err = str(e)
            continue
    err = {
        "error": "Ollama not reachable",
        "detail": last_err,
        "hosts_tried": OLLAMA_HOSTS,
        "hint": (
            "1) Start Ollama (ollama.com)  2) ollama pull qwen3:8b  "
            "3) backend/.env → OLLAMA_HOST=127.0.0.1:11434  4) .\\start.ps1"
        ),
    }
    return err


async def _prepare_chat_messages(payload: dict) -> tuple[list, dict | None, dict | None]:
    """Firewall scan + WorldBase context. Returns (messages, firewall_meta, block_payload)."""
    firewall_meta = None
    messages = list(payload.get("messages", []))

    if payload.get("firewall"):
        from firewall_bridge import _extract_user_text, guard_chat_user_text

        user_text = _extract_user_text(messages)
        if user_text:
            session_id = payload.get("chat_session_id") or payload.get("session_id")
            firewall_meta, block_payload = await guard_chat_user_text(
                user_text,
                session_id=str(session_id) if session_id else None,
            )
            if block_payload:
                return messages, firewall_meta, block_payload

    search_results = payload.get("search_results", "")
    entity_context = payload.get("entity_context", "")
    force_fast = payload.get("force_fast") or bool(entity_context)
    want_ctx = payload.get("context") and not force_fast
    ctx = await build_chat_context() if want_ctx else ""

    rag_block = ""
    if want_ctx:
        from firewall_bridge import _extract_user_text
        from rag_crag import build_rag_crag_block

        user_q = _extract_user_text(messages)
        if len(user_q) >= 8:
            rag_block = await build_rag_crag_block(user_q)

    if ctx or entity_context or search_results or rag_block:
        parts = []
        if ctx:
            parts.append("=== INTERNAL TELEMETRY ===\n" + ctx)
        if rag_block:
            parts.append(rag_block)
        if entity_context:
            parts.append("=== SELECTED TARGET (Globe) ===\n" + entity_context)
        if search_results:
            parts.append("=== WEB SEARCH RESULTS ===\n" + search_results)
        entity_rules = (
            "\n6. SELECTED TARGET is the operator's picked map entity — analyze IT first; "
            "do not answer with generic world news unless the target clearly ties to it.\n"
            if entity_context
            else ""
        )
        system_msg = {
            "role": "system",
            "content": (
                "You are WorldBase AI — local Ollama on a spatial intelligence workstation.\n\n"
                "CAPABILITIES (be honest if asked):\n"
                "- Direct internet: only when the operator enabled web search (🔍); "
                "then you receive DuckDuckGo snippets below — not live browsing.\n"
                "- Live feeds (aircraft, quakes, nodes, CVE, headlines): only when "
                "INTERNAL TELEMETRY is attached (CTX/situation mode).\n"
                "- RAG MEMORY block: citable indexed briefings/feeds; CRAG fallback "
                "adds live situations + FtM subgraph when memory confidence is low.\n"
                "- Tools may query WorldBase APIs (situations, OSINT lookups).\n\n"
                "RULES:\n"
                "1. Answer the user's actual question FIRST (1-3 sentences), same language.\n"
                "2. Use ONLY data in the blocks below — never invent URLs, headlines, or CVEs.\n"
                "3. Cite sources only from WEB SEARCH RESULTS or INTERNAL TELEMETRY; "
                "if none apply, say so — no fake SOURCES section.\n"
                "4. Use KEY FINDINGS → DETAILS → SOURCES only for explicit analysis requests; "
                "skip that template for simple or meta questions.\n"
                "5. If data is missing, say 'DATA GAP: [topic]' — do not guess.\n"
                + entity_rules
                + "\n\n"
                + "\n\n".join(parts)
            ),
        }
        messages = [system_msg] + messages
    elif not any(m.get("role") == "system" for m in messages):
        messages = [{
            "role": "system",
            "content": (
                "You are WorldBase AI (local Ollama). No live feeds or web search are "
                "attached to this message unless the operator enables CTX or 🔍. "
                "Answer honestly and concisely in the user's language. "
                "Do not invent URLs or claim internet access you do not have."
            ),
        }] + messages

    return messages, firewall_meta, None


@router.post("/api/chat")
@rate_limit_general()
async def chat_proxy(request: Request, payload: dict, api_key: str = Depends(verify_api_key)):
    """Proxy chat requests to LLM providers. Supports SSE streaming.

    Providers: ollama (default), openai, anthropic, groq, openrouter.
    Set payload['context'] = True to inject live WorldBase state as a system message.
    Set payload['firewall'] = True to route user messages through the LLM-Security-Firewall.
    """
    from ollama_config import chat_timeout, keep_alive
    import chat_routing

    opts = chat_routing.resolve_chat_options(
        payload,
        default_model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
    )
    provider = opts["provider"]
    model = opts["model"]
    use_stream = opts["use_stream"]
    use_tools = opts["use_tools"]
    force_fast = opts["force_fast"]

    def _ollama_chat_body(model_name: str, messages: list, *, stream: bool) -> dict:
        return chat_routing.build_ollama_chat_body(
            model_name,
            messages,
            stream=stream,
            force_fast=force_fast,
            keep_alive=keep_alive(),
        )

    # ------------------------------------------------------------------
    # OLLAMA (local, default)
    # ------------------------------------------------------------------
    if provider == "ollama":
        if use_stream:
            async def ollama_stream():
                yield f"data: {json.dumps({'status': 'preparing'})}\n\n"
                messages, firewall_meta, block_msg = await _prepare_chat_messages(payload)
                if block_msg:
                    yield f"data: {json.dumps(block_msg)}\n\n"
                    return
                if firewall_meta:
                    yield f"data: {json.dumps({'firewall_result': firewall_meta})}\n\n"
                last_err = None
                ollama_timeout = chat_timeout()
                for host in OLLAMA_HOSTS:
                    host = host.strip()
                    try:
                        if use_tools:
                            yield f"data: {json.dumps({'status': 'tools'})}\n\n"
                            async for event in chat_tools.stream_ollama_with_tools(
                                host, model, messages, max_rounds=4
                            ):
                                if event.get("token"):
                                    yield f"data: {json.dumps({'token': event['token']})}\n\n"
                                elif event.get("status"):
                                    yield f"data: {json.dumps(event)}\n\n"
                                elif event.get("client_action"):
                                    yield f"data: {json.dumps({'client_action': event['client_action']})}\n\n"
                                elif event.get("done"):
                                    yield f"data: {json.dumps({'done': True})}\n\n"
                            return
                        yield f"data: {json.dumps({'status': 'generating'})}\n\n"
                        url = f"http://{host}/api/chat"
                        chat_body = _ollama_chat_body(model, messages, stream=True)
                        async with httpx.AsyncClient(timeout=ollama_timeout) as client:
                            async with client.stream(
                                "POST",
                                url,
                                json=chat_body,
                            ) as r:
                                r.raise_for_status()
                                async for line in r.aiter_lines():
                                    if not line.strip():
                                        continue
                                    try:
                                        data = json.loads(line)
                                    except json.JSONDecodeError:
                                        continue
                                    if data.get("done"):
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    content = data.get("message", {}).get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                        return
                    except httpx.ConnectError:
                        last_err = f"Ollama not reachable at {host}"
                        continue
                    except Exception as e:
                        last_err = str(e)
                        continue
                yield f"data: {json.dumps({'error': last_err or 'Ollama not reachable'})}\n\n"

            return StreamingResponse(ollama_stream(), media_type="text/event-stream")

        messages, firewall_meta, block_msg = await _prepare_chat_messages(payload)
        if block_msg:
            return block_msg

        last_err = None
        for host in OLLAMA_HOSTS:
            host = host.strip()
            try:
                if use_tools:
                    final_msgs, actions = await chat_tools.run_ollama_with_tools(
                        host, model, messages, max_rounds=4
                    )
                    text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                    return {
                        "message": {"role": "assistant", "content": text},
                        "client_actions": actions,
                        "done": True,
                    }
                url = f"http://{host}/api/chat"
                async with httpx.AsyncClient(timeout=chat_timeout()) as client:
                    r = await client.post(
                        url,
                        json=_ollama_chat_body(model, messages, stream=False),
                    )
                    r.raise_for_status()
                    return r.json()
            except httpx.ConnectError:
                last_err = f"Ollama not reachable at {host}"
                continue
            except httpx.HTTPStatusError as e:
                detail = ""
                try:
                    detail = e.response.text[:200]
                except Exception:
                    pass
                status = e.response.status_code
                if status == 404:
                    return {
                        "error": f"Model '{model}' not found. Run: ollama pull {model}",
                        "host": host,
                        "status": status,
                    }
                return {
                    "error": f"Ollama HTTP {status} at {host}",
                    "detail": detail,
                }
            except Exception as e:
                last_err = str(e)
                continue

        return {
            "error": last_err or "Ollama not running. Install from ollama.com",
            "hosts_tried": OLLAMA_HOSTS,
        }

    # ------------------------------------------------------------------
    # EXTERNAL PROVIDERS (OpenAI-compatible or Anthropic)
    # ------------------------------------------------------------------
    messages, firewall_meta, block_msg = await _prepare_chat_messages(payload)
    if block_msg:
        if use_stream:
            return StreamingResponse(
                (f"data: {json.dumps(block_msg)}\n\n" async for _ in [1]),
                media_type="text/event-stream",
            )
        return block_msg

    api_keys = payload.get("api_keys") if isinstance(payload.get("api_keys"), dict) else None
    api_base_urls = payload.get("api_base_urls") if isinstance(payload.get("api_base_urls"), dict) else None
    client_url_override = _client_base_url_override_allowed()
    if client_url_override:
        url_err = chat_routing.validate_client_base_urls(api_base_urls)
        if url_err:
            return {"error": url_err, "provider": provider}

    PROVIDER_CONFIG = {
        "openai": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "openai",
                    api_base_urls,
                    os.getenv("OPENAI_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["openai"],
                    client_override=client_url_override,
                )
            ),
            "key": chat_routing.select_api_key("openai", api_keys, os.getenv("OPENAI_API_KEY")),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "groq": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "groq",
                    api_base_urls,
                    os.getenv("GROQ_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["groq"],
                    client_override=client_url_override,
                )
            ),
            "key": chat_routing.select_api_key("groq", api_keys, os.getenv("GROQ_API_KEY")),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
        "openrouter": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "openrouter",
                    api_base_urls,
                    os.getenv("OPENROUTER_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["openrouter"],
                    client_override=client_url_override,
                )
            ),
            "key": chat_routing.select_api_key("openrouter", api_keys, os.getenv("OPENROUTER_API_KEY")),
            "header": "Authorization",
            "prefix": "Bearer ",
        },
    }

    if provider in PROVIDER_CONFIG:
        cfg = PROVIDER_CONFIG[provider]
        api_key = cfg["key"]
        if not api_key:
            return {
                "error": (
                    f"No API key for {provider}. Add it in the HUD settings "
                    f"or set {provider.upper()}_API_KEY in .env"
                ),
                "provider": provider,
            }

        headers = {
            "Content-Type": "application/json",
            cfg["header"]: cfg["prefix"] + api_key,
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://worldbase.local"
            headers["X-Title"] = "WorldBase"

        body = {
            "model": model,
            "messages": messages,
            "stream": use_stream,
            "temperature": 0.7,
        }

        # ----- Tool-calling loop (full WorldBase access for cloud models) -----
        if use_tools:
            if use_stream:
                async def openai_tools_stream():
                    try:
                        async for event in chat_tools.stream_openai_with_tools(
                            cfg["url"], headers, model, messages, max_rounds=4
                        ):
                            yield f"data: {json.dumps(event)}\n\n"
                    except Exception as e:
                        yield f"data: {json.dumps({'error': f'{provider} tool stream error: {e}'})}\n\n"

                return StreamingResponse(openai_tools_stream(), media_type="text/event-stream")

            try:
                final_msgs, actions = await chat_tools.run_openai_with_tools(
                    cfg["url"], headers, model, messages, max_rounds=4
                )
                text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                return {
                    "message": {"role": "assistant", "content": text},
                    "client_actions": actions,
                    "done": True,
                    "provider": provider,
                }
            except httpx.HTTPStatusError as e:
                return {
                    "error": f"{provider} HTTP {e.response.status_code}",
                    "detail": e.response.text[:300],
                    "provider": provider,
                }
            except Exception as e:
                return {"error": f"{provider} tool request failed: {e}", "provider": provider}

        if use_stream:
            async def openai_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream("POST", cfg["url"], headers=headers, json=body) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    if payload_text.strip() == "[DONE]":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'{provider} stream error: {e}'})}\n\n"

            return StreamingResponse(openai_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(cfg["url"], headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                choice = data.get("choices", [{}])[0]
                return {
                    "message": {
                        "role": "assistant",
                        "content": choice.get("message", {}).get("content", "") or choice.get("text", ""),
                    },
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"{provider} HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"{provider} request failed: {e}", "provider": provider}

    # ------------------------------------------------------------------
    # ANTHROPIC (Messages API, non-OpenAI format)
    # ------------------------------------------------------------------
    if provider == "anthropic":
        api_key = chat_routing.select_api_key("anthropic", api_keys, os.getenv("ANTHROPIC_API_KEY"))
        if not api_key:
            return {
                "error": (
                    "No API key for anthropic. Add it in the HUD settings "
                    "or set ANTHROPIC_API_KEY in .env"
                ),
                "provider": provider,
            }

        url = chat_routing.anthropic_messages_url(
            chat_routing.select_base_url(
                "anthropic",
                api_base_urls,
                os.getenv("ANTHROPIC_BASE_URL"),
                chat_routing.DEFAULT_BASE_URLS["anthropic"],
                client_override=client_url_override,
            )
        )
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

        # Extract system message if present
        system_text = ""
        chat_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text = m.get("content", "")
            else:
                chat_messages.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": model,
            "messages": chat_messages,
            "max_tokens": 4096,
            "stream": use_stream,
        }
        if system_text:
            body["system"] = system_text

        if use_stream:
            async def anthropic_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream("POST", url, headers=headers, json=body) as r:
                            r.raise_for_status()
                            async for line in r.aiter_lines():
                                if not line.strip():
                                    continue
                                if line.startswith("data: "):
                                    payload_text = line[6:]
                                    try:
                                        chunk = json.loads(payload_text)
                                    except json.JSONDecodeError:
                                        continue
                                    t = chunk.get("type", "")
                                    if t == "content_block_delta":
                                        text = chunk.get("delta", {}).get("text", "")
                                        if text:
                                            yield f"data: {json.dumps({'token': text})}\n\n"
                                    elif t == "message_stop":
                                        yield f"data: {json.dumps({'done': True})}\n\n"
                                        break
                            yield f"data: {json.dumps({'done': True})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': f'anthropic stream error: {e}'})}\n\n"

            return StreamingResponse(anthropic_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, headers=headers, json=body)
                r.raise_for_status()
                data = r.json()
                content_blocks = data.get("content", [])
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text += block.get("text", "")
                return {
                    "message": {"role": "assistant", "content": text},
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                }
        except httpx.HTTPStatusError as e:
            return {
                "error": f"anthropic HTTP {e.response.status_code}",
                "detail": e.response.text[:300],
                "provider": provider,
            }
        except Exception as e:
            return {"error": f"anthropic request failed: {e}", "provider": provider}

    return {"error": f"Unknown provider '{provider}'", "available": ["ollama", "openai", "anthropic", "groq", "openrouter"]}


@router.get("/api/providers")
def list_providers():
    """Catalog of LLM providers.

    All providers are listed so the operator can configure a key in the HUD even
    when ``.env`` has none. ``key_set`` reports whether an ``.env`` key exists;
    ``supports_tools`` flags providers wired to the WorldBase tool loop.
    """
    catalog = [
        {"id": "ollama", "name": "Ollama (Local)", "models": [], "requires_key": False, "env_key": None, "env_base": None, "default_base_url": None},
        {"id": "openai", "name": "OpenAI", "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"], "requires_key": True, "env_key": "OPENAI_API_KEY", "env_base": "OPENAI_BASE_URL", "default_base_url": chat_routing.DEFAULT_BASE_URLS["openai"]},
        {"id": "anthropic", "name": "Anthropic", "models": ["claude-3-5-sonnet-20241022", "claude-3-opus-20240229", "claude-3-haiku-20240307"], "requires_key": True, "env_key": "ANTHROPIC_API_KEY", "env_base": "ANTHROPIC_BASE_URL", "default_base_url": chat_routing.DEFAULT_BASE_URLS["anthropic"]},
        {"id": "groq", "name": "Groq", "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"], "requires_key": True, "env_key": "GROQ_API_KEY", "env_base": "GROQ_BASE_URL", "default_base_url": chat_routing.DEFAULT_BASE_URLS["groq"]},
        {"id": "openrouter", "name": "OpenRouter", "models": ["openai/gpt-4o", "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.3-70b-instruct"], "requires_key": True, "env_key": "OPENROUTER_API_KEY", "env_base": "OPENROUTER_BASE_URL", "default_base_url": chat_routing.DEFAULT_BASE_URLS["openrouter"]},
    ]
    providers = []
    for p in catalog:
        env_key_name = p.pop("env_key")
        env_base_name = p.pop("env_base")
        providers.append({
            **p,
            "key_set": bool(os.getenv(env_key_name)) if env_key_name else False,
            "base_url_set": bool(os.getenv(env_base_name)) if env_base_name else False,
            "supports_tools": chat_routing.provider_supports_tools(p["id"]),
        })
    return {"providers": providers}
