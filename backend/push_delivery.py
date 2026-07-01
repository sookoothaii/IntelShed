"""Proactive Push Delivery — SSE + WebSocket for watch-item notifications.

Server-Sent Events (SSE) endpoint for real-time push of:
- Watch-item triggers (entity matches, geo-fence breaches, keyword hits)
- Feed anomaly alerts
- Briefing completion notifications
- Fusion hotspot updates

SSE is the primary transport (simpler than WebSocket, works through proxies).
Falls back to polling if SSE is not supported.

WORLDBASE_PUSH=1 enables (default off). Uses in-memory event queue per client.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from structured_log import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/push", tags=["push"])

# In-memory event bus — per-client queues
_client_queues: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_watch_items: dict[str, dict[str, Any]] = {}
_last_event_id: int = 0
_event_history: deque[dict[str, Any]] = deque(maxlen=100)


def push_enabled() -> bool:
    return os.getenv("WORLDBASE_PUSH", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


import os  # noqa: E402


# ---------------------------------------------------------------------------
# Watch-item management
# ---------------------------------------------------------------------------


def register_watch_item(
    item_id: str,
    *,
    item_type: str,
    criteria: dict[str, Any],
    label: str = "",
) -> dict[str, Any]:
    """Register a watch item for proactive monitoring."""
    item = {
        "id": item_id,
        "type": item_type,
        "criteria": criteria,
        "label": label or item_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "triggered_count": 0,
        "last_triggered": None,
        "active": True,
    }
    _watch_items[item_id] = item
    return item


def remove_watch_item(item_id: str) -> bool:
    return _watch_items.pop(item_id, None) is not None


def get_watch_items() -> list[dict[str, Any]]:
    return list(_watch_items.values())


def trigger_event(
    event_type: str,
    data: dict[str, Any],
    *,
    watch_item_id: str | None = None,
) -> dict[str, Any]:
    """Push an event to all connected SSE clients.

    Can be called from any async context (feed ingest, anomaly detector, etc.).
    """
    global _last_event_id
    _last_event_id += 1

    event = {
        "id": _last_event_id,
        "type": event_type,
        "data": data,
        "watch_item_id": watch_item_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _event_history.append(event)

    # Update watch item stats
    if watch_item_id and watch_item_id in _watch_items:
        _watch_items[watch_item_id]["triggered_count"] += 1
        _watch_items[watch_item_id]["last_triggered"] = event["timestamp"]

    # Broadcast to all connected clients
    for client_id, queue in _client_queues.items():
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("push_queue_full", client_id=client_id)

    return event


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


@router.get("/events")
async def sse_events(
    request: Request,
    last_event_id: int = Query(0, ge=0, alias="lastEventId"),
):
    """Server-Sent Events stream for proactive push notifications.

    Client connects with EventSource:
      const es = new EventSource('/api/push/events?lastEventId=0');
      es.addEventListener('watch_trigger', (e) => { ... });
      es.addEventListener('anomaly', (e) => { ... });
      es.addEventListener('briefing', (e) => { ... });
    """
    if not push_enabled():
        return StreamingResponse(
            _disabled_stream(),
            media_type="text/event-stream",
        )

    client_id = f"client_{id(request)}_{int(time.time() * 1000)}"
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
    _client_queues[client_id] = queue

    # Replay missed events
    if last_event_id > 0:
        for evt in _event_history:
            if evt["id"] > last_event_id:
                await queue.put(evt)

    async def event_stream():
        try:
            # Send initial connection event
            yield _format_sse(
                "connected",
                {"client_id": client_id, "watch_items": len(_watch_items)},
            )

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield _format_sse(event["type"], event, event["id"])
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            _client_queues.pop(client_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


async def _disabled_stream():
    yield _format_sse(
        "error",
        {"reason": "Push delivery disabled — set WORLDBASE_PUSH=1"},
    )


def _format_sse(
    event_type: str, data: dict[str, Any], event_id: int | None = None
) -> str:
    """Format a Server-Sent Event string."""
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, default=str)}")
    lines.append("")
    return "\n".join(lines) + "\n\n"


# ---------------------------------------------------------------------------
# Watch-item CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/watch-items")
async def list_watch_items() -> dict[str, Any]:
    """List all registered watch items."""
    return {
        "enabled": push_enabled(),
        "items": get_watch_items(),
        "count": len(_watch_items),
    }


@router.post("/watch-items")
async def create_watch_item(request: Request) -> dict[str, Any]:
    """Register a new watch item for proactive monitoring.

    Body:
    {
        "id": "watch_gulf_tankers",
        "type": "geo_fence",
        "label": "Gulf of Thailand tankers",
        "criteria": {"bbox": [100, 7, 102, 9], "vessel_type": "tanker"}
    }
    """
    body = await request.json()
    item_id = body.get("id", f"watch_{int(time.time())}")
    item = register_watch_item(
        item_id,
        item_type=body.get("type", "generic"),
        criteria=body.get("criteria", {}),
        label=body.get("label", ""),
    )
    return {"created": True, "item": item}


@router.delete("/watch-items/{item_id}")
async def delete_watch_item(item_id: str) -> dict[str, Any]:
    """Remove a watch item."""
    removed = remove_watch_item(item_id)
    return {"deleted": removed, "id": item_id}


@router.post("/trigger")
async def manual_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger a push event (for testing or external integrations).

    Body:
    {
        "type": "watch_trigger",
        "data": {"message": "Test alert"},
        "watch_item_id": "watch_gulf_tankers"
    }
    """
    body = await request.json()
    event = trigger_event(
        body.get("type", "manual"),
        body.get("data", {}),
        watch_item_id=body.get("watch_item_id"),
    )
    return {"triggered": True, "event": event}


@router.get("/history")
async def event_history(limit: int = Query(50, ge=1, le=100)) -> dict[str, Any]:
    """Recent push events (last N)."""
    events = list(_event_history)[-limit:]
    return {
        "count": len(events),
        "events": events,
    }
