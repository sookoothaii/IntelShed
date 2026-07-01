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
_FLOWSINT_UI = os.getenv("FLOWSINT_UI_URL", "http://127.0.0.1:5173").rstrip("/")
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

# ---------------------------------------------------------------------------
# Enricher catalog (static — mirrors Flowsint's 47 enrichers)
# ---------------------------------------------------------------------------

_ENRICHER_CATALOG: list[dict[str, Any]] = [
    # IP
    {
        "name": "ip_to_infos",
        "category": "IP",
        "input": "ip",
        "output": "Ip",
        "desc": "[ip-api.com] Get information data for IP addresses.",
        "params": False,
    },
    {
        "name": "ip_to_domain",
        "category": "IP",
        "input": "ip",
        "output": "Domain",
        "desc": "Resolve IP to domain names (PTR, CT logs).",
        "params": False,
    },
    {
        "name": "ip_to_asn",
        "category": "IP",
        "input": "ip",
        "output": "ASN",
        "desc": "[ASNMAP] IP to ASN.",
        "params": True,
    },
    {
        "name": "ip_to_ports",
        "category": "IP",
        "input": "ip",
        "output": "Port",
        "desc": "[NAABU] Port scan IP addresses.",
        "params": True,
    },
    {
        "name": "ip_to_fraudscore",
        "category": "IP",
        "input": "ip",
        "output": "RiskProfile",
        "desc": "[Scamalytics] Fraud score for IP.",
        "params": True,
    },
    {
        "name": "ip_to_intelligence",
        "category": "IP",
        "input": "ip",
        "output": "Individual",
        "desc": "[DeHashed] Breach intelligence from IP.",
        "params": True,
    },
    # Domain
    {
        "name": "domain_to_whois",
        "category": "Domain",
        "input": "domain",
        "output": "Whois",
        "desc": "WHOIS information for a domain.",
        "params": False,
    },
    {
        "name": "domain_to_ip",
        "category": "Domain",
        "input": "domain",
        "output": "Ip",
        "desc": "Resolve domain to IP addresses.",
        "params": False,
    },
    {
        "name": "domain_to_subdomains",
        "category": "Domain",
        "input": "domain",
        "output": "Domain",
        "desc": "Find subdomains for a domain.",
        "params": False,
    },
    {
        "name": "domain_to_tls",
        "category": "Domain",
        "input": "domain",
        "output": "Website",
        "desc": "[httpX] TLS information from domain.",
        "params": False,
    },
    {
        "name": "domain_to_website",
        "category": "Domain",
        "input": "domain",
        "output": "Website",
        "desc": "From domain to website.",
        "params": False,
    },
    {
        "name": "domain_to_root_domain",
        "category": "Domain",
        "input": "domain",
        "output": "Domain",
        "desc": "Subdomain to root domain.",
        "params": False,
    },
    {
        "name": "domain_to_history",
        "category": "Domain",
        "input": "domain",
        "output": "Domain",
        "desc": "[WHOXY] Domain history (orgs, owners, emails).",
        "params": True,
    },
    {
        "name": "domain_to_asn",
        "category": "Domain",
        "input": "domain",
        "output": "ASN",
        "desc": "[ASNMAP] Domain to ASN.",
        "params": True,
    },
    {
        "name": "domain_to_dehashed",
        "category": "Domain",
        "input": "domain",
        "output": "Individual",
        "desc": "[DeHashed] Breach intelligence from domain.",
        "params": True,
    },
    {
        "name": "domain_to_whois_history",
        "category": "Domain",
        "input": "domain",
        "output": "Whois",
        "desc": "[WHOISXML] WHOIS history records.",
        "params": True,
    },
    # Email
    {
        "name": "email_to_gravatar",
        "category": "Email",
        "input": "email",
        "output": "Gravatar",
        "desc": "MD5 hash of email to gravatar.",
        "params": False,
    },
    {
        "name": "email_to_domain",
        "category": "Email",
        "input": "email",
        "output": "Domain",
        "desc": "From email to domain.",
        "params": False,
    },
    {
        "name": "email_to_username",
        "category": "Email",
        "input": "email",
        "output": "Username",
        "desc": "From email to username.",
        "params": False,
    },
    {
        "name": "email_to_breaches",
        "category": "Email",
        "input": "email",
        "output": "Any",
        "desc": "[HIBPWNED] Get breaches for email.",
        "params": True,
    },
    {
        "name": "email_to_intelligence",
        "category": "Email",
        "input": "email",
        "output": "Individual",
        "desc": "[DeHashed] Breach intelligence from email.",
        "params": True,
    },
    {
        "name": "email_to_domains",
        "category": "Email",
        "input": "email",
        "output": "Domain",
        "desc": "[WHOXY] Domains registered by email.",
        "params": True,
    },
    {
        "name": "email_to_device_hudsonrock",
        "category": "Email",
        "input": "email",
        "output": "Device",
        "desc": "[HudsonRock] Infostealer device data.",
        "params": False,
    },
    # Social / Username
    {
        "name": "username_to_socials_maigret",
        "category": "Social",
        "input": "username",
        "output": "SocialAccount",
        "desc": "[MAIGRET] Scan username across social platforms.",
        "params": False,
    },
    {
        "name": "username_to_socials_sherlock",
        "category": "Social",
        "input": "username",
        "output": "SocialAccount",
        "desc": "[SHERLOCK] Scan username across social platforms.",
        "params": False,
    },
    {
        "name": "username_to_dehashed",
        "category": "Social",
        "input": "username",
        "output": "Individual",
        "desc": "[DeHashed] Breach intelligence from username.",
        "params": True,
    },
    {
        "name": "username_to_device_hudsonrock",
        "category": "Social",
        "input": "username",
        "output": "Device",
        "desc": "[HudsonRock] Infostealer device data.",
        "params": False,
    },
    # Website
    {
        "name": "website_to_links",
        "category": "Website",
        "input": "website",
        "output": "Website",
        "desc": "Extract internal/external links from website.",
        "params": False,
    },
    {
        "name": "website_to_text",
        "category": "Website",
        "input": "website",
        "output": "Phrase",
        "desc": "Extract text from webpage.",
        "params": False,
    },
    {
        "name": "website_to_domain",
        "category": "Website",
        "input": "website",
        "output": "Domain",
        "desc": "From website to domain.",
        "params": False,
    },
    {
        "name": "website_to_crawler",
        "category": "Website",
        "input": "website",
        "output": "ReturnType",
        "desc": "Crawl website.",
        "params": False,
    },
    {
        "name": "website_to_webtrackers",
        "category": "Website",
        "input": "website",
        "output": "WebTracker",
        "desc": "Extract web trackers from website.",
        "params": False,
    },
    {
        "name": "website_to_subdomains",
        "category": "Website",
        "input": "website",
        "output": "Website",
        "desc": "[c99.nl] Find subdomains of website.",
        "params": True,
    },
    # Organization
    {
        "name": "org_to_infos",
        "category": "Organization",
        "input": "organization",
        "output": "Organization",
        "desc": "[SIRENE] Organization data (France).",
        "params": False,
    },
    {
        "name": "org_to_domains",
        "category": "Organization",
        "input": "organization",
        "output": "Domain",
        "desc": "[WHOXY] Domains registered by org.",
        "params": True,
    },
    {
        "name": "org_to_asn",
        "category": "Organization",
        "input": "organization",
        "output": "ASN",
        "desc": "Organization to ASN.",
        "params": True,
    },
    # Phone
    {
        "name": "phone_to_infos",
        "category": "Phone",
        "input": "phone",
        "output": "Any",
        "desc": "Phone number information.",
        "params": False,
    },
    {
        "name": "phone_to_carrier",
        "category": "Phone",
        "input": "phone",
        "output": "Phone",
        "desc": "[veriphone] Phone carrier lookup.",
        "params": True,
    },
    {
        "name": "phone_to_device_hudsonrock",
        "category": "Phone",
        "input": "phone",
        "output": "Device",
        "desc": "[HudsonRock] Infostealer device data.",
        "params": False,
    },
    # Crypto
    {
        "name": "cryptowallet_to_transactions",
        "category": "Crypto",
        "input": "cryptowallet",
        "output": "CryptoWalletTransaction",
        "desc": "[ETHERSCAN] Wallet transactions (ETH).",
        "params": True,
    },
    {
        "name": "cryptowallet_to_nfts",
        "category": "Crypto",
        "input": "cryptowallet",
        "output": "CryptoNFT",
        "desc": "[ETHERSCAN] Wallet NFTs (ETH).",
        "params": True,
    },
    # Individual
    {
        "name": "individual_to_domains",
        "category": "Individual",
        "input": "individual",
        "output": "Domain",
        "desc": "[WHOXY] Domains registered by individual.",
        "params": True,
    },
    {
        "name": "individual_to_organization",
        "category": "Individual",
        "input": "individual",
        "output": "Organization",
        "desc": "[SIRENE] Find org from person (France).",
        "params": False,
    },
    # ASN / CIDR
    {
        "name": "asn_to_cidrs",
        "category": "ASN",
        "input": "asn",
        "output": "CIDR",
        "desc": "[ASNMAP] ASN to CIDRs.",
        "params": True,
    },
    {
        "name": "cidr_to_ips",
        "category": "CIDR",
        "input": "cidr",
        "output": "Ip",
        "desc": "[MAPCIDR] CIDR to IP addresses.",
        "params": True,
    },
]

