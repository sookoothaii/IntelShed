"""Ransomware briefing bridge (P8.6) — turns leak-site victims into digest signals.

Integrates with ``ransomware_tracker`` (victim metadata), ``ftm_query`` (entity
graph), and ``briefing_digest`` / ``briefing_prompt`` (24h digest pipeline).

Design constraints:
- Max 5 ransomware lines in the prompt (prompt budget).
- Prioritisation: FTM correlation > operator region > SEA/APAC > global.
- Passive metadata only: victim name, group, date, country, sector. No leaked
  files, documents, or archives are downloaded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from config import get_config


# Country ISO-3166 alpha-2 mapping for operator regions.
_OPERATOR_REGION_COUNTRIES: dict[str, list[str]] = {
    "thailand": ["TH", "MM", "LA", "KH", "VN", "MY", "ID", "SG", "PH", "BN"],
    "global": [],
}

# Broad APAC set (used when operator region is Thailand/SEA).
_APAC_COUNTRIES: set[str] = {
    "CN",
    "JP",
    "KR",
    "IN",
    "AU",
    "NZ",
    "BD",
    "NP",
    "PK",
    "LK",
    "TW",
    "HK",
    "MO",
    "MN",
    "BT",
    "MV",
}

# High-profile groups that should nudge the score up slightly.
_HIGH_PROFILE_GROUPS: set[str] = {
    "lockbit",
    "lockbit3",
    "qilin",
    "akira",
    "play",
    "blackcat",
    "alphv",
    "clop",
    "cl0p",
    "royal",
    "blackbasta",
    "medusa",
    "the_gentlemen",
    "inc ransom",
    "ransom house",
    "everest",
    "dragon force",
    "world leaks",
    "datacarry",
}


@dataclass
class RansomwareDigestLine:
    group_name: str
    victim_name: str
    victim_country: str
    victim_industry: str
    date_discovered: str
    data_size_gb: float | None
    is_correlated_to_ftm: bool
    relevance_score: float


class DarkwebBriefingBridge:
    """Select and prioritise ransomware victims for the 24h briefing."""

    def __init__(self, ftm_query: Any | None = None, config: Any | None = None):
        self.ftm_query = ftm_query
        self.config = config or get_config()
        self.operator_countries = _operator_countries(self.config.operator_region)

    def _find_ftm_match(self, victim_name: str) -> dict[str, Any] | None:
        """Find an FtM entity whose name/caption contains the victim name.

        Searches ``Organization``, ``Company``, ``Person``, ``LegalEntity`` and
        falls back to any entity whose caption/name is a close match.
        """
        if not victim_name or not self.ftm_query:
            return None
        try:
            entities = self.ftm_query.list_entities(limit=2000)
        except Exception:
            return None
        name_lower = victim_name.lower()
        best: dict[str, Any] | None = None
        best_score = 0.0
        for ent in entities:
            schema = (ent.get("schema") or "").lower()
            if schema not in {
                "organization",
                "company",
                "person",
                "legalentity",
                "publicbody",
                "vessel",
                "airplane",
                "vehicle",
                "asset",
                "crypto",
            }:
                continue
            caption = (ent.get("caption") or "").lower()
            props = ent.get("properties") or {}
            names = []
            for key in ("name", "alias", "weakAlias", "legalForm", "title"):
                vals = props.get(key) or []
                if isinstance(vals, list):
                    names.extend(vals)
                elif isinstance(vals, str):
                    names.append(vals)
            candidate_texts = [caption] + [n.lower() for n in names]
            for text in candidate_texts:
                if not text:
                    continue
                if name_lower == text:
                    score = 1.0
                elif name_lower in text:
                    score = 0.8
                elif text in name_lower:
                    score = 0.6
                else:
                    score = 0.0
                if score > best_score:
                    best_score = score
                    best = ent
        if best_score >= 0.8:
            return best
        return None

    def _score_victim(self, victim: dict[str, Any]) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        group = (victim.get("group") or "").lower()
        country = (victim.get("country") or "").upper()
        victim_name = victim.get("victim") or ""

        # 1. FTM correlation — highest priority
        ftm_match = self._find_ftm_match(victim_name)
        if ftm_match:
            score += 0.5
            reasons.append("ftm_correlated")

        # 2. Operator region / SEA
        if country in self.operator_countries:
            score += 0.3
            reasons.append("operator_region")
        elif country in _APAC_COUNTRIES:
            score += 0.15
            reasons.append("apac")

        # 3. Data volume
        data_size = self._extract_data_size_gb(victim)
        if data_size and data_size > 100:
            score += 0.1
            reasons.append("large_exfil")

        # 4. High-profile group
        if group in _HIGH_PROFILE_GROUPS:
            score += 0.1
            reasons.append("high_profile_group")

        return min(score, 1.0), reasons

    @staticmethod
    def _extract_data_size_gb(victim: dict[str, Any]) -> float | None:
        desc = victim.get("description") or ""
        # Naive regex: e.g. "50GB", "1.5 TB"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|TB|MB)", desc, re.I)
        if not m:
            return None
        val = float(m.group(1))
        unit = m.group(2).upper()
        if unit == "TB":
            return val * 1000
        if unit == "MB":
            return val / 1000
        return val

    async def gather_ransomware_digest(
        self, hours: int = 24, max_lines: int = 5
    ) -> dict[str, Any]:
        """Fetch recent victims and return selected lines + metadata.

        Fail-soft when disabled or when APIs fail.
        """
        cfg = self.config
        if not getattr(cfg, "ransomware_enabled", False):
            return {"enabled": False, "count": 0, "lines": [], "victims": []}

        try:
            import ransomware_tracker

            data = await ransomware_tracker.get_recent_victims(limit=100, refresh=False)
        except Exception:
            return {"enabled": True, "count": 0, "lines": [], "victims": []}

        victims = data.get("victims", [])
        scored: list[tuple[float, list[str], dict[str, Any]]] = []
        for v in victims:
            score, reasons = self._score_victim(v)
            scored.append((score, reasons, v))

        scored.sort(key=lambda x: (-x[0], x[2].get("discovered", "")), reverse=False)
        top = scored[:max_lines]

        lines: list[dict[str, Any]] = []
        for score, reasons, v in top:
            group = (v.get("group") or "unknown").upper()
            victim_name = v.get("victim") or "unknown"
            country = v.get("country") or "Unknown"
            activity = v.get("activity") or "Unknown"
            discovered = v.get("discovered") or ""
            size_gb = self._extract_data_size_gb(v)
            ftm_match = self._find_ftm_match(victim_name)
            is_correlated = ftm_match is not None

            tags = []
            if is_correlated:
                tags.append("CORRELATED")
            if "operator_region" in reasons:
                tags.append("REGION")
            if size_gb and size_gb > 100:
                tags.append("LARGE_EXFIL")

            text = f"[{group}] {victim_name} ({country}, {activity})"
            if size_gb:
                text += f" — {size_gb:.0f}GB"
            if discovered:
                text += f" — {discovered[:10]}"
            if tags:
                text += f" [{', '.join(tags)}]"
            if is_correlated and ftm_match:
                text += f" — matches FtM {ftm_match.get('schema', 'Entity')} {ftm_match.get('id', '')}"

            lines.append(
                {
                    "text": text,
                    "group": group,
                    "victim": victim_name,
                    "country": country,
                    "industry": activity,
                    "discovered": discovered,
                    "data_size_gb": size_gb,
                    "relevance_score": score,
                    "is_correlated_to_ftm": is_correlated,
                    "ftm_entity_id": ftm_match.get("id") if ftm_match else None,
                    "sources": [v.get("source", "ransomware.tracker")],
                    "source": "darkweb_ransomware",
                    "severity": "critical"
                    if is_correlated
                    else "high"
                    if score > 0.6
                    else "medium",
                }
            )

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "victims": [v for _, _, v in top],
        }

    def format_prompt_block(self, lines: list[dict[str, Any]]) -> str:
        """Format selected lines for the LLM prompt."""
        if not lines:
            return ""
        block = ["RANSOMWARE VICTIMS (24h, passive metadata only):"]
        for line in lines:
            block.append(f"  - {line['text']}")
        return "\n".join(block)

    def build_watch_items(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate watch items for FTM-correlated or high-score victims."""
        items: list[dict[str, Any]] = []
        for line in lines:
            if (
                not line.get("is_correlated_to_ftm")
                and line.get("relevance_score", 0) < 0.6
            ):
                continue
            items.append(
                {
                    "id": f"ransomware:{line['group']}:{line['victim']}",
                    "prefix": "ransomware",
                    "title": (
                        f"Ransomware monitor: {line['group']} → {line['victim']} "
                        f"({line['country']}, {line['industry']})"
                    ),
                    "horizon_h": 72,
                    "confidence": line.get("relevance_score", 0.5),
                    "sources": line.get("sources", ["darkweb_ransomware"]),
                    "bucket": (
                        "local"
                        if line.get("country") == "TH"
                        else "regional"
                        if line.get("country") in self.operator_countries
                        else "global"
                    ),
                    "entity_id": line.get("ftm_entity_id"),
                }
            )
        return items


def _operator_countries(region: str) -> list[str]:
    return _OPERATOR_REGION_COUNTRIES.get(region.lower(), [])


async def gather_ransomware_briefing(
    hours: int = 24, max_lines: int = 5
) -> dict[str, Any]:
    """Convenience async entry point used by ``node_briefing``."""
    try:
        import ftm_query

        bridge = DarkwebBriefingBridge(ftm_query=ftm_query)
    except Exception:
        bridge = DarkwebBriefingBridge()
    return await bridge.gather_ransomware_digest(hours=hours, max_lines=max_lines)


def build_ransomware_watch_items(
    digest: dict[str, Any], config: Any | None = None
) -> list[dict[str, Any]]:
    """Convenience sync entry point used by ``briefing_digest``."""
    cfg = config or get_config()
    bridge = DarkwebBriefingBridge(config=cfg)
    return bridge.build_watch_items(digest.get("lines", []))


def format_ransomware_block(digest: dict[str, Any]) -> str:
    """Convenience sync entry point used by ``briefing_prompt``."""
    if not digest.get("enabled") or not digest.get("lines"):
        return ""
    bridge = DarkwebBriefingBridge()
    return bridge.format_prompt_block(digest["lines"])
