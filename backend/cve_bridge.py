"""CVE / KEV feed — CISA Known Exploited Vulnerabilities (no API key)."""

import time

import httpx
from fastapi import APIRouter

from feeds.envelope import FeedEnvelope
from feeds.runner import FeedConnector

router = APIRouter(prefix="/api", tags=["cve"])

KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
_TTL = 3600.0
_CONNECTOR = FeedConnector("cve", ttl_sec=_TTL, default_source="cisa.gov/kev")
_RAW: dict = {"data": None, "ts": 0.0}


def _map_vulnerabilities(data: dict, limit: int) -> list[dict]:
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
    return items


@router.get("/cve")
async def get_cve_kev(limit: int = 30):
    """Recent CISA KEV entries (actively exploited CVEs). Cached 1h."""
    now = time.time()
    upstream_err = None
    stale = False

    if _RAW["data"] is not None and (now - _RAW["ts"]) < _TTL:
        data = _RAW["data"]
    else:
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                r = await client.get(
                    KEV_URL,
                    headers={"User-Agent": "WorldBase/1.0 (research dashboard)"},
                )
                r.raise_for_status()
                data = r.json()
            _RAW["data"] = data
            _RAW["ts"] = now
        except Exception as e:
            upstream_err = str(e)
            if _RAW["data"] is not None:
                data = _RAW["data"]
                stale = True
            else:
                stale_row = _CONNECTOR.read_disk()
                if stale_row and stale_row.get("vulnerabilities") is not None:
                    return {**stale_row, "stale": True, "error": upstream_err}
                return _CONNECTOR.build(
                    FeedEnvelope(count=0, stale=False, error=upstream_err),
                    persist=False,
                    vulnerabilities=[],
                )

    items = _map_vulnerabilities(data, limit)
    return _CONNECTOR.build(
        FeedEnvelope(
            count=len(items),
            stale=stale,
            error=upstream_err,
        ),
        persist=not stale and not upstream_err,
        catalog_version=data.get("catalogVersion"),
        date_released=data.get("dateReleased"),
        vulnerabilities=items,
    )