# Chain rules: after enricher X on type Y, auto-run enricher Z
_CHAIN_MAP: dict[str, list[tuple[str, str]]] = {
    "ip_to_infos": [("ip_to_domain", "ipv4")],
    "domain_to_whois": [("domain_to_ip", "domain")],
    "email_to_domain": [("domain_to_whois", "domain")],
}

# Map enricher input types to internal IOC types
_ENRICHER_INPUT_MAP: dict[str, str] = {
    "ip": "ipv4",
    "domain": "domain",
    "email": "email",
    "username": "username",
    "website": "website",
    "organization": "organization",
    "phone": "phone",
    "cryptowallet": "cryptowallet",
    "individual": "individual",
    "asn": "asn",
    "cidr": "cidr",
}

# Map enricher input types to _TYPE_MAP keys (extending for new types)
_TYPE_MAP_EXT: dict[str, dict[str, str]] = {
    **_TYPE_MAP,
    "username": {"nodeType": "Username", "nodeLabel": "username", "icon": "user"},
    "website": {"nodeType": "Website", "nodeLabel": "url", "icon": "globe"},
    "organization": {
        "nodeType": "Organization",
        "nodeLabel": "name",
        "icon": "building",
    },
    "phone": {"nodeType": "Phone", "nodeLabel": "phone", "icon": "phone"},
    "cryptowallet": {
        "nodeType": "CryptoWallet",
        "nodeLabel": "address",
        "icon": "crypto",
    },
}


