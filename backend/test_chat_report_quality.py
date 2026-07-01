"""P6c — Evaluation Harness for chat report quality.

Golden queries with regex/keyword checks to verify report quality.
Runs in CI and catches regressions.

Checks:
  - [EVIDENCE-NNN] tags present in reports
  - Source tags (e.g. [GDELT], [USGS])
  - Confidence tags (HIGH/MEDIUM/LOW)
  - Conflict mentions
  - Section headers (KEY FINDINGS, ASSESSMENT, etc.)
  - Report schema fields present
"""

from __future__ import annotations

import re
import unittest
from typing import Any

# ---------------------------------------------------------------------------
# Golden queries — 50+ queries using Critical Pairs method
# Covers: all 5 routes, EN+TH languages, agentic off/on, edge cases
# Critical pairs: Spatial+Live, Temporal+Graph, Multi-Hypothesis+Prognostic,
#   Agentic+Low-Provenance, Empty-Results
# ---------------------------------------------------------------------------

GOLDEN_QUERIES: list[dict[str, Any]] = [
    # === Original 15 queries (now with language + agentic fields) ===
    {
        "query": "Analyze the security situation in Bangkok",
        "route": "vector",
        "expect_keywords": ["Bangkok", "security", "situation"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze earthquake near Thailand",
        "route": "spatial",
        "expect_keywords": ["earthquake", "Thailand"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Who is connected to the Bangkok protest movement?",
        "route": "graph",
        "expect_keywords": ["Bangkok", "protest"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What is the current maritime situation near Phuket?",
        "route": "hybrid",
        "expect_keywords": ["maritime", "Phuket"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Show me live situations",
        "route": "live",
        "expect_keywords": [],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the threat assessment for ASEAN region",
        "route": "vector",
        "expect_keywords": ["threat", "ASEAN"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Assess the haze situation in Northern Thailand",
        "route": "spatial",
        "expect_keywords": ["haze", "Thailand"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Investigate connections between maritime vessels and events",
        "route": "graph",
        "expect_keywords": ["maritime", "vessel"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze GDELT events in the last 24 hours",
        "route": "hybrid",
        "expect_keywords": ["GDELT"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What humanitarian datasets are available for Myanmar border?",
        "route": "vector",
        "expect_keywords": ["humanitarian", "Myanmar"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the intelligence assessment for South China Sea",
        "route": "hybrid",
        "expect_keywords": ["intelligence", "South China Sea"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Evaluate the ransomware threat landscape in Southeast Asia",
        "route": "vector",
        "expect_keywords": ["ransomware", "Southeast Asia"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What are the fusion hotspots near Bangkok?",
        "route": "spatial",
        "expect_keywords": ["fusion", "Bangkok"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the situation report for Thailand-Myanmar border",
        "route": "hybrid",
        "expect_keywords": ["Thailand", "Myanmar"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Assess the energy infrastructure situation in ASEAN",
        "route": "vector",
        "expect_keywords": ["energy", "infrastructure"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    # === Critical Pair: Spatial + Live ===
    {
        "query": "Show me live earthquake events within 500km of Bangkok",
        "route": "spatial",
        "expect_keywords": ["earthquake", "Bangkok"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What live maritime traffic is near the Strait of Malacca?",
        "route": "spatial",
        "expect_keywords": ["maritime", "Malacca"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Live wildfire detection in Southeast Asia",
        "route": "live",
        "expect_keywords": ["wildfire"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Current volcanic activity near Indonesia",
        "route": "spatial",
        "expect_keywords": ["volcanic", "Indonesia"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    # === Critical Pair: Temporal + Graph ===
    {
        "query": "Trace the timeline of events connected to the Bangkok protest leader",
        "route": "graph",
        "expect_keywords": ["timeline", "Bangkok"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What events in the last 7 days are linked to maritime incidents near Phuket?",
        "route": "graph",
        "expect_keywords": ["events", "Phuket"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Show the temporal progression of GDELT events involving Thailand",
        "route": "graph",
        "expect_keywords": ["temporal", "Thailand"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    # === Critical Pair: Multi-Hypothesis + Prognostic ===
    {
        "query": "/analyze competing hypotheses about the South China Sea dispute escalation",
        "route": "vector",
        "expect_keywords": ["hypotheses", "South China Sea"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the prognostic assessment for ASEAN political stability",
        "route": "vector",
        "expect_keywords": ["prognostic", "ASEAN"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What are the competing scenarios for Myanmar border conflict escalation?",
        "route": "vector",
        "expect_keywords": ["scenarios", "Myanmar"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze forecast for Thai political unrest in the next 30 days",
        "route": "hybrid",
        "expect_keywords": ["forecast", "Thai"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    # === Critical Pair: Agentic + Low-Provenance ===
    {
        "query": "/analyze the darkweb chatter about Southeast Asian targets",
        "route": "vector",
        "expect_keywords": ["darkweb", "Southeast Asian"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    {
        "query": "/analyze unverified Telegram reports about Bangkok coup rumors",
        "route": "vector",
        "expect_keywords": ["Telegram", "Bangkok"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    {
        "query": "/analyze low-confidence intelligence about cyber threats in Thailand",
        "route": "vector",
        "expect_keywords": ["cyber", "Thailand"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    {
        "query": "/analyze uncorroborated reports of military movement near Cambodian border",
        "route": "spatial",
        "expect_keywords": ["military", "Cambodian"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    # === Empty-Results Edge Case ===
    {
        "query": "What happened in Antarctica yesterday?",
        "route": "vector",
        "expect_keywords": [],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Show me intelligence about the moon",
        "route": "vector",
        "expect_keywords": [],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What maritime incidents occurred in the Sahara desert?",
        "route": "spatial",
        "expect_keywords": [],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Show me intelligence about mining operations on Mars",
        "route": "vector",
        "expect_keywords": [],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    # === Thai Language Queries (operator region) ===
    {
        "query": "วิเคราะห์สถานการณ์ความมั่นคงในกรุงเทพมหานคร",
        "route": "vector",
        "expect_keywords": ["กรุงเทพ", "ความมั่นคง"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "th",
        "agentic": False,
    },
    {
        "query": "/analyze แผ่นดินไหวใกล้ภูเก็ต",
        "route": "spatial",
        "expect_keywords": ["แผ่นดินไหว", "ภูเก็ต"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "th",
        "agentic": False,
    },
    {
        "query": "สถานการณ์ทางทะเลในช่องแคบมะละกา",
        "route": "hybrid",
        "expect_keywords": ["ทะเล", "มะละกา"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "th",
        "agentic": False,
    },
    {
        "query": "ใครเชื่อมโยงกับขบวนการประท้วงในกรุงเทพ?",
        "route": "graph",
        "expect_keywords": ["ประท้วง", "กรุงเทพ"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "th",
        "agentic": False,
    },
    {
        "query": "/analyze ภัยคุกคามทางไซเบอร์ในประเทศไทย",
        "route": "vector",
        "expect_keywords": ["ไซเบอร์", "ไทย"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "th",
        "agentic": True,
    },
    {
        "query": "สถานการณ์หมอกควันในภาคเหนือตอนบน",
        "route": "spatial",
        "expect_keywords": ["หมอกควัน", "ภาคเหนือ"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "th",
        "agentic": False,
    },
    {
        "query": "/analyze สถานการณ์ชายแดนไทย-พม่า",
        "route": "hybrid",
        "expect_keywords": ["ชายแดน", "พม่า"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "th",
        "agentic": False,
    },
    # === Additional Route Coverage ===
    {
        "query": "What AIS vessel tracks are near the Gulf of Thailand?",
        "route": "spatial",
        "expect_keywords": ["AIS", "Thailand"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Show me ACLED conflict events in Southeast Asia",
        "route": "live",
        "expect_keywords": ["ACLED"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "What power outages are reported in Thailand?",
        "route": "live",
        "expect_keywords": ["outage"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 0,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Map the flood warnings in Central Thailand",
        "route": "spatial",
        "expect_keywords": ["flood", "Thailand"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    # === Additional Graph Queries ===
    {
        "query": "What organizations are linked to the Myanmar junta?",
        "route": "graph",
        "expect_keywords": ["Myanmar", "organization"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Trace connections between cyber threat actors in Southeast Asia",
        "route": "graph",
        "expect_keywords": ["cyber", "threat"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "Who are the key persons associated with Thai energy sector?",
        "route": "graph",
        "expect_keywords": ["energy", "Thai"],
        "expect_evidence_refs": False,
        "expect_section_headers": False,
        "min_block_chars": 10,
        "language": "en",
        "agentic": False,
    },
    # === Additional Hybrid Queries ===
    {
        "query": "/analyze the geopolitical implications of Mekong River dam projects",
        "route": "hybrid",
        "expect_keywords": ["Mekong", "dam"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the impact of Cyclone migration patterns on Bay of Bengal",
        "route": "hybrid",
        "expect_keywords": ["Cyclone", "Bengal"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    {
        "query": "/analyze the drone attack patterns in the Red Sea shipping lane",
        "route": "hybrid",
        "expect_keywords": ["drone", "Red Sea"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": False,
    },
    # === Additional Agentic Queries (5-Agent mode) ===
    {
        "query": "/analyze the full intelligence picture for Hormuz Strait tensions",
        "route": "hybrid",
        "expect_keywords": ["Hormuz", "Strait"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    {
        "query": "/analyze the West Asia geopolitical situation and Iran nuclear posture",
        "route": "hybrid",
        "expect_keywords": ["West Asia", "Iran"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    {
        "query": "/analyze the Persian Gulf naval buildup and escalation risk",
        "route": "hybrid",
        "expect_keywords": ["Persian Gulf", "naval"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "en",
        "agentic": True,
    },
    # === Additional Thai Agentic ===
    {
        "query": "/analyze สถานการณ์ความขัดแย้งในทะเลจีนใต้",
        "route": "hybrid",
        "expect_keywords": ["จีนใต้", "ขัดแย้ง"],
        "expect_evidence_refs": True,
        "expect_section_headers": True,
        "min_block_chars": 50,
        "language": "th",
        "agentic": True,
    },
]

# ---------------------------------------------------------------------------
# Regex patterns for quality checks
# ---------------------------------------------------------------------------

EVIDENCE_REF_PATTERN = re.compile(r"\[EVIDENCE-\d{3}\]")
SOURCE_TAG_PATTERN = re.compile(
    r"\[(?:GDELT|USGS|GDACS|EONET|AIS|HDX|NewsData|CAMS|ENTSO|SMARD|Telegram|Darkweb|Ransomware)\]",
    re.IGNORECASE,
)
CONFIDENCE_TAG_PATTERN = re.compile(r"\b(?:HIGH|MEDIUM|LOW)\b")
CONFLICT_PATTERN = re.compile(
    r"\b(?:conflict|contradict|however|discrepancy|inconsisten)\b", re.IGNORECASE
)
SECTION_HEADER_PATTERN = re.compile(
    r"(?:KEY FINDINGS|EVIDENCE TABLE|ASSESSMENT|RECOMMENDED ACTIONS|"
    r"COMPETING HYPOTHESES|TEMPORAL TIMELINE|INDICATORS|"
    r"CRITIQUE-REFINE|EVIDENCE REGISTRY|CONFLICTING EVIDENCE)",
    re.IGNORECASE,
)


def check_report_quality(
    block: str,
    golden: dict[str, Any],
) -> dict[str, Any]:
    """Run quality checks on a report block against a golden query spec.

    Returns dict with:
      - passed: bool
      - checks: list of {check, passed, detail}
    """
    checks: list[dict[str, Any]] = []
    block_lower = (block or "").lower()

    # Check 1: Minimum block length
    min_chars = golden.get("min_block_chars", 0)
    checks.append(
        {
            "check": "min_block_chars",
            "passed": len(block or "") >= min_chars,
            "detail": f"expected>={min_chars}, got={len(block or '')}",
        }
    )

    # Check 2: Expected keywords present
    for kw in golden.get("expect_keywords", []):
        checks.append(
            {
                "check": f"keyword:{kw}",
                "passed": kw.lower() in block_lower,
                "detail": f"keyword '{kw}' {'found' if kw.lower() in block_lower else 'missing'}",
            }
        )

    # Check 3: Evidence references
    if golden.get("expect_evidence_refs"):
        has_refs = bool(EVIDENCE_REF_PATTERN.search(block or ""))
        checks.append(
            {
                "check": "evidence_refs",
                "passed": has_refs,
                "detail": f"[EVIDENCE-NNN] tags {'present' if has_refs else 'absent'}",
            }
        )

    # Check 4: Section headers
    if golden.get("expect_section_headers"):
        has_headers = bool(SECTION_HEADER_PATTERN.search(block or ""))
        checks.append(
            {
                "check": "section_headers",
                "passed": has_headers,
                "detail": f"section headers {'present' if has_headers else 'absent'}",
            }
        )

    # Check 5: Source tags (always check, but only fail if evidence refs expected)
    has_source_tags = bool(SOURCE_TAG_PATTERN.search(block or ""))
    checks.append(
        {
            "check": "source_tags",
            "passed": has_source_tags if golden.get("expect_evidence_refs") else True,
            "detail": f"source tags {'present' if has_source_tags else 'absent'}",
        }
    )

    # Check 6: Confidence tags (always check, but only fail if evidence refs expected)
    has_confidence = bool(CONFIDENCE_TAG_PATTERN.search(block or ""))
    checks.append(
        {
            "check": "confidence_tags",
            "passed": has_confidence if golden.get("expect_evidence_refs") else True,
            "detail": f"confidence tags {'present' if has_confidence else 'absent'}",
        }
    )

    all_passed = all(c["passed"] for c in checks)
    return {"passed": all_passed, "checks": checks}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGoldenQueryDefinitions(unittest.TestCase):
    """Verify golden query definitions are well-formed."""

    def test_golden_queries_count(self) -> None:
        self.assertGreaterEqual(len(GOLDEN_QUERIES), 50)
        self.assertLessEqual(len(GOLDEN_QUERIES), 60)

    def test_each_golden_has_required_fields(self) -> None:
        for i, gq in enumerate(GOLDEN_QUERIES):
            self.assertIn("query", gq, f"Golden query {i} missing 'query'")
            self.assertIn("route", gq, f"Golden query {i} missing 'route'")
            self.assertIn(
                "expect_keywords", gq, f"Golden query {i} missing 'expect_keywords'"
            )
            self.assertIn(
                "expect_evidence_refs",
                gq,
                f"Golden query {i} missing 'expect_evidence_refs'",
            )
            self.assertIn(
                "expect_section_headers",
                gq,
                f"Golden query {i} missing 'expect_section_headers'",
            )
            self.assertIn(
                "min_block_chars", gq, f"Golden query {i} missing 'min_block_chars'"
            )
            self.assertIn("language", gq, f"Golden query {i} missing 'language'")
            self.assertIn("agentic", gq, f"Golden query {i} missing 'agentic'")

    def test_routes_are_valid(self) -> None:
        valid_routes = {"vector", "graph", "spatial", "hybrid", "live"}
        for i, gq in enumerate(GOLDEN_QUERIES):
            self.assertIn(
                gq["route"],
                valid_routes,
                f"Golden query {i} has invalid route: {gq['route']}",
            )

    def test_languages_are_valid(self) -> None:
        valid_langs = {"en", "th"}
        for i, gq in enumerate(GOLDEN_QUERIES):
            self.assertIn(
                gq["language"],
                valid_langs,
                f"Golden query {i} has invalid language: {gq['language']}",
            )

    def test_each_route_represented(self) -> None:
        routes_seen = {gq["route"] for gq in GOLDEN_QUERIES}
        for r in ("vector", "graph", "spatial", "hybrid", "live"):
            self.assertIn(
                r, routes_seen, f"Route '{r}' not represented in golden queries"
            )

    def test_each_language_represented(self) -> None:
        langs_seen = {gq["language"] for gq in GOLDEN_QUERIES}
        self.assertIn("en", langs_seen, "English not represented")
        self.assertIn("th", langs_seen, "Thai not represented")

    def test_agentic_queries_present(self) -> None:
        agentic_count = sum(1 for gq in GOLDEN_QUERIES if gq["agentic"])
        self.assertGreaterEqual(agentic_count, 5, "Need at least 5 agentic queries")

    def test_empty_results_edge_cases_present(self) -> None:
        empty_kw = [gq for gq in GOLDEN_QUERIES if not gq["expect_keywords"]]
        self.assertGreaterEqual(
            len(empty_kw), 5, "Need at least 5 empty-results edge cases"
        )

    def test_analyze_queries_expect_evidence(self) -> None:
        for i, gq in enumerate(GOLDEN_QUERIES):
            if gq["query"].startswith("/analyze"):
                self.assertTrue(
                    gq["expect_evidence_refs"],
                    f"Golden query {i} is /analyze but doesn't expect evidence refs",
                )
                self.assertTrue(
                    gq["expect_section_headers"],
                    f"Golden query {i} is /analyze but doesn't expect section headers",
                )


class TestQualityCheckFunction(unittest.TestCase):
    """Tests for the check_report_quality function."""

    def test_quality_check_passes_good_report(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": ["Bangkok", "security"],
            "expect_evidence_refs": True,
            "expect_section_headers": True,
            "min_block_chars": 50,
        }
        block = (
            "KEY FINDINGS: Bangkok security situation is stable.\n"
            "[EVIDENCE-001] [GDELT] reports indicate calm. HIGH confidence.\n"
            "ASSESSMENT: The situation is normal.\n"
        )
        result = check_report_quality(block, golden)
        self.assertTrue(result["passed"])

    def test_quality_check_fails_missing_keywords(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": ["Bangkok"],
            "expect_evidence_refs": False,
            "expect_section_headers": False,
            "min_block_chars": 10,
        }
        result = check_report_quality("Tokyo weather report", golden)
        self.assertFalse(result["passed"])
        keyword_check = [c for c in result["checks"] if c["check"] == "keyword:Bangkok"]
        self.assertFalse(keyword_check[0]["passed"])

    def test_quality_check_fails_missing_evidence_refs(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": [],
            "expect_evidence_refs": True,
            "expect_section_headers": False,
            "min_block_chars": 10,
        }
        result = check_report_quality("no evidence tags here", golden)
        self.assertFalse(result["passed"])

    def test_quality_check_fails_missing_section_headers(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": [],
            "expect_evidence_refs": False,
            "expect_section_headers": True,
            "min_block_chars": 10,
        }
        result = check_report_quality("just some text without headers", golden)
        self.assertFalse(result["passed"])

    def test_quality_check_fails_short_block(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": [],
            "expect_evidence_refs": False,
            "expect_section_headers": False,
            "min_block_chars": 500,
        }
        result = check_report_quality("short", golden)
        self.assertFalse(result["passed"])

    def test_quality_check_empty_block(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": [],
            "expect_evidence_refs": False,
            "expect_section_headers": False,
            "min_block_chars": 0,
        }
        result = check_report_quality("", golden)
        self.assertTrue(result["passed"])

    def test_quality_check_none_block(self) -> None:
        golden = {
            "query": "test",
            "route": "vector",
            "expect_keywords": [],
            "expect_evidence_refs": False,
            "expect_section_headers": False,
            "min_block_chars": 0,
        }
        result = check_report_quality(None, golden)  # type: ignore[arg-type]
        self.assertTrue(result["passed"])

    def test_quality_check_conflict_mention_detected(self) -> None:
        block = "There is a conflict between sources about the event."
        self.assertTrue(CONFLICT_PATTERN.search(block))

    def test_quality_check_source_tag_pattern(self) -> None:
        block = "[GDELT] reports indicate unrest"
        self.assertTrue(SOURCE_TAG_PATTERN.search(block))
        block2 = "[USGS] earthquake data"
        self.assertTrue(SOURCE_TAG_PATTERN.search(block2))

    def test_quality_check_evidence_ref_pattern(self) -> None:
        self.assertTrue(EVIDENCE_REF_PATTERN.search("[EVIDENCE-001]"))
        self.assertTrue(EVIDENCE_REF_PATTERN.search("[EVIDENCE-999]"))
        self.assertFalse(EVIDENCE_REF_PATTERN.search("[EVIDENCE-1]"))
        self.assertFalse(EVIDENCE_REF_PATTERN.search("EVIDENCE-001"))


class TestReportSchemaQuality(unittest.TestCase):
    """Tests for report schema output quality."""

    def test_report_has_mandatory_fields(self) -> None:
        from report_schema import MANDATORY_FIELDS

        self.assertIn("key_findings", MANDATORY_FIELDS)
        self.assertIn("evidence_table", MANDATORY_FIELDS)
        self.assertIn("assessment", MANDATORY_FIELDS)

    def test_build_report_includes_evidence_table(self) -> None:
        from agent_blackboard import Blackboard
        from report_schema import build_report_from_blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(source="usgs", text="M4.5 quake", provenance_score=0.9)
        bb.add_claim(
            "quake occurred", confidence="HIGH", supporting_ids=["[EVIDENCE-001]"]
        )
        report = build_report_from_blackboard(bb)
        self.assertEqual(len(report["evidence_table"]), 1)
        self.assertEqual(report["evidence_table"][0]["source"], "usgs")

    def test_build_report_includes_conflicts(self) -> None:
        from agent_blackboard import Blackboard
        from report_schema import build_report_from_blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(source="gdelt", text="event reported", provenance_score=0.7)
        bb.add_conflict("[EVIDENCE-001]", "[EVIDENCE-002]", "existence", "conflict")
        report = build_report_from_blackboard(bb)
        self.assertEqual(len(report["indicators_warnings"]), 1)

    def test_format_report_has_section_headers(self) -> None:
        from report_schema import format_report_as_text

        report = {
            "key_findings": ["finding 1"],
            "evidence_table": [
                {"claim": "test", "source": "gdelt", "confidence": "HIGH"}
            ],
            "assessment": "test assessment",
        }
        text = format_report_as_text(report)
        self.assertTrue(SECTION_HEADER_PATTERN.search(text))


class TestOrchestratorReportQuality(unittest.IsolatedAsyncioTestCase):
    """Integration tests: orchestrate() output meets quality standards for golden queries."""

    def setUp(self) -> None:
        import sys

        for mod in list(sys.modules):
            if mod in (
                "agent_orchestrator",
                "query_router",
                "chat_agentic",
                "agent_bus",
                "agent_blackboard",
                "conflict_detection",
                "config",
            ):
                del sys.modules[mod]

    class _ConfigStub:
        def __init__(
            self,
            enabled: bool = True,
            max_workers: int = 4,
            phase_timeout: float = 10.0,
            circuit_breaker_threshold: int = 3,
            circuit_breaker_window: int = 60,
            blackboard_enabled: bool = True,
            two_pass_enabled: bool = False,
        ):
            self.agent_orchestrator_enabled = enabled
            self.agent_orchestrator_max_workers = max_workers
            self.agent_orchestrator_phase_timeout = phase_timeout
            self.agent_orchestrator_circuit_breaker_threshold = (
                circuit_breaker_threshold
            )
            self.agent_orchestrator_circuit_breaker_window = circuit_breaker_window
            self.blackboard_enabled = blackboard_enabled
            self.two_pass_enabled = two_pass_enabled

    def _patch_modules(
        self, route_block: str = "context", route_hits: list | None = None
    ) -> dict:
        from unittest.mock import AsyncMock, MagicMock

        route_hits = route_hits or []
        query_router = MagicMock()
        query_router.classify_query = MagicMock(return_value="vector")
        query_router.route_retrieval = AsyncMock(
            return_value={
                "route": "vector",
                "block": route_block,
                "hits": route_hits,
                "meta": {},
            }
        )
        query_router.VALID_ROUTES = ("vector", "graph", "spatial", "hybrid", "live")

        chat_agentic = MagicMock()
        chat_agentic.chat_agentic_enabled = MagicMock(return_value=True)
        chat_agentic.assess_coverage = MagicMock(
            return_value={
                "phase": "coverage",
                "char_count": len(route_block),
                "unique_sources": 1,
                "has_strong": True,
                "has_thin": False,
                "gaps": [],
                "needs_retrieve": False,
            }
        )
        chat_agentic.apply_corroboration_tags = MagicMock(
            return_value=(
                route_block,
                {
                    "phase": "corroboration",
                    "source_count": 1,
                    "corroborated": 0,
                    "uncorroborated": 0,
                    "tagged_lines": 0,
                },
            )
        )

        agent_bus = MagicMock()
        agent_bus.agent_bus_enabled = MagicMock(return_value=False)
        agent_bus.publish_action = AsyncMock(return_value={"ok": True, "delivered": 0})
        agent_bus.GLOBE_LAYER_KEYS = frozenset()
        agent_bus.AgentPublishBody = MagicMock()
        agent_bus.subscriber_count = MagicMock(return_value=0)

        return {
            "query_router": query_router,
            "chat_agentic": chat_agentic,
            "agent_bus": agent_bus,
        }

    async def test_orchestrate_produces_nonempty_block(self) -> None:
        import sys
        from unittest.mock import patch

        import agent_orchestrator
        import agent_blackboard

        hits = [
            {"text": "Bangkok security situation stable", "source": "gdelt"},
        ]
        modules = self._patch_modules(route_block="Bangkok context", route_hits=hits)
        with (
            patch.dict(
                sys.modules,
                {
                    "query_router": modules["query_router"],
                    "chat_agentic": modules["chat_agentic"],
                    "agent_bus": modules["agent_bus"],
                },
            ),
            patch.object(
                agent_orchestrator,
                "get_config",
                return_value=self._ConfigStub(blackboard_enabled=True),
            ),
            patch.object(
                agent_blackboard,
                "get_config",
                return_value=self._ConfigStub(blackboard_enabled=True),
            ),
        ):
            result = await agent_orchestrator.orchestrate("Analyze Bangkok security")

        self.assertTrue(len(result["final_block"]) > 0)
        self.assertIn("Bangkok", result["final_block"])

    async def test_orchestrate_with_evidence_has_refs(self) -> None:
        import sys
        from unittest.mock import patch

        import agent_orchestrator
        import agent_blackboard

        hits = [
            {
                "text": "M4.5 earthquake near Bangkok",
                "source": "usgs",
                "url": "https://example.com",
            },
        ]
        modules = self._patch_modules(route_block="earthquake context", route_hits=hits)
        with (
            patch.dict(
                sys.modules,
                {
                    "query_router": modules["query_router"],
                    "chat_agentic": modules["chat_agentic"],
                    "agent_bus": modules["agent_bus"],
                },
            ),
            patch.object(
                agent_orchestrator,
                "get_config",
                return_value=self._ConfigStub(blackboard_enabled=True),
            ),
            patch.object(
                agent_blackboard,
                "get_config",
                return_value=self._ConfigStub(blackboard_enabled=True),
            ),
        ):
            result = await agent_orchestrator.orchestrate(
                "Analyze earthquake near Bangkok"
            )

        self.assertEqual(result["blackboard"]["evidence_count"], 1)
        self.assertIn("[EVIDENCE-001]", result["blackboard"]["evidence_ids"])

    async def test_two_pass_adds_critique_phase(self) -> None:
        import sys
        from unittest.mock import patch

        import agent_orchestrator
        import agent_blackboard

        modules = self._patch_modules(route_block="thin context")
        with (
            patch.dict(
                sys.modules,
                {
                    "query_router": modules["query_router"],
                    "chat_agentic": modules["chat_agentic"],
                    "agent_bus": modules["agent_bus"],
                },
            ),
            patch.object(
                agent_orchestrator,
                "get_config",
                return_value=self._ConfigStub(
                    blackboard_enabled=True, two_pass_enabled=True
                ),
            ),
            patch.object(
                agent_blackboard,
                "get_config",
                return_value=self._ConfigStub(
                    blackboard_enabled=True, two_pass_enabled=True
                ),
            ),
        ):
            result = await agent_orchestrator.orchestrate("/analyze Bangkok situation")

        phase_names = [p.get("phase") for p in result["phases"]]
        self.assertIn("critique", phase_names)
        self.assertTrue(result["two_pass"])


if __name__ == "__main__":
    unittest.main()
