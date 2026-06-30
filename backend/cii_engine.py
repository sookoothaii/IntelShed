"""Country Instability Index (CII) — 0-100 risk score per country.

Calculates a composite instability score from four weighted signal families:
  Conflict (40%), Economy (20%), Climate (20%), Governance (20%)

Data sources:
  - GDELT local pulse + geo events (theme-based classification)
  - NewsData articles (category/title keyword classification)
  - ACLED conflict events (when credentials available)

Snapshots are stored in SQLite (``cii_snapshots`` table) for 24h delta
and 7-day trend calculation.

API endpoints:
  GET /api/cii/country?code=TH   — single country CII breakdown
  GET /api/cii/rankings           — all countries ranked by CII

Feature flag: ``WORLDBASE_CII=1`` (default on).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cii", tags=["cii"])

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

_CACHE_TTL = float(os.getenv("WORLDBASE_CII_CACHE_SEC", "300"))
_mem_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _enabled() -> bool:
    return os.getenv("WORLDBASE_CII", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Country code mapping (ISO2 ↔ ISO3 ↔ name)
# ---------------------------------------------------------------------------

_ISO2_TO_ISO3: dict[str, str] = {
    "TH": "THA",
    "MM": "MMR",
    "LA": "LAO",
    "KH": "KHM",
    "VN": "VNM",
    "PH": "PHL",
    "MY": "MYS",
    "SG": "SGP",
    "BN": "BRN",
    "ID": "IDN",
    "CN": "CHN",
    "JP": "JPN",
    "KR": "KOR",
    "IN": "IND",
    "PK": "PAK",
    "BD": "BGD",
    "LK": "LKA",
    "AF": "AFG",
    "IR": "IRN",
    "IQ": "IRQ",
    "SY": "SYR",
    "YE": "YEM",
    "SA": "SAU",
    "AE": "ARE",
    "IL": "ISR",
    "PS": "PSE",
    "JO": "JOR",
    "LB": "LBN",
    "TR": "TUR",
    "EG": "EGY",
    "LY": "LBY",
    "SD": "SDN",
    "SS": "SSD",
    "ET": "ETH",
    "SO": "SOM",
    "KE": "KEN",
    "NG": "NGA",
    "ZA": "ZAF",
    "RU": "RUS",
    "UA": "UKR",
    "BY": "BLR",
    "PL": "POL",
    "DE": "DEU",
    "FR": "FRA",
    "GB": "GBR",
    "US": "USA",
    "CA": "CAN",
    "MX": "MEX",
    "BR": "BRA",
    "AR": "ARG",
    "CO": "COL",
    "VE": "VEN",
    "CL": "CHL",
    "PE": "PER",
    "BO": "BOL",
    "AU": "AUS",
    "NZ": "NZL",
    "PG": "PNG",
    "FJ": "FJI",
    "KP": "PRK",
    "TW": "TWN",
    "HK": "HKG",
    "MO": "MAC",
    "KZ": "KAZ",
    "UZ": "UZB",
    "TM": "TKM",
    "KG": "KGZ",
    "TJ": "TJK",
    "MN": "MNG",
    "NP": "NPL",
    "BT": "BTN",
    "MV": "MDV",
    "TL": "TLS",
    "ES": "ESP",
    "IT": "ITA",
    "PT": "PRT",
    "NL": "NLD",
    "BE": "BEL",
    "CH": "CHE",
    "AT": "AUT",
    "SE": "SWE",
    "NO": "NOR",
    "DK": "DNK",
    "FI": "FIN",
    "IE": "IRL",
    "GR": "GRC",
    "CZ": "CZE",
    "SK": "SVK",
    "HU": "HUN",
    "RO": "ROU",
    "BG": "BGR",
    "RS": "SRB",
    "HR": "HRV",
    "SI": "SVN",
    "BA": "BIH",
    "MK": "MKD",
    "AL": "ALB",
    "XK": "XKX",
    "MD": "MDA",
    "GE": "GEO",
    "AM": "ARM",
    "AZ": "AZE",
}

_ISO3_TO_NAME: dict[str, str] = {
    "THA": "Thailand",
    "MMR": "Myanmar",
    "LAO": "Laos",
    "KHM": "Cambodia",
    "VNM": "Vietnam",
    "PHL": "Philippines",
    "MYS": "Malaysia",
    "SGP": "Singapore",
    "BRN": "Brunei",
    "IDN": "Indonesia",
    "CHN": "China",
    "JPN": "Japan",
    "KOR": "South Korea",
    "IND": "India",
    "PAK": "Pakistan",
    "BGD": "Bangladesh",
    "LKA": "Sri Lanka",
    "AFG": "Afghanistan",
    "IRN": "Iran",
    "IRQ": "Iraq",
    "SYR": "Syria",
    "YEM": "Yemen",
    "SAU": "Saudi Arabia",
    "ARE": "UAE",
    "ISR": "Israel",
    "PSE": "Palestine",
    "JOR": "Jordan",
    "LBN": "Lebanon",
    "TUR": "Turkey",
    "EGY": "Egypt",
    "LBY": "Libya",
    "SDN": "Sudan",
    "SSD": "South Sudan",
    "ETH": "Ethiopia",
    "SOM": "Somalia",
    "KEN": "Kenya",
    "NGA": "Nigeria",
    "ZAF": "South Africa",
    "RUS": "Russia",
    "UKR": "Ukraine",
    "BLR": "Belarus",
    "POL": "Poland",
    "DEU": "Germany",
    "FRA": "France",
    "GBR": "United Kingdom",
    "USA": "United States",
    "CAN": "Canada",
    "MEX": "Mexico",
    "BRA": "Brazil",
    "ARG": "Argentina",
    "COL": "Colombia",
    "VEN": "Venezuela",
    "CHL": "Chile",
    "PER": "Peru",
    "BOL": "Bolivia",
    "AUS": "Australia",
    "NZL": "New Zealand",
    "PNG": "Papua New Guinea",
    "FJI": "Fiji",
    "PRK": "North Korea",
    "TWN": "Taiwan",
    "HKG": "Hong Kong",
    "MAC": "Macao",
    "KAZ": "Kazakhstan",
    "UZB": "Uzbekistan",
    "TKM": "Turkmenistan",
    "KGZ": "Kyrgyzstan",
    "TJK": "Tajikistan",
    "MNG": "Mongolia",
    "NPL": "Nepal",
    "BTN": "Bhutan",
    "MDV": "Maldives",
    "TLS": "Timor-Leste",
    "ESP": "Spain",
    "ITA": "Italy",
    "PRT": "Portugal",
    "NLD": "Netherlands",
    "BEL": "Belgium",
    "CHE": "Switzerland",
    "AUT": "Austria",
    "SWE": "Sweden",
    "NOR": "Norway",
    "DNK": "Denmark",
    "FIN": "Finland",
    "IRL": "Ireland",
    "GRC": "Greece",
    "CZE": "Czechia",
    "SVK": "Slovakia",
    "HUN": "Hungary",
    "ROU": "Romania",
    "BGR": "Bulgaria",
    "SRB": "Serbia",
    "HRV": "Croatia",
    "SVN": "Slovenia",
    "BIH": "Bosnia",
    "MKD": "North Macedonia",
    "ALB": "Albania",
    "XKX": "Kosovo",
    "MDA": "Moldova",
    "GEO": "Georgia",
    "ARM": "Armenia",
    "AZE": "Azerbaijan",
}

_NAME_TO_ISO2: dict[str, str] = {}
for _iso2, _iso3 in _ISO2_TO_ISO3.items():
    _name = _ISO3_TO_NAME.get(_iso3, "")
    if _name:
        _NAME_TO_ISO2[_name.lower()] = _iso2


def normalize_country_code(code: str) -> str:
    """Accept ISO2, ISO3, or country name → return ISO2 (uppercase)."""
    code = code.strip().upper()
    if len(code) == 2 and code in _ISO2_TO_ISO3:
        return code
    if len(code) == 3:
        for iso2, iso3 in _ISO2_TO_ISO3.items():
            if iso3 == code:
                return iso2
    # Try name lookup
    iso2 = _NAME_TO_ISO2.get(code.lower())
    if iso2:
        return iso2
    # Fallback: return as-is if 2 chars
    return code[:2] if len(code) >= 2 else code


def iso2_to_iso3(code: str) -> str:
    return _ISO2_TO_ISO3.get(code.upper(), code.upper())


def iso2_to_name(code: str) -> str:
    iso3 = _ISO2_TO_ISO3.get(code.upper())
    if iso3:
        return _ISO3_TO_NAME.get(iso3, code)
    return code


# ---------------------------------------------------------------------------
# Signal family keyword sets
# ---------------------------------------------------------------------------

_CONFLICT_KEYWORDS = re.compile(
    r"\b(armed|battle|clash|attack|airstrike|bombing|shelling|missile|"
    r"drone strike|explosion|casualt|fatalit|killed|wounded|combat|"
    r"insurgen|militia|rebel|coup|martial law|curfew|border.*incident|"
    r"cross.?border|skirmish|offensive|siege|massacre|warlord|"
    r"paramilitary|guerrilla|terror|extremist|jihad|sectarian)",
    re.IGNORECASE,
)

_ECONOMY_KEYWORDS = re.compile(
    r"\b(inflation|currency.*crisis|devaluation|recession|economic.*crisis|"
    r"default|bankrupt|unemployment|food.*price|fuel.*price|supply.*chain|"
    r"shortage|sanction|trade.*war|tariff|embargo|debt.*crisis|"
    r"financial.*crisis|market.*crash|capital.*flight|austerity|"
    r"currency.*collapse|hyperinflation|stagnation|poverty|famine)",
    re.IGNORECASE,
)

_CLIMATE_KEYWORDS = re.compile(
    r"\b(flood|drought|cyclone|typhoon|hurricane|earthquake|tsunami|"
    r"landslide|wildfire|heatwave|cold.*snap|storm|disaster|"
    r"climate|el nino|la nina|monsoon|avalanche|volcan|"
    r"sea.*level|erosion|desertification|water.*shortage|"
    r"crop.*failure|food.*security|humanitarian.*crisis|evacuat)",
    re.IGNORECASE,
)

_GOVERNANCE_KEYWORDS = re.compile(
    r"\b(protest|march|demonstration|riot|unrest|strike|labor.*dispute|"
    r"corruption|scandal|impeach|resign|dissolve.*parliament|"
    r"election.*violence|vote.*rigging|authoritarian|crackdown|"
    r"oppression|censorship|press.*freedom|human.*rights|civil.*liberties|"
    r"political.*prisoner|opposition.*arrest|martial|emergency.*rule|"
    r"constitutional.*crisis|regime|junta|military.*council|"
    r"no.?confidence|referendum|uprising|revolt|civil.*disobedience)",
    re.IGNORECASE,
)

_CONFLICT_THEMES = {
    "ARMEDCONFLICT",
    "TERROR",
    "MILITARY",
    "WAR",
    "SECURITY",
    "REFUGEES",
    "INTERNAL_CONFLICT",
}
_ECONOMY_THEMES = {
    "ECON",
    "TRADE",
    "FINANCIAL",
    "FOOD",
    "ENERGY",
    "SANCTIONS",
}
_CLIMATE_THEMES = {
    "DISASTER",
    "ENV",
    "DROUGHT",
    "FLOOD",
    "EARTHQUAKE",
    "WILDFIRES",
    "EPIDEMIC",
}
_GOVERNANCE_THEMES = {
    "PROTEST",
    "ELECTION",
    "GOV",
    "HUMAN_RIGHTS",
    "CORRUPTION",
    "OPPOSITION",
    "LEGITIMACY",
}


# ---------------------------------------------------------------------------
# Signal family weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "conflict": 0.40,
    "economy": 0.20,
    "climate": 0.20,
    "governance": 0.20,
}


# ---------------------------------------------------------------------------
# SQLite snapshot storage
# ---------------------------------------------------------------------------


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_table() -> None:
    try:
        with _conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS cii_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    country_code TEXT NOT NULL,
                    score REAL NOT NULL,
                    conflict REAL NOT NULL,
                    economy REAL NOT NULL,
                    climate REAL NOT NULL,
                    governance REAL NOT NULL,
                    article_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_cii_country_time "
                "ON cii_snapshots(country_code, recorded_at DESC)"
            )
            c.commit()
    except Exception as exc:
        log.warning("cii: table init failed: %s", exc)


def _save_snapshot(scores: dict[str, dict[str, Any]]) -> None:
    """Persist all country scores to SQLite."""
    _ensure_table()
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _conn() as c:
            for code, data in scores.items():
                c.execute(
                    "INSERT INTO cii_snapshots "
                    "(recorded_at, country_code, score, conflict, economy, "
                    "climate, governance, article_count, event_count, raw_json) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        now,
                        code,
                        data["score"],
                        data["conflict"],
                        data["economy"],
                        data["climate"],
                        data["governance"],
                        data.get("article_count", 0),
                        data.get("event_count", 0),
                        json.dumps(data),
                    ),
                )
            c.commit()
    except Exception as exc:
        log.warning("cii: snapshot save failed: %s", exc)


def _load_previous_snapshot(
    country_code: str, hours_ago: int = 24
) -> dict[str, Any] | None:
    """Load the most recent snapshot older than hours_ago for delta calculation."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT * FROM cii_snapshots "
                "WHERE country_code = ? AND recorded_at <= ? "
                "ORDER BY recorded_at DESC LIMIT 1",
                (country_code, cutoff),
            ).fetchone()
            if row:
                return {
                    "score": row["score"],
                    "conflict": row["conflict"],
                    "economy": row["economy"],
                    "climate": row["climate"],
                    "governance": row["governance"],
                    "recorded_at": row["recorded_at"],
                }
    except Exception:
        pass
    return None


