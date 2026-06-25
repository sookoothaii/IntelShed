"""WorldBase AI tool definitions and execution (Ollama function calling)."""

from __future__ import annotations

import json
from typing import Any

import httpx

import entity_store
import feeds_extra
import osint_tools

_UA = {"User-Agent": "WorldBase/1.0"}

OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "osint_ip",
            "description": "Geolocate an IPv4 address (passive OSINT).",
            "parameters": {
                "type": "object",
                "properties": {"ip": {"type": "string", "description": "IPv4 address"}},
                "required": ["ip"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "osint_domain",
            "description": "DNS lookup for a domain (A/MX records).",
            "parameters": {
                "type": "object",
                "properties": {"domain": {"type": "string"}},
                "required": ["domain"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_correlations",
            "description": "List current cross-feed situation correlations.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_situations",
            "description": "Unified situation board items (correlations, anomalies, GDACS, pegel, sensors).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "entity_context",
            "description": "Get all WorldBase knowledge about an entity ID (e.g. aircraft:abc123, osint:ip:8.8.8.8).",
            "parameters": {
                "type": "object",
                "properties": {"entity_id": {"type": "string"}},
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_globe",
            "description": "Ask the UI to focus the globe on coordinates. Returns client_action for the dashboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "title": {"type": "string"},
                    "lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["lat", "lon", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_briefing",
            "description": "Trigger a new LLM world-situation briefing on the server.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Semantic search over indexed briefings and GDELT headlines (citable RAG memory).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "k": {"type": "integer", "description": "Max results (default 6)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spatial_query",
            "description": "Execute a natural-language spatial query against WorldBase entities. Examples: 'within 50km of Bangkok', 'near Phuket', 'downstream from Chao Phraya'. Returns matching entities with coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language spatial query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 12)",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


async def execute_tool(name: str, arguments: dict) -> dict[str, Any]:
    args = arguments or {}
    client_action = None

    if name == "osint_ip":
        ip = str(args.get("ip", "")).strip()
        result = await osint_tools.ip_lookup(ip)
        if result.get("lat") is not None:
            eid = entity_store.entity_id_for_pin("ip", ip)
            entity_store.upsert_entity(
                eid,
                "osint_ip",
                label=f"IP {ip}",
                lat=result["lat"],
                lon=result["lon"],
                source_feed="osint",
                external_id=ip,
                meta=result,
            )
            result["entity_id"] = eid
        return {"tool": name, "result": result}

    if name == "osint_domain":
        domain = str(args.get("domain", "")).strip()
        result = await osint_tools.domain_lookup(domain)
        return {"tool": name, "result": result}

    if name == "list_correlations":
        result = await feeds_extra.cross_feed_correlations()
        return {"tool": name, "result": result}

    if name == "list_situations":
        from situations import unified_situations

        result = await unified_situations()
        return {
            "tool": name,
            "result": {
                "count": result.get("count"),
                "items": (result.get("items") or [])[:20],
            },
        }

    if name == "entity_context":
        eid = str(args.get("entity_id", "")).strip()
        result = entity_store.get_entity_context(eid)
        return {"tool": name, "result": result}

    if name == "focus_globe":
        lat = float(args["lat"])
        lon = float(args["lon"])
        title = str(args.get("title", "Focus"))
        lines = args.get("lines") or []
        client_action = {
            "type": "focus_globe",
            "lat": lat,
            "lon": lon,
            "title": title,
            "lines": lines,
            "kind": "ai_focus",
        }
        return {
            "tool": name,
            "result": {"ok": True, "lat": lat, "lon": lon},
            "client_action": client_action,
        }

    if name == "generate_briefing":
        import node_sync

        result = await node_sync.generate_briefing_internal()
        return {
            "tool": name,
            "result": {
                "created_at": result.get("created_at"),
                "preview": (result.get("text") or "")[:500],
            },
        }

    if name == "search_memory":
        import rag_memory
        from rag_spatial import operator_search_bbox, spatial_enabled

        query = str(args.get("query", "")).strip()
        k = int(args.get("k") or 6)
        bbox = operator_search_bbox() if spatial_enabled() else None
        results = await rag_memory.search(query, k=k, bbox=bbox)
        return {
            "tool": name,
            "result": {
                "query": query,
                "count": len(results),
                "spatial": bool(bbox),
                "results": results,
            },
        }

    if name == "spatial_query":
        import spatial_reasoning

        query = str(args.get("query", "")).strip()
        limit = int(args.get("limit") or 12)
        raw = spatial_reasoning.spatial_query(query)
        results = (raw.get("results") or [])[:limit]
        return {
            "tool": name,
            "result": {
                "query": query,
                "enabled": raw.get("enabled"),
                "composition": raw.get("composition"),
                "operations": raw.get("operations"),
                "resolved_entities": raw.get("resolved_entities"),
                "count": len(results),
                "results": [
                    {
                        "id": r.get("id"),
                        "schema": r.get("schema"),
                        "caption": r.get("caption"),
                        "lat": r.get("lat"),
                        "lon": r.get("lon"),
                    }
                    for r in results
                ],
            },
        }

    return {"tool": name, "error": f"unknown tool: {name}"}


def parse_tool_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def _ollama_chat_body(
    model: str, messages: list, *, stream: bool, with_tools: bool
) -> dict:
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "keep_alive": __import__("ollama_config").keep_alive(),
    }
    if with_tools:
        body["tools"] = OLLAMA_TOOLS
    if "qwen3" in (model or "").lower():
        body["think"] = False
    return body


async def stream_ollama_with_tools(
    host: str,
    model: str,
    messages: list,
    max_rounds: int = 4,
):
    """Stream Ollama chat with tools — yields token/status/client_action/done events."""
    working = list(messages)
    url = f"http://{host}/api/chat"
    timeout = __import__("ollama_config").chat_timeout()

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(max_rounds):
            tool_calls_final: list = []
            content_final = ""
            yield {"status": "generating"}

            async with client.stream(
                "POST",
                url,
                json=_ollama_chat_body(model, working, stream=True, with_tools=True),
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
                        msg = data.get("message") or {}
                        tool_calls_final = msg.get("tool_calls") or []
                        if not content_final:
                            content_final = msg.get("content") or ""
                        break
                    chunk = (data.get("message") or {}).get("content", "")
                    if chunk:
                        content_final += chunk
                        yield {"token": chunk}

            if tool_calls_final:
                working.append(
                    {
                        "role": "assistant",
                        "content": content_final,
                        "tool_calls": tool_calls_final,
                    }
                )
                for tc in tool_calls_final:
                    fn = tc.get("function") or {}
                    tname = fn.get("name", "")
                    targs = parse_tool_arguments(fn.get("arguments"))
                    yield {"status": "tool", "tool": tname}
                    out = await execute_tool(tname, targs)
                    if out.get("client_action"):
                        yield {"client_action": out["client_action"]}
                    working.append(
                        {
                            "role": "tool",
                            "content": json.dumps(out.get("result", out), default=str)[
                                :8000
                            ],
                        }
                    )
                continue

            yield {"done": True}
            return

    yield {"token": "Tool loop limit reached."}
    yield {"done": True}


async def run_ollama_with_tools(
    host: str,
    model: str,
    messages: list,
    max_rounds: int = 4,
) -> tuple[list[dict], list[dict]]:
    """Run Ollama chat with tools; returns (final_messages_delta, client_actions)."""
    client_actions: list[dict] = []
    working = list(messages)
    url = f"http://{host}/api/chat"

    timeout = __import__("ollama_config").chat_timeout()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(max_rounds):
            r = await client.post(
                url,
                json=_ollama_chat_body(model, working, stream=False, with_tools=True),
            )
            r.raise_for_status()
            data = r.json()
            msg = data.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                return ([msg], client_actions)

            working.append(msg)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tname = fn.get("name", "")
                targs = parse_tool_arguments(fn.get("arguments"))
                out = await execute_tool(tname, targs)
                if out.get("client_action"):
                    client_actions.append(out["client_action"])
                working.append(
                    {
                        "role": "tool",
                        "content": json.dumps(out.get("result", out), default=str)[
                            :8000
                        ],
                    }
                )

    return (
        [{"role": "assistant", "content": "Tool loop limit reached."}],
        client_actions,
    )


# ----------------------------------------------------------------------
# OpenAI-compatible providers (OpenAI / Groq / OpenRouter, any /v1/chat/completions)
# Reuses OLLAMA_TOOLS (already OpenAI function-calling schema) + execute_tool.
# ----------------------------------------------------------------------


def _openai_chat_body(
    model: str, messages: list, *, stream: bool, with_tools: bool
) -> dict:
    body: dict = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": 0.7,
    }
    if with_tools:
        body["tools"] = OLLAMA_TOOLS
        body["tool_choice"] = "auto"
    return body


def _accumulate_tool_call_deltas(acc: dict, deltas: list) -> None:
    """Merge streamed OpenAI tool_call deltas (keyed by index) in place."""
    for tc in deltas or []:
        idx = tc.get("index", 0)
        slot = acc.setdefault(idx, {"id": None, "name": "", "args": ""})
        if tc.get("id"):
            slot["id"] = tc["id"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            slot["name"] = fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]


def _ordered_tool_calls(acc: dict) -> list[dict]:
    out: list[dict] = []
    for i, key in enumerate(sorted(acc)):
        slot = acc[key]
        out.append(
            {
                "id": slot["id"] or f"call_{i}",
                "name": slot["name"],
                "args": slot["args"] or "{}",
            }
        )
    return out


async def stream_openai_with_tools(
    url: str,
    headers: dict,
    model: str,
    messages: list,
    *,
    max_rounds: int = 4,
    timeout: float = 120.0,
):
    """Stream an OpenAI-compatible chat with WorldBase tools.

    Yields the same event shapes as ``stream_ollama_with_tools``:
    ``{"token"}`` / ``{"status"}`` / ``{"client_action"}`` / ``{"done"}``.
    """
    working = list(messages)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(max_rounds):
            yield {"status": "generating"}
            acc: dict = {}
            content_final = ""

            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=_openai_chat_body(model, working, stream=True, with_tools=True),
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip() or not line.startswith("data: "):
                        continue
                    payload_text = line[6:]
                    if payload_text.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_text)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        content_final += content
                        yield {"token": content}
                    if delta.get("tool_calls"):
                        _accumulate_tool_call_deltas(acc, delta["tool_calls"])

            if acc:
                ordered = _ordered_tool_calls(acc)
                working.append(
                    {
                        "role": "assistant",
                        "content": content_final or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {"name": c["name"], "arguments": c["args"]},
                            }
                            for c in ordered
                        ],
                    }
                )
                for c in ordered:
                    targs = parse_tool_arguments(c["args"])
                    yield {"status": "tool", "tool": c["name"]}
                    out = await execute_tool(c["name"], targs)
                    if out.get("client_action"):
                        yield {"client_action": out["client_action"]}
                    working.append(
                        {
                            "role": "tool",
                            "tool_call_id": c["id"],
                            "content": json.dumps(out.get("result", out), default=str)[
                                :8000
                            ],
                        }
                    )
                continue

            yield {"done": True}
            return

    yield {"token": "\nTool loop limit reached."}
    yield {"done": True}


async def run_openai_with_tools(
    url: str,
    headers: dict,
    model: str,
    messages: list,
    *,
    max_rounds: int = 4,
    timeout: float = 120.0,
) -> tuple[list[dict], list[dict]]:
    """Non-streaming OpenAI-compatible tool loop; returns (final_msgs, client_actions)."""
    client_actions: list[dict] = []
    working = list(messages)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(max_rounds):
            r = await client.post(
                url,
                headers=headers,
                json=_openai_chat_body(model, working, stream=False, with_tools=True),
            )
            r.raise_for_status()
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                return (
                    [{"role": "assistant", "content": msg.get("content") or ""}],
                    client_actions,
                )

            working.append(msg)
            for tc in tool_calls:
                fn = tc.get("function") or {}
                out = await execute_tool(
                    fn.get("name", ""), parse_tool_arguments(fn.get("arguments"))
                )
                if out.get("client_action"):
                    client_actions.append(out["client_action"])
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(out.get("result", out), default=str)[
                            :8000
                        ],
                    }
                )

    return (
        [{"role": "assistant", "content": "Tool loop limit reached."}],
        client_actions,
    )
