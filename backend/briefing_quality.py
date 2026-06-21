"""Rule-based 24h briefing quality score (no LLM judge).

Stored in briefings.sources.quality and exposed on GET /api/briefing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_SECTION_LOCAL = re.compile(r"\bLOCAL\b", re.I)
_SECTION_INTEL = re.compile(r"\bINTEL\b", re.I)
_GDELT_HINT = re.compile(r"\bGDELT\b|\bgdelt\b|local news|Local news|Regional media heat|Media heat", re.I)
_GDELT_DIGEST_PREFIXES = (
    "local news:",
    "regional media heat:",
    "media heat:",
    "news:",
)


def is_gdelt_digest_text(text: str) -> bool:
    """True when digest line text came from a GDELT feed (local pulse, geo, global)."""
    low = str(text or "").lower().strip()
    return any(low.startswith(prefix) for prefix in _GDELT_DIGEST_PREFIXES)


def _gdelt_item_text(text: str) -> bool:
    return is_gdelt_digest_text(text)


def count_gdelt_digest_items(items: list[dict[str, Any]] | None) -> int:
    """GDELT lines collected before per-bucket severity cap."""
    return sum(1 for item in items or [] if _gdelt_item_text(item.get("text", "")))


def _gdelt_block_volume(block: dict[str, Any] | None, *, list_key: str = "articles") -> int:
    """Digestible rows in a feed block — prefer list length over stale count metadata."""
    if not block:
        return 0
    if list_key in block:
        return len(block.get(list_key) or [])
    return int(block.get("count") or 0)


def gdelt_digest_pipeline_meta(snap: dict[str, Any], digest: dict[str, Any]) -> dict[str, Any]:
    """Compare GDELT feed volume vs digest collection and final bucket placement."""
    local_pulse = snap.get("gdelt_pulse_local") or {}
    geo_local = snap.get("gdelt_geo_local") or {}
    pulse = snap.get("gdelt_pulse") or {}
    geo = snap.get("gdelt_geo") or {}

    feed_local = _gdelt_block_volume(local_pulse, list_key="articles")
    feed_geo_local = _gdelt_block_volume(geo_local, list_key="events")
    feed_global = _gdelt_block_volume(pulse, list_key="articles") + _gdelt_block_volume(
        geo, list_key="events"
    )
    reported_local = int(local_pulse.get("count") or 0)
    reported_geo_local = int(geo_local.get("count") or 0)

    def _count_gdelt_lines(bucket_lines: list[str] | None) -> int:
        total = 0
        for line in bucket_lines or []:
            low = str(line).lower().lstrip("- ").strip()
            if any(low.startswith(prefix) for prefix in _GDELT_DIGEST_PREFIXES):
                total += 1
        return total

    placed_local = _count_gdelt_lines(digest.get("local"))
    placed_regional = _count_gdelt_lines(digest.get("regional"))
    placed_global = _count_gdelt_lines(digest.get("global"))
    placed_total = placed_local + placed_regional + placed_global
    collected = int(digest.get("_gdelt_collected") or 0)
    feed_operator = feed_local + feed_geo_local
    feed_total = feed_operator + feed_global

    if feed_operator >= 1:
        pipeline_ok = collected >= 1
        pipeline_yield = round(min(1.0, collected / max(feed_operator, 1)), 3)
    elif (reported_local + reported_geo_local) > 0:
        pipeline_ok = False
        pipeline_yield = 0.0
    else:
        pipeline_ok = True
        pipeline_yield = None

    if collected >= 1:
        placement_yield = round(placed_total / max(collected, 1), 3)
        pipeline_placed_ok = placed_total >= 1
    else:
        placement_yield = None
        pipeline_placed_ok = True

    blocker = None
    if (reported_local + reported_geo_local) > 0 and feed_operator == 0:
        blocker = "empty_feed_body"
    elif collected >= 1 and placed_total == 0:
        blocker = "bucket_cap"

    return {
        "digest_local_lines": placed_local,
        "digest_regional_lines": placed_regional,
        "digest_global_lines": placed_global,
        "digest_gdelt_lines": placed_total,
        "gdelt_collected": collected,
        "feed_operator_available": feed_operator,
        "feed_global_available": feed_global,
        "feed_total": feed_total,
        "feed_reported_local": reported_local,
        "feed_reported_geo_local": reported_geo_local,
        "pipeline_yield": pipeline_yield,
        "placement_yield": placement_yield,
        "pipeline_ok": pipeline_ok,
        "pipeline_placed_ok": pipeline_placed_ok,
        "pipeline_blocker": blocker,
    }


def _gdelt_feed_meta(sources: dict[str, Any]) -> dict[str, Any]:
    return sources.get("gdelt") or {}


def _gdelt_from_feed(meta: dict[str, Any]) -> bool:
    if not meta:
        return False
    available = int(meta.get("feed_operator_available") or 0)
    if available > 0:
        return True
    if int(meta.get("gdelt_collected") or 0) > 0:
        return True
    if int(meta.get("digest_gdelt_lines") or 0) > 0:
        return True
    # Legacy keys from older briefings
    local_pulse = int(meta.get("local_pulse_count") or 0)
    geo_local = int(meta.get("geo_local_count") or 0)
    if local_pulse > 0 or geo_local > 0:
        return True
    if meta.get("stale"):
        return False
    return False


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
    gdelt_meta = _gdelt_feed_meta(sources)
    has_local_section = bool(_SECTION_LOCAL.search(body)) or local_count >= 1
    has_intel = intel_count >= 1 or bool(_SECTION_INTEL.search(body))
    has_gdelt = (
        _gdelt_from_feed(gdelt_meta)
        or bool(_GDELT_HINT.search(body))
        or any(
            "local news" in line.lower()
            or "regional media heat" in line.lower()
            or "media heat" in line.lower()
            for line in local_lines
        )
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
            "gdelt_local_pulse": int(
                gdelt_meta.get("feed_operator_available")
                or gdelt_meta.get("local_pulse_count")
                or 0
            ),
            "gdelt_geo_local": int(gdelt_meta.get("geo_local_count") or 0),
            "gdelt_collected": int(gdelt_meta.get("gdelt_collected") or 0),
            "gdelt_digest_lines": int(gdelt_meta.get("digest_gdelt_lines") or 0),
            "gdelt_pipeline_yield": gdelt_meta.get("pipeline_yield"),
            "gdelt_placement_yield": gdelt_meta.get("placement_yield"),
            "gdelt_pipeline_ok": gdelt_meta.get("pipeline_ok"),
            "gdelt_pipeline_placed_ok": gdelt_meta.get("pipeline_placed_ok"),
            "gdelt_pipeline_blocker": gdelt_meta.get("pipeline_blocker"),
            "gdelt_error": gdelt_meta.get("error"),
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "max_age_hours": max_age_hours,
            "watch_count": len(sources.get("watch_items") or []),
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
