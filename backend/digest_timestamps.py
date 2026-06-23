"""Digest line timestamps — parse feed dates and format HUD/LLM tags."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_observed_at(raw: str | float | int | datetime | None) -> datetime | None:
    """Parse GDELT seendate, ISO-8601, Unix epoch, or NewsData pubDate."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    if len(s) >= 15 and s[0:8].isdigit() and "T" in s and s.endswith("Z"):
        try:
            return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass
    for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            dt = datetime.strptime(s[:width], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def format_digest_date_tag(dt: datetime | None) -> str:
    """Compact English prefix for digest lines, e.g. ``[22 Jun 14:30 UTC]``."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("[%d %b %H:%M UTC]")


def normalize_observed_at(raw: str | float | int | datetime | None) -> str | None:
    dt = parse_observed_at(raw)
    if not dt:
        return None
    return dt.isoformat()


def feed_block_updated_at(block: dict[str, Any] | None) -> str | None:
    if not block:
        return None
    return normalize_observed_at(block.get("updated") or block.get("cached_at"))


def apply_observed_at(
    text: str,
    observed_at: str | float | int | datetime | None,
) -> tuple[str, str | None]:
    """Return display text with date tag and ISO ``observed_at`` for metadata."""
    iso = normalize_observed_at(observed_at)
    if not iso:
        return text.strip(), None
    tag = format_digest_date_tag(parse_observed_at(iso))
    body = f"{tag} {text}".strip() if tag else text.strip()
    return body, iso
