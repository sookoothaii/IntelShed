"""ENTSO-E Transparency Platform — EU electricity data.

Day-ahead prices and generation by source per country.
Requires ENTSOE_SECURITY_TOKEN env var for live data.
Without token, returns demo data.

Docs: https://transparency.entsoe.eu/content/static_content/Static%20content/web%20api/Guide.html
"""

import os
import time
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/eu-energy", tags=["eu-energy"])

TOKEN = os.getenv("ENTSOE_SECURITY_TOKEN", "")
BASE_URL = "https://web-api.tp.entsoe.eu/api"

# EIC area codes for bidding zones
AREA_CODES: dict[str, str] = {
    "de": "10Y1001A1001A83F",
    "fr": "10YFR-RTE------C",
    "nl": "10YNL----------L",
    "at": "10YAT-APG------L",
    "pl": "10YPL-EGH------M",
    "es": "10YES-REE------0",
    "it": "10YIT-GRTN-----B",
    "se": "10YSE-1--------K",
    "dk": "10Y1001A1001A65H",
    "no": "10YNO-0--------C",
    "be": "10YBE----------2",
    "ch": "10YCH-SWISSGRIDX",
    "cz": "10YCZ-CEPS-----N",
    "fi": "10YFI-1--------U",
}

# DocumentType / process codes (ENTSO-E Transparency API)
DOC_PRICE = "A44"    # Price document
DOC_GEN = "A75"      # Actual generation per production type
PROC_REALISED = "A16"  # Realised (actual) values for generation
CONTRACT_DAY_AHEAD = "A01"  # Day-ahead market agreement for prices

NS_URI = "urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3"
_RESOLUTION_MINUTES = {"PT15M": 15, "PT30M": 30, "PT60M": 60}


def _ns(tag: str) -> str:
    return f"{{{NS_URI}}}{tag}"

_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 300  # 5 min


def _period_start_end() -> tuple[str, str]:
    """Return ENTSO-E periodStart/periodEnd strings (UTC, YYYYMMDDHHMM)."""
    now = datetime.now(timezone.utc)
    start = now.strftime("%Y%m%d%H%M")
    end = (now + timedelta(hours=24)).strftime("%Y%m%d%H%M")
    return start, end


def _parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _point_start_time(period_start: datetime | None, position: int, resolution: str) -> str | None:
    minutes = _RESOLUTION_MINUTES.get(resolution or "")
    if period_start is None or minutes is None or position < 1:
        return period_start.isoformat() if period_start else None
    return (period_start + timedelta(minutes=minutes * (position - 1))).isoformat()


def _normalize_prices_to_hourly(points: list[dict]) -> list[dict]:
    """Average sub-hourly ENTSO-E price slots into hourly buckets for the HUD."""
    if not points:
        return points
    if all(p.get("resolution") in (None, "PT60M") for p in points):
        return [
            {
                "position": idx + 1,
                "price_eur_mwh": p["price_eur_mwh"],
                "start_time": p.get("start_time"),
            }
            for idx, p in enumerate(sorted(points, key=lambda x: x.get("position", 0)))
        ]

    buckets: dict[str, list[float]] = {}
    for p in points:
        start = p.get("start_time")
        if not start:
            continue
        hour_key = start[:13]  # YYYY-MM-DDTHH
        buckets.setdefault(hour_key, []).append(p["price_eur_mwh"])

    hourly: list[dict] = []
    for idx, hour_key in enumerate(sorted(buckets)):
        vals = buckets[hour_key]
        hourly.append({
            "position": idx + 1,
            "price_eur_mwh": round(sum(vals) / len(vals), 2),
            "start_time": f"{hour_key}:00:00+00:00",
        })
    return hourly


def _parse_price_xml(xml_text: str) -> list[dict]:
    """Parse ENTSO-E price XML (PT15M/PT30M/PT60M) into hourly points."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    points: list[dict] = []
    for ts in root.findall(f".//{_ns('TimeSeries')}"):
        for period in ts.findall(_ns("Period")):
            resolution_el = period.find(_ns("resolution"))
            resolution = resolution_el.text if resolution_el is not None else "PT60M"
            if resolution not in _RESOLUTION_MINUTES:
                continue
            time_interval = period.find(_ns("timeInterval"))
            start_el = time_interval.find(_ns("start")) if time_interval is not None else None
            period_start = _parse_iso_utc(start_el.text if start_el is not None else None)
            for pt in period.findall(_ns("Point")):
                pos_el = pt.find(_ns("position"))
                price_el = pt.find(_ns("price.amount"))
                if pos_el is None or price_el is None:
                    continue
                position = int(pos_el.text)
                points.append({
                    "position": position,
                    "price_eur_mwh": round(float(price_el.text), 2),
                    "start_time": _point_start_time(period_start, position, resolution),
                    "resolution": resolution,
                })
    return _normalize_prices_to_hourly(points)


def _parse_generation_xml(xml_text: str) -> list[dict]:
    """Parse ENTSO-E generation XML into hourly points by source."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    points: list[dict] = []
    for ts in root.findall(f".//{_ns('TimeSeries')}"):
        psr_type_el = ts.find(f"{_ns('MktPSRType')}/{_ns('psrType')}")
        psr_type = psr_type_el.text if psr_type_el is not None else "unknown"
        for period in ts.findall(_ns("Period")):
            for pt in period.findall(_ns("Point")):
                pos_el = pt.find(_ns("position"))
                qty_el = pt.find(_ns("quantity"))
                if pos_el is not None and qty_el is not None:
                    points.append({
                        "position": int(pos_el.text),
                        "source": psr_type,
                        "mw": int(float(qty_el.text)),
                    })
    return points


