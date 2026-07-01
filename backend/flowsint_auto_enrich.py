"""Automatic Flowsint enrichment of briefing IOCs.

Runs after each briefing generation. Extracts IOCs (IPs, domains, emails)
from the latest briefing text, runs the appropriate Flowsint enricher on
each, and ingests the results as FtM cyber entities + intel edges + globe pins.

Feature flag: WORLDBASE_FLOWSINT_AUTO_ENRICH=1 (default off, opt-in).

Env:
  WORLDBASE_FLOWSINT_AUTO_ENRICH=1          enable auto-enrichment
  WORLDBASE_FLOWSINT_AUTO_MAX_IOCS=20       max IOCs per run (default 20)
  WORLDBASE_FLOWSINT_AUTO_TIMEOUT=30        per-enricher timeout in seconds
  WORLDBASE_FLOWSINT_AUTO_ENRICHERS_IP=ip_to_infos
  WORLDBASE_FLOWSINT_AUTO_ENRICHERS_DOMAIN=domain_to_whois
  WORLDBASE_FLOWSINT_AUTO_ENRICHERS_EMAIL=email_to_gravatar
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

import httpx

from structured_log import get_logger

log = get_logger(__name__)

_DB_PATH = os.getenv("WORLDBASE_DB_PATH", "worldbase.db")

_FLOWSINT_API = os.getenv("FLOWSINT_API_URL", "http://127.0.0.1:5001").rstrip("/")
_FLOWSINT_EMAIL = os.getenv("FLOWSINT_EMAIL", "")
_FLOWSINT_PASSWORD = os.getenv("FLOWSINT_PASSWORD", "")

_MAX_IOCS = int(os.getenv("WORLDBASE_FLOWSINT_AUTO_MAX_IOCS", "20"))
_TIMEOUT = int(os.getenv("WORLDBASE_FLOWSINT_AUTO_TIMEOUT", "30"))

# Which enricher to run per IOC type
_ENRICHER_MAP: dict[str, str] = {
    "ipv4": os.getenv("WORLDBASE_FLOWSINT_AUTO_ENRICHERS_IP", "ip_to_infos"),
    "domain": os.getenv("WORLDBASE_FLOWSINT_AUTO_ENRICHERS_DOMAIN", "domain_to_whois"),
    "email": os.getenv("WORLDBASE_FLOWSINT_AUTO_ENRICHERS_EMAIL", "email_to_gravatar"),
}

# Flowsint node type + label key per IOC type
_TYPE_MAP: dict[str, dict[str, str]] = {
    "ipv4": {"nodeType": "Ip", "nodeLabel": "address", "icon": "ip"},
    "domain": {"nodeType": "Domain", "nodeLabel": "domain", "icon": "domain"},
    "email": {"nodeType": "Email", "nodeLabel": "email", "icon": "email"},
}

# In-memory token cache
_token_cache: dict[str, Any] = {"token": None, "expires": 0}


def _enabled() -> bool:
    return os.getenv("WORLDBASE_FLOWSINT_AUTO_ENRICH", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Briefing text retrieval
# ---------------------------------------------------------------------------


def _latest_briefing_text() -> str | None:
    """Get the text of the most recent briefing from SQLite."""
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT text FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return row["text"] if row else None
    except Exception as e:
        log.warning("auto_enrich_briefing_fetch_error", error=str(e)[:200])
        return None


# ---------------------------------------------------------------------------
# IOC extraction (lightweight regex — same patterns as intel_ingest)
# ---------------------------------------------------------------------------

_IOC_PATTERNS: dict[str, re.Pattern[str]] = {
    "ipv4": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
    ),
    "domain": re.compile(
        r"\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
        r"(?:[a-zA-Z]{2,})\b"
    ),
    "email": re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
}

_IOC_EXCLUDE: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "localhost",
        "cesium.com",
        "unpkg.com",
        "fonts.googleapis.com",
        "fonts.gstatic.com",
    }
)


def _extract_iocs(text: str) -> dict[str, list[str]]:
    """Extract IPs, domains, and emails from text."""
    results: dict[str, list[str]] = {}
    for ioc_type, pattern in _IOC_PATTERNS.items():
        seen: set[str] = set()
        matches: list[str] = []
        for m in pattern.findall(text):
            val = m if isinstance(m, str) else m[0]
            val = val.strip().rstrip(".,;)")
            if not val or val.lower() in _IOC_EXCLUDE:
                continue
            if val.lower() in seen:
                continue
            seen.add(val.lower())
            matches.append(val)
        if matches:
            results[ioc_type] = matches
    return results


# ---------------------------------------------------------------------------
# Flowsint API helpers
# ---------------------------------------------------------------------------


async def _get_token(client: httpx.AsyncClient) -> str:
    if (
        _token_cache["token"]
        and asyncio.get_event_loop().time() < _token_cache["expires"]
    ):
        return _token_cache["token"]
    if not _FLOWSINT_EMAIL or not _FLOWSINT_PASSWORD:
        raise RuntimeError("FLOWSINT_EMAIL/FLOWSINT_PASSWORD not set")
    r = await client.post(
        f"{_FLOWSINT_API}/api/auth/token",
        data={"username": _FLOWSINT_EMAIL, "password": _FLOWSINT_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in Flowsint response")
    _token_cache["token"] = token
    _token_cache["expires"] = asyncio.get_event_loop().time() + 3600
    return token


async def _enrich_one(
    client: httpx.AsyncClient,
    token: str,
    enricher_name: str,
    ioc_type: str,
    value: str,
) -> dict[str, Any]:
    """Run a single enricher on a value and return the graph."""
    headers = {"Authorization": f"Bearer {token}"}
    type_info = _TYPE_MAP.get(ioc_type)
    if not type_info:
        return {"error": f"no type map for {ioc_type}"}

    try:
        # Create investigation
        r = await client.post(
            f"{_FLOWSINT_API}/api/investigations/create",
            json={
                "name": f"auto-{ioc_type}-{value[:30]}",
                "description": "Auto-enriched from briefing",
            },
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        inv_id = r.json()["id"]

        # Create sketch
        r = await client.post(
            f"{_FLOWSINT_API}/api/sketches/create",
            json={
                "title": f"auto-{enricher_name}",
                "description": value,
                "investigation_id": inv_id,
            },
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        sketch_id = r.json()["id"]

        # Add node
        node_payload = {
            "id": None,
            "nodeLabel": value,
            "nodeType": type_info["nodeType"],
            "nodeIcon": type_info["icon"],
            "nodeMetadata": {},
            "nodeProperties": {type_info["nodeLabel"]: value},
            "x": 100.0,
            "y": 100.0,
        }
        r = await client.post(
            f"{_FLOWSINT_API}/api/sketches/{sketch_id}/nodes/add",
            json=node_payload,
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        node_resp = r.json()
        node = node_resp.get("node") or node_resp
        node_id = node.get("id")
        if not node_id:
            return {"error": "no node id"}

        # Launch enricher
        r = await client.post(
            f"{_FLOWSINT_API}/api/enrichers/{enricher_name}/launch",
            json={"node_ids": [node_id], "sketch_id": sketch_id},
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        scan_id = r.json().get("id")

        # Poll for completion
        deadline = asyncio.get_event_loop().time() + _TIMEOUT
        scan_status = "pending"
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2.0)
            r = await client.get(
                f"{_FLOWSINT_API}/api/scans/{scan_id}", headers=headers, timeout=5.0
            )
            if r.status_code == 200:
                scan_status = r.json().get("status", "unknown")
                if scan_status.lower() in (
                    "success",
                    "completed",
                    "done",
                    "failed",
                    "error",
                ):
                    break

        # Get graph
        r = await client.get(
            f"{_FLOWSINT_API}/api/sketches/{sketch_id}/graph",
            headers=headers,
            timeout=10.0,
        )
        graph = r.json() if r.status_code == 200 else {"nds": [], "rls": []}

        return {
            "enricher": enricher_name,
            "ioc_type": ioc_type,
            "value": value,
            "sketch_id": sketch_id,
            "scan_status": scan_status,
            "graph": graph,
        }
    except Exception as e:
        return {"error": str(e)[:200], "value": value, "enricher": enricher_name}


# ---------------------------------------------------------------------------
# Ingest enriched graph nodes into intelshed FtM store + globe pins
# ---------------------------------------------------------------------------


def _ingest_enriched_nodes(
    graph: dict, ioc_type: str, source_value: str
) -> dict[str, Any]:
    """Parse Flowsint graph nodes and ingest as FtM entities + globe pins."""
    import ftm_query
    import entity_store

    seen_at = datetime.now(timezone.utc).isoformat()
    dataset = "flowsint_auto"
    entity_ids: list[str] = []
    pins: list[dict[str, Any]] = []
    edge_count = 0

    nodes = graph.get("nds") or []
    for node in nodes:
        node_type = (node.get("nodeType") or "").lower()
        props = node.get("nodeProperties") or {}
        label = node.get("nodeLabel") or ""

        # Determine entity schema
        schema = "Thing"
        if node_type in ("ip", "ipaddress"):
            schema = "IpAddress"
        elif node_type in ("domain",):
            schema = "Domain"
        elif node_type in ("email",):
            schema = "Person"
        elif node_type in ("whois",):
            schema = "Thing"
        elif node_type in ("organization", "org"):
            schema = "Organization"
        elif node_type in ("website",):
            schema = "HyperText"
        elif node_type in ("socialaccount", "social"):
            schema = "Thing"
        elif node_type in ("port",):
            schema = "Thing"
        elif node_type in ("asn",):
            schema = "Thing"

        # Build entity
        ftm_props: dict[str, list[str]] = {"name": [label]}
        if props.get("country"):
            ftm_props["notes"] = [f"Country: {props['country']}"]
        if props.get("city"):
            ftm_props.setdefault("notes", []).append(f"City: {props['city']}")
        if props.get("isp"):
            ftm_props.setdefault("notes", []).append(f"ISP: {props['isp']}")
        if props.get("registrar"):
            ftm_props.setdefault("notes", []).append(f"Registrar: {props['registrar']}")

        proxy = ftm_query.make_entity(
            "Thing", ["flowsint", node_type, label], ftm_props
        )
        lat = None
        lon = None
        try:
            lat = float(props["latitude"]) if props.get("latitude") else None
            lon = float(props["longitude"]) if props.get("longitude") else None
        except (TypeError, ValueError):
            pass

        eid = ftm_query.upsert_cyber_entity(
            proxy,
            schema,
            dataset,
            seen_at=seen_at,
            lat=lat,
            lon=lon,
        )
        if eid:
            entity_ids.append(eid)

            # Create globe pin if we have geo coords
            if lat is not None and lon is not None:
                pin_id = f"flowsint_auto:{eid[:12]}"
                entity_store.upsert_entity(
                    entity_id=pin_id,
                    entity_type=node_type or "flowsint",
                    label=label,
                    lat=lat,
                    lon=lon,
                    source_feed="flowsint_auto",
                    external_id=pin_id,
                    meta={
                        "investigation_id": source_value,
                        "pin_type": node_type,
                        "country": props.get("country"),
                        "city": props.get("city"),
                        "isp": props.get("isp"),
                    },
                )
                pins.append({"lat": lat, "lon": lon, "label": label, "type": node_type})

    # Link source IOC to enriched entities
    if entity_ids:
        source_props: dict[str, list[str]] = {"name": [source_value]}
        source_proxy = ftm_query.make_entity(
            "Thing",
            ["flowsint", ioc_type, source_value],
            source_props,
        )
        source_id = ftm_query.upsert_cyber_entity(
            source_proxy,
            _TYPE_MAP.get(ioc_type, {}).get("nodeType", "Thing"),
            dataset,
            seen_at=seen_at,
        )
        if source_id:
            for eid in entity_ids:
                if eid != source_id:
                    ftm_query.add_intel_edge(
                        source_id,
                        eid,
                        "linkedTo",
                        dataset=dataset,
                        confidence=0.8,
                        source_ref="flowsint_auto_enrich",
                        seen_at=seen_at,
                    )
                    edge_count += 1

    return {
        "entities_created": len(entity_ids),
        "entity_ids": entity_ids,
        "pins_created": len(pins),
        "pins": pins,
        "edges_created": edge_count,
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


async def run_auto_enrich() -> dict[str, Any]:
    """Extract IOCs from latest briefing, enrich via Flowsint, ingest results.

    Returns a summary dict. Fail-soft: errors are logged but don't raise.
    """
    if not _enabled():
        return {"enabled": False, "reason": "WORLDBASE_FLOWSINT_AUTO_ENRICH not set"}

    if not _FLOWSINT_EMAIL or not _FLOWSINT_PASSWORD:
        return {"enabled": True, "error": "FLOWSINT_EMAIL/FLOWSINT_PASSWORD not set"}

    briefing_text = _latest_briefing_text()
    if not briefing_text:
        return {"enabled": True, "error": "no briefing found"}

    iocs = _extract_iocs(briefing_text)
    if not iocs:
        return {"enabled": True, "ioc_count": 0, "message": "no IOCs found in briefing"}

    # Flatten + limit
    flat_iocs: list[tuple[str, str]] = []
    for ioc_type, values in iocs.items():
        enricher = _ENRICHER_MAP.get(ioc_type)
        if not enricher:
            continue
        for val in values:
            flat_iocs.append((ioc_type, val))
    flat_iocs = flat_iocs[:_MAX_IOCS]

    log.info(
        "auto_enrich_start",
        ioc_count=len(flat_iocs),
        ioc_types=list(iocs.keys()),
        max=_MAX_IOCS,
    )

    total_entities = 0
    total_pins = 0
    total_edges = 0
    enriched = 0
    errors = 0
    all_pins: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            token = await _get_token(client)
        except Exception as e:
            log.error("auto_enrich_auth_failed", error=str(e)[:200])
            return {"enabled": True, "error": f"Flowsint auth failed: {str(e)[:100]}"}

        for ioc_type, value in flat_iocs:
            enricher = _ENRICHER_MAP[ioc_type]
            result = await _enrich_one(client, token, enricher, ioc_type, value)

            if "error" in result:
                log.warning(
                    "auto_enrich_ioc_error",
                    value=value,
                    enricher=enricher,
                    error=result["error"],
                )
                errors += 1
                continue

            graph = result.get("graph") or {}
            ingest = _ingest_enriched_nodes(graph, ioc_type, value)
            total_entities += ingest["entities_created"]
            total_pins += ingest["pins_created"]
            total_edges += ingest["edges_created"]
            all_pins.extend(ingest["pins"])
            enriched += 1

            log.info(
                "auto_enrich_ioc_done",
                value=value,
                enricher=enricher,
                status=result.get("scan_status"),
                nodes=len(graph.get("nds") or []),
                entities=ingest["entities_created"],
                pins=ingest["pins_created"],
            )

    summary = {
        "enabled": True,
        "briefing_ioc_count": sum(len(v) for v in iocs.values()),
        "enriched": enriched,
        "errors": errors,
        "entities_created": total_entities,
        "pins_created": total_pins,
        "edges_created": total_edges,
        "pins": all_pins,
        "ioc_types": list(iocs.keys()),
    }
    log.info(
        "auto_enrich_complete", **{k: v for k, v in summary.items() if k != "pins"}
    )
    return summary


# ---------------------------------------------------------------------------
# REST endpoint (manual trigger + status)
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Depends  # noqa: E402

from auth.security import verify_lan_auth  # noqa: E402

router = APIRouter(prefix="/api", tags=["flowsint-auto"])


@router.post("/flowsint/auto-enrich")
async def trigger_auto_enrich(
    _auth: str | None = Depends(verify_lan_auth),
):
    """Manually trigger Flowsint auto-enrichment of the latest briefing."""
    result = await run_auto_enrich()
    return result


@router.get("/flowsint/enriched-graph")
async def get_enriched_graph(
    _auth: str | None = Depends(verify_lan_auth),
):
    """Return all flowsint_auto entities as graph nodes + links for 3D visualization.

    Queries DuckDB FtM store for entities with dataset=flowsint_auto
    and SQLite entity_store for globe pins.
    """
    import ftm_query
    import sqlite3

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    pins: list[dict[str, Any]] = []

    # 1. Fetch flowsint_auto entities from DuckDB FtM store
    schemas = ["IpAddress", "Domain", "Organization", "Person", "HyperText", "Email"]
    seen_ids: set[str] = set()

    for schema in schemas:
        try:
            result = ftm_query.list_entities_by_schema(
                schema, limit=100, dataset="flowsint_auto"
            )
            for ent in result.get("entities", []):
                eid = ent.get("id") or ""
                if not eid or eid in seen_ids:
                    continue
                seen_ids.add(eid)
                props = ent.get("properties") or {}
                label = ""
                if isinstance(props.get("name"), list) and props["name"]:
                    label = props["name"][0]
                elif isinstance(props.get("name"), str):
                    label = props["name"]
                nodes.append(
                    {
                        "id": eid,
                        "label": label or ent.get("caption") or eid[:12],
                        "type": ent.get("schema") or "Thing",
                        "lat": ent.get("lat"),
                        "lon": ent.get("lon"),
                        "props": props,
                        "dataset": "flowsint_auto",
                    }
                )
        except Exception:
            pass

    # 2. Fetch intel edges between these entities
    for edge_type in ("linkedTo", "ownsAsset", "mentionedIn", "locatedAt"):
        try:
            result = ftm_query.list_edges_by_type(
                edge_type, limit=200, dataset="flowsint_auto"
            )
            edges = result if isinstance(result, list) else result.get("edges", [])
            for e in edges:
                src = e.get("source") or e.get("source_id") or ""
                tgt = e.get("target") or e.get("target_id") or ""
                if src in seen_ids or tgt in seen_ids:
                    links.append(
                        {
                            "source": src,
                            "target": tgt,
                            "type": edge_type,
                            "confidence": e.get("confidence", 0.8),
                        }
                    )
        except Exception:
            pass

    # 3. Fetch globe pins from SQLite entity_store
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, type, label, lat, lon, meta_json FROM entities WHERE source_feed = 'flowsint_auto' ORDER BY updated_at DESC LIMIT 200"
        ).fetchall()
        conn.close()
        for row in rows:
            meta = {}
            try:
                meta = json.loads(row["meta_json"] or "{}")
            except Exception:
                pass
            pins.append(
                {
                    "id": row["id"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "label": row["label"] or "",
                    "type": row["type"] or "unknown",
                    "meta": meta,
                }
            )
    except Exception:
        pass

    return {
        "nodes": nodes,
        "links": links,
        "pins": pins,
        "node_count": len(nodes),
        "link_count": len(links),
        "pin_count": len(pins),
    }
