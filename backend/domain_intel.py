"""Domain intelligence bridge — CT logs, Wayback CDX, RDAP (no API key).

Provides OSINT for a given domain:
  - crt.sh: Certificate Transparency log entries (subdomain discovery)
  - Wayback CDX: historical web archive snapshots
  - RDAP: domain registration data (replacement for WHOIS)

All sources are free / no-key. Fail-soft: each source degrades independently.

Env:
  WORLDBASE_DOMAIN_INTEL=1 (default on)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Query

from feeds.envelope import utc_now_iso
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api/domain", tags=["domain-intel"])

_UA = {"User-Agent": "WorldBase/1.0 (spatial intelligence research)"}
_TIMEOUT = 30.0

_CONNECTOR = FeedConnector(
    "domain_intel", ttl_sec=3600.0, default_source="crt.sh+wayback+rdap"
)

# Module-local cache for individual domain lookups (keyed by domain)
_DOMAIN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DOMAIN_TTL = 3600.0  # 1 hour


def _enabled() -> bool:
    return os.getenv("WORLDBASE_DOMAIN_INTEL", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _domain_cache_get(domain: str) -> dict[str, Any] | None:
    item = _DOMAIN_CACHE.get(domain)
    if item and (time.time() - item[0]) < _DOMAIN_TTL:
        return item[1]
    return None


def _domain_cache_set(domain: str, value: dict[str, Any]) -> None:
    _DOMAIN_CACHE[domain] = (time.time(), value)


# ---------------------------------------------------------------------------
# crt.sh — Certificate Transparency
# ---------------------------------------------------------------------------


async def _fetch_crt_sh(domain: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch CT log entries from crt.sh."""
    url = f"https://crt.sh/?q=%25.{domain}&output=json"
    try:
        r = await client.get(url, timeout=20.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"enabled": False, "error": str(e), "certificates": [], "count": 0}

    seen: set[str] = set()
    certs: list[dict[str, Any]] = []
    for entry in data[:200]:
        ca = entry.get("ca", {})
        cert_id = entry.get("id") or entry.get("issuer_ca_id")
        common_name = entry.get("common_name") or ""
        name_value = entry.get("name_value") or ""
        not_before = entry.get("not_before") or ""
        not_after = entry.get("not_after") or ""
        issuer = ca.get("name") or ""

        # Deduplicate by common_name + name_value
        dedup_key = f"{common_name}|{name_value}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        # Extract unique subdomains from name_value
        subdomains = sorted(
            {ln.strip().lower() for ln in name_value.split("\n") if ln.strip()}
        )

        certs.append(
            {
                "id": cert_id,
                "common_name": common_name[:200],
                "subdomains": subdomains[:20],
                "not_before": not_before,
                "not_after": not_after,
                "issuer": issuer[:200],
            }
        )

    # Collect all unique subdomains
    all_subs: set[str] = set()
    for c in certs:
        all_subs.update(c["subdomains"])

    return {
        "enabled": True,
        "count": len(certs),
        "certificates": certs,
        "unique_subdomains": sorted(all_subs)[:100],
        "subdomain_count": len(all_subs),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Wayback CDX — historical snapshots
# ---------------------------------------------------------------------------


async def _fetch_wayback(
    domain: str, client: httpx.AsyncClient, limit: int = 50
) -> dict[str, Any]:
    """Fetch Wayback CDX snapshots for a domain."""
    url = (
        f"https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/*&output=json&limit={limit}&collapse=urlkey"
        "&fl=timestamp,original,statuscode,mimetype"
    )
    try:
        r = await client.get(url, timeout=20.0)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"enabled": False, "error": str(e), "snapshots": [], "count": 0}

    snapshots: list[dict[str, Any]] = []
    if not data or len(data) < 2:
        return {
            "enabled": True,
            "count": 0,
            "snapshots": [],
            "error": None,
        }

    # First row is header
    for row in data[1 : limit + 1]:
        if len(row) < 4:
            continue
        ts, original, status, mime = row[0], row[1], row[2], row[3]
        # Format timestamp: 20200615123456 -> 2020-06-15T12:34:56Z
        formatted_ts = ts
        if len(ts) == 14:
            formatted_ts = (
                f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"
            )
        snapshots.append(
            {
                "timestamp": formatted_ts,
                "url": original[:300],
                "status_code": status,
                "mimetype": mime[:80],
            }
        )

    # Earliest and latest snapshots
    timestamps = [s["timestamp"] for s in snapshots if s["timestamp"]]
    first_seen = min(timestamps) if timestamps else None
    last_seen = max(timestamps) if timestamps else None

    return {
        "enabled": True,
        "count": len(snapshots),
        "snapshots": snapshots,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "error": None,
    }


