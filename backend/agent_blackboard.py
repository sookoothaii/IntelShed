"""P1 — Shared Blackboard for multi-agent orchestration (0 VRAM).

Provides a structured, phase-shared workspace that replaces string-passing
between agents.  When ``WORLDBASE_BLACKBOARD=1`` every phase reads from and
writes to the same :class:`Blackboard` instance, enabling evidence chains,
conflict detection, and structured JSON output.

Env:
  WORLDBASE_BLACKBOARD=1 (default off, opt-in)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import get_config


def blackboard_enabled() -> bool:
    return get_config().blackboard_enabled


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """An entity extracted from the query or evidence (location, event, actor)."""

    name: str
    entity_type: str = "unknown"  # location, event, actor, organisation, vessel…
    lat: float | None = None
    lon: float | None = None
    source: str = "query"


@dataclass
class EvidenceItem:
    """A single piece of evidence with provenance metadata."""

    id: str  # [EVIDENCE-NNN]
    source: str
    text: str
    url: str = ""
    retrieved_at: str = ""
    provenance_score: float = 0.0
    confidence: str = "LOW"  # HIGH / MEDIUM / LOW
    corroborated_by: list[str] = field(default_factory=list)

    @property
    def timestamp_dt(self) -> datetime | None:
        """Parse retrieved_at into a datetime for temporal comparison."""
        if not self.retrieved_at:
            return None
        try:
            ts = datetime.fromisoformat(self.retrieved_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except Exception:
            return None


@dataclass
class Claim:
    """A claim extracted from evidence, linked to supporting evidence IDs."""

    claim: str
    confidence: str = "LOW"
    supporting_ids: list[str] = field(default_factory=list)
    uncorroborated: bool = False


@dataclass
class RetrievalDecision:
    """Record of a retrieval action taken by the retrieval agent."""

    route: str
    query: str
    hits: int = 0
    secondary_route: str = ""
    errors: list[str] = field(default_factory=list)


@dataclass
class ConflictPair:
    """A detected conflict between two evidence items."""

    evidence_id_a: str
    evidence_id_b: str
    conflict_type: str  # "existence" or "temporal"
    description: str
    severity: float = 0.5  # 0–1


@dataclass
class Blackboard:
    """Shared working memory for all orchestration phases.

    Each phase reads from and writes to this object instead of passing
    raw strings between agents.
    """

    query: str
    route: str = "vector"
    extracted_entities: list[Entity] = field(default_factory=list)
    evidence_registry: list[EvidenceItem] = field(default_factory=list)
    claim_candidates: list[Claim] = field(default_factory=list)
    retrieval_decisions: list[RetrievalDecision] = field(default_factory=list)
    conflicts: list[ConflictPair] = field(default_factory=list)
    synthesis_draft: str | None = None
    critique_notes: str | None = None
    final_report: dict[str, Any] | None = None
    # Phase trace (same structure as legacy trace["phases"])
    phases: list[dict[str, Any]] = field(default_factory=list)
    # Context block (the merged text used by legacy / chat paths)
    context_block: str = ""

    # --- Evidence registry helpers ---

    _evidence_counter: int = field(default=0, repr=False)

    def add_evidence(
        self,
        source: str,
        text: str,
        *,
        url: str = "",
        retrieved_at: str = "",
        provenance_score: float = 0.0,
        corroborated_by: list[str] | None = None,
    ) -> EvidenceItem:
        """Register a new evidence item and return it."""
        self._evidence_counter += 1
        eid = f"[EVIDENCE-{self._evidence_counter:03d}]"
        confidence = _score_to_confidence(provenance_score)
        item = EvidenceItem(
            id=eid,
            source=source,
            text=text,
            url=url,
            retrieved_at=retrieved_at,
            provenance_score=provenance_score,
            confidence=confidence,
            corroborated_by=corroborated_by or [],
        )
        self.evidence_registry.append(item)
        return item

    def evidence_by_id(self, eid: str) -> EvidenceItem | None:
        for item in self.evidence_registry:
            if item.id == eid:
                return item
        return None

    # --- Entity helpers ---

    def add_entity(self, name: str, **kwargs: Any) -> Entity:
        ent = Entity(name=name, **kwargs)
        self.extracted_entities.append(ent)
        return ent

    # --- Claim helpers ---

    def add_claim(
        self,
        claim: str,
        *,
        confidence: str = "LOW",
        supporting_ids: list[str] | None = None,
        uncorroborated: bool = False,
    ) -> Claim:
        c = Claim(
            claim=claim,
            confidence=confidence,
            supporting_ids=supporting_ids or [],
            uncorroborated=uncorroborated,
        )
        self.claim_candidates.append(c)
        return c

    # --- Conflict helpers ---

    def add_conflict(
        self,
        eid_a: str,
        eid_b: str,
        conflict_type: str,
        description: str,
        severity: float = 0.5,
    ) -> ConflictPair:
        cp = ConflictPair(
            evidence_id_a=eid_a,
            evidence_id_b=eid_b,
            conflict_type=conflict_type,
            description=description,
            severity=severity,
        )
        self.conflicts.append(cp)
        return cp

    # --- Temporal timeline ---

    def temporal_timeline(self, limit: int = 8) -> list[dict[str, str]]:
        """Return top-N evidence items sorted by retrieved_at."""
        timed = [e for e in self.evidence_registry if e.retrieved_at]
        timed.sort(key=lambda e: e.retrieved_at)
        return [
            {
                "timestamp": e.retrieved_at,
                "event": e.text[:200],
                "source": e.source,
            }
            for e in timed[:limit]
        ]

    # --- Condensed state for HUD / status endpoint ---

    def condensed(self) -> dict[str, Any]:
        """Return a condensed view suitable for ``GET /api/agent/status``."""
        return {
            "query": self.query,
            "route": self.route,
            "entity_count": len(self.extracted_entities),
            "evidence_count": len(self.evidence_registry),
            "claim_count": len(self.claim_candidates),
            "conflict_count": len(self.conflicts),
            "retrieval_decisions": len(self.retrieval_decisions),
            "has_synthesis": self.synthesis_draft is not None,
            "has_final_report": self.final_report is not None,
            "evidence_ids": [e.id for e in self.evidence_registry],
            "conflict_types": [c.conflict_type for c in self.conflicts],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _score_to_confidence(score: float) -> str:
    """Map a provenance score to a confidence tag."""
    if score >= 0.8:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


def confidence_to_score(confidence: str) -> float:
    """Map a confidence tag back to a numeric score (midpoint)."""
    c = (confidence or "").strip().upper()
    if c == "HIGH":
        return 0.9
    if c == "MEDIUM":
        return 0.65
    return 0.3


def extract_entities_from_query(query: str) -> list[Entity]:
    """Rule-based entity extraction from a user query (0 VRAM).

    Extracts potential place names, event types, and keywords.  This is
    intentionally lightweight — no NLP model, just pattern matching.
    """
    entities: list[Entity] = []
    if not query:
        return entities

    # Known event-type keywords
    event_keywords = (
        "earthquake",
        "quake",
        "eruption",
        "flood",
        "fire",
        "wildfire",
        "protest",
        "unrest",
        "cyclone",
        "typhoon",
        "tsunami",
        "landslide",
        "explosion",
        "attack",
        "cyberattack",
        "ransomware",
        "anomaly",
        "vessel",
        "ship",
        "aircraft",
        "storm",
        "drought",
        "heatwave",
    )
    query_lower = query.lower()
    for kw in event_keywords:
        if kw in query_lower:
            entities.append(Entity(name=kw, entity_type="event", source="query"))

    # Capitalised words (potential place names) — simple heuristic
    import re

    caps = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", query)
    seen = {e.name.lower() for e in entities}
    for cap in caps:
        if cap.lower() not in seen and len(cap) > 2:
            entities.append(Entity(name=cap, entity_type="location", source="query"))
            seen.add(cap.lower())

    return entities


def evidence_block_to_text(bb: Blackboard) -> str:
    """Render the evidence registry as a text block for prompt injection."""
    if not bb.evidence_registry:
        return ""
    lines: list[str] = []
    for e in bb.evidence_registry:
        line = f"{e.id} [{e.source}] ({e.confidence}) {e.text[:300]}"
        if e.url:
            line += f" — {e.url}"
        lines.append(line)
    return "\n".join(lines)


def conflicts_block_to_text(bb: Blackboard) -> str:
    """Render detected conflicts as a text block for prompt injection."""
    if not bb.conflicts:
        return ""
    lines: list[str] = ["CONFLICTING EVIDENCE:"]
    for c in bb.conflicts:
        lines.append(
            f"- {c.evidence_id_a} vs {c.evidence_id_b} "
            f"({c.conflict_type}): {c.description}"
        )
    lines.append(
        "INSTRUCTION: State both, note the conflict, and explain which "
        "source is more reliable and why."
    )
    return "\n".join(lines)


def timeline_block_to_text(bb: Blackboard, limit: int = 8) -> str:
    """Render the temporal timeline as a text block for prompt injection."""
    timeline = bb.temporal_timeline(limit=limit)
    if not timeline:
        return ""
    lines: list[str] = ["TEMPORAL TIMELINE:"]
    for t in timeline:
        lines.append(f"  {t['timestamp']} [{t['source']}] {t['event']}")
    return "\n".join(lines)
