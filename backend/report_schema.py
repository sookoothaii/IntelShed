"""P2 — Structured JSON report schema with regex fallback (0 VRAM).

Enforces a guaranteed report structure that downstream systems can parse.
Does **not** rely on Ollama JSON mode.  Instead uses:

  1. A strict system prompt instructing the LLM to output JSON.
  2. A deterministic regex fallback parser that extracts JSON from
     plaintext output (handles markdown fences, trailing prose, missing
     outer braces).

The schema is designed for intelligence reports with evidence tables,
competing hypotheses, devil's advocacy, and recommended actions.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Report schema (JSON-Schema-like spec)
# ---------------------------------------------------------------------------

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["key_findings", "evidence_table", "assessment"],
    "properties": {
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Top 3-5 key findings as concise statements.",
        },
        "evidence_table": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "source", "confidence"],
                "properties": {
                    "claim": {"type": "string"},
                    "source": {"type": "string"},
                    "source_url": {"type": "string"},
                    "retrieved_at": {"type": "string"},
                    "provenance_score": {"type": "number"},
                    "confidence": {"type": "string"},
                    "corroborated_by": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "assessment": {"type": "string"},
        "assumptions_check": {
            "type": "array",
            "items": {"type": "string"},
        },
        "competing_hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["hypothesis", "confidence"],
                "properties": {
                    "hypothesis": {"type": "string"},
                    "evidence_for": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "evidence_against": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {"type": "string"},
                },
            },
        },
        "devils_advocacy": {"type": "string"},
        "indicators_warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "blind_spots": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommended_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "temporal_timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["timestamp", "event", "source"],
                "properties": {
                    "timestamp": {"type": "string"},
                    "event": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        },
    },
}

MANDATORY_FIELDS = ("key_findings", "evidence_table", "assessment")


# ---------------------------------------------------------------------------
# System prompt for JSON output
# ---------------------------------------------------------------------------

JSON_SYSTEM_PROMPT = """\
You are an intelligence editor. Produce a structured JSON report.

OUTPUT FORMAT: Return ONLY a JSON object with these fields:
{
  "key_findings": ["..."],
  "evidence_table": [{"claim": "...", "source": "...", "confidence": "HIGH|MEDIUM|LOW", "corroborated_by": ["..."]}],
  "assessment": "...",
  "assumptions_check": ["..."],
  "competing_hypotheses": [{"hypothesis": "...", "evidence_for": ["..."], "evidence_against": ["..."], "confidence": "HIGH|MEDIUM|LOW"}],
  "devils_advocacy": "...",
  "indicators_warnings": ["..."],
  "blind_spots": ["..."],
  "recommended_actions": ["..."],
  "temporal_timeline": [{"timestamp": "...", "event": "...", "source": "..."}]
}

