"""Security-advisor style 24h digest — operator home region + world pulse.

Used by node_sync briefing generation (local Ollama). Classifies feed items
into LOCAL (Thailand), REGIONAL (ASEAN / near), and GLOBAL buckets before
the LLM writes the narrative protocol.
"""

from __future__ import annotations

import math
import os
from typing import Any

from stac_bridge import REGION_PRESETS

OPERATOR_REGION = os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower()
BRIEFING_LANG = os.getenv("WORLDBASE_BRIEFING_LANG", "en").strip().lower()


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

_LOCAL_KEYWORDS = (
    "thailand", "thai", "bangkok", "phuket", "chiang mai", "pattaya",
    "andaman", "gulf of thailand", "mekong", "isaan", "krabi",
)
_REGION_KEYWORDS = (
    "myanmar", "burma", "cambodia", "laos", "vietnam", "viet nam",
    "malaysia", "singapore", "indonesia", "philippines", "asean",
    "south china sea", "andaman", "mekong", "bay of bengal",
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
) -> str:
    """local | regional | global"""
    if lat is not None and lon is not None and local_bbox and _in_bbox(lat, lon, local_bbox):
        return "local"
    text_hit = _text_bucket(text)
    if text_hit == "local":
        return "local"
    if lat is not None and lon is not None and regional_bbox and _in_bbox(lat, lon, regional_bbox):
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


