"""LLM proxy endpoints — /api/models, /api/chat, /api/providers.

Extracted from routes/chat.py (Phase 2). Handles provider fan-out,
SSE streaming, firewall gate, and the chat message preparation pipeline.
"""

from __future__ import annotations

import json
import os
import time

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

import chat_routing
import chat_tools
from auth.security import verify_api_key
from middleware.rate_limit import rate_limit_general

from chat_context import (
    OLLAMA_HOSTS,
    _is_embed_model,
    _models_cache,
    _MODELS_CACHE_TTL,
    build_chat_context,
)

router = APIRouter(tags=["chat"])


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
                chat_models = [
                    m for m in all_models if not _is_embed_model(m.get("name", ""))
                ]
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
                    "default": default_model
                    if default_model in chat_names
                    else (chat_names[0] if chat_names else None),
                    "embed_model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                    "embed_available": any(_is_embed_model(n or "") for n in all_names),
                    "models": [
                        {
                            "name": m.get("name"),
                            "size": m.get("size"),
                            "parameter_size": m.get("details", {}).get(
                                "parameter_size"
                            ),
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


async def _prepare_chat_messages(
    payload: dict,
) -> tuple[list, dict | None, dict | None, str]:
    """Firewall scan + WorldBase context. Returns (messages, firewall_meta, block_payload, user_text)."""
    firewall_meta = None
    messages = list(payload.get("messages", []))
    user_text = ""

    # Layer 2: Session Guard — multi-turn attack detection
    from firewall_bridge import _extract_user_text
    user_text = _extract_user_text(messages)
    session_id = payload.get("chat_session_id") or payload.get("session_id") or "default"
    if user_text:
        try:
            from session_guard import get_guard as get_session_guard
            sg = get_session_guard()
            session_result = sg.check_session(str(session_id), user_text)
            if session_result["action"] in ("block", "lock"):
                block_payload = {
                    "error": "Session guard triggered",
                    "detail": f"Session score {session_result['session_score']} — action: {session_result['action']}",
                    "guard": {"layer": "session", **session_result},
                }
                return messages, {"session_guard": session_result}, block_payload
            firewall_meta = {"session_guard": session_result} if session_result["action"] == "warn" else None
        except Exception:
            pass

    if payload.get("firewall"):
        from firewall_bridge import guard_chat_user_text

        if user_text:
            fw_meta, block_payload = await guard_chat_user_text(
                user_text,
                session_id=str(session_id) if session_id else None,
            )
            if block_payload:
                return messages, fw_meta, block_payload
            if fw_meta:
                firewall_meta = {**(firewall_meta or {}), **{"firewall": fw_meta}}

    search_results = payload.get("search_results", "")
    entity_context = payload.get("entity_context", "")
    force_fast = payload.get("force_fast") or bool(entity_context)
    want_ctx = payload.get("context") and not force_fast
    ctx = await build_chat_context() if want_ctx else ""

    rag_block = ""
    route_tag = ""
    agentic_trace_line = ""
    if want_ctx:
        from firewall_bridge import _extract_user_text
        from query_router import router_enabled, route_label

        user_q = _extract_user_text(messages)
        if len(user_q) >= 8:
            if router_enabled():
                from rag_crag import build_routed_block

                routed = await build_routed_block(user_q)
                rag_block = routed.get("block", "")
                route_tag = route_label(routed.get("route", "vector"))
            else:
                from rag_crag import build_rag_crag_block

                rag_block = await build_rag_crag_block(user_q)

            # P3: Agentic chat loop — coverage → retrieve → corroboration
            from chat_agentic import (
                chat_agentic_enabled,
                run_chat_agentic_loop,
                format_agentic_trace_line,
            )

            if chat_agentic_enabled() and rag_block:
                rag_block, agentic_trace = await run_chat_agentic_loop(
                    user_q, rag_block
                )
                agentic_trace_line = format_agentic_trace_line(agentic_trace)

    # Layer 1: RAG Integrity Guard — scan context blocks for indirect injection
    rag_integrity_meta = None
    if rag_block:
        try:
            from rag_integrity import scan_rag_block as _scan_rag
            rag_block, rag_scan = _scan_rag(rag_block, source="rag_memory")
            if rag_scan["blocked"]:
                rag_integrity_meta = rag_scan
        except Exception:
            pass
    if ctx:
        try:
            from rag_integrity import scan_rag_block as _scan_rag
            ctx, ctx_scan = _scan_rag(ctx, source="briefing")
            if ctx_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or ctx_scan
        except Exception:
            pass
    if entity_context:
        try:
            from rag_integrity import scan_rag_block as _scan_rag
            entity_context, ent_scan = _scan_rag(entity_context, source="ftm_entity")
            if ent_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or ent_scan
        except Exception:
            pass
    if search_results:
        try:
            from rag_integrity import scan_rag_block as _scan_rag
            search_results, sr_scan = _scan_rag(search_results, source="web_search")
            if sr_scan["blocked"]:
                rag_integrity_meta = rag_integrity_meta or sr_scan
        except Exception:
            pass
    if rag_integrity_meta:
        firewall_meta = {**(firewall_meta or {}), **{"rag_integrity": rag_integrity_meta}}

    if ctx or entity_context or search_results or rag_block:
        parts = []
        if ctx:
            parts.append("=== INTERNAL TELEMETRY ===\n" + ctx)
        if rag_block:
            prefix = ""
            if route_tag:
                prefix = f"Retrieval mode: {route_tag}"
            if agentic_trace_line:
                prefix = (
                    (prefix + "\n" + agentic_trace_line).strip()
                    if prefix
                    else agentic_trace_line
                )
            if prefix:
                parts.append(f"{prefix}\n\n" + rag_block)
            else:
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
                "- Query Router (P1): retrieval mode shown above — use the indicated "
                "retrieval strategy (VECTOR/GRAPH/SPATIAL/HYBRID/LIVE) for context.\n"
                "- Agentic (P3): when AGENTIC trace is shown, coverage gaps were filled "
                "with targeted retrieval; [corroborated]/[uncorroborated] tags mark "
                "claim strength — weigh tagged claims accordingly.\n"
                "- Tools may query WorldBase APIs (situations, OSINT lookups, "
                "spatial_query for 'within X km of Y' questions).\n\n"
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
        messages = [
            {
                "role": "system",
                "content": (
                    "You are WorldBase AI (local Ollama). No live feeds or web search are "
                    "attached to this message unless the operator enables CTX or 🔍. "
                    "Answer honestly and concisely in the user's language. "
                    "Do not invent URLs or claim internet access you do not have."
                ),
            }
        ] + messages

    return messages, firewall_meta, None, user_text


def _apply_output_guard(response_text: str, user_text: str = "") -> tuple[str, dict | None]:
    """Layer 3: Output Guard — scan LLM response for leaks/echo before returning."""
    try:
        from output_guard import check_output
        result = check_output(response_text, user_text)
        if result["blocked"]:
            return result["sanitized"], {"output_guard": result}
    except Exception:
        pass
    return response_text, None


@router.post("/api/chat")
@rate_limit_general()
async def chat_proxy(
    request: Request, payload: dict, api_key: str = Depends(verify_api_key)
):
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
                messages, firewall_meta, block_msg, user_text = await _prepare_chat_messages(
                    payload
                )
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

        messages, firewall_meta, block_msg, user_text = await _prepare_chat_messages(payload)
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
                    text, og_meta = _apply_output_guard(text, user_text)
                    return {
                        "message": {"role": "assistant", "content": text},
                        "client_actions": actions,
                        "done": True,
                        **({"firewall_result": {**(firewall_meta or {}), **og_meta}} if og_meta else {}),
                    }
                url = f"http://{host}/api/chat"
                async with httpx.AsyncClient(timeout=chat_timeout()) as client:
                    r = await client.post(
                        url,
                        json=_ollama_chat_body(model, messages, stream=False),
                    )
                    r.raise_for_status()
                    data = r.json()
                    # Layer 3: Output Guard on non-streaming Ollama response
                    resp_text = (data.get("message") or {}).get("content", "")
                    if resp_text:
                        resp_text, og_meta = _apply_output_guard(resp_text, user_text)
                        data.setdefault("message", {})['content'] = resp_text
                        if og_meta:
                            data["firewall_result"] = {**(firewall_meta or {}), **og_meta}
                    return data
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
    messages, firewall_meta, block_msg, user_text = await _prepare_chat_messages(payload)
    if block_msg:
        if use_stream:
            return StreamingResponse(
                (f"data: {json.dumps(block_msg)}\n\n" async for _ in [1]),
                media_type="text/event-stream",
            )
        return block_msg

    api_keys = (
        payload.get("api_keys") if isinstance(payload.get("api_keys"), dict) else None
    )
    api_base_urls = (
        payload.get("api_base_urls")
        if isinstance(payload.get("api_base_urls"), dict)
        else None
    )

    if api_base_urls:
        for prov, raw in api_base_urls.items():
            if not isinstance(raw, str) or not raw.strip():
                continue
            env_name = chat_routing.PROVIDER_ENV_BASE_URLS.get(prov)
            env_base = os.getenv(env_name) if env_name else None
            try:
                chat_routing.assert_safe_provider_base_url(prov, raw, env_base=env_base)
            except ValueError as exc:
                return {"error": str(exc), "provider": prov}

    PROVIDER_CONFIG = {
        "openai": {
            "url": chat_routing.openai_chat_completions_url(
                chat_routing.select_base_url(
                    "openai",
                    api_base_urls,
                    os.getenv("OPENAI_BASE_URL"),
                    chat_routing.DEFAULT_BASE_URLS["openai"],
                )
            ),
            "key": chat_routing.select_api_key(
                "openai", api_keys, os.getenv("OPENAI_API_KEY")
            ),
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
                )
            ),
            "key": chat_routing.select_api_key(
                "groq", api_keys, os.getenv("GROQ_API_KEY")
            ),
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
                )
            ),
            "key": chat_routing.select_api_key(
                "openrouter", api_keys, os.getenv("OPENROUTER_API_KEY")
            ),
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

                return StreamingResponse(
                    openai_tools_stream(), media_type="text/event-stream"
                )

            try:
                final_msgs, actions = await chat_tools.run_openai_with_tools(
                    cfg["url"], headers, model, messages, max_rounds=4
                )
                text = (final_msgs[-1].get("content") or "") if final_msgs else ""
                text, og_meta = _apply_output_guard(text, user_text)
                return {
                    "message": {"role": "assistant", "content": text},
                    "client_actions": actions,
                    "done": True,
                    "provider": provider,
                    **({"firewall_result": {**(firewall_meta or {}), **og_meta}} if og_meta else {}),
                }
            except httpx.HTTPStatusError as e:
                return {
                    "error": f"{provider} HTTP {e.response.status_code}",
                    "detail": e.response.text[:300],
                    "provider": provider,
                }
            except Exception as e:
                return {
                    "error": f"{provider} tool request failed: {e}",
                    "provider": provider,
                }

        if use_stream:

            async def openai_stream():
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        async with client.stream(
                            "POST", cfg["url"], headers=headers, json=body
                        ) as r:
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
                                    delta = chunk.get("choices", [{}])[0].get(
                                        "delta", {}
                                    )
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
                resp_text = choice.get("message", {}).get("content", "") or choice.get("text", "")
                resp_text, og_meta = _apply_output_guard(resp_text, user_text)
                return {
                    "message": {
                        "role": "assistant",
                        "content": resp_text,
                    },
                    "done": True,
                    "provider": provider,
                    "model": data.get("model"),
                    **({"firewall_result": {**(firewall_meta or {}), **og_meta}} if og_meta else {}),
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
        api_key = chat_routing.select_api_key(
            "anthropic", api_keys, os.getenv("ANTHROPIC_API_KEY")
        )
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
                        async with client.stream(
                            "POST", url, headers=headers, json=body
                        ) as r:
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
                text, og_meta = _apply_output_guard(text, user_text)
                return {
                    "message": {"role": "assistant", "content": text},
                    "done": True,
                    **({"firewall_result": {**(firewall_meta or {}), **og_meta}} if og_meta else {}),
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

    return {
        "error": f"Unknown provider '{provider}'",
        "available": ["ollama", "openai", "anthropic", "groq", "openrouter"],
    }


@router.get("/api/providers")
def list_providers():
    """Catalog of LLM providers.

    All providers are listed so the operator can configure a key in the HUD even
    when ``.env`` has none. ``key_set`` reports whether an ``.env`` key exists;
    ``supports_tools`` flags providers wired to the WorldBase tool loop.
    """
    catalog = [
        {
            "id": "ollama",
            "name": "Ollama (Local)",
            "models": [],
            "requires_key": False,
            "env_key": None,
            "env_base": None,
            "default_base_url": None,
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
            "requires_key": True,
            "env_key": "OPENAI_API_KEY",
            "env_base": "OPENAI_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["openai"],
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "models": [
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
                "claude-3-haiku-20240307",
            ],
            "requires_key": True,
            "env_key": "ANTHROPIC_API_KEY",
            "env_base": "ANTHROPIC_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["anthropic"],
        },
        {
            "id": "groq",
            "name": "Groq",
            "models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
            "requires_key": True,
            "env_key": "GROQ_API_KEY",
            "env_base": "GROQ_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["groq"],
        },
        {
            "id": "openrouter",
            "name": "OpenRouter",
            "models": [
                "openai/gpt-4o",
                "anthropic/claude-3.5-sonnet",
                "meta-llama/llama-3.3-70b-instruct",
            ],
            "requires_key": True,
            "env_key": "OPENROUTER_API_KEY",
            "env_base": "OPENROUTER_BASE_URL",
            "default_base_url": chat_routing.DEFAULT_BASE_URLS["openrouter"],
        },
    ]
    providers = []
    for p in catalog:
        env_key_name = p.pop("env_key")
        env_base_name = p.pop("env_base")
        providers.append(
            {
                **p,
                "key_set": bool(os.getenv(env_key_name)) if env_key_name else False,
                "base_url_set": bool(os.getenv(env_base_name))
                if env_base_name
                else False,
                "supports_tools": chat_routing.provider_supports_tools(p["id"]),
            }
        )
    return {"providers": providers}
