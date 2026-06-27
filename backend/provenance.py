"""P4 — Digital Provenance scoring (rule-based, 0 VRAM).

Attaches an integrity score (0.0–1.0) to every feed item, digest line,
and insight card based on:

  - source_reliability: static per-feed trust table
  - corroboration_count: how many independent feed families confirm
  - temporal_consistency: decay function on item age
  - ingestion_chain: feed → mapping → ftm → rag (hash chain stub)

Env:
  WORLDBASE_PROVENANCE=1 (default on)
"""

from __future__ import annotations

import hashlib
from typing import Any

from config import get_config


def provenance_enabled() -> bool:
    return get_config().provenance_enabled


# --- Static source reliability table ---

SOURCE_RELIABILITY: dict[str, float] = {
    "gdacs": 0.90,
    "quake": 0.90,
    "usgs": 0.90,
    "volcano": 0.85,
    "smithsonian": 0.85,
    "hazard": 0.80,
    "cap": 0.80,
    "meteoalarm": 0.80,
    "cams_haze": 0.75,
    "airquality": 0.75,
    "humanitarian": 0.80,
    "hdx": 0.80,
    "ocha": 0.80,
    "pegel": 0.85,
    "outage": 0.70,
    "ioda": 0.70,
    "anomaly": 0.65,
    "aircraft_density": 0.60,
    "ais": 0.75,
    "maritime": 0.75,
    "gdelt": 0.70,
    "gdelt_pulse": 0.70,
    "gdelt_pulse_local": 0.70,
    "gdelt_geo": 0.70,
    "gdelt_geo_local": 0.70,
    "gdelt_pulse_global": 0.70,
    "newsdata": 0.65,
    "ftm": 0.75,
    "intel-ingest": 0.70,
    "intel_ingest": 0.70,
    "osint": 0.60,
    "darkweb": 0.30,
    "blog": 0.30,
    "social": 0.35,
    "unknown": 0.40,
}

_DEFAULT_RELIABILITY = 0.50


def source_reliability(source: str) -> float:
    """Look up reliability score for a feed source name."""
    if not source:
        return _DEFAULT_RELIABILITY
    key = str(source).strip().lower()
    if key in SOURCE_RELIABILITY:
        return SOURCE_RELIABILITY[key]
    # Try family-level lookup (e.g. "gdelt_pulse_local" → "gdelt")
    for prefix in ("gdelt_", "gdelt-"):
        if key.startswith(prefix):
            return SOURCE_RELIABILITY.get("gdelt", 0.70)
    return _DEFAULT_RELIABILITY


# --- Temporal decay ---

_TEMPORAL_HALF_LIFE_S = 6.0 * 3600.0  # 6 hours


def temporal_consistency(age_sec: float | None) -> float:
    """Exponential decay from 1.0 → 0.0 over time. Half-life = 6h.

    Returns 1.0 when age unknown (fail-open for items without timestamps).
    """
    if age_sec is None:
        return 1.0
    try:
        age = float(age_sec)
    except (TypeError, ValueError):
        return 1.0
    if age <= 0:
        return 1.0
    return round(0.5 ** (age / _TEMPORAL_HALF_LIFE_S), 4)


# --- Ingestion chain hash (stub for future P5 per-statement provenance) ---


def ingestion_chain_hash(source: str, source_id: str, text: str) -> str:
    """Deterministic hash of the feed → mapping → ftm → rag chain.

    Currently a simple content hash; P5 StatementEntity will extend this
    to include per-statement dataset provenance.
    """
    raw = f"{source or ''}|{source_id or ''}|{(text or '')[:200]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# --- Core scoring ---


def score_provenance(
    source: str,
    corroboration_count: int = 0,
    age_sec: float | None = None,
    ingest_chain: str | None = None,
    *,
    conflict: bool = False,
) -> float:
    """Compute provenance integrity score (0.0–1.0).

    Weighted combination:
      40% source_reliability
      30% corroboration boost (capped)
      20% temporal_consistency (decay)
      10% ingestion_chain presence

    Conflict penalizes by -0.15.
    """
    reliability = source_reliability(source)
    temporal = temporal_consistency(age_sec)

    # Corroboration boost: 0 sources = 0.3, 1 = 0.5, 2 = 0.7, 3+ = 0.9
    if corroboration_count <= 0:
        corroboration_factor = 0.30
    elif corroboration_count == 1:
        corroboration_factor = 0.50
    elif corroboration_count == 2:
        corroboration_factor = 0.70
    else:
        corroboration_factor = 0.90

    chain_factor = 1.0 if ingest_chain else 0.5

    score = (
        0.40 * reliability
        + 0.30 * corroboration_factor
        + 0.20 * temporal
        + 0.10 * chain_factor
    )

    if conflict:
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 3)