# ---------------------------------------------------------------------------
# RDAP — domain registration data
# ---------------------------------------------------------------------------


async def _fetch_rdap(domain: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Fetch RDAP registration data."""
    url = f"https://rdap.org/domain/{domain}"
    try:
        r = await client.get(url, timeout=15.0)
        if r.status_code == 404:
            return {
                "enabled": True,
                "registered": False,
                "error": "Domain not found in RDAP",
            }
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return {"enabled": False, "error": str(e), "registered": None}

    # Extract key fields
    events = data.get("events") or []
    registration = None
    expiration = None
    last_changed = None
    for ev in events:
        action = ev.get("eventAction", "")
        date = ev.get("eventDate")
        if action == "registration":
            registration = date
        elif action == "expiration":
            expiration = date
        elif action == "last changed":
            last_changed = date

    # Extract entities (registrar, registrant, admin, tech)
    entities = data.get("entities") or []
    roles_map: dict[str, str] = {}
    for ent in entities:
        roles = ent.get("roles") or []
        vcard = ent.get("vcardArray") or []
        name = ""
        if isinstance(vcard, list) and len(vcard) >= 2:
            for field in vcard[1]:
                if isinstance(field, list) and len(field) >= 4 and field[0] == "fn":
                    name = field[3]
                    break
        handle = ent.get("handle") or ""
        for role in roles:
            roles_map[role] = name or handle

    # Nameservers
    nameservers = [(ns.get("ldhName") or "") for ns in (data.get("nameservers") or [])]

    # Status
    status_list = data.get("status") or []

    return {
        "enabled": True,
        "registered": True,
        "domain": data.get("ldhName") or domain,
        "registrar": roles_map.get("registrar", ""),
        "registrant": roles_map.get("registrant", ""),
        "registration_date": registration,
        "expiration_date": expiration,
        "last_changed": last_changed,
        "nameservers": [ns for ns in nameservers if ns],
        "status": status_list,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Combined domain intel
# ---------------------------------------------------------------------------


async def _gather_domain_intel(domain: str, wayback_limit: int = 50) -> dict[str, Any]:
    """Fetch all three sources in parallel."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
        certs_task = _fetch_crt_sh(domain, client)
        wayback_task = _fetch_wayback(domain, client, limit=wayback_limit)
        rdap_task = _fetch_rdap(domain, client)
        certs, wayback, rdap = await asyncio.gather(
            certs_task, wayback_task, rdap_task, return_exceptions=True
        )

    # Handle exceptions from gather
    if isinstance(certs, Exception):
        certs = {"enabled": False, "error": str(certs), "certificates": [], "count": 0}
    if isinstance(wayback, Exception):
        wayback = {"enabled": False, "error": str(wayback), "snapshots": [], "count": 0}
    if isinstance(rdap, Exception):
        rdap = {"enabled": False, "error": str(rdap), "registered": None}

    # Build summary
    subdomain_count = certs.get("subdomain_count", 0) if certs.get("enabled") else 0
    snapshot_count = wayback.get("count", 0) if wayback.get("enabled") else 0
    registered = rdap.get("registered") if rdap.get("enabled") else None

    return {
        "domain": domain,
        "certs": certs,
        "wayback": wayback,
        "rdap": rdap,
        "summary": {
            "subdomains_found": subdomain_count,
            "wayback_snapshots": snapshot_count,
            "registered": registered,
            "registrar": rdap.get("registrar", "") if rdap.get("enabled") else "",
            "first_seen": wayback.get("first_seen") if wayback.get("enabled") else None,
            "last_seen": wayback.get("last_seen") if wayback.get("enabled") else None,
        },
        "updated": utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/intel")
async def domain_intel(
    domain: str = Query(..., description="Domain to investigate (e.g. example.com)"),
    wayback_limit: int = Query(50, ge=1, le=200, description="Max Wayback snapshots"),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Combined domain intelligence: CT logs + Wayback + RDAP. Cached 1h."""
    if not _enabled():
        return _CONNECTOR.empty_payload("domain_intel disabled")

    domain = domain.strip().lower().lstrip("*.")
    if not domain or "." not in domain:
        return _CONNECTOR.empty_payload("invalid domain")

    if not refresh:
        cached = _domain_cache_get(domain)
        if cached:
            return cached

    try:
        result = await _gather_domain_intel(domain, wayback_limit=wayback_limit)
        result["count"] = (
            result["certs"].get("count", 0)
            + result["wayback"].get("count", 0)
            + (1 if result["rdap"].get("registered") else 0)
        )
        result["source"] = "crt.sh+wayback+rdap"
        result["stale"] = False
        result["error"] = None
        _domain_cache_set(domain, result)
        return result
    except Exception as e:
        return _CONNECTOR.empty_payload(str(e))


@router.get("/certs")
async def domain_certs(
    domain: str = Query(..., description="Domain to search in CT logs"),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Certificate Transparency log entries via crt.sh. Cached 1h."""
    if not _enabled():
        return _CONNECTOR.empty_payload("domain_intel disabled")

    domain = domain.strip().lower().lstrip("*.")
    if not domain or "." not in domain:
        return _CONNECTOR.empty_payload("invalid domain")

    cache_key = f"certs:{domain}"
    if not refresh:
        cached = _domain_cache_get(cache_key)
        if cached:
            return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            result = await _fetch_crt_sh(domain, client)
        result["domain"] = domain
        result["source"] = "crt.sh"
        result["stale"] = False
        _domain_cache_set(cache_key, result)
        return result
    except Exception as e:
        return _CONNECTOR.empty_payload(str(e))


@router.get("/wayback")
async def domain_wayback(
    domain: str = Query(..., description="Domain to search in Wayback"),
    limit: int = Query(50, ge=1, le=200, description="Max snapshots"),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """Wayback CDX historical snapshots. Cached 1h."""
    if not _enabled():
        return _CONNECTOR.empty_payload("domain_intel disabled")

    domain = domain.strip().lower().lstrip("*.")
    if not domain or "." not in domain:
        return _CONNECTOR.empty_payload("invalid domain")

    cache_key = f"wayback:{domain}:{limit}"
    if not refresh:
        cached = _domain_cache_get(cache_key)
        if cached:
            return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            result = await _fetch_wayback(domain, client, limit=limit)
        result["domain"] = domain
        result["source"] = "wayback.cdx"
        result["stale"] = False
        _domain_cache_set(cache_key, result)
        return result
    except Exception as e:
        return _CONNECTOR.empty_payload(str(e))


@router.get("/rdap")
async def domain_rdap(
    domain: str = Query(..., description="Domain to look up in RDAP"),
    refresh: bool = Query(False, description="Bypass cache"),
):
    """RDAP domain registration data. Cached 1h."""
    if not _enabled():
        return _CONNECTOR.empty_payload("domain_intel disabled")

    domain = domain.strip().lower().lstrip("*.")
    if not domain or "." not in domain:
        return _CONNECTOR.empty_payload("invalid domain")

    cache_key = f"rdap:{domain}"
    if not refresh:
        cached = _domain_cache_get(cache_key)
        if cached:
            return cached

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_UA) as client:
            result = await _fetch_rdap(domain, client)
        result["domain"] = domain
        result["source"] = "rdap.org"
        result["stale"] = False
        _domain_cache_set(cache_key, result)
        return result
    except Exception as e:
        return _CONNECTOR.empty_payload(str(e))
