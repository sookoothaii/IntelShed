"""Security-advisor style 24h digest — operator home region + world pulse.

Extracted from operator_briefing.py (Phase 2). Classifies feed items
into LOCAL (Thailand), REGIONAL (ASEAN / near), and GLOBAL buckets before
the LLM writes the narrative protocol.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from stac_bridge import REGION_PRESETS
from gdelt_bridge import filter_local_pulse_articles
from newsdata_bridge import is_sports_content, is_tourism_promo_content

from config import get_config

_cfg = get_config
OPERATOR_REGION = _cfg().operator_region
BRIEFING_LANG = _cfg().briefing_lang


def _gdelt_local_slots() -> int:
    try:
        return max(
            0,
            min(3, int(os.getenv("WORLDBASE_BRIEFING_GDELT_LOCAL_SLOTS", "2") or "2")),
        )
    except ValueError:
        return 2


def _newsdata_slots() -> int:
    try:
        return max(
            0, min(3, int(os.getenv("WORLDBASE_BRIEFING_NEWSDATA_SLOTS", "2") or "2"))
        )
    except ValueError:
        return 2


def _is_newsdata_item(item: dict) -> bool:
    return "newsdata" in (item.get("sources") or [])


def _watch_max_items() -> int:
    try:
        return max(
            1, min(8, int(os.getenv("WORLDBASE_BRIEFING_WATCH_MAX", "5") or "5"))
        )
    except ValueError:
        return 5


def _watch_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(f"{prefix}:{key}".encode("utf-8")).hexdigest()
    return digest[:12]


def _cell_id(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    return f"{float(lat):.2f},{float(lon):.2f}"


def _watch_item(
    *,
    prefix: str,
    key: str,
    title: str,
    horizon_h: int,
    confidence: float,
    sources: list[str],
    bucket: str = "global",
    cell_id: str | None = None,
    delta_score: float | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": _watch_id(prefix, key),
        "prefix": prefix,
        "title": title[:200],
        "horizon_h": max(24, min(72, int(horizon_h))),
        "confidence": round(max(0.0, min(1.0, confidence)), 3),
        "sources": sources[:6],
        "bucket": bucket,
        "cell_id": cell_id,
    }
    if cell_id and "," in cell_id:
        try:
            lat_s, lon_s = cell_id.split(",", 1)
            item["lat"] = float(lat_s)
            item["lon"] = float(lon_s)
        except (TypeError, ValueError):
            pass
    if delta_score is not None:
        item["delta_score"] = round(float(delta_score), 4)
    return item


def enrich_watch_items_coords(
    watch_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Add lat/lon from cell_id for cached briefings stored before coord denorm."""
    if not watch_items:
        return []
    out: list[dict[str, Any]] = []
    for item in watch_items:
        row = dict(item)
        if row.get("lat") is None and row.get("cell_id") and "," in str(row["cell_id"]):
            try:
                lat_s, lon_s = str(row["cell_id"]).split(",", 1)
                row["lat"] = float(lat_s)
                row["lon"] = float(lon_s)
            except (TypeError, ValueError):
                pass
        out.append(row)
    return out


def _resolve_lang(lang: str | None) -> str:
    """Override env BRIEFING_LANG when caller passes 'de' or 'en' explicitly."""
    if not lang:
        return BRIEFING_LANG
    norm = str(lang).strip().lower()
    if norm.startswith("de"):
        return "de"
    if norm.startswith("en"):
        return "en"
    return BRIEFING_LANG


# Wider ASEAN / Southeast Asia bbox when operator home is Thailand
_ASEAN_BBOX = [92.0, -8.0, 112.0, 24.0]

# West Asia / Iran / Hormuz / Persian Gulf — always included in REGION bucket
_WEST_ASIA_BBOX = [44.0, 12.0, 63.0, 40.0]
_ASEAN_COUNTRY_CODES = {
    "TH",
    "MM",
    "LA",
    "KH",
    "VN",
    "MY",
    "ID",
    "SG",
    "PH",
    "BN",
}

_LOCAL_KEYWORDS = (
    "thailand",
    "thai",
    "bangkok",
    "phuket",
    "chiang mai",
    "pattaya",
    "andaman",
    "gulf of thailand",
    "mekong",
    "isaan",
    "krabi",
)
_REGION_KEYWORDS = (
    "myanmar",
    "burma",
    "cambodia",
    "laos",
    "vietnam",
    "viet nam",
    "malaysia",
    "singapore",
    "indonesia",
    "philippines",
    "asean",
    "south china sea",
    "andaman",
    "mekong",
    "bay of bengal",
    # West Asia / Iran / Hormuz
    "iran",
    "tehran",
    "strait of hormuz",
    "hormuz",
    "persian gulf",
    "arabian gulf",
    "gulf of oman",
    "israel",
    "lebanon",
    "syria",
    "iraq",
    "saudi arabia",
    "yemen",
    "jordan",
    "uae",
    "dubai",
    "abu dhabi",
    "qatar",
    "kuwait",
    "bahrain",
    "oman",
    "gaza",
    "hezbollah",
    "houthi",
    "bandar",
    "bushehr",
    "israel",
    "idf",
    "irgc",
)

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _region_bbox(region: str) -> list[float] | None:
    preset = REGION_PRESETS.get(region)
    if not preset:
        return None
    return list(preset["bbox"])


