"""In-memory Agent Bus — API/MCP publish → SSE stream → open HUD session.

Single-process operator stack (no Redis). Disabled by default (WORLDBASE_AGENT_BUS=0).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth.security import API_KEY, verify_api_key, verify_lan_auth

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Globe layer keys (must match frontend GlobeLayers in Globe.tsx).
GLOBE_LAYER_KEYS: frozenset[str] = frozenset(
    {
        "aircraft",
        "satellites",
        "orbits",
        "quakes",
        "events",
        "nodes",
        "military",
        "spaceweather",
        "geopolitics",
        "wildfires",
        "lightning",
        "transit",
        "trafficCams",
        "maritime",
        "gdacs",
        "hazards",
        "outages",
        "volcanoes",
        "airquality",
        "weather",
        "pegel",
        "energy",
        "osint",
        "intelFt",
    }
)

_subscribers: set[asyncio.Queue[str]] = set()
_last_camera: dict[str, Any] | None = None


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def agent_bus_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_AGENT_BUS", "0"))


def _require_enabled() -> None:
    if not agent_bus_enabled():
        raise HTTPException(
            status_code=503,
            detail="Agent Bus disabled (set WORLDBASE_AGENT_BUS=1 and restart backend)",
        )


class CameraState(BaseModel):
    lon: float
    lat: float
    height: float
    pitch: float | None = None


class AgentPublishBody(BaseModel):
    action: str
    lat: float | None = None
    lon: float | None = None
    height: float | None = None
    title: str | None = None
    lines: list[str] = Field(default_factory=list)
    layer: str | None = None
    enabled: bool | None = None


def get_camera_state() -> dict[str, Any]:
    return dict(_last_camera) if _last_camera else {}


def subscriber_count() -> int:
    return len(_subscribers)


def _validate_publish(body: AgentPublishBody) -> None:
    action = (body.action or "").strip().lower()
    if action == "fly_to":
        if body.lat is None or body.lon is None:
            raise HTTPException(status_code=422, detail="fly_to requires lat and lon")
        return
    if action == "toggle_layer":
        layer = (body.layer or "").strip()
        if layer not in GLOBE_LAYER_KEYS:
            allowed = ", ".join(sorted(GLOBE_LAYER_KEYS))
            raise HTTPException(
                status_code=422, detail=f"Unknown layer {layer!r}. Allowed: {allowed}"
            )
        return
    if action == "agent_phase":
        # Generic phase update from the orchestrator.  Requires a title;
        # lines are optional human-readable context.
        if not (body.title or "").strip():
            raise HTTPException(status_code=422, detail="agent_phase requires a title")
        return
    raise HTTPException(
        status_code=422,
        detail=f"Unknown action {body.action!r}. Use fly_to, toggle_layer, or agent_phase.",
    )


async def publish_action(body: AgentPublishBody) -> dict[str, Any]:
    """Broadcast an agent action to all HUD stream subscribers."""
    _require_enabled()
    _validate_publish(body)
    msg = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        **body.model_dump(exclude_none=True),
    }
    delivered = await _broadcast(msg)
    return {"ok": True, "delivered": delivered, "message": msg}


async def publish_fly_to(
    *,
    lat: float,
    lon: float,
    height: float | None = None,
    title: str | None = None,
    lines: list[str] | None = None,
) -> dict[str, Any]:
    return await publish_action(
        AgentPublishBody(
            action="fly_to",
            lat=lat,
            lon=lon,
            height=height,
            title=title or "Agent focus",
            lines=lines or [],
        )
    )


async def publish_toggle_layer(
    *, layer: str, enabled: bool | None = None
) -> dict[str, Any]:
    return await publish_action(
        AgentPublishBody(
            action="toggle_layer",
            layer=layer.strip(),
            enabled=enabled,
        )
    )


async def _broadcast(message: dict[str, Any]) -> int:
    payload = json.dumps(message, ensure_ascii=False)
    dead: list[asyncio.Queue[str]] = []
    delivered = 0
    for q in list(_subscribers):
        try:
            q.put_nowait(payload)
            delivered += 1
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _subscribers.discard(q)
    return delivered


def _verify_stream_auth(request: Request, token: str | None = None) -> None:
    if not API_KEY:
        return
    if request.headers.get("x-api-key") == API_KEY:
        return
    if token == API_KEY:
        return
    raise HTTPException(
        status_code=401, detail="Invalid or missing API key for Agent Bus stream"
    )


@router.get("/status")
async def agent_status():
    return {
        "enabled": agent_bus_enabled(),
        "subscribers": len(_subscribers),
        "camera": get_camera_state() or None,
        "layers": sorted(GLOBE_LAYER_KEYS),
    }


@router.post("/publish")
async def agent_publish(
    body: AgentPublishBody,
    _api_key: str | None = Depends(verify_api_key),
    _lan: str | None = Depends(verify_lan_auth),
):
    return await publish_action(body)


@router.post("/camera")
async def agent_camera(
    body: CameraState,
    _lan: str | None = Depends(verify_lan_auth),
):
    _require_enabled()
    global _last_camera
    _last_camera = {
        **body.model_dump(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"ok": True}


@router.get("/camera")
async def agent_get_camera():
    _require_enabled()
    cam = get_camera_state()
    if not cam:
        return {"camera": None}
    return {"camera": cam}


@router.get("/stream")
async def agent_stream(request: Request, token: str | None = None):
    _require_enabled()
    _verify_stream_auth(request, token=token)

    async def event_generator():
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        _subscribers.add(q)
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
