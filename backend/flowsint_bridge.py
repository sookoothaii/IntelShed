"""Flowsint stack bridge — health probe + enricher proxy.

Provides per-tool OSINT enrichment via the Flowsint API. The intelshed backend
acts as a proxy: logs into Flowsint, creates an investigation + sketch, adds a
node, launches the requested enricher, polls for completion, and returns the
resulting graph.
"""

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api", tags=["flowsint"])

_FLOWSINT_UI = os.getenv("FLOWSINT_URL", "http://127.0.0.1:5173").rstrip("/")
_FLOWSINT_API = os.getenv("FLOWSINT_API_URL", "http://127.0.0.1:5001").rstrip("/")
_FLOWSINT_EMAIL = os.getenv("FLOWSINT_EMAIL", "")
_FLOWSINT_PASSWORD = os.getenv("FLOWSINT_PASSWORD", "")

# In-memory token cache (avoids re-login on every call)
_token_cache: dict[str, Any] = {"token": None, "expires": 0}


async def _get_flowsint_token(client: httpx.AsyncClient) -> str:
    """Login to Flowsint and cache the bearer token."""
    if _token_cache["token"] and time.time() < _token_cache["expires"]:
        return _token_cache["token"]
    if not _FLOWSINT_EMAIL or not _FLOWSINT_PASSWORD:
        raise HTTPException(
            500, "FLOWSINT_EMAIL/FLOWSINT_PASSWORD not set in backend .env"
        )
    r = await client.post(
        f"{_FLOWSINT_API}/api/auth/token",
        data={"username": _FLOWSINT_EMAIL, "password": _FLOWSINT_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    if r.status_code != 200:
        raise HTTPException(
            502, f"Flowsint auth failed: {r.status_code} {r.text[:200]}"
        )
    token = r.json().get("access_token")
    if not token:
        raise HTTPException(502, "Flowsint auth: no access_token in response")
    _token_cache["token"] = token
    _token_cache["expires"] = time.time() + 3600  # 1h cache
    return token


async def _flowsint_headers(client: httpx.AsyncClient) -> dict[str, str]:
    token = await _get_flowsint_token(client)
    return {"Authorization": f"Bearer {token}"}


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
        nodes.append(
            {
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
            }
        )
    return {
        "title": title,
        "node_count": len(nodes),
        "flowsint_hint": "OSINT tab → paste as pin import JSON or enrich in Flowsint UI",
        "nodes": nodes,
    }


# ---------------------------------------------------------------------------
# Enricher proxy — per-tool OSINT enrichment via Flowsint
# ---------------------------------------------------------------------------


class EnrichRequest(BaseModel):
    """Run a single Flowsint enricher on a value."""

    enricher_name: str
    entity_type: (
        str  # Ip, Domain, Email, Username, Website, Phone, Organization, CryptoWallet
    )
    value: str  # the IP address, domain, email, username, URL, phone, org name, wallet address
    investigation_name: str | None = None
    timeout_seconds: int = 60


# Map intelshed entity types to Flowsint node types + label keys
_TYPE_MAP: dict[str, dict[str, str]] = {
    "ip": {"nodeType": "Ip", "nodeLabel": "address", "icon": "ip"},
    "domain": {"nodeType": "Domain", "nodeLabel": "domain", "icon": "domain"},
    "email": {"nodeType": "Email", "nodeLabel": "email", "icon": "email"},
    "username": {"nodeType": "Username", "nodeLabel": "value", "icon": "username"},
    "website": {"nodeType": "Website", "nodeLabel": "url", "icon": "website"},
    "phone": {"nodeType": "Phone", "nodeLabel": "number", "icon": "phone"},
    "organization": {
        "nodeType": "Organization",
        "nodeLabel": "name",
        "icon": "organization",
    },
    "cryptowallet": {
        "nodeType": "CryptoWallet",
        "nodeLabel": "address",
        "icon": "cryptowallet",
    },
}


@router.get("/flowsint/enrichers")
async def list_enrichers(
    _auth: str | None = Depends(verify_lan_auth),
):
    """List all available Flowsint enrichers with their input types."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = await _flowsint_headers(client)
        r = await client.get(f"{_FLOWSINT_API}/api/enrichers", headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"Flowsint API error: {r.status_code}")
        enrichers = r.json()
        # Compact summary
        return {
            "count": len(enrichers),
            "enrichers": [
                {
                    "name": e.get("name"),
                    "category": e.get("category"),
                    "input_type": e.get("inputs", {}).get("type"),
                    "output_type": e.get("outputs", {}).get("type"),
                    "description": (e.get("description") or "")[:120],
                    "requires_params": bool(e.get("params_schema")),
                }
                for e in enrichers
            ],
        }


@router.post("/flowsint/enrich")
async def run_enricher(
    req: EnrichRequest,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Run a Flowsint enricher on a single value.

    Full workflow (automated):
    1. Login to Flowsint
    2. Create investigation (or reuse existing)
    3. Create sketch in investigation
    4. Add node with the given value
    5. Launch enricher on that node
    6. Poll scan status until complete
    7. Return resulting graph (nodes + edges)
    """
    type_info = _TYPE_MAP.get(req.entity_type.lower())
    if not type_info:
        raise HTTPException(
            400,
            f"Unsupported entity_type: {req.entity_type}. "
            f"Supported: {list(_TYPE_MAP.keys())}",
        )

    async with httpx.AsyncClient(timeout=120.0) as client:
        headers = await _flowsint_headers(client)

        # 1. Create investigation
        inv_name = (
            req.investigation_name or f"intelshed-{req.entity_type}-{req.value[:30]}"
        )
        r = await client.post(
            f"{_FLOWSINT_API}/api/investigations/create",
            json={
                "name": inv_name,
                "description": f"Auto-created by intelshed for {req.enricher_name}",
            },
            headers=headers,
        )
        if r.status_code not in (200, 201):
            raise HTTPException(
                502, f"Create investigation failed: {r.status_code} {r.text[:200]}"
            )
        inv = r.json()
        inv_id = inv["id"]

        # 2. Create sketch in investigation
        r = await client.post(
            f"{_FLOWSINT_API}/api/sketches/create",
            json={
                "title": f"enrich-{req.enricher_name}",
                "description": f"Auto sketch for {req.value}",
                "investigation_id": inv_id,
            },
            headers=headers,
        )
        if r.status_code not in (200, 201):
            raise HTTPException(
                502, f"Create sketch failed: {r.status_code} {r.text[:200]}"
            )
        sketch = r.json()
        sketch_id = sketch["id"]

        # 3. Add node with the value
        node_payload = {
            "id": None,
            "nodeLabel": req.value,
            "nodeType": type_info["nodeType"],
            "nodeIcon": type_info["icon"],
            "nodeMetadata": {},
            "nodeProperties": {type_info["nodeLabel"]: req.value},
            "x": 100.0,
            "y": 100.0,
        }
        r = await client.post(
            f"{_FLOWSINT_API}/api/sketches/{sketch_id}/nodes/add",
            json=node_payload,
            headers=headers,
        )
        if r.status_code not in (200, 201):
            raise HTTPException(502, f"Add node failed: {r.status_code} {r.text[:200]}")
        node_resp = r.json()
        node = node_resp.get("node") or node_resp
        node_id = node.get("id")
        if not node_id:
            raise HTTPException(
                502, f"Add node: no node id returned. Response: {str(node_resp)[:200]}"
            )

        # 4. Launch enricher
        r = await client.post(
            f"{_FLOWSINT_API}/api/enrichers/{req.enricher_name}/launch",
            json={"node_ids": [node_id], "sketch_id": sketch_id},
            headers=headers,
        )
        if r.status_code != 200:
            raise HTTPException(
                502, f"Launch enricher failed: {r.status_code} {r.text[:200]}"
            )
        task = r.json()
        scan_id = task.get("id")
        if not scan_id:
            raise HTTPException(502, "Launch enricher: no task id returned")

        # 5. Poll scan status
        deadline = time.time() + req.timeout_seconds
        scan_status = "pending"
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            r = await client.get(
                f"{_FLOWSINT_API}/api/scans/{scan_id}",
                headers=headers,
            )
            if r.status_code == 200:
                scan_data = r.json()
                scan_status = scan_data.get("status", "unknown")
                if scan_status in ("success", "completed", "done", "failed", "error"):
                    break
            # Also check via sketch logs endpoint
            r2 = await client.get(
                f"{_FLOWSINT_API}/api/events/sketch/{sketch_id}/logs",
                headers=headers,
            )
            if r2.status_code == 200:
                logs = r2.json()
                if isinstance(logs, list) and logs:
                    last = logs[-1]
                    if isinstance(last, dict) and last.get("status") in (
                        "success",
                        "error",
                        "failed",
                    ):
                        scan_status = last["status"]
                        break

        # 6. Get resulting graph
        r = await client.get(
            f"{_FLOWSINT_API}/api/sketches/{sketch_id}/graph",
            headers=headers,
        )
        graph = (
            r.json()
            if r.status_code == 200
            else {"error": f"graph fetch failed: {r.status_code}"}
        )

        return {
            "enricher": req.enricher_name,
            "entity_type": req.entity_type,
            "value": req.value,
            "investigation_id": inv_id,
            "sketch_id": sketch_id,
            "node_id": node_id,
            "scan_id": scan_id,
            "scan_status": scan_status,
            "flowsint_ui_url": f"{_FLOWSINT_UI}/sketch/{sketch_id}",
            "graph": graph,
        }


@router.get("/flowsint/investigations")
async def list_investigations(
    _auth: str | None = Depends(verify_lan_auth),
):
    """List Flowsint investigations for the configured user."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = await _flowsint_headers(client)
        r = await client.get(f"{_FLOWSINT_API}/api/investigations", headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, f"Flowsint API error: {r.status_code}")
        return r.json()


@router.get("/flowsint/sketch/{sketch_id}/graph")
async def get_sketch_graph(
    sketch_id: str,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Get the graph (nodes + edges) for a Flowsint sketch."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        headers = await _flowsint_headers(client)
        r = await client.get(
            f"{_FLOWSINT_API}/api/sketches/{sketch_id}/graph",
            headers=headers,
        )
        if r.status_code != 200:
            raise HTTPException(502, f"Flowsint API error: {r.status_code}")
        return r.json()
