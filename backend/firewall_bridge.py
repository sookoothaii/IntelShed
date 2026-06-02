"""Optional LLM-Security-Firewall bridge.

Connects to the external HAK_GAL firewall service (default port 8001).
If the firewall is not reachable, falls through silently (fail-open for UX).

Usage in /api/chat: check each incoming user message with firewall_scan().
If blocked, return a warning instead of proxying to Ollama.
"""

import os

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/firewall", tags=["firewall"])

FIREWALL_HOST = os.getenv("FIREWALL_HOST", "localhost:8001")
FIREWALL_URL = f"http://{FIREWALL_HOST}/api/v1/detect"
TIMEOUT = 5.0  # fast — don't slow down chat


def _extract_user_text(messages: list[dict]) -> str:
    """Concatenate the last few user messages for scanning."""
    texts = []
    for m in messages:
        if m.get("role") == "user" and m.get("content"):
            texts.append(str(m["content"]))
    # Only scan the last message to keep latency low
    return texts[-1] if texts else ""


async def firewall_scan(text: str) -> dict:
    """Scan text through the external firewall. Returns empty dict on any failure."""
    if not text.strip():
        return {}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                FIREWALL_URL,
                json={"text": text, "session_id": "worldbase"},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code != 200:
                return {"_error": f"firewall returned {r.status_code}", "_available": False}
            return {**r.json(), "_available": True}
    except Exception:
        return {"_available": False}


@router.get("/status")
async def firewall_status():
    """Return whether the external firewall is reachable."""
    result = await firewall_scan("hello")
    available = result.get("_available", False)
    return {
        "enabled": bool(os.getenv("FIREWALL_HOST")),
        "reachable": available,
        "host": FIREWALL_HOST,
        "url": FIREWALL_URL,
    }
