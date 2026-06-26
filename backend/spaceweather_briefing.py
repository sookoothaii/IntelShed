"""Space weather briefing bridge — turns NOAA SWPC snapshot into digest lines.

Fail-soft: every upstream field is optional. If no data is available, the digest
is disabled and the prompt block is skipped.
"""

from __future__ import annotations

from typing import Any


def _f(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _severity(kp: float | None, dst: float | None, alerts: list[dict]) -> str:
    if any(a.get("severity", "").lower() in ("extreme", "severe") for a in alerts):
        return "high"
    if (kp is not None and kp >= 7) or (dst is not None and dst <= -100):
        return "high"
    if (kp is not None and kp >= 5) or (dst is not None and dst <= -80):
        return "medium"
    return "low"


def gather_spaceweather_digest(snap: dict) -> dict[str, Any]:
    """Build a compact digest block from the /api/spaceweather snapshot."""
    sw = snap.get("spaceweather") or {}
    if not sw or sw.get("kp_index") is None and sw.get("error"):
        return {"enabled": False, "count": 0, "lines": []}

    kp = sw.get("kp_index")
    dst = sw.get("dst")
    solar = sw.get("solar_wind") or {}
    protons = sw.get("protons") or {}
    alerts = sw.get("alerts") or []
    forecast = sw.get("forecast") or []
    scale = sw.get("scale") or "unknown"

    lines: list[str] = []
    parts = [f"Kp={_f(kp)} ({scale})"] if kp is not None else [f"Kp={_f(kp)}"]
    if dst is not None:
        parts.append(f"Dst={_f(dst)} nT")
    if solar.get("speed_km_s") is not None:
        parts.append(f"solar wind {_f(solar['speed_km_s'])} km/s")
    if protons.get("gt_10_mev") is not None:
        parts.append(f"protons >10 MeV {_f(protons['gt_10_mev'])}")
    lines.append("Space weather: " + ", ".join(parts))

    if alerts:
        for a in alerts[:3]:
            msg = a.get("message", "").strip()
            if not msg:
                continue
            lines.append(f"SWPC alert: {msg[:140]}")

    if forecast:
        upcoming = [f for f in forecast if f.get("kp") is not None][:3]
        if upcoming:
            fc_parts = [f"{_f(f['kp'])} at {f.get('time', '—')}" for f in upcoming]
            lines.append("Kp forecast: " + "; ".join(fc_parts))

    return {
        "enabled": True,
        "count": len(lines),
        "lines": lines,
        "kp": kp,
        "dst": dst,
        "scale": scale,
        "alerts": alerts,
        "sources": ["spaceweather"],
    }


def build_spaceweather_watch_items(digest: dict) -> list[dict[str, Any]]:
    """Generate watch items for significant space-weather conditions."""
    if not digest.get("enabled"):
        return []

    items: list[dict[str, Any]] = []
    kp = digest.get("kp")
    dst = digest.get("dst")
    alerts = digest.get("alerts") or []

    sev = _severity(kp, dst, alerts)
    if sev in ("high", "medium"):
        title_parts = [f"Space weather — Kp {_f(kp)}"]
        if dst is not None:
            title_parts.append(f"Dst {_f(dst)} nT")
        items.append(
            {
                "id": "spacewx:storm",
                "prefix": "spacewx",
                "key": f"{kp}:{dst}",
                "title": ", ".join(title_parts),
                "horizon_h": 24,
                "confidence": 0.85 if sev == "high" else 0.65,
                "sources": ["spaceweather"],
                "bucket": "global",
            }
        )

    for a in alerts[:2]:
        msg = (a.get("message") or "").strip()
        if not msg:
            continue
        asev = a.get("severity", "").lower()
        conf = 0.85 if asev in ("extreme", "severe") else 0.65
        items.append(
            {
                "id": f"spacewx:alert:{hash(msg) & 0xFFFFFFFF}",
                "prefix": "spacewx_alert",
                "key": msg[:80],
                "title": f"SWPC alert: {msg[:120]}",
                "horizon_h": 12,
                "confidence": conf,
                "sources": ["spaceweather"],
                "bucket": "global",
            }
        )

    return items
