"""Smithsonian GVP holocene volcanoes — WFS proxy (no key, avoids CORS)."""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/volcanoes", tags=["volcanoes"])

_UA = {"User-Agent": "WorldBase/1.0 (civic OSINT)"}
_WFS = (
    "https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeName=GVP-VOTW:Smithsonian_VOTW_Holocene_Volcanoes&outputFormat=json"
)
_CACHE: dict[str, tuple[float, dict]] = {}


@router.get("")
async def holocene_volcanoes(active_only: bool = False, limit: int = 400):
    """Holocene volcanoes worldwide. Cached 6h. active_only = eruption since 2020."""
    key = f"volc:{active_only}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached[0]) < 21600:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=60.0, headers=_UA) as client:
            r = await client.get(f"{_WFS}&count={min(limit, 800)}")
            r.raise_for_status()
            gj = r.json()
    except Exception as e:
        stale = _CACHE.get(key)
        if stale:
            out = stale[1].copy()
            out["stale"] = True
            return out
        return {"count": 0, "volcanoes": [], "error": str(e)}

    volcanoes = []
    for f in gj.get("features") or []:
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        lon, lat = coords[0], coords[1]
        if lat is None or lon is None:
            continue
        last = p.get("Last_Eruption_Year")
        try:
            last_y = int(last) if last not in (None, "", "Unknown") else None
        except (TypeError, ValueError):
            last_y = None
        evidence = (p.get("Evidence_Category") or "").lower()
        is_active = (last_y is not None and last_y >= 2020) or "observed" in evidence
        if active_only and not is_active:
            continue
        volcanoes.append(
            {
                "name": p.get("Volcano_Name"),
                "number": p.get("Volcano_Number"),
                "country": p.get("Country"),
                "type": p.get("Primary_Volcano_Type"),
                "last_eruption": last_y,
                "elevation_m": p.get("Elevation"),
                "evidence": p.get("Evidence_Category"),
                "active": is_active,
                "lat": float(lat),
                "lon": float(lon),
            }
        )

    out = {
        "count": len(volcanoes),
        "active_count": sum(1 for v in volcanoes if v.get("active")),
        "volcanoes": volcanoes[:limit],
        "source": "smithsonian_gvp",
        "cached_at": time.time(),
    }
    _CACHE[key] = (time.time(), out)
    return out
