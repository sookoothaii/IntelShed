"""LLM prompt building and fallback protocol for operator briefing.

Extracted from operator_briefing.py (Phase 2). Builds the security-advisor
prompt from a digest dict and provides a fallback protocol when the LLM
is offline.
"""

from __future__ import annotations

from typing import Any

from briefing_digest import _resolve_lang, format_watch_items_block


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
        final_reminder = (
            "Reminder: write the entire protocol body in English."
        )

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
        f"{_prediction_calibration_line(lang=lang)}\n\n"
        f"WATCH ITEMS (monitor over stated horizon — do not invent more):\n"
        f"{format_watch_items_block(digest.get('watch_items') or [], lang=lang)}\n\n"
        f"{rag_block}"
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
    return "\n\n".join(parts)
