"""Cyber intelligence bridge — Shodan InternetDB (keyless).

Provides passive IP intelligence from Shodan's free InternetDB API:
  https://internetdb.shodan.io/{ip}

No API key required. Returns ports, hostnames, vulns (CVEs), tags, and ISP.

Env:
  WORLDBASE_CYBER_BRIDGE=1 (default on)

Endpoints:
  GET /api/cyber/status
  GET /api/cyber/ip/{ip}
  POST /api/cyber/ip/{ip}/ingest
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Query

from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cyber", tags=["cyber-intel"])

_SHODAN_URL = "https://internetdb.shodan.io"
_TIMEOUT = 15.0
_UA = {"User-Agent": "WorldBase/1.0 (OSINT research)"}

_IP_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 3600.0  # 1 hour


def _enabled() -> bool:
    return get_config().cyber_bridge_enabled


def _cache_get(ip: str) -> dict[str, Any] | None:
    item = _IP_CACHE.get(ip)
    if item and (time.time() - item[0]) < _CACHE_TTL:
        return item[1]
    return None


def _cache_set(ip: str, value: dict[str, Any]) -> None:
    _IP_CACHE[ip] = (time.time(), value)


def _validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


async def _fetch_internetdb(ip: str) -> dict[str, Any]:
    """Fetch Shodan InternetDB data for a single IP (keyless)."""
    cached = _cache_get(ip)
    if cached is not None:
        return cached

    url = f"{_SHODAN_URL}/{ip}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                result = {"ip": ip, "found": False, "source": "shodan_internetdb"}
                _cache_set(ip, result)
                return result
            resp.raise_for_status()
            data = resp.json()
            result = {
                "ip": ip,
                "found": True,
                "source": "shodan_internetdb",
                "ports": data.get("ports", []),
                "hostnames": data.get("hostnames", []),
                "domains": data.get("domains", []),
                "tags": data.get("tags", []),
                "vulns": data.get("vulns", []),
                "isp": data.get("isp"),
                "org": data.get("org"),
                "os": data.get("os"),
                "cpes": data.get("cpes", []),
            }
            _cache_set(ip, result)
            return result
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "shodan_internetdb_http_error ip=%s status=%s", ip, exc.response.status_code
        )
        return {
            "ip": ip,
            "found": False,
            "error": f"HTTP {exc.response.status_code}",
            "source": "shodan_internetdb",
        }
    except Exception as exc:
        logger.warning("shodan_internetdb_error ip=%s: %s", ip, exc)
        return {
            "ip": ip,
            "found": False,
            "error": str(exc)[:200],
            "source": "shodan_internetdb",
        }


async def fetch_ip_intel(ip: str) -> dict[str, Any]:
    """Public API: fetch Shodan InternetDB data for an IP."""
    if not _validate_ip(ip):
        return {"ip": ip, "found": False, "error": "Invalid IP address"}
    return await _fetch_internetdb(ip)


def ingest_ip_intel(
    ip: str, data: dict[str, Any], dataset: str = "cyber_shodan"
) -> dict[str, Any]:
    """Ingest Shodan InternetDB data into the FtM store as cyber entities.

    Creates:
      - IpAddress entity (stored as Thing with schema='IpAddress')
      - Domain entities for each hostname/domain
      - intel_edges: ownsAsset (org → ip), linkedTo (ip → domain)
    """
    import ftm_query

    seen_at = ftm_query._now()
    entity_ids: list[str] = []
    edge_count = 0

    # IpAddress entity
    ip_props: dict[str, list[str]] = {
        "name": [ip],
        "notes": ["Shodan InternetDB lookup"],
    }
    if data.get("isp"):
        ip_props["notes"].append(f"ISP: {data['isp']}")
    if data.get("org"):
        ip_props["notes"].append(f"Org: {data['org']}")
    if data.get("ports"):
        ip_props["keywords"] = [f"port:{p}" for p in data["ports"][:20]]
    if data.get("tags"):
        ip_props["keywords"].extend(data["tags"][:10])

    ip_proxy = ftm_query.make_entity("Thing", ["cyber", "ip", ip], ip_props)
    ip_id = ftm_query.upsert_cyber_entity(
        ip_proxy, "IpAddress", dataset, seen_at=seen_at
    )
    if ip_id:
        entity_ids.append(ip_id)

    # Organization entity (if available)
    org_id = None
    if data.get("org"):
        org_props: dict[str, list[str]] = {"name": [data["org"]]}
        if data.get("isp"):
            org_props["notes"] = [f"ISP: {data['isp']}"]
        org_proxy = ftm_query.make_entity(
            "Organization", ["cyber", "org", data["org"]], org_props
        )
        org_id = ftm_query.upsert(org_proxy, dataset=dataset, seen_at=seen_at)
        if org_id:
            entity_ids.append(org_id)
            # org ownsAsset ip
            ftm_query.add_intel_edge(
                org_id,
                ip_id,
                "ownsAsset",
                dataset=dataset,
                confidence=0.8,
                source_ref="shodan_internetdb",
                seen_at=seen_at,
            )
            edge_count += 1

    # Domain / hostname entities
    hostnames = data.get("hostnames", []) + data.get("domains", [])
    for hn in hostnames[:10]:
        hn = hn.strip()
        if not hn:
            continue
        dom_props: dict[str, list[str]] = {"name": [hn]}
        dom_proxy = ftm_query.make_entity("Thing", ["cyber", "domain", hn], dom_props)
        dom_id = ftm_query.upsert_cyber_entity(
            dom_proxy, "Domain", dataset, seen_at=seen_at
        )
        if dom_id:
            entity_ids.append(dom_id)
            # ip linkedTo domain
            ftm_query.add_intel_edge(
                ip_id,
                dom_id,
                "linkedTo",
                dataset=dataset,
                confidence=0.7,
                source_ref="shodan_internetdb",
                seen_at=seen_at,
            )
            edge_count += 1
            # org ownsAsset domain (if org exists)
            if org_id:
                ftm_query.add_intel_edge(
                    org_id,
                    dom_id,
                    "ownsAsset",
                    dataset=dataset,
                    confidence=0.6,
                    source_ref="shodan_internetdb",
                    seen_at=seen_at,
                )
                edge_count += 1

    return {
        "ip": ip,
        "ingested": True,
        "entity_ids": entity_ids,
        "edge_count": edge_count,
        "dataset": dataset,
    }


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def cyber_status():
    return {
        "enabled": _enabled(),
        "source": "shodan_internetdb",
        "keyless": True,
        "cache_ttl": _CACHE_TTL,
        "cached_ips": len(_IP_CACHE),
    }


@router.get("/ip/{ip}")
async def cyber_ip_lookup(ip: str):
    """Look up IP intelligence from Shodan InternetDB (keyless)."""
    if not _enabled():
        return {"enabled": False, "error": "Cyber bridge disabled"}
    if not _validate_ip(ip):
        return {"ip": ip, "found": False, "error": "Invalid IP address"}
    result = await _fetch_internetdb(ip)
    return result


@router.post("/ip/{ip}/ingest")
async def cyber_ip_ingest(
    ip: str,
    dataset: str = Query("cyber_shodan", description="Provenance dataset tag"),
):
    """Look up and ingest IP intelligence into the FtM store."""
    if not _enabled():
        return {"enabled": False, "error": "Cyber bridge disabled"}
    if not _validate_ip(ip):
        return {"ip": ip, "found": False, "error": "Invalid IP address"}
    data = await _fetch_internetdb(ip)
    if not data.get("found"):
        return {"ip": ip, "ingested": False, "error": data.get("error", "No data")}
    return await asyncio.to_thread(ingest_ip_intel, ip, data, dataset)
