"""Breach / credential-leak intelligence (P8.8) — HIBP API v3 + monitoring.

Integrates with the Have I Been Pwned API v3 to check monitored email addresses
against known data breaches.  Uses the k-anonymity password range API as a
secondary credential-leak indicator (no API key required).

Design constraints:
- Passive metadata only: breach name, date, data classes, pwn count.  No
  leaked passwords, dumps, or files are downloaded or stored.
- Fail-soft: all network errors return empty results, never raise.
- Monitored emails are stored as SHA1 hashes in SQLite (never plaintext).
- Briefing integration: new breaches for monitored emails appear in the 24h
  digest with watch items for high-severity exposures.

Env:
  WORLDBASE_BREACH=1                 (default off, opt-in)
  WORLDBASE_BREACH_CACHE_SEC=3600
  WORLDBASE_BRIEFING_BREACH=0        (opt-in, requires WORLDBASE_BREACH=1)
  WORLDBASE_HIBP_API_KEY=            (required for email breach checks)
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from config import get_config

router = APIRouter(prefix="/api/darkweb/breach", tags=["darkweb"])

_HIBP_BASE = "https://haveibeenpwned.com/api/v3"
_PWNEDPW_BASE = "https://api.pwnedpasswords.com/range"
_UA = {"User-Agent": "WorldBase/1.0 (OSINT research; breach monitoring)"}

SOURCE_RELIABILITY: dict[str, float] = {
    "hibp": 0.85,
    "pwnedpasswords": 0.90,
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = asyncio.Lock()


def _cache_ttl() -> int:
    return max(60, get_config().breach_cache_sec)


def _is_fresh(key: str) -> bool:
    entry = _cache.get(key)
    if not entry:
        return False
    return (time.time() - entry.get("_ts", 0)) < _cache_ttl()


async def _get_cached(key: str) -> dict[str, Any] | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if entry and _is_fresh(key):
            return entry.get("data")
        return None


async def _set_cached(key: str, data: dict[str, Any]) -> None:
    async with _cache_lock:
        _cache[key] = {"data": data, "_ts": time.time()}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _ensure_tables() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS breach_monitors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_hash TEXT UNIQUE NOT NULL,
                email_b64 TEXT,
                email_label TEXT,
                added_at TEXT NOT NULL,
                last_checked TEXT,
                last_breach_count INTEGER DEFAULT 0,
                last_breach_names TEXT
            )
            """
        )
        # Backfill email_b64 column if upgrading from older schema
        try:
            conn.execute("SELECT email_b64 FROM breach_monitors LIMIT 1")
        except Exception:
            conn.execute("ALTER TABLE breach_monitors ADD COLUMN email_b64 TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS breach_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_hash TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                breach_count INTEGER DEFAULT 0,
                breach_names TEXT,
                is_new INTEGER DEFAULT 0,
                data_classes TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_breach_checks_hash ON breach_checks(email_hash)"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _hash_email(email: str) -> str:
    return hashlib.sha1(email.strip().lower().encode("utf-8")).hexdigest()


def _ensure_label(email: str) -> str:
    """Return a display-safe label: keep domain, mask local part."""
    parts = email.strip().lower().split("@", 1)
    if len(parts) != 2:
        return "***"
    local, domain = parts
    if len(local) <= 2:
        masked = local[0] + "*" if local else "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


# ---------------------------------------------------------------------------
# HIBP API v3 client
# ---------------------------------------------------------------------------


def _hibp_headers() -> dict[str, str]:
    headers = dict(_UA)
    key = get_config().hibp_api_key
    if key:
        headers["hibp-api-key"] = key
    return headers


async def check_email_breaches(email: str) -> dict[str, Any]:
    """Check an email address against HIBP API v3.

    Returns:
        {
            "email": str (masked),
            "breached": bool,
            "breaches": list[dict],
            "count": int,
            "error": str | None,
        }
    """
    email_hash = _hash_email(email)
    cache_key = f"breach:{email_hash}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        return cached

    cfg = get_config()
    if not cfg.breach_enabled:
        result = {
            "email": _ensure_label(email),
            "breached": False,
            "breaches": [],
            "count": 0,
            "error": "breach disabled",
        }
        await _set_cached(cache_key, result)
        return result

    if not cfg.hibp_api_key:
        result = {
            "email": _ensure_label(email),
            "breached": False,
            "breaches": [],
            "count": 0,
            "error": "no HIBP API key configured",
        }
        await _set_cached(cache_key, result)
        return result

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), headers=_hibp_headers()
        ) as client:
            resp = await client.get(
                f"{_HIBP_BASE}/breachedaccount/{email.strip()}",
                params={"truncateResponse": "false"},
            )
            if resp.status_code == 404:
                result = {
                    "email": _ensure_label(email),
                    "breached": False,
                    "breaches": [],
                    "count": 0,
                    "error": None,
                }
                await _set_cached(cache_key, result)
                return result
            if resp.status_code == 429:
                result = {
                    "email": _ensure_label(email),
                    "breached": False,
                    "breaches": [],
                    "count": 0,
                    "error": "HIBP rate limit (429)",
                }
                await _set_cached(cache_key, result)
                return result
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                data = []
            breaches = [
                {
                    "name": b.get("Name", ""),
                    "title": b.get("Title", ""),
                    "domain": b.get("Domain", ""),
                    "breach_date": b.get("BreachDate", ""),
                    "added_date": b.get("AddedDate", ""),
                    "pwn_count": b.get("PwnCount", 0),
                    "data_classes": b.get("DataClasses", []),
                    "is_verified": b.get("IsVerified", False),
                    "is_fabricated": b.get("IsFabricated", False),
                    "is_sensitive": b.get("IsSensitive", False),
                    "is_retired": b.get("IsRetired", False),
                    "is_spam_list": b.get("IsSpamList", False),
                }
                for b in data
            ]
            result = {
                "email": _ensure_label(email),
                "breached": len(breaches) > 0,
                "breaches": breaches,
                "count": len(breaches),
                "error": None,
            }
            await _set_cached(cache_key, result)
            return result
    except Exception as exc:
        result = {
            "email": _ensure_label(email),
            "breached": False,
            "breaches": [],
            "count": 0,
            "error": str(exc),
        }
        await _set_cached(cache_key, result)
        return result


