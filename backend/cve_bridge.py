"""CVE / KEV feed — CISA Known Exploited Vulnerabilities (no API key)."""

import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

import feed_registry

router = APIRouter(prefix="/api", tags=["cve"])

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_CACHE: dict = {"data": None, "ts": 0.0}
_TTL = 3600.0


@router.get("/cve")
async def get_cve_kev(limit: int = 30):
    """Recent CISA KEV entries (actively exploited CVEs). Cached 1h."""
    now = time.time()
    upstream_err = None
    stale = False

    if _CACHE["data"] is not None and (now - _CACHE["ts"]) < _TTL:
        data = _CACHE["data"]
    else:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(
                    KEV_URL,
                    headers={"User-Agent": "WorldBase/1.0 (research dashboard)"},
                )
                r.raise_for_status()
                data = r.json()
            _CACHE["data"] = data
            _CACHE["ts"] = now
        except Exception as e:
            upstream_err = str(e)
            if _CACHE["data"] is not None:
                data = _CACHE["data"]
                stale = True
            else:
                stale_row = feed_registry.read("cve")
                if stale_row and stale_row.get("vulnerabilities") is not None:
                    return {**stale_row, "stale": True, "error": upstream_err}
                return {
                    "count": 0,
                    "vulnerabilities": [],
                    "error": upstream_err,
                    "stale": False,
                    "source": "cisa.gov/kev",
                    "updated": datetime.now(timezone.utc).isoformat(),
                }

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
    out = {
        "count": len(items),
        "catalog_version": data.get("catalogVersion"),
        "date_released": data.get("dateReleased"),
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "cisa.gov/kev",
        "stale": stale,
        "error": upstream_err,
        "vulnerabilities": items,
    }
    if not stale and not upstream_err:
        feed_registry.write_auto("cve", out)
    return out
