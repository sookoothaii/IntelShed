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
                    "query": {"type": "string", "description": "Natural language search query"},
                    "k": {"type": "integer", "description": "Max results (default 6)"},
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
                eid, "osint_ip", label=f"IP {ip}", lat=result["lat"], lon=result["lon"],
                source_feed="osint", external_id=ip, meta=result,
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
        return {"tool": name, "result": {"count": result.get("count"), "items": (result.get("items") or [])[:20]}}

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
        return {"tool": name, "result": {"ok": True, "lat": lat, "lon": lon}, "client_action": client_action}

    if name == "generate_briefing":
        import node_sync
        result = await node_sync.generate_briefing()
        return {"tool": name, "result": {"created_at": result.get("created_at"), "preview": (result.get("text") or "")[:500]}}

    if name == "search_memory":
        import rag_memory
        query = str(args.get("query", "")).strip()
        k = int(args.get("k") or 6)
        results = await rag_memory.search(query, k=k)
        return {"tool": name, "result": {"query": query, "count": len(results), "results": results}}

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


def _ollama_chat_body(model: str, messages: list, *, stream: bool, with_tools: bool) -> dict:
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
                working.append({
                    "role": "assistant",
                    "content": content_final,
                    "tool_calls": tool_calls_final,
                })
                for tc in tool_calls_final:
                    fn = tc.get("function") or {}
                    tname = fn.get("name", "")
                    targs = parse_tool_arguments(fn.get("arguments"))
                    yield {"status": "tool", "tool": tname}
                    out = await execute_tool(tname, targs)
                    if out.get("client_action"):
                        yield {"client_action": out["client_action"]}
                    working.append({
                        "role": "tool",
                        "content": json.dumps(out.get("result", out), default=str)[:8000],
                    })
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
                working.append({
                    "role": "tool",
                    "content": json.dumps(out.get("result", out), default=str)[:8000],
                })

    return ([{"role": "assistant", "content": "Tool loop limit reached."}], client_actions)
