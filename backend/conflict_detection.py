"""P4 — Source Conflict Detection (rule-based, 0 VRAM).

Detects and surfaces contradictions between evidence items before synthesis
so the LLM can adjudicate.  Restricted to **hard conflicts** only:

  - **Existence contradiction:** Same entity/event, one source claims it
    exists, another denies it.
  - **Temporal discrepancy:** Same entity/event, timestamps diverge by >24h.

Cross-feed severity deltas (e.g. USGS magnitude vs GDELT tone) are
intentionally excluded — they are not comparable across feed types.
"""

from __future__ import annotations

import re
from typing import Any

_TEMPORAL_THRESHOLD_H = 24.0  # hours


def detect_conflicts(
    evidence: list[Any],
) -> list[dict[str, Any]]:
    """Scan the evidence registry for hard conflicts.

    Args:
        evidence: list of EvidenceItem dataclass instances.

    Returns:
        list of conflict dicts with keys:
          evidence_id_a, evidence_id_b, conflict_type, description, severity
    """
    conflicts: list[dict[str, Any]] = []
    if len(evidence) < 2:
        return conflicts

    # Pairwise comparison (O(n²) but n is small — typically <20 evidence items)
    for i, a in enumerate(evidence):
        for j in range(i + 1, len(evidence)):
            b = evidence[j]
            # --- Existence contradiction ---
            existence = _check_existence_conflict(a, b)
            if existence:
                conflicts.append(existence)
                continue  # don't double-report the same pair

            # --- Temporal discrepancy ---
            temporal = _check_temporal_conflict(a, b)
            if temporal:
                conflicts.append(temporal)

    # Cap at top 5 by severity
    conflicts.sort(key=lambda c: c["severity"], reverse=True)
    return conflicts[:5]


# ---------------------------------------------------------------------------
# Conflict detectors
# ---------------------------------------------------------------------------


def _check_existence_conflict(
    a: Any,
    b: Any,
) -> dict[str, Any] | None:
    """Detect existence contradictions (same entity, conflicting claims)."""
    text_a = (getattr(a, "text", "") or "").lower()
    text_b = (getattr(b, "text", "") or "").lower()

    # Skip if texts are too different (no shared entity)
    if not _shares_entity(text_a, text_b):
        return None

    # Look for negation patterns
    negation_patterns = [
        (r"\b(no|not|none|denied|false|unconfirmed|no major)\b", "negation"),
        (r"\b(deny|refute|contradict|dispute)\b", "denial"),
    ]

    a_has_negation = any(re.search(p, text_a) for p, _ in negation_patterns)
    b_has_negation = any(re.search(p, text_b) for p, _ in negation_patterns)

    # Conflict: one affirms, the other denies
    if a_has_negation != b_has_negation:
        negated = a if a_has_negation else b
        affirmed = b if a_has_negation else a
        return {
            "evidence_id_a": a.id,
            "evidence_id_b": b.id,
            "conflict_type": "existence",
            "description": (
                f"{affirmed.source} affirms an event while "
                f"{negated.source} denies or downplays it: "
                f"'{negated.text[:120]}'"
            ),
            "severity": _conflict_severity(a, b),
        }

    return None


def _check_temporal_conflict(
    a: Any,
    b: Any,
) -> dict[str, Any] | None:
    """Detect temporal discrepancies >24h for the same entity/event."""
    text_a = (getattr(a, "text", "") or "").lower()
    text_b = (getattr(b, "text", "") or "").lower()

    if not _shares_entity(text_a, text_b):
        return None

    ts_a = getattr(a, "timestamp_dt", None)
    ts_b = getattr(b, "timestamp_dt", None)

    if ts_a is None or ts_b is None:
        return None

    delta = abs((ts_a - ts_b).total_seconds())
    delta_h = delta / 3600.0

    if delta_h > _TEMPORAL_THRESHOLD_H:
        return {
            "evidence_id_a": a.id,
            "evidence_id_b": b.id,
            "conflict_type": "temporal",
            "description": (
                f"Same entity reported at divergent times: "
                f"{a.source} at {a.retrieved_at}, "
                f"{b.source} at {b.retrieved_at} "
                f"(Δ={delta_h:.1f}h)"
            ),
            "severity": _conflict_severity(a, b) * 0.8,
        }

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shares_entity(text_a: str, text_b: str) -> bool:
    """Heuristic: do two text blocks share a named entity?

    Checks for common capitalised words or significant token overlap.
    """
    # Extract capitalised words (potential entity names)
    caps_a = set(re.findall(r"\b([A-Z][a-z]{2,})\b", text_a))
    caps_b = set(re.findall(r"\b([A-Z][a-z]{2,})\b", text_b))
    if caps_a & caps_b:
        return True

    # Token overlap (Jaccard on significant words)
    stop = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "have",
        "were",
        "been",
        "was",
        "are",
        "not",
        "but",
        "had",
        "has",
        "his",
        "her",
        "its",
        "their",
        "there",
        "where",
        "when",
        "what",
        "which",
        "who",
        "whom",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "did",
        "does",
        "done",
        "about",
        "into",
        "over",
        "under",
        "after",
        "before",
        "between",
        "during",
        "through",
        "above",
        "below",
    }
    tokens_a = set(w for w in re.findall(r"\b[a-z]{4,}\b", text_a) if w not in stop)
    tokens_b = set(w for w in re.findall(r"\b[a-z]{4,}\b", text_b) if w not in stop)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))
    return overlap > 0.4


def _conflict_severity(a: Any, b: Any) -> float:
    """Compute severity score for a conflict pair.

    Based on provenance scores: higher provenance on both sides → higher
    severity (both are trustworthy yet disagree).
    """
    pa = getattr(a, "provenance_score", 0.5)
    pb = getattr(b, "provenance_score", 0.5)
    # Average provenance × disagreement factor
    base = (pa + pb) / 2.0
    # Boost when both are high-confidence (they should agree)
    if pa >= 0.7 and pb >= 0.7:
        base *= 1.2
    return round(min(1.0, base), 3)
