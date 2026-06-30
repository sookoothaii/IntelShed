"""WorldBase AI tool definitions and execution (Ollama function calling)."""

from __future__ import annotations

import json
from typing import Any

import httpx

import entity_store
import feeds_extra
import osint_tools

_UA = {"User-Agent": "WorldBase/1.0"}

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_DDG_URL = "https://api.duckduckgo.com/"


async def _verify_claim(
    claim: str,
    suggested_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Verify a claim via RAG memory + DuckDuckGo (fail-soft).

    Returns relevant snippets with source attribution and a confidence
    assessment.  Network errors return ``confidence: "unknown"`` with empty
    lists — never raises.
    """
    suggested_sources = suggested_sources or []
    snippets: list[dict[str, Any]] = []
    confidence = "unknown"

    if not claim:
        return {
            "tool": "verify_claim",
            "result": {
                "claim": "",
                "confidence": "unknown",
                "snippets": [],
                "error": "empty claim",
            },
        }

    # Phase 1: RAG memory search
    try:
        import rag_memory

        results = await rag_memory.search(claim, k=4)
        for r in results:
            text = str(r.get("text") or r.get("content") or "")[:300]
            source = str(r.get("source") or r.get("feed") or "rag_memory")
            snippets.append(
                {
                    "text": text,
                    "source": source,
                    "url": str(r.get("url") or r.get("link") or ""),
                    "backend": "rag",
                }
            )
    except Exception:
        pass

    # Phase 2: DuckDuckGo instant answer API (fail-soft)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(
                _DDG_URL,
                params={
                    "q": claim,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers=_UA,
            )
            r.raise_for_status()
            data = r.json()
            abstract = str(data.get("Abstract") or "").strip()
            if abstract:
                snippets.append(
                    {
                        "text": abstract[:300],
                        "source": str(data.get("AbstractSource") or "DuckDuckGo"),
                        "url": str(data.get("AbstractURL") or ""),
                        "backend": "duckduckgo",
                    }
                )
            for topic in (data.get("RelatedTopics") or [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    snippets.append(
                        {
                            "text": str(topic["Text"])[:300],
                            "source": "DuckDuckGo",
                            "url": str(topic.get("FirstURL") or ""),
                            "backend": "duckduckgo",
                        }
                    )
    except Exception:
        pass

    # Confidence assessment (rule-based, 0 VRAM)
    if snippets:
        source_match = any(
            any(s.lower() in snip.get("source", "").lower() for s in suggested_sources)
            for snip in snippets
        )
        if source_match and len(snippets) >= 2:
            confidence = "HIGH"
        elif len(snippets) >= 2:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

    return {
        "tool": "verify_claim",
        "result": {
            "claim": claim[:300],
            "confidence": confidence,
            "snippets": snippets[:6],
            "suggested_sources": suggested_sources,
        },
    }


async def _geocode_place(query: str) -> dict[str, Any] | None:
    """Resolve a place name to lat/lon via OpenStreetMap Nominatim (fail-soft)."""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(
                _NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers=_UA,
            )
            r.raise_for_status()
            results = r.json()
            if not results:
                return None
            hit = results[0]
            return {
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
                "display_name": hit.get("display_name", query),
                "boundingbox": hit.get("boundingbox"),
                "place_rank": hit.get("place_rank"),
                "osm_type": hit.get("osm_type"),
                "osm_id": hit.get("osm_id"),
            }
    except Exception:
        return None


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
            "description": "Navigate the operator's 3D globe to a specific location. Use this when the user asks to show, focus, zoom to, or display any place (e.g. 'show me Berlin', 'focus on Tokyo', 'go to 13.75,100.5'). IMPORTANT: pass 'place' (a city/region/country name) whenever the user names a location. The server geocodes via OpenStreetMap for exact coordinates and ignores any lat/lon you might guess. Only provide lat/lon directly when the user explicitly gives numeric coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "place": {
                        "type": "string",
                        "description": "Place name to geocode (e.g. 'Berlin', 'Mount Everest', 'Phuket, Thailand'). Preferred over guessing lat/lon.",
                    },
                    "lat": {
                        "type": "number",
                        "description": "Latitude — provide only if the user gave exact coordinates",
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude — provide only if the user gave exact coordinates",
                    },
                    "title": {
                        "type": "string",
                        "description": "Display name for the location marker (defaults to place name)",
                    },
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional info lines to show in the marker popup",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocode_place",
            "description": "Resolve a place name to exact lat/lon coordinates via OpenStreetMap Nominatim. Returns coordinates, display name, bounding box, and place rank. Use this when you need coordinates for any purpose other than focus_globe (which geocodes internally).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Place name to geocode (e.g. 'Berlin, Germany', 'K2 mountain', 'Strait of Malacca')",
                    },
                },
                "required": ["query"],
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
    {
        "type": "function",
        "function": {
            "name": "verify_claim",
            "description": "Verify a claim by searching RAG memory and optionally DuckDuckGo. Returns relevant snippets with source attribution and a confidence assessment. Use this to cross-check claims during analysis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "The claim text to verify",
                    },
                    "suggested_sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of source names to look for (e.g. ['GDELT', 'USGS'])",
                    },
                },
                "required": ["claim"],
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
        place = str(args.get("place", "")).strip()
        title = str(args.get("title") or place or "Focus")
        lines = args.get("lines") or []
        lat_raw = args.get("lat")
        lon_raw = args.get("lon")

        if place:
            # Always geocode the place name; ignore any LLM-guessed lat/lon.
            # This prevents DeepSeek and similar models from hallucinating coordinates.
            geo = await _geocode_place(place)
            if geo is None:
                return {
                    "tool": name,
                    "result": {"ok": False, "error": f"Geocoding failed for '{place}'"},
                }
            lat = geo["lat"]
            lon = geo["lon"]
            if not args.get("title"):
                title = geo.get("display_name", place)
            lines = lines or [
                f"Geocoded via OpenStreetMap: {geo.get('display_name', place)}"
            ]
        elif lat_raw is not None and lon_raw is not None:
            lat = float(lat_raw)
            lon = float(lon_raw)
        else:
            return {
                "tool": name,
                "result": {
                    "ok": False,
                    "error": "Provide either 'place' or both 'lat' and 'lon'",
                },
            }

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
            "result": {"ok": True, "lat": lat, "lon": lon, "place": place or None},
            "client_action": client_action,
        }

    if name == "geocode_place":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"tool": name, "result": {"ok": False, "error": "query is required"}}
        geo = await _geocode_place(query)
        if geo is None:
            return {
                "tool": name,
                "result": {"ok": False, "error": f"No results for '{query}'"},
            }
        return {"tool": name, "result": {"ok": True, **geo}}

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

    if name == "verify_claim":
        return await _verify_claim(
            str(args.get("claim", "")).strip(),
            args.get("suggested_sources") or [],
        )

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
