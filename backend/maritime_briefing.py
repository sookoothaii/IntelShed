"""Maritime anomaly briefing bridge (P7).

Gathers AIS trajectory anomalies and formats them for the 24h briefing digest.
Follows the same pattern as darkweb_briefing.py:

- ``gather_maritime_anomaly_digest()`` — called from node_briefing.py
- Anomaly lines added to digest buckets (LOCAL/REGIONAL/GLOBAL)
- Watch items for high-score anomalies
- FtM Vessel correlation by MMSI
- Region prioritisation: Thailand corridors > ASEAN > global
- Fail-soft: returns empty digest when trajectory disabled or no anomalies

WORLDBASE_MARITIME_TRAJECTORY=1 enables trajectory storage (prerequisite).
No separate briefing flag — if trajectory is on, anomalies flow to briefing.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_BRIEFING_LINES = 5
_HIGH_SCORE_THRESHOLD = 0.7

_THAI_CORRIDORS = (
    "laem_chabang",
    "bangkok_port",
    "phuket",
    "malacca",
    "singapore",
)


def _classify_bucket(anomaly: dict[str, Any]) -> str:
    """Classify anomaly into LOCAL / REGIONAL / GLOBAL based on nearest port / corridor."""
    port_id = anomaly.get("nearest_port_id") or ""
    in_corridor = anomaly.get("in_corridor")

    if port_id in ("laem_chabang", "bangkok_port", "phuket"):
        return "local"
    if port_id in ("singapore", "port_klang", "penang") or in_corridor:
        return "regional"
    return "global"


def _format_anomaly_line(anomaly: dict[str, Any]) -> dict[str, Any]:
    """Format a single anomaly dict into a briefing line dict."""
    mmsi = anomaly.get("mmsi", "unknown")
    score = anomaly.get("anomaly_score", 0.0)
    port = anomaly.get("nearest_port_id") or "unknown"
    port_nm = anomaly.get("nearest_port_nm", 999.0)
    gap_sec = anomaly.get("ais_gap_max_sec", 0.0)
    night_port = anomaly.get("night_port_visits", 0)
    course_changes = anomaly.get("course_changes", 0)
    speed_var = anomaly.get("speed_variance", 0.0)
    risk_zone = anomaly.get("risk_zone_id") or ""
    mean_speed = anomaly.get("mean_speed", 0.0)

    indicators: list[str] = []
    if gap_sec > 7200:
        indicators.append(f"AIS gap {gap_sec / 3600:.1f}h")
    if night_port > 0:
        indicators.append(f"night-port x{night_port}")
    if course_changes > 5:
        indicators.append(f"course changes x{course_changes}")
    if speed_var > 15:
        indicators.append(f"speed var {speed_var:.1f}")
    if risk_zone:
        indicators.append(f"near {risk_zone}")
    if mean_speed < 1.0 and port_nm < 5:
        indicators.append("anchored near port")

    ind_str = ", ".join(indicators) if indicators else "pattern deviation"
    bucket = _classify_bucket(anomaly)
    severity = (
        "critical"
        if score >= 0.8
        else "high"
        if score >= _HIGH_SCORE_THRESHOLD
        else "medium"
    )

    text = f"MMSI {mmsi} (near {port}, score {score:.2f}): {ind_str}"

    return {
        "text": text,
        "mmsi": mmsi,
        "anomaly_score": score,
        "nearest_port": port,
        "bucket": bucket,
        "severity": severity,
        "indicators": indicators,
        "source": "maritime_trajectory",
        "sources": ["maritime_trajectory"],
    }


def _find_ftm_vessel(mmsi: str, ftm_query: Any | None = None) -> dict[str, Any] | None:
    """Find an FtM Vessel entity matching this MMSI."""
    if not mmsi or not ftm_query:
        return None
    try:
        entities = ftm_query.list_entities(limit=3000)
    except Exception:
        return None
    mmsi_str = str(mmsi)
    for ent in entities:
        if (ent.get("schema") or "") != "Vessel":
            continue
        props = ent.get("properties") or {}
        for key in ("mmsi", "imoNumber", "callSign"):
            vals = props.get(key) or []
            if isinstance(vals, list):
                for v in vals:
                    if str(v).strip() == mmsi_str:
                        return ent
            elif str(vals).strip() == mmsi_str:
                return ent
        caption = (ent.get("caption") or "").lower()
        if mmsi_str in caption:
            return ent
    return None


async def gather_maritime_anomaly_digest(
    max_lines: int = _MAX_BRIEFING_LINES,
    ftm_query: Any | None = None,
) -> dict[str, Any]:
    """Gather maritime anomaly digest for the briefing.

    Fail-soft: returns empty digest when trajectory disabled or no anomalies.
    """
    try:
        import ais_trajectory

        if not ais_trajectory.trajectory_enabled():
            return {"enabled": False, "count": 0, "lines": [], "anomalies": []}
    except Exception:
        return {"enabled": False, "count": 0, "lines": [], "anomalies": []}

    try:
        anomalies = ais_trajectory.detect_anomalies()
    except Exception as e:
        logger.warning("maritime_anomaly_digest_failed", error=str(e))
        return {"enabled": True, "count": 0, "lines": [], "anomalies": []}

    if not anomalies:
        return {"enabled": True, "count": 0, "lines": [], "anomalies": []}

    scored: list[tuple[float, dict[str, Any]]] = []
    for anomaly in anomalies:
        line = _format_anomaly_line(anomaly)
        ftm_match = _find_ftm_vessel(anomaly.get("mmsi", ""), ftm_query)
        if ftm_match:
            line["ftm_entity_id"] = ftm_match.get("id")
            line["ftm_schema"] = ftm_match.get("schema")
            line["text"] += f" — matches FtM Vessel {ftm_match.get('id', '')}"
            line["anomaly_score"] = min(line["anomaly_score"] + 0.1, 1.0)
        scored.append((line["anomaly_score"], line))

    scored.sort(key=lambda x: -x[0])
    top = scored[:max_lines]
    lines = [line for _, line in top]

    return {
        "enabled": True,
        "count": len(lines),
        "lines": lines,
        "anomalies": [a for a in anomalies[:20]],
        "total_anomalies": len(anomalies),
    }


def build_maritime_watch_items(digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate watch items for high-score maritime anomalies."""
    items: list[dict[str, Any]] = []
    for line in digest.get("lines") or []:
        score = line.get("anomaly_score", 0.0)
        if score < _HIGH_SCORE_THRESHOLD and not line.get("ftm_entity_id"):
            continue
        mmsi = line.get("mmsi", "unknown")
        items.append(
            {
                "id": f"maritime_anomaly:{mmsi}",
                "prefix": "maritime",
                "title": (
                    f"Maritime anomaly: MMSI {mmsi} near {line.get('nearest_port', 'unknown')} "
                    f"(score {score:.2f})"
                ),
                "horizon_h": 24,
                "confidence": min(score, 0.95),
                "sources": line.get("sources", ["maritime_trajectory"]),
                "bucket": line.get("bucket", "global"),
                "entity_id": line.get("ftm_entity_id"),
            }
        )
    return items