@router.get("/flowsint/enrichers")
async def list_enrichers(
    _auth: str | None = Depends(verify_lan_auth),
):
    """Return all available Flowsint enrichers grouped by category."""
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for e in _ENRICHER_CATALOG:
        cat = e["category"]
        by_cat.setdefault(cat, []).append(e)
    return {
        "count": len(_ENRICHER_CATALOG),
        "categories": by_cat,
        "enrichers": _ENRICHER_CATALOG,
    }


@router.post("/flowsint/auto-enrich")
async def trigger_auto_enrich(
    _auth: str | None = Depends(verify_lan_auth),
):
    """Manually trigger Flowsint auto-enrichment of the latest briefing."""
    result = await run_auto_enrich()
    return result


@router.post("/flowsint/enrich-and-ingest")
async def enrich_and_ingest(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Enrich a single IOC via Flowsint and ingest into DuckDB + globe pins.

    Body: {"entity_type": "ip|domain|email", "value": "8.8.8.8", "enricher_name": "ip_to_infos"}
    """
    entity_type = body.get("entity_type", "ip").strip()
    # Map frontend-friendly types to internal IOC types
    if entity_type == "ip":
        entity_type = "ipv4"
    value = body.get("value", "").strip()
    enricher_name = body.get("enricher_name") or _ENRICHER_MAP.get(
        entity_type, "ip_to_infos"
    )
    if not value:
        return {"error": "value is required"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            token = await _get_token(client)
        except Exception as e:
            return {"error": f"Flowsint auth failed: {str(e)[:100]}"}

        result = await _enrich_one(client, token, enricher_name, entity_type, value)
    if "error" in result:
        return result

    graph = result.get("graph") or {}
    ingest = _ingest_enriched_nodes(graph, entity_type, value)

    # Auto-chain: run follow-up enrichers on enriched node values
    chain_results: list[dict[str, Any]] = []
    chain_enrichers = _CHAIN_MAP.get(enricher_name, [])
    if chain_enrichers and _truthy(os.getenv("WORLDBASE_FLOWSINT_CHAIN", "1")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            for chain_enricher, chain_type in chain_enrichers:
                # Use the original value for chained enrichment
                try:
                    chain_result = await _enrich_one(
                        client, token, chain_enricher, chain_type, value
                    )
                    if "error" not in chain_result:
                        chain_graph = chain_result.get("graph") or {}
                        chain_ingest = _ingest_enriched_nodes(
                            chain_graph, chain_type, value
                        )
                        chain_results.append(
                            {
                                "enricher": chain_enricher,
                                "entities": chain_ingest["entities_created"],
                                "edges": chain_ingest["edges_created"],
                            }
                        )
                except Exception as e:
                    chain_results.append(
                        {
                            "enricher": chain_enricher,
                            "error": str(e)[:100],
                        }
                    )

    return {
        "value": value,
        "enricher": enricher_name,
        "scan_status": result.get("scan_status"),
        "nodes_in_graph": len(graph.get("nds") or []),
        "entities_created": ingest["entities_created"],
        "pins_created": ingest["pins_created"],
        "edges_created": ingest["edges_created"],
        "pins": ingest["pins"],
        "chain": chain_results,
    }


@router.post("/flowsint/enrich-further")
async def enrich_further(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Enrich an existing graph node further with a specific enricher.

    Body: {"value": "8.8.8.8", "entity_type": "ip", "enricher_name": "ip_to_ports"}
    """
    value = body.get("value", "").strip()
    enricher_name = body.get("enricher_name", "").strip()
    entity_type = body.get("entity_type", "ip").strip()
    if entity_type == "ip":
        entity_type = "ipv4"
    if not value or not enricher_name:
        return {"error": "value and enricher_name are required"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            token = await _get_token(client)
        except Exception as e:
            return {"error": f"Flowsint auth failed: {str(e)[:100]}"}

        result = await _enrich_one(client, token, enricher_name, entity_type, value)
    if "error" in result:
        return result

    graph = result.get("graph") or {}
    ingest = _ingest_enriched_nodes(graph, entity_type, value)
    return {
        "value": value,
        "enricher": enricher_name,
        "scan_status": result.get("scan_status"),
        "nodes_in_graph": len(graph.get("nds") or []),
        "entities_created": ingest["entities_created"],
        "pins_created": ingest["pins_created"],
        "edges_created": ingest["edges_created"],
        "pins": ingest["pins"],
    }


@router.post("/flowsint/auto-chain")
async def auto_chain(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Run a multi-step enrichment chain on a value.

    Body: {"value": "8.8.8.8", "entity_type": "ip", "chain": ["ip_to_infos", "ip_to_domain", "domain_to_subdomains"]}
    """
    value = body.get("value", "").strip()
    entity_type = body.get("entity_type", "ip").strip()
    chain = body.get("chain", [])
    if entity_type == "ip":
        entity_type = "ipv4"
    if not value or not chain:
        return {"error": "value and chain are required"}

    results: list[dict[str, Any]] = []
    current_value = value
    current_type = entity_type

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            token = await _get_token(client)
        except Exception as e:
            return {"error": f"Flowsint auth failed: {str(e)[:100]}"}

        for enricher_name in chain:
            try:
                result = await _enrich_one(
                    client, token, enricher_name, current_type, current_value
                )
                if "error" in result:
                    results.append(
                        {
                            "enricher": enricher_name,
                            "error": result["error"],
                        }
                    )
                    break
                graph = result.get("graph") or {}
                ingest = _ingest_enriched_nodes(graph, current_type, current_value)
                results.append(
                    {
                        "enricher": enricher_name,
                        "value": current_value,
                        "entities": ingest["entities_created"],
                        "edges": ingest["edges_created"],
                        "pins": ingest["pins_created"],
                    }
                )
                # Extract next value from graph nodes if available
                nds = graph.get("nds") or []
                if nds and len(nds) > 1:
                    # Use the enriched node's value as next input
                    props = nds[-1].get("nodeProperties") or {}
                    next_val = (
                        props.get("domain")
                        or props.get("address")
                        or props.get("url")
                        or props.get("name")
                    )
                    if next_val and next_val != current_value:
                        current_value = next_val
                        # Update type based on enricher output
                        for e in _ENRICHER_CATALOG:
                            if e["name"] == enricher_name:
                                out = e.get("output", "").lower()
                                if "domain" in out:
                                    current_type = "domain"
                                elif "ip" in out:
                                    current_type = "ipv4"
                                elif "website" in out:
                                    current_type = "website"
                                break
            except Exception as e:
                results.append(
                    {
                        "enricher": enricher_name,
                        "error": str(e)[:100],
                    }
                )
                break

    return {
        "value": value,
        "chain": chain,
        "steps": results,
        "total_entities": sum(r.get("entities", 0) for r in results),
        "total_edges": sum(r.get("edges", 0) for r in results),
    }


@router.post("/flowsint/export-investigation")
async def export_investigation(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Export intelshed entities to Flowsint as a new investigation.

    Body: {"name": "My Investigation", "entity_ids": ["id1", "id2"], "enrich": true}
    """
    from ftm_connection import run_query_ro

    name = body.get(
        "name",
        f"intelshed-export-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
    )
    entity_ids = body.get("entity_ids", [])
    do_enrich = body.get("enrich", False)

    if not entity_ids:
        return {"error": "entity_ids is required"}

    # Fetch entities from DuckDB
    entities: list[dict[str, Any]] = []
    try:
        placeholders = ", ".join(f"'{eid}'" for eid in entity_ids[:50])
        rows = run_query_ro(
            f"SELECT id, schema, caption, lat, lon, properties, datasets "
            f"FROM entities WHERE id IN ({placeholders})"
        )
        for r in rows:
            props = {}
            try:
                import json as _json

                props = _json.loads(r["properties"]) if r["properties"] else {}
            except Exception:
                pass
            entities.append(
                {
                    "id": r["id"],
                    "schema": r["schema"],
                    "label": r["caption"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                    "props": props,
                    "datasets": r["datasets"],
                }
            )
    except Exception as e:
        return {"error": f"DuckDB query failed: {str(e)[:100]}"}

    if not entities:
        return {"error": "no entities found for given IDs"}

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            token = await _get_token(client)
        except Exception as e:
            return {"error": f"Flowsint auth failed: {str(e)[:100]}"}

        headers = {"Authorization": f"Bearer {token}"}

        # Create investigation
        r = await client.post(
            f"{_FLOWSINT_API}/api/investigations/create",
            json={
                "name": name,
                "description": f"Exported from intelshed ({len(entities)} entities)",
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
                "title": name,
                "description": "intelshed export",
                "investigation_id": inv_id,
            },
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        sketch_id = r.json()["id"]

        # Add nodes
        node_ids: list[int] = []
        for ent in entities:
            schema = ent["schema"] or "Thing"
            label = ent["label"] or ent["id"]
            props = ent["props"] or {}

            # Determine node type and label key
            node_type = "Thing"
            node_label_key = "name"
            if schema == "IpAddress":
                node_type = "Ip"
                node_label_key = "ip"
            elif schema == "Domain":
                node_type = "Domain"
                node_label_key = "domain"
            elif schema == "Organization":
                node_type = "Organization"
                node_label_key = "name"
            elif schema == "Person":
                node_type = "Person"
                node_label_key = "name"
            elif schema == "HyperText":
                node_type = "Website"
                node_label_key = "url"

            node_payload = {
                "id": None,
                "nodeLabel": label,
                "nodeType": node_type,
                "nodeIcon": "default",
                "nodeMetadata": {},
                "nodeProperties": {node_label_key: label},
                "x": 100.0,
                "y": 100.0,
            }
            try:
                r = await client.post(
                    f"{_FLOWSINT_API}/api/sketches/{sketch_id}/nodes/add",
                    json=node_payload,
                    headers=headers,
                    timeout=10.0,
                )
                r.raise_for_status()
                node_resp = r.json()
                node = node_resp.get("node") or node_resp
                nid = node.get("id")
                if nid:
                    node_ids.append(nid)
            except Exception:
                pass

        # Optionally enrich all nodes
        enrich_results: list[dict[str, Any]] = []
        if do_enrich and node_ids:
            for ent in entities:
                schema = ent["schema"] or ""
                enricher = None
                if schema == "IpAddress":
                    enricher = "ip_to_infos"
                elif schema == "Domain":
                    enricher = "domain_to_whois"
                elif schema == "Person":
                    enricher = "email_to_gravatar"
                if not enricher:
                    continue
                try:
                    r = await client.post(
                        f"{_FLOWSINT_API}/api/enrichers/{enricher}/launch",
                        json={"node_ids": node_ids, "sketch_id": sketch_id},
                        headers=headers,
                        timeout=10.0,
                    )
                    r.raise_for_status()
                    enrich_results.append({"enricher": enricher, "status": "launched"})
                except Exception as e:
                    enrich_results.append({"enricher": enricher, "error": str(e)[:100]})

    return {
        "investigation_id": inv_id,
        "sketch_id": sketch_id,
        "nodes_sent": len(node_ids),
        "entities": len(entities),
        "enrich": enrich_results if do_enrich else None,
        "flowsint_url": f"{_FLOWSINT_UI}/investigation/{inv_id}",
    }


@router.post("/flowsint/auto-chain-pipeline")
async def auto_chain_pipeline(
    body: dict,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Run a full auto-chain pipeline: IP → Domain → Subdomains → Websites.

    Body: {"value": "8.8.8.8", "entity_type": "ip"}
    """
    value = body.get("value", "").strip()
    entity_type = body.get("entity_type", "ip").strip()
    if entity_type == "ip":
        entity_type = "ipv4"
    if not value:
        return {"error": "value is required"}

    # Default pipeline: IP → Domain → Subdomains → Websites
    pipeline: list[str] = []
    if entity_type == "ipv4":
        pipeline = [
            "ip_to_infos",
            "ip_to_domain",
            "domain_to_subdomains",
            "domain_to_website",
        ]
    elif entity_type == "domain":
        pipeline = [
            "domain_to_whois",
            "domain_to_ip",
            "ip_to_infos",
            "domain_to_subdomains",
        ]
    elif entity_type == "email":
        pipeline = ["email_to_domain", "domain_to_whois", "domain_to_ip", "ip_to_infos"]
    else:
        return {"error": f"auto-chain pipeline not defined for type: {entity_type}"}

    # Use the auto-chain endpoint logic
    chain_body = {"value": value, "entity_type": entity_type, "chain": pipeline}
    return await auto_chain(chain_body, _auth)


@router.get("/flowsint/enriched-graph")
async def get_enriched_graph(
    _auth: str | None = Depends(verify_lan_auth),
):
    """Return all flowsint_auto entities as graph nodes + links for 3D visualization.

    Queries DuckDB FtM store for entities with dataset=flowsint_auto
    and SQLite entity_store for globe pins.
    """
    import sqlite3
    from ftm_connection import run_query_ro

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    pins: list[dict[str, Any]] = []

    # 1. Fetch flowsint_auto entities directly from DuckDB (bypass statements JOIN)
    try:
        rows = run_query_ro(
            "SELECT id, schema, caption, lat, lon, properties, datasets "
            "FROM entities WHERE datasets LIKE '%flowsint%' LIMIT 500"
        )
        for r in rows:
            eid = r[0]
            props = json.loads(r[5]) if r[5] else {}
            label = ""
            if isinstance(props.get("name"), list) and props["name"]:
                label = props["name"][0]
            elif isinstance(props.get("name"), str):
                label = props["name"]
            nodes.append(
                {
                    "id": eid,
                    "label": label or r[2] or eid[:12],
                    "type": r[1] or "Thing",
                    "lat": r[3],
                    "lon": r[4],
                    "props": props,
                    "dataset": "flowsint_auto",
                }
            )
    except Exception as e:
        log.warning("enriched_graph_entities_failed", error=str(e)[:200])

    seen_ids = {n["id"] for n in nodes}

    # 2. Fetch edges between these entities from DuckDB
    try:
        edge_rows = run_query_ro(
            "SELECT source_id, target_id, kind, confidence, dataset "
            "FROM intel_edges WHERE dataset LIKE '%flowsint%' LIMIT 500"
        )
        for r in edge_rows:
            if r[0] in seen_ids or r[1] in seen_ids:
                links.append(
                    {
                        "source": r[0],
                        "target": r[1],
                        "type": r[2],
                        "confidence": r[3] or 0.8,
                    }
                )
    except Exception as e:
        log.warning("enriched_graph_edges_failed", error=str(e)[:200])

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
