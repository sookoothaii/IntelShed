"""LLM prompt building and fallback protocol for operator briefing.

Extracted from operator_briefing.py (Phase 2). Builds the security-advisor
prompt from a digest dict and provides a fallback protocol when the LLM
is offline.
"""

from __future__ import annotations

import logging
from typing import Any

from briefing_digest import _resolve_lang, format_watch_items_block

logger = logging.getLogger(__name__)


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


def _prediction_calibration_line(lang: str | None = None) -> str:
    try:
        import prediction_ledger

        return prediction_ledger.format_accuracy_line(lang=lang)
    except Exception:
        return "Forecast calibration: unavailable."


def build_security_advisor_prompt(
    digest: dict[str, Any], lang: str | None = None
) -> str:
    region = digest.get("region_label", "Thailand")
    lang = _resolve_lang(lang or digest.get("lang"))
    is_de = lang.startswith("de")

    if is_de:
        section_hints = (
            f"LOCAL ({region}) — was vor Ort in den letzten 24h zählt\n"
            "REGION — ASEAN / Nachbarn / Westasien (Iran, Hormuz, Persischer Golf, Levante) wenn relevant\n"
            "GLOBAL — Rest der Welt, der für informierte Bewohner relevant bleibt\n"
            "CYBER & INFRA — KEV, Nodes, Weltraumwetter, Märkte, Luftqualität wenn vorhanden\n"
            "MARITIME ANOMALIES — AIS Mustererkennung (immer nennen, auch wenn keine Anomalien)\n"
            "SATELLITE CHANGE DETECTION — Sentinel-2 NDVI-Veränderung (immer nennen, auch wenn keine Anomalien)\n"
            "RECOMMENDATION — 1–2 Sätze: ruhig, umsetzbar, keine Panik\n"
        )
        no_data_clause = (
            "Nutze NUR das untenstehende Feed-Digest, WATCH ITEMS und INTEL ENTITIES. "
            "Wenn ein Abschnitt keine Daten hat, schreibe klar, dass die Feeds dort "
            "nichts Auffälliges zeigen (keine Ereignisse erfinden). "
            "Bei WATCH ITEMS: in RECOMMENDATION erwähnen, wenn relevant — "
            "keine zusätzlichen Watch-Themen erfinden. "
            "Bei INTEL ENTITIES: nenne konkrete Akteure/Orte/Ereignisse aus dem FtM-Graph, "
            "nicht generische Feed-Schlagzeilen wiederholen. "
            "Keine Sport-, Unterhaltungs- oder Promi-Themen. "
            "Digest-Zeilen mit [Datum]-Präfix: Zeitpunkt im Protokoll wiedergeben; "
            "Zeilen ohne Datum sind Feed-Snapshots (Sensor/Catalog), keine Breaking-News-Schlagzeilen."
        )
        digest_header = "--- DIGEST"
        protocol_label = "Protokoll:"
        final_reminder = (
            "WICHTIG: Schreibe den gesamten Protokoll-Text auf Deutsch. "
            "Behalte die Labels LOCAL / REGION / GLOBAL / CYBER & INFRA / MARITIME ANOMALIES / SATELLITE CHANGE DETECTION / RECOMMENDATION "
            "wörtlich auf Englisch — der Fließtext darunter MUSS deutsch sein."
        )
    else:
        section_hints = (
            f"LOCAL ({region}) — what matters at home in the last 24h\n"
            "REGION — ASEAN / neighbours / West Asia (Iran, Hormuz, Persian Gulf, Levant) if relevant\n"
            "GLOBAL — rest of the world that still matters to an informed resident\n"
            "CYBER & INFRA — KEV, nodes, space weather, markets, air quality if present\n"
            "MARITIME ANOMALIES — AIS pattern-of-life (always include, even if no anomalies)\n"
            "SATELLITE CHANGE DETECTION — Sentinel-2 NDVI change (always include, even if no anomalies)\n"
            "ANOMALY ALERT — Isolation Forest feed anomalies (always include, even if no anomalies)\n"
            "RECOMMENDATION — 1–2 sentences: calm, actionable, no panic\n"
        )
        no_data_clause = (
            "Use ONLY the feed digest, WATCH ITEMS, and INTEL ENTITIES below. "
            "If a section has no data, say clearly that feeds show nothing notable "
            "(do not invent events). For WATCH ITEMS: reflect them in RECOMMENDATION "
            "when relevant — do not add watch topics not listed. "
            "For INTEL ENTITIES: name specific actors/places/events from the FtM graph; "
            "do not repeat generic feed headlines. "
            "Omit sports, entertainment, and celebrity news. "
            "When digest lines include a [date] prefix, reflect that timing in the protocol; "
            "lines without a date are feed snapshots (sensors/catalog), not breaking headlines."
        )
        digest_header = "--- DIGEST"
        protocol_label = "Protocol:"
        final_reminder = "Reminder: write the entire protocol body in English."

    intel_prompt = ""
    try:
        import intel_briefing

        intel_prompt = intel_briefing.format_intel_prompt_block(
            digest.get("intel") or {},
            lang=lang,
        )
    except Exception:
        intel_prompt = "- Intel graph unavailable."

    rag_block = ""
    try:
        from briefing_agentic import format_rag_recall_block

        rag_block = format_rag_recall_block(digest.get("rag_recall"), lang=lang)
        if rag_block:
            rag_block = f"{rag_block}\n\n"
    except Exception:
        rag_block = ""

    prompt = (
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
        "REGION signals:\n" + "\n".join(digest["regional"]) + "\n\n"
        "GLOBAL signals:\n" + "\n".join(digest["global"]) + "\n\n"
        f"{intel_prompt}\n\n"
        f"{_prediction_calibration_line(lang=lang)}\n\n"
        f"WATCH ITEMS (monitor over stated horizon — do not invent more):\n"
        f"{format_watch_items_block(digest.get('watch_items') or [], lang=lang)}\n\n"
        f"{rag_block}"
        f"Fusion hotspots (spatial grid):\n{digest['fusion']}\n\n"
        f"Cyber (CISA KEV):\n" + "\n".join(digest["cyber"]) + "\n\n"
        "Infra:\n" + "\n".join(f"- {x}" for x in digest["infra"]) + "\n\n"
    )
    darkweb = digest.get("darkweb") or {}
    if darkweb.get("enabled") and darkweb.get("lines"):
        if is_de:
            prompt += "DARK WEB / Darknet:\n" + "\n".join(darkweb["lines"]) + "\n\n"
        else:
            prompt += "DARK WEB / Darknet:\n" + "\n".join(darkweb["lines"]) + "\n\n"
    ransomware = digest.get("ransomware") or {}
    if ransomware.get("enabled") and ransomware.get("lines"):
        prompt += "RANSOMWARE VICTIMS (24h, passive metadata only):\n"
        for line in ransomware["lines"]:
            prompt += f"  - {line.get('text')}\n"
        prompt += "\n"
    telegram = digest.get("telegram") or {}
    if telegram.get("enabled") and telegram.get("lines"):
        prompt += "TELEGRAM SOCMINT (24h, allow-listed public channels only):\n"
        for line in telegram["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    identity = digest.get("identity") or {}
    if identity.get("enabled") and identity.get("lines"):
        prompt += "IDENTITY OSINT (recent lookups, passive existence checks only):\n"
        for line in identity["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    domain = digest.get("domain") or {}
    if domain.get("enabled") and domain.get("lines"):
        prompt += "DOMAIN INTEL (CT logs, Wayback, RDAP — passive reconnaissance):\n"
        for line in domain["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    thai = digest.get("thai") or {}
    if thai.get("enabled") and thai.get("lines"):
        prompt += "THAI OPEN DATA (data.go.th — environmental & government datasets):\n"
        for line in thai["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    spaceweather = digest.get("spaceweather") or {}
    if spaceweather.get("enabled"):
        prompt += "SPACE WEATHER (NOAA SWPC, 24h):\n"
        if spaceweather.get("lines"):
            for line in spaceweather.get("lines"):
                prompt += f"  - {line}\n"
        else:
            prompt += "  - No significant space weather activity.\n"
        prompt += "\n"
    maritime = digest.get("maritime") or {}
    if maritime.get("enabled"):
        prompt += "MARITIME ANOMALIES (AIS pattern-of-life, 24h):\n"
        if maritime.get("lines"):
            for line in maritime["lines"]:
                prompt += f"  - {line.get('text', line)}\n"
        else:
            prompt += "  - No anomalies detected (threshold 0.6).\n"
        prompt += "\n"
    satellite = digest.get("satellite_change") or {}
    if satellite.get("enabled"):
        prompt += "SATELLITE CHANGE DETECTION (Sentinel-2 NDVI, 30-day window):\n"
        if satellite.get("lines"):
            for line in satellite["lines"]:
                prompt += f"  - {line.get('text', line)}\n"
        else:
            prompt += "  - No significant NDVI anomalies detected.\n"
        prompt += "\n"
    forecast = digest.get("forecast") or {}
    if forecast.get("enabled") and forecast.get("lines"):
        prompt += "FORECAST (Predictive Analytics, next 24h):\n"
        for line in forecast["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    anomaly = digest.get("anomaly") or {}
    if anomaly.get("enabled"):
        prompt += "ANOMALY ALERT (Isolation Forest, feed time series):\n"
        if anomaly.get("lines"):
            for line in anomaly["lines"]:
                prompt += f"  - {line.get('text', line)}\n"
        else:
            prompt += "  - No anomalies detected in last 24h.\n"
        prompt += "\n"
    acled = digest.get("acled") or {}
    if acled.get("enabled"):
        prompt += "CONFLICT EVENTS (ACLED, last 7 days):\n"
        if acled.get("lines"):
            for line in acled["lines"]:
                prompt += f"  - {line}\n"
        else:
            prompt += "  - No conflict events reported.\n"
        prompt += "\n"
    weather_fc = digest.get("weather_forecast") or {}
    if weather_fc.get("enabled") and weather_fc.get("lines"):
        prompt += "WEATHER FORECAST (Open-Meteo, 7-day, severe weather alerts):\n"
        for line in weather_fc["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    lightning = digest.get("lightning") or {}
    if lightning.get("enabled") and lightning.get("lines"):
        prompt += "LIGHTNING ACTIVITY (Blitzortung, recent strikes):\n"
        for line in lightning["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    osm = digest.get("osm") or {}
    if osm.get("enabled") and osm.get("lines"):
        prompt += "CRITICAL INFRASTRUCTURE (OSM Overpass POIs):\n"
        for line in osm["lines"]:
            prompt += f"  - {line}\n"
        prompt += "\n"
    prompt += (
        "Edge nodes:\n"
        + "\n".join(digest["nodes"])
        + "\n\n"
        + final_reminder
        + "\n\n"
        + protocol_label
    )
    _approx_tokens = len(prompt) // 4
    logger.info(
        "briefing prompt: %d chars, ~%d tokens (lang=%s, region=%s)",
        len(prompt),
        _approx_tokens,
        lang,
        region,
    )
    return prompt


def format_fallback_protocol(digest: dict[str, Any], lang: str | None = None) -> str:
    region = digest.get("region_label", "Thailand")
    lang = _resolve_lang(lang or digest.get("lang"))
    watch_items = digest.get("watch_items") or []
    intel_items = digest.get("intel", {}).get("items") or []
    if lang.startswith("de"):
        parts = [
            f"LOKAL ({region}): " + " ".join(digest["local"]).replace("- ", ""),
            "REGION: " + " ".join(digest["regional"]).replace("- ", ""),
            "GLOBAL: " + " ".join(digest["global"][:3]).replace("- ", ""),
            "Fusion: " + digest["fusion"].replace("\n", " "),
        ]
        if watch_items:
            parts.append(
                "WATCH: "
                + "; ".join(
                    f"{w.get('title', '')[:60]} ({w.get('horizon_h')}h)"
                    for w in watch_items[:3]
                )
            )
        if intel_items:
            parts.append(
                "INTEL: " + " ".join(i.get("text", "") for i in intel_items[:4])
            )
        parts.append(
            "EMPFEHLUNG: LLM offline — Rohdaten oben prüfen; keine automatische Bewertung."
        )
        anomaly = digest.get("anomaly") or {}
        if anomaly.get("enabled") and anomaly.get("lines"):
            parts.append(
                "ANOMALIE: "
                + "; ".join(line.get("text", "")[:80] for line in anomaly["lines"][:3])
            )
        return "\n\n".join(parts)
    parts = [
        f"LOCAL ({region}): " + " ".join(digest["local"]).replace("- ", ""),
        "REGION: " + " ".join(digest["regional"]).replace("- ", ""),
        "GLOBAL: " + " ".join(digest["global"][:3]).replace("- ", ""),
        "Fusion: " + digest["fusion"].replace("\n", " "),
    ]
    if watch_items:
        parts.append(
            "WATCH: "
            + "; ".join(
                f"{w.get('title', '')[:60]} ({w.get('horizon_h')}h)"
                for w in watch_items[:3]
            )
        )
    if intel_items:
        parts.append("INTEL: " + " ".join(i.get("text", "") for i in intel_items[:4]))
    parts.append("NOTE: LLM offline — review raw digest above.")
    anomaly = digest.get("anomaly") or {}
    if anomaly.get("enabled") and anomaly.get("lines"):
        parts.append(
            "ANOMALY: "
            + "; ".join(line.get("text", "")[:80] for line in anomaly["lines"][:3])
        )
    return "\n\n".join(parts)