_PSR_LABELS: dict[str, str] = {
    "B01": "Biomass", "B02": "Fossil Brown coal/Lignite", "B03": "Fossil Coal-derived gas",
    "B04": "Fossil Gas", "B05": "Fossil Hard coal", "B06": "Fossil Oil",
    "B07": "Fossil Oil shale", "B08": "Fossil Peat", "B09": "Geothermal",
    "B10": "Hydro Pumped Storage", "B11": "Hydro Run-of-river", "B12": "Hydro Water Reservoir",
    "B13": "Marine", "B14": "Nuclear", "B15": "Other renewable",
    "B16": "Solar", "B17": "Waste", "B18": "Wind Offshore", "B19": "Wind Onshore",
    "B20": "Other", "B21": "AC Link", "B22": "DC Link", "B23": "Substation",
    "B24": "Transformer",
}


def _demo_prices(country: str) -> list[dict]:
    """Return synthetic demo day-ahead prices."""
    now = datetime.now(timezone.utc)
    base = {"de": 85, "fr": 78, "nl": 82, "at": 88, "pl": 95, "es": 70, "it": 90, "se": 45, "dk": 50, "no": 40, "be": 80, "ch": 75, "cz": 92, "fi": 55}.get(country, 80)
    points = []
    for h in range(24):
        hour = (now + timedelta(hours=h)).hour
        # Peak/offpeak pattern
        mult = 1.3 if 8 <= hour <= 20 else 0.7
        noise = (hash(f"{country}{h}") % 20 - 10) / 10
        price = round(base * mult * (1 + noise * 0.1), 2)
        points.append({
            "position": h + 1,
            "price_eur_mwh": price,
            "start_time": (now + timedelta(hours=h)).isoformat(),
        })
    return points


def _demo_generation(country: str) -> list[dict]:
    """Return synthetic demo generation mix."""
    sources = ["B16", "B19", "B12", "B11", "B04", "B05", "B14", "B01"]
    points = []
    for h in range(24):
        for s in sources:
            mw = (hash(f"{country}{s}{h}") % 5000) + 500
            points.append({"position": h + 1, "source": s, "mw": mw})
    return points


@router.get("/price/{country}")
async def get_day_ahead_price(country: str):
    """Fetch day-ahead price for a country."""
    country = country.lower().strip()
    if country not in AREA_CODES:
        return {"error": f"Unknown country '{country}'", "available": sorted(AREA_CODES.keys())}

    cache_key = f"entsoe:price:{country}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < TTL:
        return cached[1]

    area = AREA_CODES[country]
    start, end = _period_start_end()

    if not TOKEN:
        result = {
            "country": country,
            "area_code": area,
            "demo_mode": True,
            "hint": "Set ENTSOE_SECURITY_TOKEN env var for live data. Get one free at https://transparency.entsoe.eu/",
            "prices": _demo_prices(country),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _CACHE[cache_key] = (time.time(), result)
        return result

    url = (
        f"{BASE_URL}?securityToken={TOKEN}&documentType={DOC_PRICE}"
        f"&contract_MarketAgreement.type={CONTRACT_DAY_AHEAD}"
        f"&in_Domain={area}&out_Domain={area}"
        f"&periodStart={start}&periodEnd={end}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            xml = r.text
    except Exception as exc:
        stale = _CACHE.get(cache_key)
        if stale:
            stale[1]["stale"] = True
            return stale[1]
        return {"error": f"ENTSO-E fetch failed: {exc}", "country": country}

    prices = _parse_price_xml(xml)
    if not prices:
        # Fallback to demo if XML parse yields nothing
        prices = _demo_prices(country)
        demo = True
    else:
        demo = False

    result = {
        "country": country,
        "area_code": area,
        "demo_mode": demo,
        "prices": prices,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _CACHE[cache_key] = (time.time(), result)
    return result


@router.get("/generation/{country}")
async def get_generation(country: str):
    """Fetch generation by source for a country."""
    country = country.lower().strip()
    if country not in AREA_CODES:
        return {"error": f"Unknown country '{country}'", "available": sorted(AREA_CODES.keys())}

    cache_key = f"entsoe:gen:{country}"
    cached = _CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < TTL:
        return cached[1]

    area = AREA_CODES[country]
    start, end = _period_start_end()

    if not TOKEN:
        points = _demo_generation(country)
        result = {
            "country": country,
            "area_code": area,
            "demo_mode": True,
            "hint": "Set ENTSOE_SECURITY_TOKEN env var for live data.",
            "generation": points,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _CACHE[cache_key] = (time.time(), result)
        return result

    url = (
        f"{BASE_URL}?securityToken={TOKEN}&documentType={DOC_GEN}"
        f"&processType={PROC_REALISED}"
        f"&in_Domain={area}&periodStart={start}&periodEnd={end}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            xml = r.text
    except Exception as exc:
        stale = _CACHE.get(cache_key)
        if stale:
            stale[1]["stale"] = True
            return stale[1]
        return {"error": f"ENTSO-E fetch failed: {exc}", "country": country}

    points = _parse_generation_xml(xml)
    if not points:
        points = _demo_generation(country)
        demo = True
    else:
        demo = False

    # Aggregate latest hour by source
    latest_pos = max((p["position"] for p in points), default=0)
    latest = [p for p in points if p["position"] == latest_pos]
    by_source = {}
    for p in latest:
        src = _PSR_LABELS.get(p["source"], p["source"])
        by_source[src] = p["mw"]

    result = {
        "country": country,
        "area_code": area,
        "demo_mode": demo,
        "generation_by_source": by_source,
        "total_mw": sum(by_source.values()),
        "hourly_points": points,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _CACHE[cache_key] = (time.time(), result)
    return result


@router.get("/countries")
def list_countries():
    return {"countries": [{"id": k, "area_code": v} for k, v in AREA_CODES.items()]}