def _line(severity: str, text: str, bucket: str) -> dict:
    return {
        "severity": severity,
        "text": text.strip(),
        "bucket": bucket,
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

    items: list[dict] = []

    for city in (snap.get("airquality", {}) or {}).get("cities") or []:
        pm25 = city.get("pm25")
        if pm25 is None:
            continue
        name = city.get("city") or "City"
        lat, lon = city.get("lat"), city.get("lon")
        bucket = classify_item(lat, lon, name, local_bbox, regional_bbox)
        items.append(_line(
            _pm25_severity(float(pm25)),
            f"Air quality {name}: PM2.5 {pm25} µg/m³",
            bucket,
        ))

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
        bucket = classify_item(lat, lon, name, local_bbox, regional_bbox)
        sev = row.get("severity") or _pm25_severity(float(pm25)) if pm25 is not None else "low"
        items.append(_line(
            sev,
            f"CAMS haze {name}: " + ", ".join(parts),
            bucket,
        ))

    for ds in (snap.get("humanitarian", {}) or {}).get("datasets") or []:
        title = ds.get("title") or "Humanitarian dataset"
        org = ds.get("organization") or ""
        text = f"Humanitarian data: {title[:90]}"
        if org:
            text += f" ({org})"
        bucket = _text_bucket(title) or "regional"
        items.append(_line("medium", text, bucket))

    thai_vessels = [
        v for v in (snap.get("maritime", {}) or {}).get("vessels") or []
        if (v.get("region") or "") in ("malacca", "laem_chabang", "bangkok_port", "phuket", "singapore")
    ]
    if thai_vessels:
        by_region: dict[str, int] = {}
        for v in thai_vessels:
            reg = v.get("region") or "unknown"
            by_region[reg] = by_region.get(reg, 0) + 1
        summary = ", ".join(f"{k}={n}" for k, n in sorted(by_region.items()))
        items.append(_line(
            "low",
            f"Maritime traffic (Thailand corridor): {len(thai_vessels)} vessels ({summary})",
            "local" if any(r in by_region for r in ("laem_chabang", "bangkok_port", "phuket")) else "regional",
        ))

    local_pulse = snap.get("gdelt_pulse_local", {}) or {}
    for art in (local_pulse.get("articles") or [])[:10]:
        title = art.get("title") or art.get("url") or "Headline"
        items.append(_line("low", f"Local news: {title[:120]}", "local"))

    for row in (snap.get("gdelt_geo_local", {}) or {}).get("events", [])[:12]:
        name = row.get("name") or "GDELT signal"
        lat, lon = row.get("lat"), row.get("lon")
        bucket = classify_item(lat, lon, str(name), local_bbox, regional_bbox)
        items.append(_line("medium", f"Regional media heat: {str(name)[:100]}", bucket))

    for q in (snap.get("earthquakes", {}) or {}).get("earthquakes", [])[:40]:
        place = q.get("place") or "Earthquake"
        mag = q.get("mag") or q.get("magnitude")
        lat, lon = q.get("lat"), q.get("lon")
        text = f"M{mag} — {place}"
        bucket = classify_item(lat, lon, text, local_bbox, regional_bbox)
        sev = "high" if (mag or 0) >= 6 else "medium" if (mag or 0) >= 5 else "low"
        items.append(_line(sev, text, bucket))

    for ev in (snap.get("events", {}) or {}).get("events", [])[:25]:
        title = ev.get("title") or ev.get("category") or "Event"
        lat, lon = ev.get("lat"), ev.get("lon")
        bucket = classify_item(lat, lon, title, local_bbox, regional_bbox)
        items.append(_line("low", f"{ev.get('category', 'EVENT')}: {title}", bucket))

    for a in (snap.get("gdacs", {}) or {}).get("alerts", [])[:15]:
        title = a.get("title") or "GDACS alert"
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(lat, lon, title, local_bbox, regional_bbox)
        items.append(_line("medium", title, bucket))

    for h in (snap.get("hazards", {}) or {}).get("alerts", [])[:20]:
        label = h.get("event") or h.get("headline") or "Hazard"
        lat, lon = h.get("lat"), h.get("lon")
        bucket = classify_item(lat, lon, label, local_bbox, regional_bbox)
        sev = (h.get("severity") or "").lower()
        severity = "high" if "extreme" in sev else "medium" if "severe" in sev else "low"
        if bucket == "local" and severity == "low":
            severity = "medium"
        items.append(_line(severity, label, bucket))

    for g in (snap.get("geopolitics", {}) or {}).get("items", [])[:15]:
        name = g.get("name") or g.get("title") or "Crisis"
        lat, lon = g.get("lat"), g.get("lon")
        bucket = classify_item(lat, lon, name, local_bbox, regional_bbox)
        items.append(_line("medium", f"Crisis: {name}", bucket))

    for row in (snap.get("gdelt_geo", {}) or {}).get("events", [])[:20]:
        name = row.get("name") or "GDELT signal"
        lat, lon = row.get("lat"), row.get("lon")
        bucket = classify_item(lat, lon, str(name), local_bbox, regional_bbox)
        items.append(_line("low", f"Media heat: {str(name)[:100]}", bucket))

    pulse = snap.get("gdelt_pulse", {}) or {}
    seen_titles: set[str] = {
        (a.get("title") or "")[:80].lower()
        for a in (local_pulse.get("articles") or [])
    }
    for art in (pulse.get("articles") or [])[:12]:
        title = art.get("title") or art.get("url") or "Headline"
        key = title[:80].lower()
        if key in seen_titles:
            continue
        bucket = _text_bucket(title) or "global"
        items.append(_line("low", f"News: {title[:120]}", bucket))

    for v in (snap.get("volcanoes", {}) or {}).get("volcanoes", [])[:10]:
        name = v.get("name") or "Volcano"
        lat, lon = v.get("lat"), v.get("lon")
        bucket = classify_item(lat, lon, name, local_bbox, regional_bbox)
        items.append(_line("low", f"Volcano: {name}", bucket))

    for sig in (snap.get("river", {}) or {}).get("anomalies") or []:
        items.append(_line("high", f"Feed anomaly: {sig.get('feed')} score={sig.get('score')}", "global"))

    for a in alerts[:12]:
        text = a.get("text") or ""
        lat, lon = a.get("lat"), a.get("lon")
        bucket = classify_item(lat, lon, text, local_bbox, regional_bbox)
        items.append(_line(a.get("severity", "low"), text, bucket))

    return items


def _sort_bucket(lines: list[dict], limit: int = 6) -> list[str]:
    ranked = sorted(
        lines,
        key=lambda x: (_SEVERITY_RANK.get(x.get("severity"), 9), x.get("text", "")),
    )
    out: list[str] = []
    seen: set[str] = set()
    for item in ranked:
        t = item.get("text", "")
        key = t[:80].lower()
        if not t or key in seen:
            continue
        seen.add(key)
        out.append(f"- {t}")
        if len(out) >= limit:
            break
    return out


def format_digest_sections(
    snap: dict,
    alerts: list[dict],
    fusion_lines: str,
    fusion_hotspots: list[dict],
    *,
    intel_meta: dict | None = None,
    lang: str | None = None,
) -> dict[str, Any]:
    lang = _resolve_lang(lang)
    items = _collect_digest_items(snap, alerts)

    intel_block: dict[str, Any] = {"enabled": False, "count": 0, "entities": [], "items": []}
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

    local_lines = _sort_bucket(buckets["local"], 6)
    regional_lines = _sort_bucket(buckets["regional"], 6)
    global_lines = _sort_bucket(buckets["global"], 8)

    sw = snap.get("spaceweather", {}) or {}
    cve_items = (snap.get("cve", {}) or {}).get("vulnerabilities", [])[:5]
    nodes = (snap.get("nodes", {}) or {}).get("nodes", [])
    aq = snap.get("airquality", {}) or {}
    bangkok_aq = next(
        (c for c in (aq.get("cities") or []) if "bangkok" in (c.get("city") or "").lower()),
        None,
    )

    cyber_lines = [
        f"- {v.get('cve_id')}: {v.get('vendor')} {v.get('product')}"
        for v in cve_items
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
        infra_bits.append(
            f"Bangkok air: PM2.5 {bangkok_aq.get('pm25', '—')} µg/m³"
        )
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
        "intel": {
            "enabled": intel_block.get("enabled", False),
            "count": intel_block.get("count", 0),
            "by_bucket": intel_block.get("by_bucket") or {},
            "entities": intel_block.get("entities") or [],
            "items": intel_block.get("items") or [],
            "window_hours": intel_block.get("window_hours"),
            "error": intel_block.get("error"),
        },
        "cyber": cyber_lines,
        "infra": infra_bits,
        "nodes": node_lines,
    }


def _lang_instructions(lang: str | None = None) -> str:
    lang = _resolve_lang(lang)
    if lang.startswith("de"):
        return (
            "Schreibe auf Deutsch. Ton: ruhiger Sicherheitsberater für einen Privat-Operator "
            "mit Wohnsitz in der Fokusregion — wie ein persönliches Weltlage-Protokoll, "
            "keine Sensationspresse."
        )
    return (
        "Write in English. Tone: calm private security advisor for a home-region operator — "
        "a personal world digest, not sensational news."
    )


def build_security_advisor_prompt(digest: dict[str, Any], lang: str | None = None) -> str:
    region = digest.get("region_label", "Thailand")
    lang = _resolve_lang(lang or digest.get("lang"))
    is_de = lang.startswith("de")

    if is_de:
        section_hints = (
            f"LOCAL ({region}) — was vor Ort in den letzten 24h zählt\n"
            "REGION — ASEAN / Nachbarn / nahe Umgebung wenn relevant\n"
            "GLOBAL — Rest der Welt, der für informierte Bewohner relevant bleibt\n"
            "CYBER & INFRA — KEV, Nodes, Weltraumwetter, Märkte, Luftqualität wenn vorhanden\n"
            "RECOMMENDATION — 1–2 Sätze: ruhig, umsetzbar, keine Panik\n"
        )
        no_data_clause = (
            "Nutze NUR das untenstehende Feed-Digest und die INTEL ENTITIES. "
            "Wenn ein Abschnitt keine Daten hat, schreibe klar, dass die Feeds dort "
            "nichts Auffälliges zeigen (keine Ereignisse erfinden). "
            "Bei INTEL ENTITIES: nenne konkrete Akteure/Orte/Ereignisse aus dem FtM-Graph, "
            "nicht generische Feed-Schlagzeilen wiederholen."
        )
        digest_header = "--- DIGEST"
        protocol_label = "Protokoll:"
        final_reminder = (
            "WICHTIG: Schreibe den gesamten Protokoll-Text auf Deutsch. "
            "Behalte die Labels LOCAL / REGION / GLOBAL / CYBER & INFRA / RECOMMENDATION "
            "wörtlich auf Englisch — der Fließtext darunter MUSS deutsch sein."
        )
    else:
        section_hints = (
            f"LOCAL ({region}) — what matters at home in the last 24h\n"
            "REGION — ASEAN / neighbours / nearby if relevant\n"
            "GLOBAL — rest of the world that still matters to an informed resident\n"
            "CYBER & INFRA — KEV, nodes, space weather, markets, air quality if present\n"
            "RECOMMENDATION — 1–2 sentences: calm, actionable, no panic\n"
        )
        no_data_clause = (
            "Use ONLY the feed digest and INTEL ENTITIES below. If a section has no data, "
            "say clearly that feeds show nothing notable (do not invent events). "
            "For INTEL ENTITIES: name specific actors/places/events from the FtM graph; "
            "do not repeat generic feed headlines."
        )
        digest_header = "--- DIGEST"
        protocol_label = "Protocol:"
        final_reminder = (
            "Reminder: write the entire protocol body in English."
        )

    intel_prompt = ""
    try:
        import intel_briefing

        intel_prompt = intel_briefing.format_intel_prompt_block(
            {"items": digest.get("intel", {}).get("items") or []},
            lang=lang,
        )
    except Exception:
        intel_prompt = "- Intel graph unavailable."

    return (
        "You produce a 24-hour security & situational awareness protocol for one operator.\n"
        + _lang_instructions(lang)
        + "\n"
        "Max 280 words. Plain text only — NO markdown headers, NO bullet lists in the output. "
        "Use short labeled paragraphs in this order (keep labels exactly as written):\n"
        + section_hints
        + "\n"
        + no_data_clause
        + "\n\n"
        f"{digest_header} (last {digest.get('window', '24h')}) ---\n"
        f"LOCAL signals:\n" + "\n".join(digest["local"]) + "\n\n"
        f"REGION signals:\n" + "\n".join(digest["regional"]) + "\n\n"
        f"GLOBAL signals:\n" + "\n".join(digest["global"]) + "\n\n"
        f"{intel_prompt}\n\n"
        f"Fusion hotspots (spatial grid):\n{digest['fusion']}\n\n"
        f"Cyber (CISA KEV):\n" + "\n".join(digest["cyber"]) + "\n\n"
        f"Infra:\n" + "\n".join(f"- {x}" for x in digest["infra"]) + "\n\n"
        f"Edge nodes:\n" + "\n".join(digest["nodes"]) + "\n\n"
        + final_reminder + "\n\n"
        + protocol_label
    )


def format_fallback_protocol(digest: dict[str, Any], lang: str | None = None) -> str:
    region = digest.get("region_label", "Thailand")
    lang = _resolve_lang(lang or digest.get("lang"))
    if lang.startswith("de"):
        parts = [
            f"LOKAL ({region}): " + " ".join(digest["local"]).replace("- ", ""),
            "REGION: " + " ".join(digest["regional"]).replace("- ", ""),
            "GLOBAL: " + " ".join(digest["global"][:3]).replace("- ", ""),
            "Fusion: " + digest["fusion"].replace("\n", " "),
        ]
        intel_items = digest.get("intel", {}).get("items") or []
        if intel_items:
            parts.append(
                "INTEL: " + " ".join(i.get("text", "") for i in intel_items[:4])
            )
        parts.append(
            "EMPFEHLUNG: LLM offline — Rohdaten oben prüfen; keine automatische Bewertung."
        )
        return "\n\n".join(parts)
    parts = [
        f"LOCAL ({region}): " + " ".join(digest["local"]).replace("- ", ""),
        "REGION: " + " ".join(digest["regional"]).replace("- ", ""),
        "GLOBAL: " + " ".join(digest["global"][:3]).replace("- ", ""),
        "Fusion: " + digest["fusion"].replace("\n", " "),
    ]
    intel_items = digest.get("intel", {}).get("items") or []
    if intel_items:
        parts.append("INTEL: " + " ".join(i.get("text", "") for i in intel_items[:4]))
    parts.append("NOTE: LLM offline — review raw digest above.")
    return "\n\n".join(parts)
