"""Telegram SOCMINT briefing bridge (K3).

Selects and prioritizes recent Telegram posts for the 24h digest. SEA relevance
and FtM correlation dominate the ranking; the bridge is fail-soft when the
Telegram feature is disabled or no posts are cached.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import telegram_bridge
from config import get_config


async def gather_telegram_briefing() -> dict[str, Any]:
    """Return a digest-ready summary of recent Telegram posts.

    Mirrors the darkweb_briefing / ransomware briefing contract:
    ``{"enabled", "count", "lines", "posts"}``.
    """
    cfg = get_config()
    if not cfg.telegram_enabled or not cfg.briefing_telegram:
        return {"enabled": False, "count": 0, "lines": [], "posts": []}

    try:
        posts = telegram_bridge.get_cached_posts_sync()
    except Exception:
        posts = []

    if not posts:
        return {"enabled": True, "count": 0, "lines": [], "posts": []}

    recent = [p for p in posts if _is_recent(p, hours=24)]
    ranked = sorted(recent, key=lambda x: -float(x.get("score") or 0))
    top = ranked[:8]

    return {
        "enabled": True,
        "count": len(top),
        "lines": [_format_briefing_line(p) for p in top],
        "posts": top,
    }


def build_telegram_watch_items(telegram_digest: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate watch items from high-priority Telegram posts."""
    items: list[dict[str, Any]] = []
    if not telegram_digest.get("enabled"):
        return items

    for p in telegram_digest.get("posts", []):
        score = float(p.get("score") or 0)
        if score < 0.55:
            continue
        bucket = _post_bucket(p)
        countries = p.get("countries") or []
        title = _format_briefing_line(p)
        items.append(
            _watch_item(
                prefix="telegram",
                key=p.get("id", "")[:16],
                title=title,
                horizon_h=24,
                confidence=min(0.9, 0.55 + score * 0.3),
                sources=["telegram"],
                bucket=bucket,
                cell_id=_cell_id(p.get("lat"), p.get("lon")),
                extra={"score": score, "countries": countries},
            )
        )
    return items


def _post_bucket(p: dict[str, Any]) -> str:
    """Classify a post into local / regional / global buckets."""
    cfg = get_config()
    region = cfg.operator_region
    countries = [c.lower() for c in (p.get("countries") or [])]
    cities = [c.lower() for c in (p.get("cities") or [])]

    if region in countries:
        return "local"
    if region and any(c in cities for c in _operator_cities(region)):
        return "local"
    if any(c in _SEA_COUNTRIES for c in countries):
        return "regional"
    return "global"


def _operator_cities(region: str) -> list[str]:
    mapping = {
        "thailand": ["bangkok", "chiang mai", "pattaya", "phuket"],
        "germany": ["berlin", "hamburg", "munich"],
        "bangkok": ["bangkok"],
    }
    return mapping.get(region, [])


_SEA_COUNTRIES = {
    "thailand",
    "myanmar",
    "burma",
    "cambodia",
    "vietnam",
    "laos",
    "malaysia",
    "singapore",
    "indonesia",
    "philippines",
    "brunei",
    "east timor",
    "timor-leste",
}


def _format_briefing_line(p: dict[str, Any]) -> str:
    channel = p.get("channel", "")
    text = _first_sentence(p.get("text", ""), 120)
    flags = []
    if p.get("countries"):
        flags.append(",".join(p["countries"][:2]))
    if p.get("score"):
        flags.append(f"score={p['score']}")
    tail = f" ({', '.join(flags)})" if flags else ""
    return f"Telegram {channel}: {text}{tail}"


def _first_sentence(text: str, max_len: int = 140) -> str:
    text = text.strip().replace("\n", " ")
    if not text:
        return ""
    for sep in ".!?":
        if sep in text:
            idx = text.find(sep)
            if idx > 10:
                return text[: idx + 1].strip()[:max_len]
    return text[:max_len]


def _is_recent(p: dict[str, Any], hours: int = 24) -> bool:
    try:
        dt = datetime.fromisoformat(p.get("date", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)
    except Exception:
        return False


def _watch_item(
    *,
    prefix: str,
    key: str,
    title: str,
    horizon_h: int,
    confidence: float,
    sources: list[str],
    bucket: str,
    cell_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": f"{prefix}:{key}",
        "prefix": prefix,
        "title": title[:160],
        "horizon_h": horizon_h,
        "confidence": round(confidence, 3),
        "sources": sources,
        "bucket": bucket,
        "cell_id": cell_id,
        "extra": extra or {},
    }


def _cell_id(lat: Any, lon: Any) -> str | None:
    if lat is None or lon is None:
        return None
    try:
        return f"{int(float(lat))}:{int(float(lon))}"
    except Exception:
        return None


def _correlate_ftm_names(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark posts that mention entities already in the FtM graph.

    Lightweight keyword overlap against entity captions; returns posts with
    an added ``ftm_matches`` list.
    """
    if not posts:
        return posts
    try:
        import ftm_query

        rows = ftm_query.list_entities(limit=2000)
        captions = [r.get("caption", "") for r in rows if r.get("caption")]
    except Exception:
        return posts

    for p in posts:
        text = f"{p.get('text', '')} {' '.join(p.get('hashtags', []))}".lower()
        matches = []
        for cap in captions:
            if not cap:
                continue
            words = [w for w in re.findall(r"\w{3,}", cap.lower()) if len(w) >= 4]
            hits = [w for w in set(words) if w in text]
            if hits:
                matches.append({"caption": cap, "hits": hits})
        p["ftm_matches"] = matches[:3]
    return posts
