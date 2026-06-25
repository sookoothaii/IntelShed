"""WorldBase — OSINT tool proxy for AI chat.

The AI chat can call these tools through the backend (no direct Pi exposure).
All tools are passive reconnaissance only — no active scanning, no exploitation.
No API keys required where possible.
"""

import os
import ipaddress
import socket
import re
import hashlib
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Request, Depends
from auth.security import verify_api_key
from middleware.rate_limit import rate_limit_general

import entity_store

router = APIRouter(prefix="/api/osint", tags=["osint-tools"])

_UA = {"User-Agent": "WorldBase-OSINT/1.0 (research only)"}
_HIBP_API_KEY = os.getenv("HIBP_API_KEY", "").strip()


def _is_private_or_reserved(ip_str: str) -> bool:
    """Check if an IP is private, loopback, link-local, or reserved."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        return True


def _parse_crt_sh_names(rows: list, domain: str, limit: int = 40) -> list[str]:
    """Extract unique hostnames from crt.sh JSON response."""
    names: set[str] = set()
    domain = domain.lower().strip()
    for row in rows[:300]:
        if not isinstance(row, dict):
            continue
        raw = row.get("name_value") or row.get("common_name") or ""
        for part in str(raw).split("\n"):
            host = part.strip().lower().lstrip("*.")
            if not host:
                continue
            if host == domain or host.endswith(f".{domain}"):
                names.add(host)
    return sorted(names)[:limit]


async def _fetch_crt_sh_subdomains(domain: str) -> tuple[list[str], str | None]:
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
            r = await client.get(
                "https://crt.sh/",
                params={"q": f"%.{domain}", "output": "json"},
            )
            if r.status_code != 200:
                return [], f"crt.sh HTTP {r.status_code}"
            rows = r.json()
            if not isinstance(rows, list):
                return [], "crt.sh invalid response"
            return _parse_crt_sh_names(rows, domain), None
    except Exception as e:
        return [], str(e)


async def _hibp_breaches(email: str) -> tuple[list[dict] | None, str | None]:
    if not _HIBP_API_KEY:
        return None, "HIBP_API_KEY not set"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers={
                    "hibp-api-key": _HIBP_API_KEY,
                    "User-Agent": "WorldBase-OSINT/1.0",
                },
                params={"truncateResponse": "true"},
            )
            if r.status_code == 404:
                return [], None
            if r.status_code == 401:
                return None, "HIBP API key invalid"
            if r.status_code != 200:
                return None, f"HIBP HTTP {r.status_code}"
            data = r.json()
            return data if isinstance(data, list) else [], None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# IP geolocation + basic info (ip-api.com — free, no key, 45 req/min)
# ---------------------------------------------------------------------------
@router.get("/ip/{ip}")
@rate_limit_general()
async def ip_lookup(request: Request, ip: str, api_key: str = Depends(verify_api_key)):
    """Geolocate an IP address. No key. Rate-limited."""
    try:
        # Validate IP
        socket.inet_aton(ip)
    except OSError:
        return {"error": "Invalid IPv4 address"}
    if _is_private_or_reserved(ip):
        return {"error": "Private or reserved IP addresses are not allowed"}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,zip,lat,lon,isp,org,as,mobile,proxy,hosting"
            )
            d = r.json()
        if d.get("status") != "success":
            return {"error": d.get("message", "lookup failed")}
        return {
            "ip": ip,
            "country": d.get("country"),
            "region": d.get("regionName"),
            "city": d.get("city"),
            "zip": d.get("zip"),
            "lat": d.get("lat"),
            "lon": d.get("lon"),
            "isp": d.get("isp"),
            "org": d.get("org"),
            "asn": d.get("as"),
            "mobile": d.get("mobile"),
            "proxy": d.get("proxy"),
            "hosting": d.get("hosting"),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Domain WHOIS (whoisjsonapi.com — free tier, no key required for basic)
# Fallback: simple DNS resolution
# ---------------------------------------------------------------------------
@router.get("/domain/{domain}")
@rate_limit_general()
async def domain_lookup(
    request: Request, domain: str, api_key: str = Depends(verify_api_key)
):
    """Basic domain info: DNS resolution + IP. No key."""
    # Sanitize domain
    domain = re.sub(r"[^a-zA-Z0-9.-]", "", domain).lower()
    if not domain or "." not in domain:
        return {"error": "Invalid domain"}
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "A")
        ips = [str(r) for r in answers]
    except Exception:
        ips = []
    # Block private/resolved IPs to prevent SSRF
    ips = [ip for ip in ips if not _is_private_or_reserved(ip)]
    try:
        answers = dns.resolver.resolve(domain, "MX")
        mx = [str(r.exchange) for r in answers]
    except Exception:
        mx = []
    try:
        import socket

        host_ip = socket.gethostbyname(domain)
        if _is_private_or_reserved(host_ip):
            host_ip = None
    except Exception:
        host_ip = None
    cert_names, cert_error = await _fetch_crt_sh_subdomains(domain)
    return {
        "domain": domain,
        "resolved_ips": ips,
        "mx_records": mx,
        "host_ip": host_ip,
        "cert_names": cert_names,
        "cert_count": len(cert_names),
        "cert_source": "crt.sh" if cert_names or not cert_error else None,
        "cert_error": cert_error if not cert_names else None,
        "crt_sh_url": f"https://crt.sh/?q={domain}",
    }


# ---------------------------------------------------------------------------
# Username reconnaissance (simple: check if username exists on platforms)
# ---------------------------------------------------------------------------
@router.get("/username/{username}")
@rate_limit_general()
async def username_lookup(
    request: Request, username: str, api_key: str = Depends(verify_api_key)
):
    """Check username availability on major platforms. No key. Passive only."""
    username = re.sub(r"[^a-zA-Z0-9_.-]", "", username)
    if not username:
        return {"error": "Invalid username"}
    results = {}
    async with httpx.AsyncClient(timeout=8.0, headers=_UA) as client:
        # GitHub
        try:
            r = await client.get(f"https://api.github.com/users/{username}")
            results["github"] = {
                "exists": r.status_code == 200,
                "url": f"https://github.com/{username}",
            }
        except Exception:
            results["github"] = {"exists": None}
        # Reddit (check user profile)
        try:
            r = await client.get(
                f"https://www.reddit.com/user/{username}/about.json",
                headers={**_UA, "Accept": "application/json"},
            )
            results["reddit"] = {
                "exists": r.status_code == 200,
                "url": f"https://reddit.com/u/{username}",
            }
        except Exception:
            results["reddit"] = {"exists": None}
    return {"username": username, "platforms": results}


# ---------------------------------------------------------------------------
# Email reputation (simple MX check + disposable domain check)
# ---------------------------------------------------------------------------
DISPOSABLE_DOMAINS = {
    "tempmail.com",
    "10minutemail.com",
    "guerrillamail.com",
    "mailinator.com",
    "throwawaymail.com",
    "yopmail.com",
    "getairmail.com",
    "sharklasers.com",
}


@router.get("/email/{email}")
@rate_limit_general()
async def email_check(
    request: Request, email: str, api_key: str = Depends(verify_api_key)
):
    """Basic email validation + disposable domain detection. No key."""
    email = email.lower().strip()
    if "@" not in email:
        return {"error": "Invalid email"}
    domain = email.split("@")[1]
    is_disposable = domain in DISPOSABLE_DOMAINS
    # MX check
    has_mx = False
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
        has_mx = len(answers) > 0
    except Exception:
        pass
    breaches, breach_error = await _hibp_breaches(email)
    breach_names = [
        b.get("Name") for b in (breaches or []) if isinstance(b, dict) and b.get("Name")
    ]
    return {
        "email": email,
        "domain": domain,
        "valid_format": True,
        "has_mx": has_mx,
        "disposable": is_disposable,
        "suspicious": is_disposable or not has_mx,
        "breach_check_url": f"https://haveibeenpwned.com/account/{email}",
        "breaches": breach_names if breaches is not None else None,
        "breach_count": len(breach_names) if breaches is not None else None,
        "breach_source": "hibp" if breaches is not None and not breach_error else None,
        "breach_error": breach_error if breaches is None and _HIBP_API_KEY else None,
    }


# ---------------------------------------------------------------------------
# Geo lookup for EXIF-like coordinates (reverse geocoding)
# ---------------------------------------------------------------------------
@router.get("/reverse-geocode")
@rate_limit_general()
async def reverse_geocode(
    request: Request, lat: float, lon: float, api_key: str = Depends(verify_api_key)
):
    """Reverse geocode coordinates to location name. No key."""
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
            r = await client.get(
                f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en"
            )
            d = r.json()
        return {
            "lat": lat,
            "lon": lon,
            "locality": d.get("locality"),
            "city": d.get("city"),
            "region": d.get("principalSubdivision"),
            "country": d.get("countryName"),
            "country_code": d.get("countryCode"),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Flowsint / investigation → globe pins (client merges into localStorage)
# ---------------------------------------------------------------------------
@router.post("/pins/import")
@rate_limit_general()
async def import_pins(
    request: Request, payload: dict, api_key: str = Depends(verify_api_key)
):
    """Normalize Flowsint or manual geo entities into OsintPin-shaped objects.

    Body: { "pins": [...], "investigation_id": "optional-default" }
    Each pin: lat, lon, label|title, type|pin_type, query?, tool?, investigation_id?, lines?
    """
    raw_pins = payload.get("pins") or payload.get("entities") or []
    if isinstance(payload, dict) and payload.get("lat") is not None and not raw_pins:
        raw_pins = [payload]
    default_inv = (
        payload.get("investigation_id") or payload.get("investigationId") or ""
    ).strip()
    out = []

    for p in raw_pins:
        if not isinstance(p, dict):
            continue
        try:
            lat = float(p.get("lat"))
            lon = float(p.get("lon"))
        except (TypeError, ValueError):
            continue
        label = (p.get("label") or p.get("title") or p.get("name") or "OSINT").strip()
        pin_type = (p.get("type") or p.get("pin_type") or "flowsint").strip()
        query = (p.get("query") or label or f"{lat},{lon}").strip()
        inv = (
            p.get("investigation_id") or p.get("investigationId") or default_inv
        ).strip()
        tool = (p.get("tool") or "flowsint").strip()
        lines = p.get("lines") or []
        if isinstance(lines, str):
            lines = [lines]
        if not lines and inv:
            lines.append(f"Investigation: {inv}")
        if pin_type:
            lines.insert(0, f"Type: {pin_type}")

        pin_id = p.get("id")
        if not pin_id:
            h = hashlib.sha256(f"{inv}:{query}:{lat}:{lon}".encode()).hexdigest()[:12]
            pin_id = f"flowsint:{h}"

        eid = entity_store.entity_id_for_pin(tool, query)
        entity_store.upsert_entity(
            eid,
            pin_type or "osint",
            label=label,
            lat=lat,
            lon=lon,
            source_feed="flowsint" if tool == "flowsint" else tool,
            external_id=pin_id,
            meta={"investigation_id": inv, "pin_type": pin_type},
        )
        if inv:
            inv_eid = f"investigation:{inv}"
            entity_store.upsert_entity(
                inv_eid, "investigation", label=f"Investigation {inv}"
            )
            entity_store.link_entities(inv_eid, eid, "contains")

        out.append(
            {
                "id": pin_id,
                "tool": tool,
                "query": query,
                "lat": lat,
                "lon": lon,
                "title": label,
                "lines": lines[:12],
                "pinType": pin_type,
                "investigationId": inv or None,
                "entityId": eid,
                "ts": int(datetime.now(timezone.utc).timestamp() * 1000),
            }
        )

    return {"count": len(out), "pins": out}