def _region_label(region: str) -> str:
    preset = REGION_PRESETS.get(region)
    if preset:
        return str(preset.get("label") or region)
    return region.replace("_", " ").title()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def _in_bbox(lat: float, lon: float, bbox: list[float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


def _text_bucket(text: str) -> str | None:
    low = (text or "").lower()
    if any(k in low for k in _LOCAL_KEYWORDS):
        return "local"
    if any(k in low for k in _REGION_KEYWORDS):
        return "regional"
    return None


def classify_item(
    lat: float | None,
    lon: float | None,
    text: str,
    local_bbox: list[float] | None,
    regional_bbox: list[float] | None,
    extra_regional_bboxes: list[list[float]] | None = None,
) -> str:
    """local | regional | global"""
    if (
        lat is not None
        and lon is not None
        and local_bbox
        and _in_bbox(lat, lon, local_bbox)
    ):
        return "local"
    text_hit = _text_bucket(text)
    if text_hit == "local":
        return "local"
    if (
        lat is not None
        and lon is not None
        and regional_bbox
        and _in_bbox(lat, lon, regional_bbox)
    ):
        return "regional"
    # Check extra regional bboxes (e.g. West Asia when operator is in Thailand)
    if extra_regional_bboxes:
        for bbox in extra_regional_bboxes:
            if lat is not None and lon is not None and _in_bbox(lat, lon, bbox):
                return "regional"
    if text_hit == "regional":
        return "regional"
    if lat is not None and lon is not None and local_bbox:
        # Thailand center ~ Bangkok
        west, south, east, north = local_bbox
        center_lat = (south + north) / 2
        center_lon = (west + east) / 2
        dist = haversine_km(lat, lon, center_lat, center_lon)
        if dist <= 250:
            return "local"
        if dist <= 1200:
            return "regional"
    return "global"


def _line(
    severity: str,
    text: str,
    bucket: str,
    *,
    sources: list[str] | None = None,
    lat: float | None = None,
    lon: float | None = None,
    observed_at: str | float | int | None = None,
) -> dict:
    from digest_timestamps import apply_observed_at

    body, iso = apply_observed_at(text, observed_at)
    return {
        "severity": severity,
        "text": body,
        "bucket": bucket,
        "sources": list(sources or []),
        "lat": lat,
        "lon": lon,
        "observed_at": iso,
    }


def _pm25_severity(pm25: float) -> str:
    if pm25 >= 75:
        return "high"
    if pm25 >= 35:
        return "medium"
    return "low"


def _collect_digest_items(snap: dict, alerts: list[dict]) -> list[dict]:
    local_bbox = _region_bbox(OPERATOR_REGION)
    regional_bbox = _ASEAN_BBOX if OPERATOR_REGION == "thailand" else local_bbox
    if regional_bbox is None and local_bbox:
        # Expand local bbox ~3° for regional fallback
        w, s, e, n = local_bbox
        regional_bbox = [w - 8, s - 6, e + 8, n + 4]
    _extra = [_WEST_ASIA_BBOX]

    items: list[dict] = []
    from digest_timestamps import feed_block_updated_at

    aq_updated = feed_block_updated_at(snap.get("airquality"))
    cams_updated = feed_block_updated_at(snap.get("cams_haze"))
    humanitarian_updated = feed_block_updated_at(snap.get("humanitarian"))

    for city in (snap.get("airquality", {}) or {}).get("cities") or []:
        pm25 = city.get("pm25")
        if pm25 is None:
            continue
        name = city.get("city") or "City"
        lat, lon = city.get("lat"), city.get("lon")
        bucket = classify_item(
            lat, lon, name, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                _pm25_severity(float(pm25)),
                f"Air quality {name}: PM2.5 {pm25} µg/m³",
                bucket,
                sources=["airquality"],
                lat=lat,
                lon=lon,
                observed_at=aq_updated,
            )
        )

    for row in (snap.get("cams_haze", {}) or {}).get("cities") or []:
        name = row.get("city") or "City"
        lat, lon = row.get("lat"), row.get("lon")
        pm25 = row.get("pm25")
        dust = row.get("dust")
        aod = row.get("aerosol_optical_depth")
        parts = []
        if pm25 is not None:
            parts.append(f"PM2.5 {pm25} µg/m³")
        if dust is not None:
            parts.append(f"dust {dust} µg/m³")
        if aod is not None:
            parts.append(f"AOD {aod}")
        if not parts:
            continue
        bucket = classify_item(
            lat, lon, name, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        sev = (
            row.get("severity") or _pm25_severity(float(pm25))
            if pm25 is not None
            else "low"
        )
        items.append(
            _line(
                sev,
                f"CAMS haze {name}: " + ", ".join(parts),
                bucket,
                sources=["cams_haze"],
                lat=lat,
                lon=lon,
                observed_at=cams_updated,
            )
        )

    for ds in (snap.get("humanitarian", {}) or {}).get("datasets") or []:
        title = ds.get("title") or "Humanitarian dataset"
        org = ds.get("organization") or ""
        text = f"Humanitarian data: {title[:90]}"
        if org:
            text += f" ({org})"
        bucket = _text_bucket(title) or "regional"
        items.append(
            _line(
                "medium",
                text,
                bucket,
                sources=["humanitarian"],
                observed_at=ds.get("modified") or humanitarian_updated,
            )
        )

    thai_vessels = [
        v
        for v in (snap.get("maritime", {}) or {}).get("vessels") or []
        if (v.get("region") or "")
        in ("malacca", "laem_chabang", "bangkok_port", "phuket", "singapore")
    ]
    if thai_vessels:
        by_region: dict[str, int] = {}
        for v in thai_vessels:
            reg = v.get("region") or "unknown"
            by_region[reg] = by_region.get(reg, 0) + 1
        summary = ", ".join(f"{k}={n}" for k, n in sorted(by_region.items()))
        items.append(
            _line(
                "low",
                f"Maritime traffic (Thailand corridor): {len(thai_vessels)} vessels ({summary})",
                "local"
                if any(
                    r in by_region for r in ("laem_chabang", "bangkok_port", "phuket")
                )
                else "regional",
                sources=["maritime"],
            )
        )

    local_pulse = snap.get("gdelt_pulse_local", {}) or {}
    for art in filter_local_pulse_articles(local_pulse.get("articles"))[:10]:
        title = art.get("title") or art.get("url") or "Headline"
        if is_sports_content(title=title, description=art.get("description") or ""):
            continue
        if is_tourism_promo_content(
            title=title, description=art.get("description") or ""
        ):
            continue
        items.append(
            _line(
                "low",
                f"Local news: {title[:120]}",
                "local",
                sources=["gdelt_pulse_local"],
                observed_at=art.get("seendate"),
            )
        )

    # West Asia / Iran / Hormuz pulse articles — always regional
    west_asia_pulse = snap.get("gdelt_pulse_west_asia", {}) or {}
    for art in filter_local_pulse_articles(west_asia_pulse.get("articles"))[:8]:
        title = art.get("title") or art.get("url") or "West Asia headline"
        if is_sports_content(title=title, description=art.get("description") or ""):
            continue
        items.append(
            _line(
                "medium",
                f"West Asia: {title[:120]}",
                "regional",
                sources=["gdelt_pulse_west_asia"],
                observed_at=art.get("seendate"),
            )
        )

    newsdata = snap.get("newsdata") or {}
    if newsdata.get("configured") is not False:
        for art in (newsdata.get("articles") or [])[:5]:
            title = art.get("title") or "Headline"
            if is_sports_content(
                title=title,
                description=art.get("description") or "",
                categories=art.get("category"),
            ):
                continue
            if is_tourism_promo_content(
                title=title,
                description=art.get("description") or "",
            ):
                continue
            desc = art.get("description") or ""
            bucket = _text_bucket(f"{title} {desc}") or "global"
            items.append(
                _line(
                    "low",
                    f"News: {title[:120]}",
                    bucket,
                    sources=["newsdata"],
                    observed_at=art.get("pubDate"),
                )
            )

    ransomware_digest = snap.get("ransomware_digest") or {}
    if ransomware_digest.get("enabled"):
        for line in (ransomware_digest.get("lines") or [])[:5]:
            country = line.get("country", "Unknown")
            bucket = "global"
            if country in _ASEAN_COUNTRY_CODES or country == "TH":
                bucket = "regional"
            if country == "TH":
                bucket = "local"
            items.append(
                _line(
                    line.get("severity", "high"),
                    line.get("text", ""),
                    bucket,
                    sources=["darkweb_ransomware"],
                )
            )

    breach_digest = snap.get("breach_digest") or {}
    if breach_digest.get("enabled"):
        for line in (breach_digest.get("lines") or [])[:5]:
            items.append(
                _line(
                    line.get("severity", "high"),
                    line.get("text", ""),
                    "global",
                    sources=line.get("sources", ["hibp"]),
                )
            )

    maritime_anomaly_digest = snap.get("maritime_anomaly_digest") or {}
    if maritime_anomaly_digest.get("enabled"):
        for line in (maritime_anomaly_digest.get("lines") or [])[:5]:
            items.append(
                _line(
                    line.get("severity", "medium"),
                    line.get("text", ""),
                    line.get("bucket", "global"),
                    sources=["maritime_trajectory"],
                )
            )

    anomaly_digest = snap.get("anomaly_digest") or {}
    if anomaly_digest.get("enabled"):
        for line in (anomaly_digest.get("lines") or [])[:5]:
            items.append(
                _line(
                    line.get("severity", "medium"),
                    line.get("text", ""),
                    "global",
                    sources=["anomaly_detector"],
                )
            )

    for row in (snap.get("gdelt_geo_local", {}) or {}).get("events", [])[:12]:
        name = row.get("name") or "GDELT signal"
        lat, lon = row.get("lat"), row.get("lon")
        bucket = classify_item(
            lat, lon, str(name), local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "medium",
                f"Regional media heat: {str(name)[:100]}",
                bucket,
                sources=["gdelt_geo_local"],
                lat=lat,
                lon=lon,
            )
        )

    # West Asia / Iran / Hormuz geo events — always regional
    for row in (snap.get("gdelt_geo_west_asia", {}) or {}).get("events", [])[:12]:
        name = row.get("name") or "West Asia signal"
        lat, lon = row.get("lat"), row.get("lon")
        items.append(
            _line(
                "medium",
                f"West Asia media heat: {str(name)[:100]}",
                "regional",
                sources=["gdelt_geo_west_asia"],
                lat=lat,
                lon=lon,
            )
        )

    for q in (snap.get("earthquakes", {}) or {}).get("earthquakes", [])[:40]:
        place = q.get("place") or "Earthquake"
        mag = q.get("mag") or q.get("magnitude")
        lat, lon = q.get("lat"), q.get("lon")
        text = f"M{mag} — {place}"
        bucket = classify_item(
            lat, lon, text, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        sev = "high" if (mag or 0) >= 6 else "medium" if (mag or 0) >= 5 else "low"
        items.append(
            _line(
                sev,
                text,
                bucket,
                sources=["earthquakes"],
                lat=lat,
                lon=lon,
                observed_at=q.get("time") or q.get("updated"),
            )
        )

    for ev in (snap.get("events", {}) or {}).get("events", [])[:25]:
        title = ev.get("title") or ev.get("category") or "Event"
        lat, lon = ev.get("lat"), ev.get("lon")
        bucket = classify_item(
            lat, lon, title, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "low",
                f"{ev.get('category', 'EVENT')}: {title}",
                bucket,
                sources=["events"],
                lat=lat,
                lon=lon,
            )
        )

    for a in (snap.get("gdacs", {}) or {}).get("alerts", [])[:15]:
        title = a.get("title") or "GDACS alert"
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(
            lat, lon, title, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "medium",
                title,
                bucket,
                sources=["gdacs"],
                lat=lat,
                lon=lon,
                observed_at=a.get("published"),
            )
        )

    for h in (snap.get("hazards", {}) or {}).get("alerts", [])[:20]:
        label = h.get("event") or h.get("headline") or "Hazard"
        lat, lon = h.get("lat"), h.get("lon")
        bucket = classify_item(
            lat, lon, label, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        sev = (h.get("severity") or "").lower()
        severity = (
            "high" if "extreme" in sev else "medium" if "severe" in sev else "low"
        )
        if bucket == "local" and severity == "low":
            severity = "medium"
        items.append(
            _line(severity, label, bucket, sources=["hazards"], lat=lat, lon=lon)
        )

    for g in (snap.get("geopolitics", {}) or {}).get("items", [])[:15]:
        name = g.get("name") or g.get("title") or "Crisis"
        lat, lon = g.get("lat"), g.get("lon")
        bucket = classify_item(
            lat, lon, name, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "medium",
                f"Crisis: {name}",
                bucket,
                sources=["geopolitics"],
                lat=lat,
                lon=lon,
            )
        )

    for row in (snap.get("gdelt_geo", {}) or {}).get("events", [])[:20]:
        name = row.get("name") or "GDELT signal"
        lat, lon = row.get("lat"), row.get("lon")
        bucket = classify_item(
            lat, lon, str(name), local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "low",
                f"Media heat: {str(name)[:100]}",
                bucket,
                sources=["gdelt_geo"],
                lat=lat,
                lon=lon,
            )
        )

    pulse = snap.get("gdelt_pulse", {}) or {}
    seen_titles: set[str] = {
        (a.get("title") or "")[:80].lower() for a in (local_pulse.get("articles") or [])
    }
    for art in (pulse.get("articles") or [])[:12]:
        title = art.get("title") or art.get("url") or "Headline"
        key = title[:80].lower()
        if key in seen_titles:
            continue
        bucket = _text_bucket(title) or "global"
        items.append(
            _line(
                "low",
                f"News: {title[:120]}",
                bucket,
                sources=["gdelt_pulse"],
                observed_at=art.get("seendate"),
            )
        )

    for v in (snap.get("volcanoes", {}) or {}).get("volcanoes", [])[:10]:
        name = v.get("name") or "Volcano"
        lat, lon = v.get("lat"), v.get("lon")
        bucket = classify_item(
            lat, lon, name, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                "low",
                f"Volcano: {name}",
                bucket,
                sources=["volcanoes"],
                lat=lat,
                lon=lon,
            )
        )

    for sig in (snap.get("river", {}) or {}).get("anomalies") or []:
        items.append(
            _line(
                "high",
                f"Feed anomaly: {sig.get('feed')} score={sig.get('score')}",
                "global",
                sources=["river"],
            )
        )

    for a in alerts[:12]:
        text = a.get("text") or ""
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(
            lat, lon, text, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        items.append(
            _line(
                a.get("severity", "low"),
                text,
                bucket,
                sources=["alerts"],
                lat=lat,
                lon=lon,
            )
        )

    return items


def build_watch_items(
    snap: dict,
    alerts: list[dict],
    fusion_hotspots: list[dict] | None = None,
    *,
    fusion_deltas: list[dict] | None = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """Forward-looking watch list from feeds — pre-LLM, rule-based (Track 1 + 5 deltas)."""
    cap = max_items if max_items is not None else _watch_max_items()
    local_bbox = _region_bbox(OPERATOR_REGION)
    regional_bbox = _ASEAN_BBOX if OPERATOR_REGION == "thailand" else local_bbox
    if regional_bbox is None and local_bbox:
        w, s, e, n = local_bbox
        regional_bbox = [w - 8, s - 6, e + 8, n + 4]
    _extra = [_WEST_ASIA_BBOX]

    candidates: list[dict[str, Any]] = []
    delta_cells = {c.get("cell_id") for c in (fusion_deltas or []) if c.get("cell_id")}

    for cell in fusion_deltas or []:
        delta = float(cell.get("delta_score") or 0)
        if delta < 0.12:
            continue
        lat, lon = cell.get("lat"), cell.get("lon")
        cid = cell.get("cell_id") or _cell_id(lat, lon)
        score = float(cell.get("score") or 0)
        sources = list(cell.get("sources") or [])
        sample = (cell.get("samples") or [{}])[0].get("label") or ""
        label = sample[:100] if sample else (cid or "fusion cell")
        bucket = classify_item(
            lat, lon, label, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        candidates.append(
            _watch_item(
                prefix="fusion_delta",
                key=f"{cid}:{delta}",
                title=f"Rising fusion cell (Δ+{delta:.2f}): {label}",
                horizon_h=48,
                confidence=min(0.92, 0.5 + delta + score * 0.25),
                sources=sources or ["fusion"],
                bucket=bucket,
                cell_id=cid,
                delta_score=delta,
            )
        )

    for i, cell in enumerate(fusion_hotspots or []):
        cid = cell.get("cell_id") or _cell_id(cell.get("lat"), cell.get("lon"))
        if cid and cid in delta_cells:
            continue
        score = float(cell.get("score") or 0)
        if score < 0.45:
            continue
        lat, lon = cell.get("lat"), cell.get("lon")
        sources = list(cell.get("sources") or [])
        sample = (cell.get("samples") or [{}])[0].get("label") or ""
        title = sample[:120] if sample else f"Fusion hotspot #{i + 1}"
        bucket = classify_item(
            lat, lon, title, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        candidates.append(
            _watch_item(
                prefix="fusion",
                key=f"{lat},{lon},{score}",
                title=f"Monitor fusion cell: {title}",
                horizon_h=48,
                confidence=0.55 + score * 0.4,
                sources=sources or ["fusion"],
                bucket=bucket,
                cell_id=_cell_id(lat, lon),
            )
        )

    for row in (snap.get("cams_haze", {}) or {}).get("cities") or []:
        pm25 = row.get("pm25")
        dust = row.get("dust")
        sev = row.get("severity") or (
            _pm25_severity(float(pm25)) if pm25 is not None else "low"
        )
        if sev not in ("medium", "high") and (pm25 is None or float(pm25) < 35):
            continue
        name = row.get("city") or "City"
        lat, lon = row.get("lat"), row.get("lon")
        bucket = classify_item(
            lat, lon, name, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        parts = []
        if pm25 is not None:
            parts.append(f"PM2.5 {pm25} µg/m³")
        if dust is not None:
            parts.append(f"dust {dust} µg/m³")
        candidates.append(
            _watch_item(
                prefix="cams",
                key=name.lower(),
                title=f"Haze trajectory — {name}: {', '.join(parts)}",
                horizon_h=72,
                confidence=0.7 if sev == "high" else 0.55,
                sources=["cams_haze"],
                bucket=bucket,
                cell_id=_cell_id(lat, lon),
            )
        )

    local_pulse = snap.get("gdelt_pulse_local") or {}
    geo_local = snap.get("gdelt_geo_local") or {}
    pulse_n = len(local_pulse.get("articles") or [])
    geo_n = len(geo_local.get("events") or [])
    if pulse_n >= 4 or geo_n >= 3:
        candidates.append(
            _watch_item(
                prefix="gdelt",
                key=f"{pulse_n}:{geo_n}",
                title=(
                    f"Elevated media attention — {pulse_n} local headlines, "
                    f"{geo_n} geo signals"
                ),
                horizon_h=24,
                confidence=min(0.85, 0.45 + (pulse_n + geo_n) * 0.04),
                sources=["gdelt_pulse_local", "gdelt_geo_local"],
                bucket="local" if pulse_n >= geo_n else "regional",
            )
        )

    for q in (snap.get("earthquakes", {}) or {}).get("earthquakes", [])[:15]:
        mag = float(q.get("mag") or q.get("magnitude") or 0)
        if mag < 5.0:
            continue
        place = q.get("place") or "Earthquake"
        lat, lon = q.get("lat"), q.get("lon")
        bucket = classify_item(
            lat, lon, place, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        if bucket == "global" and mag < 6.0:
            continue
        candidates.append(
            _watch_item(
                prefix="quake",
                key=f"{place}:{mag}",
                title=f"Aftershock / impact watch — M{mag} {place}",
                horizon_h=48,
                confidence=0.6 if mag < 6 else 0.8,
                sources=["earthquakes"],
                bucket=bucket,
                cell_id=_cell_id(lat, lon),
            )
        )

    for a in (snap.get("gdacs", {}) or {}).get("alerts", [])[:8]:
        title = a.get("title") or "GDACS alert"
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(
            lat, lon, title, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        level = (a.get("alertlevel") or a.get("severity") or "").lower()
        if bucket == "global" and "red" not in level and "orange" not in level:
            continue
        candidates.append(
            _watch_item(
                prefix="gdacs",
                key=title[:80],
                title=f"Disaster evolution — {title[:100]}",
                horizon_h=72,
                confidence=0.75 if "red" in level else 0.6,
                sources=["gdacs"],
                bucket=bucket,
                cell_id=_cell_id(lat, lon),
            )
        )

    sw = snap.get("spaceweather", {}) or {}
    kp = sw.get("kp_index")
    if kp is not None and float(kp) >= 5:
        candidates.append(
            _watch_item(
                prefix="spacewx",
                key=str(kp),
                title=f"Space weather — Kp {float(kp):.1f} (HF/GPS risk)",
                horizon_h=24,
                confidence=min(0.9, 0.5 + float(kp) * 0.05),
                sources=["spaceweather"],
                bucket="global",
            )
        )

    thai_vessels = [
        v
        for v in (snap.get("maritime", {}) or {}).get("vessels") or []
        if (v.get("region") or "")
        in ("malacca", "laem_chabang", "bangkok_port", "phuket")
    ]
    if len(thai_vessels) >= 12:
        candidates.append(
            _watch_item(
                prefix="maritime",
                key=str(len(thai_vessels)),
                title=f"Maritime corridor density — {len(thai_vessels)} vessels tracked",
                horizon_h=48,
                confidence=0.5,
                sources=["maritime"],
                bucket="regional",
            )
        )

    spaceweather_digest = snap.get("spaceweather_digest") or {}
    if spaceweather_digest.get("enabled"):
        try:
            from spaceweather_briefing import build_spaceweather_watch_items

            for item in build_spaceweather_watch_items(spaceweather_digest):
                candidates.append(item)
        except Exception:
            pass

    for ds in (snap.get("humanitarian", {}) or {}).get("datasets") or []:
        title = ds.get("title") or ""
        if not title:
            continue
        bucket = _text_bucket(title) or "regional"
        candidates.append(
            _watch_item(
                prefix="hdx",
                key=title[:60],
                title=f"Humanitarian watch — {title[:90]}",
                horizon_h=72,
                confidence=0.55,
                sources=["humanitarian"],
                bucket=bucket,
            )
        )

    for a in alerts[:6]:
        sev = (a.get("severity") or "low").lower()
        if sev not in ("critical", "high", "warning", "medium"):
            continue
        text = a.get("text") or "Alert"
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(
            lat, lon, text, local_bbox, regional_bbox, extra_regional_bboxes=_extra
        )
        conf = 0.85 if sev == "critical" else 0.7 if sev == "high" else 0.55
        candidates.append(
            _watch_item(
                prefix="alert",
                key=text[:60],
                title=text[:160],
                horizon_h=24,
                confidence=conf,
                sources=["alerts"],
                bucket=bucket,
                cell_id=_cell_id(lat, lon),
            )
        )

    ransomware_digest = snap.get("ransomware_digest") or {}
    if ransomware_digest.get("enabled"):
        try:
            from darkweb_briefing import build_ransomware_watch_items

            for item in build_ransomware_watch_items(ransomware_digest):
                candidates.append(item)
        except Exception:
            pass

    breach_digest = snap.get("breach_digest") or {}
    if breach_digest.get("enabled"):
        try:
            from breach_bridge import build_breach_watch_items

            for item in build_breach_watch_items(breach_digest):
                candidates.append(item)
        except Exception:
            pass

    telegram_digest = snap.get("telegram_digest") or {}
    if telegram_digest.get("enabled"):
        try:
            from telegram_briefing import build_telegram_watch_items

            for item in build_telegram_watch_items(telegram_digest):
                candidates.append(item)
        except Exception:
            pass

    maritime_anomaly_digest = snap.get("maritime_anomaly_digest") or {}
    if maritime_anomaly_digest.get("enabled"):
        try:
            from maritime_briefing import build_maritime_watch_items

            for item in build_maritime_watch_items(maritime_anomaly_digest):
                candidates.append(item)
        except Exception:
            pass

    anomaly_digest = snap.get("anomaly_digest") or {}
    if anomaly_digest.get("enabled"):
        try:
            from anomaly_detector import build_anomaly_watch_items

            for item in build_anomaly_watch_items(anomaly_digest):
                candidates.append(item)
        except Exception:
            pass

    satellite_digest = snap.get("satellite_change_digest") or {}
    if satellite_digest.get("enabled"):
        try:
            for line in (satellite_digest.get("lines") or [])[:3]:
                cls = line.get("class", "unknown")
                mean_delta = float(line.get("mean_delta") or 0)
                px = int(line.get("pixel_count") or 0)
                conf = float(line.get("confidence") or 0)
                region = line.get("region", OPERATOR_REGION)
                if abs(mean_delta) < 0.2 or px < 10:
                    continue
                candidates.append(
                    _watch_item(
                        prefix="satellite",
                        key=f"{region}:{cls}:{mean_delta}",
                        title=(
                            f"Sentinel-2 NDVI {cls} (Δ{mean_delta:+.3f}, "
                            f"{px} px) — {region}"
                        ),
                        horizon_h=72,
                        confidence=min(0.85, 0.4 + conf * 0.4),
                        sources=["sentinel-2", "stac"],
                        bucket="regional" if region == OPERATOR_REGION else "global",
                    )
                )
        except Exception:
            pass

    seen_ids: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda x: -float(x.get("confidence") or 0)):
        wid = item.get("id") or ""
        if wid in seen_ids:
            continue
        seen_ids.add(wid)
        ranked.append(item)
        if len(ranked) >= cap:
            break
    return ranked


def format_watch_items_block(
    watch_items: list[dict[str, Any]], lang: str | None = None
) -> str:
    """Plain-text watch block for LLM prompt."""
    lang = _resolve_lang(lang)
    if not watch_items:
        if lang.startswith("de"):
            return "- Keine priorisierten Watch-Items (Feeds ruhig)."
        return "- No ranked watch items (feeds quiet)."
    lines: list[str] = []
    for i, w in enumerate(watch_items, 1):
        hrs = w.get("horizon_h", 24)
        conf = float(w.get("confidence") or 0)
        src = ", ".join(w.get("sources") or [])
        delta = w.get("delta_score")
        delta_tag = f", Δ={float(delta):+.2f}" if delta is not None else ""
        lines.append(
            f"- #{i} [{hrs}h horizon, conf={conf:.2f}{delta_tag}] {w.get('title')} (sources: {src})"
        )
    return "\n".join(lines)


def _severity_key(item: dict) -> tuple[int, str]:
    return (_SEVERITY_RANK.get(item.get("severity"), 9), item.get("text", ""))


def _sort_bucket(
    lines: list[dict],
    limit: int = 6,
    *,
    gdelt_reserve: int = 0,
    newsdata_reserve: int = 0,
) -> tuple[list[str], list[dict]]:
    """Rank by severity; reserve slots for GDELT / NewsData so media headlines survive cap."""
    from briefing_quality import item_is_gdelt

    out: list[str] = []
    picked: list[dict] = []
    seen: set[str] = set()
    reserved: list[dict] = []

    def _append_item(item: dict) -> bool:
        t = item.get("text", "")
        key = t[:80].lower()
        if not t or key in seen:
            return False
        seen.add(key)
        out.append(f"- {t}")
        picked.append(item)
        return True

    def _reserve_from(pool: list[dict], *, cap: int, predicate) -> None:
        if cap <= 0:
            return
        ranked = sorted((x for x in pool if predicate(x)), key=_severity_key)
        for item in ranked:
            if sum(1 for x in reserved if predicate(x)) >= cap:
                break
            if item in reserved:
                continue
            if _append_item(item):
                reserved.append(item)
            if len(out) >= limit:
                return

    if gdelt_reserve > 0:
        _reserve_from(lines, cap=gdelt_reserve, predicate=item_is_gdelt)
        if len(out) >= limit:
            return out, picked

    if newsdata_reserve > 0:
        _reserve_from(lines, cap=newsdata_reserve, predicate=_is_newsdata_item)
        if len(out) >= limit:
            return out, picked

    remaining = sorted((x for x in lines if x not in reserved), key=_severity_key)
    for item in remaining:
        if len(out) >= limit:
            break
        _append_item(item)
    return out, picked


def format_digest_sections(
    snap: dict,
    alerts: list[dict],
    fusion_lines: str,
    fusion_hotspots: list[dict],
    *,
    fusion_deltas: list[dict] | None = None,
    intel_meta: dict | None = None,
    lang: str | None = None,
    darkweb_digest: dict[str, Any] | None = None,
    ransomware_digest: dict[str, Any] | None = None,
    breach_digest: dict[str, Any] | None = None,
    telegram_digest: dict[str, Any] | None = None,
    maritime_anomaly_digest: dict[str, Any] | None = None,
    spaceweather_digest: dict[str, Any] | None = None,
    identity_digest: dict[str, Any] | None = None,
    satellite_change_digest: dict[str, Any] | None = None,
    domain_digest: dict[str, Any] | None = None,
    thai_digest: dict[str, Any] | None = None,
    forecast_digest: dict[str, Any] | None = None,
    anomaly_digest: dict[str, Any] | None = None,
    acled_digest: dict[str, Any] | None = None,
    osm_digest: dict[str, Any] | None = None,
    weather_forecast_digest: dict[str, Any] | None = None,
    lightning_digest: dict[str, Any] | None = None,
    cii_digest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lang = _resolve_lang(lang)
    items = _collect_digest_items(snap, alerts)

    intel_block: dict[str, Any] = {
        "enabled": False,
        "count": 0,
        "entities": [],
        "items": [],
    }
    if intel_meta is not None:
        try:
            import intel_briefing

            feed_keys = {i.get("text", "")[:80].lower() for i in items if i.get("text")}
            intel_block = intel_briefing.finalize_intel_for_digest(
                intel_meta,
                existing_text_keys=feed_keys,
            )
            items.extend(intel_block.get("items") or [])
        except Exception:
            pass

    buckets = {"local": [], "regional": [], "global": []}
    for item in items:
        buckets.setdefault(item["bucket"], []).append(item)

    local_lines, local_picked = _sort_bucket(
        buckets["local"],
        6,
        gdelt_reserve=_gdelt_local_slots(),
        newsdata_reserve=_newsdata_slots(),
    )
    regional_lines, regional_picked = _sort_bucket(
        buckets["regional"], 6, newsdata_reserve=_newsdata_slots()
    )
    global_lines, global_picked = _sort_bucket(
        buckets["global"], 8, newsdata_reserve=_newsdata_slots()
    )

    from briefing_quality import build_digest_line_meta, count_gdelt_digest_items

    digest_line_meta = build_digest_line_meta(
        items,
        {"local": local_picked, "regional": regional_picked, "global": global_picked},
    )
    gdelt_collected = count_gdelt_digest_items(items)

    sw = snap.get("spaceweather", {}) or {}
    cve_items = (snap.get("cve", {}) or {}).get("vulnerabilities", [])[:5]
    nodes = (snap.get("nodes", {}) or {}).get("nodes", [])
    aq = snap.get("airquality", {}) or {}
    bangkok_aq = next(
        (
            c
            for c in (aq.get("cities") or [])
            if "bangkok" in (c.get("city") or "").lower()
        ),
        None,
    )

    cyber_lines = [
        f"- {v.get('cve_id')}: {v.get('vendor')} {v.get('product')}" for v in cve_items
    ] or ["- none flagged"]
    node_lines = [
        f"- {n.get('name')}: {'online' if n.get('online') else 'OFFLINE'}, "
        f"CPU {n.get('health', {}).get('cpu_temp_c', '?')}°C"
        for n in nodes[:3]
    ] or ["- none"]
    # Market stress — compact summary for the LLM, fail-soft if markets_bridge not ready
    try:
        import markets_bridge

        market_stress = markets_bridge.format_market_stress_line(
            markets_bridge.summarize_market_stress(
                snap.get("markets_crypto"), snap.get("markets_stocks")
            )
        )
    except Exception:
        market_stress = None
    infra_bits = [
        f"Space weather Kp={sw.get('kp_index')} ({sw.get('scale')})",
        market_stress or "Market stress: feeds unavailable",
    ]
    if bangkok_aq:
        infra_bits.append(f"Bangkok air: PM2.5 {bangkok_aq.get('pm25', '—')} µg/m³")
    outages_n = (snap.get("outages", {}) or {}).get("count") or 0
    if outages_n:
        infra_bits.append(f"Internet outage signals (global index): {outages_n}")

    region_label = _region_label(OPERATOR_REGION)
    if lang.startswith("de"):
        empty_local = "- Keine lokalen Signale in den Feeds (letzte 24h)."
        empty_regional = "- Keine regionalen Signale hervorgehoben."
        empty_global = "- Keine globalen Schwerpunkte jenseits Baseline."
    else:
        empty_local = "- No local signals in feeds (last 24h)."
        empty_regional = "- No regional signals highlighted."
        empty_global = "- No global highlights beyond baseline."
    watch_items = build_watch_items(
        snap, alerts, fusion_hotspots, fusion_deltas=fusion_deltas
    )
    prompt_metrics: dict[str, Any] = {}
    try:
        import intel_briefing

        prompt_metrics = intel_briefing.intel_prompt_metrics(intel_block, lang=lang)
    except Exception:
        pass
    return {
        "region": OPERATOR_REGION,
        "region_label": region_label,
        "window": "24h",
        "lang": lang,
        "local": local_lines or [empty_local],
        "regional": regional_lines or [empty_regional],
        "global": global_lines or [empty_global],
        "fusion": fusion_lines,
        "fusion_hotspots": fusion_hotspots,
        "watch_items": watch_items,
        "digest_line_meta": digest_line_meta,
        "intel": {
            "enabled": intel_block.get("enabled", False),
            "count": intel_block.get("count", 0),
            "by_bucket": intel_block.get("by_bucket") or {},
            "entities": intel_block.get("entities") or [],
            "items": intel_block.get("items") or [],
            "window_hours": intel_block.get("window_hours"),
            "error": intel_block.get("error"),
            "prompt_metrics": prompt_metrics,
        },
        "cyber": cyber_lines,
        "infra": infra_bits,
        "nodes": node_lines,
        "darkweb": darkweb_digest or {"enabled": False, "count": 0, "lines": []},
        "ransomware": ransomware_digest or {"enabled": False, "count": 0, "lines": []},
        "breach": breach_digest or {"enabled": False, "count": 0, "lines": []},
        "telegram": telegram_digest or {"enabled": False, "count": 0, "lines": []},
        "maritime": maritime_anomaly_digest
        or {"enabled": False, "count": 0, "lines": []},
        "spaceweather": spaceweather_digest
        or {"enabled": False, "count": 0, "lines": []},
        "identity": identity_digest or {"enabled": False, "count": 0, "lines": []},
        "domain": domain_digest or {"enabled": False, "count": 0, "lines": []},
        "thai": thai_digest or {"enabled": False, "count": 0, "lines": []},
        "satellite_change": satellite_change_digest
        or {"enabled": False, "count": 0, "lines": []},
        "forecast": forecast_digest or {"enabled": False, "count": 0, "lines": []},
        "anomaly": anomaly_digest or {"enabled": False, "count": 0, "lines": []},
        "acled": acled_digest or {"enabled": False, "count": 0, "lines": []},
        "osm": osm_digest or {"enabled": False, "count": 0, "lines": []},
        "weather_forecast": weather_forecast_digest
        or {"enabled": False, "count": 0, "lines": []},
        "lightning": lightning_digest or {"enabled": False, "count": 0, "lines": []},
        "cii": cii_digest or {"enabled": False, "count": 0, "lines": []},
        "_gdelt_collected": gdelt_collected,
    }
