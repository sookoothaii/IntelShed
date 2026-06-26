"""WebSocket Gateway for real-time globe updates (I10).

Bidirectional WebSocket at GET /api/ws — pushes AIS deltas, feed events,
briefing notifications, and agent bus actions to connected clients.
Clients send viewport bbox + layer subscriptions for filtered pushes.

Disabled by default (WORLDBASE_WEBSOCKET=0). Graceful degradation to SSE.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from auth.security import API_KEY, lan_exposed
from config import get_config

router = APIRouter(tags=["websocket"])

# Connection management
_connections: set["WSConnection"] = set()
_heartbeat_interval = 30.0  # seconds


def ws_enabled() -> bool:
    return get_config().websocket_enabled


class WSConnection:
    """Wraps a WebSocket with subscription state."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.bbox: tuple[float, float, float, float] | None = None  # w, s, e, n
        self.layers: set[str] = set()
        self.last_heartbeat = time.time()
        self.connected_at = datetime.now(timezone.utc)

    def in_viewport(self, lat: float, lon: float) -> bool:
        if self.bbox is None:
            return True  # no filter → all events
        w, s, e, n = self.bbox
        return s <= lat <= n and w <= lon <= e

    def subscribed(self, layer: str) -> bool:
        if not self.layers:
            return True  # no filter → all layers
        return layer in self.layers


def _verify_ws_auth(ws: WebSocket) -> bool:
    """Check auth for WebSocket connection."""
    if not API_KEY:
        return True
    key = ws.query_params.get("api_key") or ws.headers.get("x-api-key", "")
    if key and key == API_KEY:
        return True
    # Loopback without key when not LAN-exposed
    if not lan_exposed():
        client = ws.client.host if ws.client else ""
        if client in ("127.0.0.1", "::1", "localhost"):
            return True
    return False


async def broadcast_event(
    event_type: str,
    data: dict[str, Any],
    *,
    lat: float | None = None,
    lon: float | None = None,
    layer: str | None = None,
) -> int:
    """Broadcast an event to all matching WebSocket clients.

    Returns number of clients that received the event.
    """
    if not _connections:
        return 0

    msg = json.dumps(
        {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        },
        ensure_ascii=False,
    )

    delivered = 0
    dead: list[WSConnection] = []

    for conn in list(_connections):
        # Filter by viewport
        if lat is not None and lon is not None and not conn.in_viewport(lat, lon):
            continue
        # Filter by layer subscription
        if layer and not conn.subscribed(layer):
            continue
        try:
            await conn.ws.send_text(msg)
            delivered += 1
        except Exception:
            dead.append(conn)

    for conn in dead:
        _connections.discard(conn)

    return delivered


async def broadcast_ais_delta(positions: list[dict[str, Any]]) -> int:
    """Broadcast AIS position deltas to connected clients."""
    if not positions:
        return 0
    # Send each position, filtered by viewport
    total = 0
    for pos in positions:
        lat = pos.get("lat")
        lon = pos.get("lon")
        if lat is None or lon is None:
            continue
        total += await broadcast_event(
            "ais_delta", pos, lat=lat, lon=lon, layer="maritime"
        )
    return total


async def broadcast_feed_event(
    event_type: str,
    data: dict[str, Any],
    *,
    lat: float | None = None,
    lon: float | None = None,
    layer: str | None = None,
) -> int:
    """Broadcast a feed event (quake, GDACS, EONET, etc.) to clients."""
    return await broadcast_event(event_type, data, lat=lat, lon=lon, layer=layer)


async def broadcast_briefing_ready(briefing_id: str, quality: float) -> int:
    """Notify clients that a new briefing is available."""
    return await broadcast_event(
        "briefing_ready",
        {"briefing_id": briefing_id, "quality": quality},
    )


async def broadcast_agent_action(action: dict[str, Any]) -> int:
    """Relay agent bus actions via WebSocket."""
    return await broadcast_event("agent_action", action)


@router.get("/api/ws/status")
async def ws_status():
    """WebSocket gateway status."""
    return {
        "enabled": ws_enabled(),
        "connections": len(_connections),
        "heartbeat_interval": _heartbeat_interval,
    }


@router.websocket("/api/ws")
async def websocket_endpoint(ws: WebSocket):
    """Bidirectional WebSocket for real-time globe updates.

    Client → Server messages:
      {"cmd": "subscribe", "layers": ["maritime", "quakes"]}
      {"cmd": "viewport", "bbox": [w, s, e, n]}
      {"cmd": "ping"}

    Server → Client messages:
      {"type": "connected", "ts": "..."}
      {"type": "ais_delta", "data": {...}}
      {"type": "feed_event", "data": {...}}
      {"type": "briefing_ready", "data": {...}}
      {"type": "agent_action", "data": {...}}
      {"type": "pong", "ts": "..."}
    """
    if not ws_enabled():
        await ws.close(code=1008, reason="WebSocket disabled (WORLDBASE_WEBSOCKET=0)")
        return

    if not _verify_ws_auth(ws):
        await ws.close(code=1008, reason="Authentication required")
        return

    await ws.accept()
    conn = WSConnection(ws)
    _connections.add(conn)

    # Send connected confirmation
    try:
        await ws.send_text(
            json.dumps(
                {
                    "type": "connected",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "message": "WebSocket connected — send subscribe/viewport commands",
                }
            )
        )
    except Exception:
        _connections.discard(conn)
        return

    # Start heartbeat task
    async def heartbeat():
        while True:
            await asyncio.sleep(_heartbeat_interval)
            try:
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                )
            except Exception:
                break

    hb_task = asyncio.create_task(heartbeat())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            cmd = msg.get("cmd", "")

            if cmd == "subscribe":
                layers = msg.get("layers", [])
                conn.layers = set(layers) if isinstance(layers, list) else set()
                await ws.send_text(
                    json.dumps(
                        {
                            "type": "subscribed",
                            "layers": sorted(conn.layers),
                        }
                    )
                )

            elif cmd == "viewport":
                bbox = msg.get("bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    conn.bbox = tuple(float(v) for v in bbox)
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "viewport_set",
                                "bbox": list(conn.bbox),
                            }
                        )
                    )

            elif cmd == "ping":
                await ws.send_text(
                    json.dumps(
                        {"type": "pong", "ts": datetime.now(timezone.utc).isoformat()}
                    )
                )

            elif cmd == "unsubscribe":
                conn.layers.clear()
                conn.bbox = None
                await ws.send_text(json.dumps({"type": "unsubscribed"}))

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hb_task.cancel()
        _connections.discard(conn)
