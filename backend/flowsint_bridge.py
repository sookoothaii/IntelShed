"""Flowsint stack health probe (local Docker install)."""

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api", tags=["flowsint"])

_FLOWSINT_UI = os.getenv("FLOWSINT_URL", "http://127.0.0.1:5173").rstrip("/")
_FLOWSINT_API = os.getenv("FLOWSINT_API_URL", "http://127.0.0.1:5001").rstrip("/")


@router.get("/flowsint/health")
async def flowsint_health():
    """Check whether Flowsint UI and API respond (after scripts/start-flowsint.ps1)."""
    out = {
        "ok": False,
        "frontend_url": _FLOWSINT_UI,
        "api_url": _FLOWSINT_API,
        "frontend": False,
        "api": False,
        "updated": datetime.now(timezone.utc).isoformat(),
        "hint": "Run scripts/setup-flowsint.ps1 then scripts/start-flowsint.ps1 (Docker required)",
    }
    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        try:
            r = await client.get(f"{_FLOWSINT_UI}/")
            out["frontend"] = r.status_code < 500
        except Exception as e:
            out["frontend_error"] = str(e)[:200]
        try:
            r = await client.get(f"{_FLOWSINT_API}/health")
            out["api"] = r.status_code == 200
        except Exception as e:
            out["api_error"] = str(e)[:200]
    out["ok"] = out["frontend"] and out["api"]
    return out


@router.post("/flowsint/export-investigation")
async def export_investigation(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """
    Format globe/entity pins for Flowsint paste import (JSON nodes).
    Body: { "title": "...", "pins": [{ "label", "lat", "lon", "tool?", "query?" }] }
    """
    title = (body.get("title") or "WorldBase investigation").strip()
    pins = body.get("pins") or []
    nodes = []
    for i, p in enumerate(pins):
        if p.get("lat") is None or p.get("lon") is None:
            continue
        nodes.append({
            "id": p.get("id") or f"wb-{i}",
            "type": p.get("type") or "location",
            "label": p.get("label") or p.get("title") or f"Pin {i}",
            "lat": p["lat"],
            "lon": p["lon"],
            "meta": {
                "tool": p.get("tool"),
                "query": p.get("query"),
                "source": "worldbase",
            },
        })
    return {
        "title": title,
        "node_count": len(nodes),
        "flowsint_hint": "OSINT tab → paste as pin import JSON or enrich in Flowsint UI",
        "nodes": nodes,
    }
