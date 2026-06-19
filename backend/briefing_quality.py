"""Rule-based 24h briefing quality score (no LLM judge).

Stored in briefings.sources.quality and exposed on GET /api/briefing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_SECTION_LOCAL = re.compile(r"\bLOCAL\b", re.I)
_SECTION_INTEL = re.compile(r"\bINTEL\b", re.I)
_GDELT_HINT = re.compile(r"\bGDELT\b|\bgdelt\b|local news|Local news", re.I)


def _digest_lines(digest: dict[str, Any] | None, key: str) -> list[str]:
    if not digest:
        return []
    raw = digest.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    return []


def score_briefing(
    *,
    text: str,
    sources: dict[str, Any] | None,
    created_at: str | None = None,
    max_age_hours: float = 6.0,
) -> dict[str, Any]:
    """Return quality block: score 0..1, checks, factors."""
    sources = sources or {}
    digest_meta = sources.get("digest") or {}
    intel = sources.get("intel") or {}
    full_digest = sources.get("_digest_sections") or {}

    local_lines = _digest_lines(full_digest, "local") or []
    local_count = int(digest_meta.get("local_count") or len(local_lines) or 0)
    intel_count = int(digest_meta.get("intel_count") or intel.get("count") or 0)
    regional_count = int(digest_meta.get("regional_count") or 0)
    global_count = int(digest_meta.get("global_count") or 0)

    body = text or ""
    has_local_section = bool(_SECTION_LOCAL.search(body)) or local_count >= 1
    has_intel = intel_count >= 1 or bool(_SECTION_INTEL.search(body))
    has_gdelt = bool(_GDELT_HINT.search(body)) or any(
        "gdelt" in line.lower() or "local news" in line.lower() for line in local_lines
    )

    age_hours: float | None = None
    fresh = False
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600.0
            fresh = age_hours <= max_age_hours
        except Exception:
            pass

    total_signals = max(local_count + regional_count + global_count, 1)
    coverage = min(1.0, (local_count + intel_count + (1 if has_gdelt else 0)) / 3.0)
    timeliness = 1.0 if fresh else (0.5 if age_hours is not None and age_hours <= max_age_hours * 2 else 0.0)
    geo_relevance = min(1.0, local_count / max(total_signals * 0.25, 1))

    checks = {
        "local_present": has_local_section,
        "ftm_present": has_intel,
        "gdelt_present": has_gdelt,
        "fresh": fresh,
    }
    passed = sum(1 for v in checks.values() if v)

    score = round(
        0.35 * coverage + 0.25 * timeliness + 0.25 * geo_relevance + 0.15 * (passed / 4.0),
        3,
    )
    score = max(0.0, min(1.0, score))

    return {
        "score": score,
        "checks": checks,
        "factors": {
            "coverage": round(coverage, 3),
            "timeliness": round(timeliness, 3),
            "geo_relevance": round(geo_relevance, 3),
            "checks_passed": passed,
            "checks_total": 4,
        },
        "meta": {
            "local_count": local_count,
            "intel_count": intel_count,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "max_age_hours": max_age_hours,
        },
    }


def attach_quality_to_sources(
    sources: dict[str, Any],
    *,
    text: str,
    created_at: str,
    max_age_hours: float = 6.0,
) -> dict[str, Any]:
    out = dict(sources)
    out["quality"] = score_briefing(
        text=text,
        sources=out,
        created_at=created_at,
        max_age_hours=max_age_hours,
    )
    return out