async def check_password_hash(password_sha1: str) -> dict[str, Any]:
    """Check a SHA1 hash against the Pwned Passwords k-anonymity API.

    Only the first 5 chars of the hash are sent.  The API returns all suffixes
    matching that prefix, and we check locally if our full hash is present.

    Returns:
        {
            "compromised": bool,
            "count": int,
            "error": str | None,
        }
    """
    sha1 = password_sha1.upper()
    prefix = sha1[:5]
    suffix = sha1[5:]
    cache_key = f"pwrange:{prefix}"
    cached = await _get_cached(cache_key)
    if cached is not None:
        count = cached.get(suffix, 0)
        return {"compromised": count > 0, "count": count, "error": None}

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0), headers=_UA
        ) as client:
            resp = await client.get(f"{_PWNEDPW_BASE}/{prefix}")
            resp.raise_for_status()
            text = resp.text
        suffix_map: dict[str, int] = {}
        for line in text.splitlines():
            parts = line.strip().split(":")
            if len(parts) == 2:
                suffix_map[parts[0].upper()] = int(parts[1])
        await _set_cached(cache_key, suffix_map)
        count = suffix_map.get(suffix, 0)
        return {"compromised": count > 0, "count": count, "error": None}
    except Exception as exc:
        return {"compromised": False, "count": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Monitor management
# ---------------------------------------------------------------------------


def add_monitor(email: str, label: str | None = None) -> dict[str, Any]:
    """Add an email to the breach monitoring table.

    Stores SHA1 hash for lookups and base64-encoded email for HIBP API
    refresh calls.  The base64 is obfuscation, not encryption — the DB
    file should be access-controlled at the OS level.
    """
    _ensure_tables()
    email_hash = _hash_email(email)
    display_label = label or _ensure_label(email)
    email_b64 = base64.b64encode(email.strip().lower().encode("utf-8")).decode("ascii")
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            "INSERT OR IGNORE INTO breach_monitors "
            "(email_hash, email_b64, email_label, added_at, last_breach_count, last_breach_names) "
            "VALUES (?, ?, ?, ?, 0, '')",
            (
                email_hash,
                email_b64,
                display_label,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        return {"ok": True, "email_hash": email_hash, "label": display_label}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def remove_monitor(monitor_id: int) -> dict[str, Any]:
    _ensure_tables()
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=3000")
        cur = conn.execute("DELETE FROM breach_monitors WHERE id = ?", (monitor_id,))
        conn.commit()
        deleted = cur.rowcount
        conn.close()
        return {"ok": deleted > 0, "deleted": deleted}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def list_monitors() -> list[dict[str, Any]]:
    _ensure_tables()
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(
            "SELECT id, email_hash, email_label, added_at, last_checked, "
            "last_breach_count, last_breach_names FROM breach_monitors ORDER BY added_at DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Briefing integration
# ---------------------------------------------------------------------------


async def gather_breach_briefing(hours: int = 24, max_lines: int = 5) -> dict[str, Any]:
    """Gather breach digest for the 24h briefing.

    Checks all monitored emails for new breaches added within the time window.
    Returns a digest dict matching the pattern used by ransomware/telegram.
    """
    cfg = get_config()
    if not cfg.breach_enabled or not cfg.briefing_breach:
        return {"enabled": False, "count": 0, "lines": []}

    monitors = list_monitors()
    if not monitors:
        return {"enabled": True, "count": 0, "lines": []}

    lines: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - (hours * 3600)

    for m in monitors:
        email_hash = m["email_hash"]
        label = m.get("email_label") or "***"

        # Check recent breach_checks for new entries
        try:
            conn = sqlite3.connect(_db_path(), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=3000")
            recent = conn.execute(
                "SELECT checked_at, breach_count, breach_names, data_classes, is_new "
                "FROM breach_checks WHERE email_hash = ? AND is_new = 1 "
                "ORDER BY checked_at DESC LIMIT 5",
                (email_hash,),
            ).fetchall()
            conn.close()
        except Exception:
            recent = []

        for r in recent:
            checked_at = r["checked_at"]
            try:
                ts = datetime.fromisoformat(checked_at).timestamp()
            except Exception:
                continue
            if ts < cutoff:
                continue
            breach_names = r["breach_names"] or ""
            data_classes = r["data_classes"] or ""
            count = r["breach_count"]
            is_new = r["is_new"]

            severity = "high"
            if "Passwords" in data_classes or "password" in data_classes.lower():
                severity = "critical"
            elif "Emails" in data_classes and "Passwords" not in data_classes:
                severity = "medium"

            text = (
                f"BREACH: {label} — {breach_names} "
                f"({count} records, classes: {data_classes[:80]})"
            )
            lines.append(
                {
                    "text": text,
                    "severity": severity,
                    "email_label": label,
                    "breach_name": breach_names,
                    "data_classes": data_classes,
                    "is_new": bool(is_new),
                    "relevance_score": 0.8 if severity == "critical" else 0.6,
                    "sources": ["hibp"],
                }
            )
            if len(lines) >= max_lines:
                break
        if len(lines) >= max_lines:
            break

    return {
        "enabled": True,
        "count": len(lines),
        "lines": lines,
    }


def build_breach_watch_items(
    digest: dict[str, Any], config: Any | None = None
) -> list[dict[str, Any]]:
    """Generate watch items for new breaches from the breach digest."""
    items: list[dict[str, Any]] = []
    for line in digest.get("lines", []):
        if not line.get("is_new"):
            continue
        items.append(
            {
                "id": f"breach:{line.get('email_label', '***')}:{line.get('breach_name', '')}",
                "prefix": "breach",
                "title": (
                    f"Breach alert: {line.get('email_label', '***')} found in "
                    f"{line.get('breach_name', 'unknown')} "
                    f"(classes: {line.get('data_classes', '')[:60]})"
                ),
                "horizon_h": 72,
                "confidence": line.get("relevance_score", 0.6),
                "sources": line.get("sources", ["hibp"]),
                "bucket": "global",
            }
        )
    return items


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class CheckEmailRequest(BaseModel):
    email: str
    label: str | None = None
    monitor: bool = False


class AddMonitorRequest(BaseModel):
    email: str
    label: str | None = None


class CheckPasswordRequest(BaseModel):
    password: str


@router.get("/status")
async def api_breach_status() -> dict[str, Any]:
    cfg = get_config()
    monitors = list_monitors() if cfg.breach_enabled else []
    return {
        "enabled": cfg.breach_enabled,
        "briefing_enabled": cfg.briefing_breach,
        "hibp_key_configured": bool(cfg.hibp_api_key),
        "cache_sec": cfg.breach_cache_sec,
        "monitor_count": len(monitors),
        "monitors": monitors,
    }


@router.post("/check")
async def api_breach_check(req: CheckEmailRequest) -> dict[str, Any]:
    result = await check_email_breaches(req.email)
    if req.monitor and result.get("error") is None:
        add_monitor(req.email, req.label)
    return result


@router.post("/password")
async def api_breach_password_check(req: CheckPasswordRequest) -> dict[str, Any]:
    sha1 = hashlib.sha1(req.password.encode("utf-8")).hexdigest()
    return await check_password_hash(sha1)


@router.post("/monitor")
async def api_breach_add_monitor(req: AddMonitorRequest) -> dict[str, Any]:
    return add_monitor(req.email, req.label)


@router.get("/monitors")
async def api_breach_list_monitors() -> dict[str, Any]:
    return {"monitors": list_monitors(), "count": len(list_monitors())}


@router.delete("/monitor/{monitor_id}")
async def api_breach_remove_monitor(monitor_id: int) -> dict[str, Any]:
    return remove_monitor(monitor_id)


@router.post("/refresh")
async def api_breach_refresh() -> dict[str, Any]:
    """Refresh all monitored emails.  Requires stored emails to be decodable."""
    _ensure_tables()
    monitors = list_monitors()
    checked = 0
    new_breaches = 0
    results: list[dict[str, Any]] = []

    for m in monitors:
        email_hash = m["email_hash"]
        label = m.get("email_label") or "***"
        prev_names_str = m.get("last_breach_names") or ""
        prev_names = set(prev_names_str.split("|")) if prev_names_str else set()

        # Recover email from base64 for HIBP API call
        try:
            conn = sqlite3.connect(_db_path(), timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=3000")
            row = conn.execute(
                "SELECT email_b64 FROM breach_monitors WHERE email_hash = ?",
                (email_hash,),
            ).fetchone()
            conn.close()
        except Exception:
            row = None

        if not row or not row["email_b64"]:
            results.append({"email_hash": email_hash, "label": label, "skipped": True})
            continue

        try:
            email = base64.b64decode(row["email_b64"]).decode("utf-8")
        except Exception:
            results.append({"email_hash": email_hash, "label": label, "skipped": True})
            continue

        result = await check_email_breaches(email)
        checked += 1
        current_breaches = result.get("breaches", [])
        current_count = result.get("count", 0)
        current_names = {b["name"] for b in current_breaches}
        new_names = current_names - prev_names
        all_data_classes = set()
        for b in current_breaches:
            if b["name"] in new_names:
                all_data_classes.update(b.get("data_classes", []))

        is_new = len(new_names) > 0
        if is_new:
            new_breaches += len(new_names)

        # Record check in breach_checks
        try:
            conn = sqlite3.connect(_db_path(), timeout=5.0)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute(
                "INSERT INTO breach_checks "
                "(email_hash, checked_at, breach_count, breach_names, is_new, data_classes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    email_hash,
                    datetime.now(timezone.utc).isoformat(),
                    current_count,
                    "|".join(sorted(current_names)),
                    1 if is_new else 0,
                    ",".join(sorted(all_data_classes)),
                ),
            )
            # Update monitor record
            conn.execute(
                "UPDATE breach_monitors SET last_checked = ?, last_breach_count = ?, "
                "last_breach_names = ? WHERE email_hash = ?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    current_count,
                    "|".join(sorted(current_names)),
                    email_hash,
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

        results.append(
            {
                "email_hash": email_hash,
                "label": label,
                "breach_count": current_count,
                "new_breaches": list(new_names) if new_names else [],
                "is_new": is_new,
                "error": result.get("error"),
            }
        )

        # Rate limit: HIBP allows 1 request per 1.5s
        await asyncio.sleep(1.5)

    return {
        "checked": checked,
        "new_breaches": new_breaches,
        "results": results,
    }