def _load_trend(country_code: str, days: int = 7) -> list[dict[str, Any]]:
    """Load daily snapshots for trend calculation."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT recorded_at, score FROM cii_snapshots "
                "WHERE country_code = ? AND recorded_at >= ? "
                "ORDER BY recorded_at ASC",
                (country_code, cutoff),
            ).fetchall()
            return [{"date": r["recorded_at"], "score": r["score"]} for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Signal extraction from feed data
# ---------------------------------------------------------------------------


def _classify_article(text: str, themes: list[str] | None = None) -> list[str]:
    """Return list of signal families matched by this article."""
    families: list[str] = []

    # Theme-based classification (GDELT)
    if themes:
        theme_set = {t.upper() for t in themes}
        if theme_set & _CONFLICT_THEMES:
            families.append("conflict")
        if theme_set & _ECONOMY_THEMES:
            families.append("economy")
        if theme_set & _CLIMATE_THEMES:
            families.append("climate")
        if theme_set & _GOVERNANCE_THEMES:
            families.append("governance")

    # Keyword-based classification (fallback / supplement)
    if _CONFLICT_KEYWORDS.search(text):
        if "conflict" not in families:
            families.append("conflict")
    if _ECONOMY_KEYWORDS.search(text):
        if "economy" not in families:
            families.append("economy")
    if _CLIMATE_KEYWORDS.search(text):
        if "climate" not in families:
            families.append("climate")
    if _GOVERNANCE_KEYWORDS.search(text):
        if "governance" not in families:
            families.append("governance")

    return families


def _extract_country_from_article(article: dict) -> str | None:
    """Try to extract an ISO2 country code from article metadata."""
    # NewsData: country_code field
    cc = article.get("country_code") or article.get("country")
    if cc:
        code = normalize_country_code(str(cc))
        if code in _ISO2_TO_ISO3:
            return code
    # GDELT: country field (full name)
    country = article.get("country")
    if country:
        code = normalize_country_code(str(country))
        if code in _ISO2_TO_ISO3:
            return code
    # Try matching by name in title/description
    text = f"{article.get('title', '')} {article.get('description', '')}"
    text_lower = text.lower()
    for name, iso2 in _NAME_TO_ISO2.items():
        if name in text_lower:
            return iso2
    # Common short forms
    if "thai" in text_lower:
        return "TH"
    return None


def _read_feed_cache(key: str) -> dict[str, Any] | None:
    """Read parsed JSON from SQLite feed_cache table (fallback for peek_memory)."""
    try:
        with _conn() as c:
            row = c.execute(
                "SELECT value FROM feed_cache WHERE key = ?", (key,)
            ).fetchone()
            if row:
                return json.loads(row["value"])
    except Exception:
        pass
    return None


def _gather_gdelt_signals() -> dict[str, dict[str, int]]:
    """Gather GDELT article counts per country per signal family."""
    per_country: dict[str, dict[str, int]] = {}
    try:
        import gdelt_bridge

        for key in ("gdelt_pulse_local", "gdelt_pulse_west_asia", "gdelt_pulse"):
            cached = None
            found_key = key
            try:
                connector = getattr(gdelt_bridge, "_CONNECTOR", None)
                if connector:
                    cached = connector.peek_memory(
                        key.replace("gdelt_pulse_", "").replace("gdelt_pulse", "")
                        or "local"
                    )
            except Exception:
                pass
            if not cached:
                # Fallback: read from SQLite feed_cache
                for ck in (
                    "gdelt_pulse_local:thailand",
                    "gdelt_pulse_local:west-asia",
                    key,
                ):
                    cached = _read_feed_cache(ck)
                    if cached:
                        found_key = ck
                        break
            if not cached:
                continue
            # Infer country hint from cache key for region-specific feeds
            country_hint = None
            for ck_hint, cc_hint in (
                ("thailand", "TH"),
                ("west-asia", None),
                ("iran", "IR"),
                ("hormuz", "IR"),
            ):
                if ck_hint in found_key.lower():
                    country_hint = cc_hint
                    break
            articles = cached.get("articles") or []
            for art in articles:
                code = _extract_country_from_article(art)
                if not code and country_hint:
                    code = country_hint
                if not code:
                    continue
                if code not in per_country:
                    per_country[code] = {
                        "conflict": 0,
                        "economy": 0,
                        "climate": 0,
                        "governance": 0,
                    }
                text = f"{art.get('title', '')} {art.get('description', '')}"
                themes = art.get("themes") or []
                families = _classify_article(text, themes)
                for fam in families:
                    per_country[code][fam] = per_country[code].get(fam, 0) + 1
    except Exception as exc:
        log.debug("cii: GDELT gather failed: %s", exc)
    return per_country


def _gather_newsdata_signals() -> dict[str, dict[str, int]]:
    """Gather NewsData article counts per country per signal family."""
    per_country: dict[str, dict[str, int]] = {}
    try:
        import newsdata_bridge

        connector = getattr(newsdata_bridge, "_CONNECTOR", None)
        cached = None
        if connector:
            cached = connector.peek_memory()
        if not cached:
            # Fallback: read from SQLite feed_cache
            cached = _read_feed_cache("newsdata")
        if not cached:
            return per_country
        articles = cached.get("articles") or []
        for art in articles:
            code = _extract_country_from_article(art)
            if not code:
                continue
            if code not in per_country:
                per_country[code] = {
                    "conflict": 0,
                    "economy": 0,
                    "climate": 0,
                    "governance": 0,
                }
            text = f"{art.get('title', '')} {art.get('description', '')}"
            categories = art.get("category")
            cats = [categories] if isinstance(categories, str) else (categories or [])
            families = _classify_article(text)
            # Map NewsData categories to families
            cat_str = " ".join(cats).lower()
            if any(c in cat_str for c in ("politics", "world", "crime")):
                if "governance" not in families:
                    families.append("governance")
            if any(c in cat_str for c in ("business", "economy")):
                if "economy" not in families:
                    families.append("economy")
            if any(c in cat_str for c in ("environment", "science")):
                if "climate" not in families:
                    families.append("climate")
            for fam in families:
                per_country[code][fam] = per_country[code].get(fam, 0) + 1
    except Exception as exc:
        log.debug("cii: NewsData gather failed: %s", exc)
    return per_country


def _gather_acled_signals() -> dict[str, dict[str, int]]:
    """Gather ACLED event counts per country per signal family."""
    per_country: dict[str, dict[str, int]] = {}
    try:
        import acled_bridge

        connector = getattr(acled_bridge, "_CONNECTOR", None)
        cached = None
        if connector:
            cached = connector.peek_memory()
        if not cached:
            # Fallback: read from SQLite feed_cache
            cached = _read_feed_cache("acled")
        if not cached:
            return per_country
        events = cached.get("events") or []
        for ev in events:
            country_name = ev.get("country") or ""
            code = normalize_country_code(country_name)
            if code not in _ISO2_TO_ISO3:
                continue
            if code not in per_country:
                per_country[code] = {
                    "conflict": 0,
                    "economy": 0,
                    "climate": 0,
                    "governance": 0,
                }
            # ACLED events are conflict by definition
            severity = ev.get("severity", "low")
            weight = 3 if severity == "high" else 2 if severity == "medium" else 1
            per_country[code]["conflict"] += weight
            # Protests/riots → governance
            etype = (ev.get("event_type") or "").lower()
            if "protest" in etype or "riot" in etype:
                per_country[code]["governance"] += weight
    except Exception as exc:
        log.debug("cii: ACLED gather failed: %s", exc)
    return per_country


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------


def _family_score(count: int, max_count: int = 50) -> float:
    """Convert article/event count to 0-100 sub-score using log-diminish."""
    if count <= 0:
        return 0.0
    # Logarithmic scaling: 1 article → ~18, 10 → ~61, 50+ → ~100
    import math

    raw = min(100.0, 100.0 * math.log10(count + 1) / math.log10(51))
    return round(raw, 1)


def _compute_cii(signals: dict[str, int]) -> float:
    """Compute weighted 0-100 CII from family sub-scores."""
    conflict = _family_score(signals.get("conflict", 0))
    economy = _family_score(signals.get("economy", 0))
    climate = _family_score(signals.get("climate", 0))
    governance = _family_score(signals.get("governance", 0))
    score = (
        conflict * _WEIGHTS["conflict"]
        + economy * _WEIGHTS["economy"]
        + climate * _WEIGHTS["climate"]
        + governance * _WEIGHTS["governance"]
    )
    return round(score, 1)


def _risk_band(score: float) -> str:
    if score >= 70:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 30:
        return "moderate"
    if score >= 15:
        return "low"
    return "stable"


def _trend_indicator(trend: list[dict[str, Any]]) -> str:
    """Determine trend from 7-day snapshot series."""
    if len(trend) < 2:
        return "insufficient_data"
    scores = [t["score"] for t in trend]
    first_half = scores[: len(scores) // 2]
    second_half = scores[len(scores) // 2 :]
    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0
    delta = avg_second - avg_first
    if delta > 5:
        return "rising"
    if delta < -5:
        return "falling"
    return "stable"


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------


def compute_all_cii() -> dict[str, dict[str, Any]]:
    """Compute CII for all countries with available feed data."""
    gdelt = _gather_gdelt_signals()
    newsdata = _gather_newsdata_signals()
    acled = _gather_acled_signals()

    # Merge all country codes
    all_codes = set(gdelt) | set(newsdata) | set(acled)

    results: dict[str, dict[str, Any]] = {}
    for code in all_codes:
        signals = {"conflict": 0, "economy": 0, "climate": 0, "governance": 0}
        article_count = 0
        event_count = 0

        for source in (gdelt.get(code), newsdata.get(code)):
            if source:
                for fam in signals:
                    signals[fam] += source.get(fam, 0)
                article_count += sum(source.values())

        acled_data = acled.get(code)
        if acled_data:
            for fam in signals:
                signals[fam] += acled_data.get(fam, 0)
            event_count += sum(acled_data.values())

        conflict = _family_score(signals["conflict"])
        economy = _family_score(signals["economy"])
        climate = _family_score(signals["climate"])
        governance = _family_score(signals["governance"])
        score = _compute_cii(signals)

        results[code] = {
            "country_code": code,
            "country_name": iso2_to_name(code),
            "iso3": iso2_to_iso3(code),
            "score": score,
            "risk_band": _risk_band(score),
            "conflict": conflict,
            "economy": economy,
            "climate": climate,
            "governance": governance,
            "article_count": article_count,
            "event_count": event_count,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    return results


def get_cii_rankings(*, refresh: bool = False) -> dict[str, Any]:
    """Get all countries ranked by CII score (cached)."""
    if not refresh:
        hit = _mem_cache.get("rankings")
        if hit and (time.time() - hit[0]) < _CACHE_TTL:
            return hit[1]

    scores = compute_all_cii()

    # Save snapshot for trend tracking
    if scores:
        _save_snapshot(scores)

    # Enrich with delta + trend
    for code, data in scores.items():
        prev = _load_previous_snapshot(code, hours_ago=24)
        if prev:
            data["delta_24h"] = round(data["score"] - prev["score"], 1)
        else:
            data["delta_24h"] = None
        trend = _load_trend(code, days=7)
        data["trend_7d"] = _trend_indicator(trend)
        data["trend_series"] = trend[-7:]

    ranked = sorted(scores.values(), key=lambda x: -x["score"])

    result = {
        "count": len(ranked),
        "updated": datetime.now(timezone.utc).isoformat(),
        "countries": ranked,
    }
    _mem_cache["rankings"] = (time.time(), result)
    return result


def get_cii_country(code: str, *, refresh: bool = False) -> dict[str, Any]:
    """Get CII breakdown for a single country."""
    iso2 = normalize_country_code(code)
    rankings = get_cii_rankings(refresh=refresh)
    for country in rankings["countries"]:
        if country["country_code"] == iso2:
            return country
    # No data for this country — return zero baseline
    return {
        "country_code": iso2,
        "country_name": iso2_to_name(iso2),
        "iso3": iso2_to_iso3(iso2),
        "score": 0.0,
        "risk_band": "stable",
        "conflict": 0.0,
        "economy": 0.0,
        "climate": 0.0,
        "governance": 0.0,
        "article_count": 0,
        "event_count": 0,
        "delta_24h": None,
        "trend_7d": "insufficient_data",
        "trend_series": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "note": "No feed signals detected for this country in current cycle.",
    }


# ---------------------------------------------------------------------------
# Briefing digest integration
# ---------------------------------------------------------------------------


def gather_cii_digest() -> dict[str, Any]:
    """Synchronous digest for briefing integration (reads cache)."""
    try:
        rankings = get_cii_rankings(refresh=False)
        countries = rankings["countries"][:10]  # Top 10 most unstable
        lines: list[dict[str, str]] = []
        for c in countries:
            if c["score"] < 15:
                continue
            delta = c.get("delta_24h")
            delta_str = f" (Δ{delta:+.1f} 24h)" if delta is not None else ""
            trend = c.get("trend_7d", "")
            trend_str = f" [{trend}]" if trend and trend != "insufficient_data" else ""
            lines.append(
                {
                    "text": f"{c['country_name']} (CII {c['score']}{delta_str}{trend_str})",
                    "country_code": c["country_code"],
                    "score": c["score"],
                    "risk_band": c["risk_band"],
                }
            )
        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "top_country": countries[0]["country_name"] if countries else None,
            "top_score": countries[0]["score"] if countries else 0,
        }
    except Exception as exc:
        log.debug("cii: digest gather failed: %s", exc)
        return {"enabled": False, "count": 0, "lines": []}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.get("/country")
async def cii_country(
    code: str = Query(..., description="ISO2 country code (e.g. TH) or country name"),
    refresh: bool = Query(False),
):
    """Country Instability Index for a single country."""
    return get_cii_country(code, refresh=refresh)


@router.get("/rankings")
async def cii_rankings(
    refresh: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
):
    """All countries ranked by CII score."""
    data = get_cii_rankings(refresh=refresh)
    data["countries"] = data["countries"][:limit]
    return data