RULES:
- Every claim in evidence_table MUST reference a source.
- Confidence tags: HIGH (provenance ≥0.8), MEDIUM (0.5-0.8), LOW (<0.5).
- Do NOT include markdown fences or trailing prose.
- If evidence is insufficient for a field, use an empty array or "Insufficient evidence."
"""


# ---------------------------------------------------------------------------
# Regex fallback parser
# ---------------------------------------------------------------------------


def extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from LLM output using regex fallback.

    Handles common Qwen3 output variants:
      - Plain JSON
      - JSON wrapped in ```json ... ``` fences
      - JSON with trailing prose
      - JSON with missing outer braces (attempts recovery)

    Returns a parsed dict or None if no JSON could be extracted.
    """
    if not text or not text.strip():
        return None

    # Strategy 1: direct parse (fast path)
    stripped = text.strip()
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return _validate_and_fill(result)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract from markdown fences
    fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    matches = re.findall(fence_pattern, stripped, re.DOTALL)
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, dict):
                return _validate_and_fill(result)
        except json.JSONDecodeError:
            continue

    # Strategy 3: find first { ... last } and try to parse
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = stripped[first_brace : last_brace + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return _validate_and_fill(result)
        except json.JSONDecodeError:
            # Try fixing common issues (trailing commas)
            fixed = _fix_trailing_commas(candidate)
            try:
                result = json.loads(fixed)
                if isinstance(result, dict):
                    return _validate_and_fill(result)
            except json.JSONDecodeError:
                pass

    # Strategy 4: line-by-line key extraction (last resort)
    return _line_by_line_parse(stripped)


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (common LLM output issue)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _validate_and_fill(data: dict[str, Any]) -> dict[str, Any]:
    """Ensure mandatory fields exist; fill missing ones with defaults."""
    for field in MANDATORY_FIELDS:
        if field not in data:
            if field == "key_findings":
                data[field] = []
            elif field == "evidence_table":
                data[field] = []
            elif field == "assessment":
                data[field] = "Insufficient evidence for assessment."
    # Ensure arrays are arrays
    for key in (
        "key_findings",
        "assumptions_check",
        "indicators_warnings",
        "blind_spots",
        "recommended_actions",
    ):
        if key in data and not isinstance(data[key], list):
            data[key] = [str(data[key])] if data[key] else []
    return data


def _line_by_line_parse(text: str) -> dict[str, Any] | None:
    """Last-resort parser: extract key-value pairs from plain text.

    Looks for patterns like:
      KEY FINDINGS: ...
      ASSESSMENT: ...
    """
    result: dict[str, Any] = {}
    lines = text.splitlines()

    # Section headers to field names
    section_map = {
        "key findings": "key_findings",
        "evidence": "evidence_table",
        "assessment": "assessment",
        "assumptions": "assumptions_check",
        "hypotheses": "competing_hypotheses",
        "devil": "devils_advocacy",
        "indicators": "indicators_warnings",
        "warnings": "indicators_warnings",
        "blind spots": "blind_spots",
        "blindspots": "blind_spots",
        "recommended": "recommended_actions",
        "actions": "recommended_actions",
        "timeline": "temporal_timeline",
    }

    current_field: str | None = None
    current_items: list[str] = []

    for line in lines:
        low = line.strip().lower()
        if not low:
            continue

        # Check if this line is a section header
        matched = False
        for header, field in section_map.items():
            if low.startswith(header):
                if current_field and current_items:
                    _store_field(result, current_field, current_items)
                current_field = field
                current_items = []
                # Rest of the line after the header
                rest = line.split(":", 1)[-1].strip() if ":" in line else ""
                if rest:
                    current_items.append(rest)
                matched = True
                break

        if not matched and current_field:
            # Bullet point or continuation
            cleaned = line.strip().lstrip("-*•").strip()
            if cleaned:
                current_items.append(cleaned)

    if current_field and current_items:
        _store_field(result, current_field, current_items)

    # Must have at least the mandatory fields
    if "key_findings" in result or "assessment" in result:
        return _validate_and_fill(result)

    return None


def _store_field(
    result: dict[str, Any],
    field: str,
    items: list[str],
) -> None:
    """Store parsed items in the result dict."""
    if field in (
        "key_findings",
        "assumptions_check",
        "indicators_warnings",
        "blind_spots",
        "recommended_actions",
    ):
        result[field] = items
    elif field == "assessment":
        result[field] = " ".join(items)
    elif field == "devils_advocacy":
        result[field] = " ".join(items)
    elif field == "evidence_table":
        result[field] = [
            {"claim": item, "source": "unknown", "confidence": "LOW"} for item in items
        ]
    elif field == "competing_hypotheses":
        result[field] = [{"hypothesis": item, "confidence": "LOW"} for item in items]
    elif field == "temporal_timeline":
        result[field] = [
            {"timestamp": "", "event": item, "source": "unknown"} for item in items
        ]


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_report_as_text(report: dict[str, Any]) -> str:
    """Format a parsed JSON report as readable text (fallback for UI)."""
    lines: list[str] = []

    findings = report.get("key_findings") or []
    if findings:
        lines.append("=== KEY FINDINGS ===")
        for f in findings:
            lines.append(f"  - {f}")
        lines.append("")

    evidence = report.get("evidence_table") or []
    if evidence:
        lines.append("=== EVIDENCE TABLE ===")
        for e in evidence:
            conf = e.get("confidence", "LOW")
            claim = e.get("claim", "")
            src = e.get("source", "unknown")
            corr = e.get("corroborated_by") or []
            corr_str = f" (corroborated by: {', '.join(corr)})" if corr else ""
            lines.append(f"  [{conf}] {claim} — {src}{corr_str}")
        lines.append("")

    assessment = report.get("assessment")
    if assessment:
        lines.append("=== ASSESSMENT ===")
        lines.append(f"  {assessment}")
        lines.append("")

    hypotheses = report.get("competing_hypotheses") or []
    if hypotheses:
        lines.append("=== COMPETING HYPOTHESES ===")
        for h in hypotheses:
            conf = h.get("confidence", "LOW")
            hyp = h.get("hypothesis", "")
            lines.append(f"  [{conf}] {hyp}")
        lines.append("")

    devils = report.get("devils_advocacy")
    if devils:
        lines.append("=== DEVIL'S ADVOCACY ===")
        lines.append(f"  {devils}")
        lines.append("")

    for section, label in [
        ("assumptions_check", "ASSUMPTIONS CHECK"),
        ("indicators_warnings", "INDICATORS & WARNINGS"),
        ("blind_spots", "BLIND SPOTS"),
        ("recommended_actions", "RECOMMENDED ACTIONS"),
    ]:
        items = report.get(section) or []
        if items:
            lines.append(f"=== {label} ===")
            for item in items:
                lines.append(f"  - {item}")
            lines.append("")

    timeline = report.get("temporal_timeline") or []
    if timeline:
        lines.append("=== TEMPORAL TIMELINE ===")
        for t in timeline:
            ts = t.get("timestamp", "")
            evt = t.get("event", "")
            src = t.get("source", "unknown")
            lines.append(f"  {ts} [{src}] {evt}")
        lines.append("")

    return "\n".join(lines).strip()


def build_report_from_blackboard(bb: Any) -> dict[str, Any]:
    """Build a structured report dict from a Blackboard instance.

    This is the deterministic (non-LLM) path that assembles the report
    from the blackboard's evidence registry and claims.
    """

    key_findings: list[str] = []
    evidence_table: list[dict[str, Any]] = []

    for e in bb.evidence_registry:
        evidence_table.append(
            {
                "claim": e.text[:300],
                "source": e.source,
                "source_url": e.url,
                "retrieved_at": e.retrieved_at,
                "provenance_score": e.provenance_score,
                "confidence": e.confidence,
                "corroborated_by": e.corroborated_by,
            }
        )
        # Top evidence items become key findings
        if e.confidence in ("HIGH", "MEDIUM") and len(key_findings) < 5:
            key_findings.append(f"{e.id} {e.text[:150]}")

    # Claims contribute to assessment
    assessment_parts: list[str] = []
    for c in bb.claim_candidates:
        if not c.uncorroborated:
            assessment_parts.append(c.claim[:200])

    assessment = (
        " ".join(assessment_parts[:3])
        if assessment_parts
        else "Insufficient evidence for assessment."
    )

    # Conflicts → indicators/warnings
    indicators: list[str] = []
    for cp in bb.conflicts:
        indicators.append(f"CONFLICT ({cp.conflict_type}): {cp.description[:200]}")

    # Temporal timeline
    timeline = bb.temporal_timeline(limit=8)

    return _validate_and_fill(
        {
            "key_findings": key_findings,
            "evidence_table": evidence_table,
            "assessment": assessment,
            "indicators_warnings": indicators,
            "temporal_timeline": timeline,
            "blind_spots": [],
            "recommended_actions": [],
            "assumptions_check": [],
            "competing_hypotheses": [],
            "devils_advocacy": "",
        }
    )