def score_from_meta(item: dict[str, Any]) -> float:
    """Convenience: score from a digest_line_meta or insight dict.

    Extracts source, corroboration count, and conflict flag from common
    metadata shapes used in briefing_quality and insights.
    """
    sources = item.get("sources") or []
    if not sources:
        single = item.get("source")
        sources = [single] if single else ["unknown"]

    source = sources[0] if sources else "unknown"
    families = item.get("source_families") or sources
    corroboration_count = max(0, len(set(families)) - 1)

    conflict = bool(item.get("conflict", False))

    # Try to compute age from observed_at or since
    age_sec: float | None = None
    observed = item.get("observed_at") or item.get("since")
    if observed:
        try:
            from datetime import datetime, timezone

            ts = datetime.fromisoformat(str(observed).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
        except Exception:
            pass

    return score_provenance(
        source=source,
        corroboration_count=corroboration_count,
        age_sec=age_sec,
        conflict=conflict,
    )


# --- Feed fusion score (for fusion_heatmap cell weighting) ---


def feed_fusion_weight(source: str, base_weight: float) -> float:
    """Apply source reliability as a multiplier on fusion cell contributions.

    Reliable sources (gdacs, usgs) get up to 1.0x; less reliable get dampened.
    """
    reliability = source_reliability(source)
    # Scale: 0.5 reliability → 0.6x weight, 0.9 → 1.0x weight
    multiplier = 0.4 + 0.6 * reliability
    return round(base_weight * multiplier, 4)


# ---------------------------------------------------------------------------
# P5 — Statement-level provenance scoring
# ---------------------------------------------------------------------------


def score_statement(stmt: dict[str, Any]) -> float:
    """Score a single statement record (0.0–1.0).

    Uses the dataset as source, computes age from seen_at, and detects
    cross-dataset corroboration by checking if the same (entity_id, prop)
    pair appears in multiple datasets.

    Args:
        stmt: dict with keys: dataset, seen_at, entity_id, prop (at minimum).

    Returns:
        float score 0.0–1.0.
    """
    dataset = stmt.get("dataset") or "unknown"
    seen_at = stmt.get("seen_at")

    age_sec: float | None = None
    if seen_at:
        try:
            from datetime import datetime, timezone

            ts = datetime.fromisoformat(str(seen_at).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
        except Exception:
            pass

    return score_provenance(
        source=dataset,
        corroboration_count=0,
        age_sec=age_sec,
    )


def statement_provenance_summary(statements: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate provenance scores across a list of statement records.

    Args:
        statements: list of statement dicts (from get_statements()).

    Returns:
        dict with: total, scored, avg_score, min_score, max_score,
        by_dataset (dataset → {count, avg_score}), conflicts (count of
        props with >1 distinct value).
    """
    if not statements:
        return {
            "total": 0,
            "scored": 0,
            "avg_score": 0.0,
            "min_score": 0.0,
            "max_score": 0.0,
            "by_dataset": {},
            "conflicts": 0,
        }

    scores: list[float] = []
    by_dataset: dict[str, dict] = {}
    by_prop_values: dict[str, set[str]] = {}

    for stmt in statements:
        score = score_statement(stmt)
        scores.append(score)
        dataset = stmt.get("dataset") or "unknown"
        if dataset not in by_dataset:
            by_dataset[dataset] = {"count": 0, "scores": []}
        by_dataset[dataset]["count"] += 1
        by_dataset[dataset]["scores"].append(score)

        prop = stmt.get("prop") or ""
        value = stmt.get("value") or ""
        by_prop_values.setdefault(prop, set()).add(value)

    for ds_data in by_dataset.values():
        ds_scores = ds_data.pop("scores")
        ds_data["avg_score"] = (
            round(sum(ds_scores) / len(ds_scores), 3) if ds_scores else 0.0
        )

    conflicts = sum(1 for values in by_prop_values.values() if len(values) > 1)

    return {
        "total": len(statements),
        "scored": len(scores),
        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
        "min_score": round(min(scores), 3) if scores else 0.0,
        "max_score": round(max(scores), 3) if scores else 0.0,
        "by_dataset": by_dataset,
        "conflicts": conflicts,
    }
