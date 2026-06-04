"""CVE / KEV feed — CISA Known Exploited Vulnerabilities (no API key)."""

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["cve"])

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_CACHE: dict = {"data": None, "ts": 0.0}
_TTL = 3600.0


@router.get("/cve")
async def get_cve_kev(limit: int = 30):
    """Recent CISA KEV entries (actively exploited CVEs). Cached 1h."""
    import time

    now = time.time()
    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL:
        data = _CACHE["data"]
    else:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(
                KEV_URL,
                headers={"User-Agent": "WorldBase/1.0 (research dashboard)"},
            )
            r.raise_for_status()
            data = r.json()
        _CACHE["data"] = data
        _CACHE["ts"] = now

    vulns = data.get("vulnerabilities", []) or []
    items = []
    for v in vulns[: max(1, min(limit, 100))]:
        items.append({
            "cve_id": v.get("cveID"),
            "vendor": v.get("vendorProject"),
            "product": v.get("product"),
            "vulnerability": v.get("vulnerabilityName"),
            "date_added": v.get("dateAdded"),
            "due_date": v.get("dueDate"),
            "ransomware": v.get("knownRansomwareCampaignUse", "Unknown"),
            "notes": (v.get("shortDescription") or "")[:240],
        })
    return {
        "count": len(items),
        "catalog_version": data.get("catalogVersion"),
        "date_released": data.get("dateReleased"),
        "updated": datetime.now(timezone.utc).isoformat(),
        "vulnerabilities": items,
    }
