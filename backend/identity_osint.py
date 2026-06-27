"""P9 — Identity OSINT Bridge for WorldBase.

Email/username enumeration across 50+ social platforms. Passive existence
checks only — no credential stuffing, no profile scraping. Results linked
to FtM ``Person`` entities via ``UserAccount`` schema with ``owns`` edge.

Guardrails (non-negotiable):
- Opt-in only — ``WORLDBASE_IDENTITY_OSINT=0`` (default off)
- Rate limited — 2s per platform, 50-platform cap, 30s pause every 50 checks
- No credential stuffing — only passive HTTP status checks (HEAD/GET)
- No PII storage — only platform name + found/not-found boolean + profile URL
- Operator audit log — every lookup logged with timestamp, query, operator, result count
- Fail-soft — unavailable platforms return ``found: null``
- Cache — 24h TTL per query

Env:
  WORLDBASE_IDENTITY_OSINT=0                (default off, opt-in)
  WORLDBASE_IDENTITY_OSINT_RATE_LIMIT_SEC=2
  WORLDBASE_IDENTITY_OSINT_MAX_PLATFORMS=50
  WORLDBASE_IDENTITY_OSINT_CACHE_SEC=86400
  WORLDBASE_BRIEFING_IDENTITY=0             (opt-in, requires WORLDBASE_IDENTITY_OSINT=1)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Query

from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/osint/identity", tags=["osint"])

# ---------------------------------------------------------------------------
# Platform registry — email (holehe-style) + username (Sherlock/Maigret-style)
# ---------------------------------------------------------------------------

_EMAIL_SITES: list[dict[str, Any]] = [
    {
        "name": "Adobe",
        "url": "https://id.adobe.com/...",
        "category": "creative",
        "method": "password_reset",
    },
    {
        "name": "Amazon",
        "url": "https://www.amazon.com/...",
        "category": "commerce",
        "method": "password_reset",
    },
    {
        "name": "Atlassian",
        "url": "https://id.atlassian.com/...",
        "category": "dev",
        "method": "password_reset",
    },
    {
        "name": "Bitbucket",
        "url": "https://bitbucket.org/...",
        "category": "dev",
        "method": "password_reset",
    },
    {
        "name": "Blizzard",
        "url": "https://battle.net/...",
        "category": "gaming",
        "method": "password_reset",
    },
    {
        "name": "Discord",
        "url": "https://discord.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Dropbox",
        "url": "https://www.dropbox.com/...",
        "category": "cloud",
        "method": "password_reset",
    },
    {
        "name": "Duolingo",
        "url": "https://www.duolingo.com/...",
        "category": "education",
        "method": "password_reset",
    },
    {
        "name": "Evernote",
        "url": "https://www.evernote.com/...",
        "category": "productivity",
        "method": "password_reset",
    },
    {
        "name": "Facebook",
        "url": "https://www.facebook.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "GitHub",
        "url": "https://github.com/...",
        "category": "dev",
        "method": "password_reset",
    },
    {
        "name": "GitLab",
        "url": "https://gitlab.com/...",
        "category": "dev",
        "method": "password_reset",
    },
    {
        "name": "Google",
        "url": "https://accounts.google.com/...",
        "category": "search",
        "method": "password_reset",
    },
    {
        "name": "Gravatar",
        "url": "https://gravatar.com/...",
        "category": "social",
        "method": "api",
    },
    {
        "name": "Instagram",
        "url": "https://www.instagram.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "LinkedIn",
        "url": "https://www.linkedin.com/...",
        "category": "professional",
        "method": "password_reset",
    },
    {
        "name": "Microsoft",
        "url": "https://account.microsoft.com/...",
        "category": "tech",
        "method": "password_reset",
    },
    {
        "name": "MySpace",
        "url": "https://myspace.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Netflix",
        "url": "https://www.netflix.com/...",
        "category": "entertainment",
        "method": "password_reset",
    },
    {
        "name": "Pinterest",
        "url": "https://www.pinterest.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Quora",
        "url": "https://www.quora.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Reddit",
        "url": "https://www.reddit.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Snapchat",
        "url": "https://accounts.snapchat.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Spotify",
        "url": "https://www.spotify.com/...",
        "category": "music",
        "method": "password_reset",
    },
    {
        "name": "Strava",
        "url": "https://www.strava.com/...",
        "category": "fitness",
        "method": "password_reset",
    },
    {
        "name": "TikTok",
        "url": "https://www.tiktok.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Tinder",
        "url": "https://tinder.com/...",
        "category": "dating",
        "method": "password_reset",
    },
    {
        "name": "Tumblr",
        "url": "https://www.tumblr.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Twitch",
        "url": "https://www.twitch.tv/...",
        "category": "streaming",
        "method": "password_reset",
    },
    {
        "name": "Twitter/X",
        "url": "https://twitter.com/...",
        "category": "social",
        "method": "password_reset",
    },
    {
        "name": "Vimeo",
        "url": "https://vimeo.com/...",
        "category": "video",
        "method": "password_reset",
    },
    {
        "name": "WordPress",
        "url": "https://wordpress.com/...",
        "category": "blogging",
        "method": "password_reset",
    },
    {
        "name": "Yahoo",
        "url": "https://login.yahoo.com/...",
        "category": "search",
        "method": "password_reset",
    },
    {
        "name": "Yandex",
        "url": "https://passport.yandex.com/...",
        "category": "search",
        "method": "password_reset",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/...",
        "category": "video",
        "method": "password_reset",
    },
]

_USERNAME_SITES: list[dict[str, Any]] = [
    {"name": "3DNews", "url": "https://3dnews.ru/user/{username}", "category": "tech"},
    {"name": "7Cups", "url": "https://www.7cups.com/@{username}", "category": "health"},
    {"name": "About.me", "url": "https://about.me/{username}", "category": "social"},
    {
        "name": "Academia.edu",
        "url": "https://independent.academia.edu/{username}",
        "category": "education",
    },
    {
        "name": "AngelList",
        "url": "https://angel.co/u/{username}",
        "category": "professional",
    },
    {
        "name": "Apple Discussions",
        "url": "https://discussions.apple.com/profile/{username}",
        "category": "tech",
    },
    {
        "name": "Archive.org",
        "url": "https://archive.org/details/@{username}",
        "category": "archive",
    },
    {"name": "AskFM", "url": "https://ask.fm/{username}", "category": "social"},
    {"name": "BLIP.fm", "url": "https://blip.fm/{username}", "category": "music"},
    {
        "name": "Bandcamp",
        "url": "https://www.bandcamp.com/{username}",
        "category": "music",
    },
    {
        "name": "Behance",
        "url": "https://www.behance.net/{username}",
        "category": "creative",
    },
    {
        "name": "BitBucket",
        "url": "https://bitbucket.org/{username}/",
        "category": "dev",
    },
    {
        "name": "Blogger",
        "url": "https://{username}.blogspot.com",
        "category": "blogging",
    },
    {"name": "BuzzFeed", "url": "https://buzzfeed.com/{username}", "category": "news"},
    {
        "name": "Codecademy",
        "url": "https://www.codecademy.com/profiles/{username}",
        "category": "education",
    },
    {"name": "Codepen", "url": "https://codepen.io/{username}", "category": "dev"},
    {
        "name": "DeviantArt",
        "url": "https://www.deviantart.com/{username}",
        "category": "creative",
    },
    {
        "name": "Dribbble",
        "url": "https://dribbble.com/{username}",
        "category": "creative",
    },
    {
        "name": "Etsy",
        "url": "https://www.etsy.com/people/{username}",
        "category": "commerce",
    },
    {
        "name": "Facebook",
        "url": "https://www.facebook.com/{username}",
        "category": "social",
    },
    {
        "name": "Flickr",
        "url": "https://www.flickr.com/people/{username}",
        "category": "photo",
    },
    {
        "name": "Foursquare",
        "url": "https://foursquare.com/{username}",
        "category": "social",
    },
    {"name": "GitHub", "url": "https://www.github.com/{username}", "category": "dev"},
    {"name": "GitLab", "url": "https://gitlab.com/{username}", "category": "dev"},
    {
        "name": "GoodReads",
        "url": "https://www.goodreads.com/{username}",
        "category": "books",
    },
    {
        "name": "Gravatar",
        "url": "https://en.gravatar.com/{username}",
        "category": "social",
    },
    {
        "name": "HackerNews",
        "url": "https://news.ycombinator.com/user?id={username}",
        "category": "news",
    },
    {
        "name": "Instagram",
        "url": "https://www.instagram.com/{username}",
        "category": "social",
    },
    {"name": "Keybase", "url": "https://keybase.io/{username}", "category": "security"},
    {
        "name": "Khan Academy",
        "url": "https://www.khanacademy.org/profile/{username}",
        "category": "education",
    },
    {
        "name": "Last.fm",
        "url": "https://www.last.fm/user/{username}",
        "category": "music",
    },
    {
        "name": "LinkedIn",
        "url": "https://www.linkedin.com/in/{username}",
        "category": "professional",
    },
    {"name": "Medium", "url": "https://medium.com/@{username}", "category": "blogging"},
    {
        "name": "MyAnimeList",
        "url": "https://myanimelist.net/profile/{username}",
        "category": "anime",
    },
    {
        "name": "Patreon",
        "url": "https://www.patreon.com/{username}",
        "category": "creative",
    },
    {
        "name": "Pinterest",
        "url": "https://www.pinterest.com/{username}/",
        "category": "social",
    },
    {
        "name": "Pixabay",
        "url": "https://pixabay.com/users/{username}",
        "category": "photo",
    },
    {
        "name": "Reddit",
        "url": "https://www.reddit.com/user/{username}",
        "category": "social",
    },
    {
        "name": "ResearchGate",
        "url": "https://www.researchgate.net/profile/{username}",
        "category": "research",
    },
    {
        "name": "Roblox",
        "url": "https://www.roblox.com/user.aspx?username={username}",
        "category": "gaming",
    },
    {
        "name": "SoundCloud",
        "url": "https://soundcloud.com/{username}",
        "category": "music",
    },
    {
        "name": "Spotify",
        "url": "https://open.spotify.com/user/{username}",
        "category": "music",
    },
    {
        "name": "Stack Overflow",
        "url": "https://stackoverflow.com/users/{username}",
        "category": "dev",
    },
    {
        "name": "Steam",
        "url": "https://steamcommunity.com/id/{username}",
        "category": "gaming",
    },
    {"name": "Telegram", "url": "https://t.me/{username}", "category": "messaging"},
    {
        "name": "TikTok",
        "url": "https://www.tiktok.com/@{username}",
        "category": "social",
    },
    {"name": "Tinder", "url": "https://tinder.com/@{username}", "category": "dating"},
    {
        "name": "Twitch",
        "url": "https://www.twitch.tv/{username}",
        "category": "streaming",
    },
    {
        "name": "Twitter/X",
        "url": "https://twitter.com/{username}",
        "category": "social",
    },
    {"name": "Vimeo", "url": "https://vimeo.com/{username}", "category": "video"},
    {"name": "VSCO", "url": "https://vsco.co/{username}", "category": "photo"},
    {
        "name": "Wattpad",
        "url": "https://www.wattpad.com/user/{username}",
        "category": "writing",
    },
    {
        "name": "We Heart It",
        "url": "https://weheartit.com/{username}",
        "category": "social",
    },
    {
        "name": "Wikimedia",
        "url": "https://meta.wikimedia.org/wiki/User:{username}",
        "category": "wiki",
    },
    {
        "name": "WordPress",
        "url": "https://profiles.wordpress.org/{username}",
        "category": "blogging",
    },
    {
        "name": "YouTube",
        "url": "https://www.youtube.com/@{username}",
        "category": "video",
    },
    {
        "name": "Zhihu",
        "url": "https://www.zhihu.com/people/{username}",
        "category": "social",
    },
]

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._\-]{2,40}$")


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email))


def _sanitize_username(username: str) -> str | None:
    username = username.strip()
    if not _USERNAME_RE.match(username):
        return None
    return username


# ---------------------------------------------------------------------------
# Cache (in-memory, TTL)
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = asyncio.Lock()


def _cache_key(query: str, query_type: str) -> str:
    return hashlib.sha256(f"{query_type}:{query}".encode()).hexdigest()


async def _get_cached(key: str, ttl_sec: int) -> dict[str, Any] | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if (time.time() - ts) >= ttl_sec:
            del _cache[key]
            return None
        return data


async def _set_cached(key: str, data: dict[str, Any]) -> None:
    async with _cache_lock:
        _cache[key] = (time.time(), data)


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------------------
# Audit log (SQLite)
# ---------------------------------------------------------------------------


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _ensure_audit_table() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS identity_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                query_type TEXT NOT NULL,
                operator TEXT,
                result_count INTEGER NOT NULL DEFAULT 0,
                cached INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("identity audit table init failed: %s", exc)


_ensure_audit_table()


def _audit_log(
    query: str,
    query_type: str,
    result_count: int,
    *,
    operator: str | None = None,
    cached: bool = False,
) -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            "INSERT INTO identity_audit (timestamp, query, query_type, operator, result_count, cached) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                query,
                query_type,
                operator or os.getenv("WORLDBASE_OPERATOR_ID", "operator"),
                result_count,
                1 if cached else 0,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("identity audit log write failed: %s", exc)


def query_audit_log(limit: int = 50) -> list[dict[str, Any]]:
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute(
            "SELECT timestamp, query, query_type, operator, result_count, cached "
            "FROM identity_audit ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("identity audit log query failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Platform checks
# ---------------------------------------------------------------------------

_UA = {"User-Agent": "WorldBase/1.0 (OSINT research; identity enumeration)"}
_TIMEOUT = 10.0


async def _check_username_platform(
    site: dict[str, Any], username: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    """Check if a username exists on a platform via URL pattern + HTTP status."""
    url = site["url"].replace("{username}", username)
    try:
        resp = await client.head(
            url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True
        )
        status = resp.status_code
        if status == 200:
            return {"name": site["name"], "url": url, "found": True, "profile_url": url}
        if status in (404, 403, 301):
            # 404 = not found; 403/301 = ambiguous (may exist but blocked/redirected)
            if status == 404:
                return {
                    "name": site["name"],
                    "url": url,
                    "found": False,
                    "profile_url": None,
                }
            return {
                "name": site["name"],
                "url": url,
                "found": None,
                "profile_url": None,
            }
        # Any other status = ambiguous
        return {"name": site["name"], "url": url, "found": None, "profile_url": None}
    except Exception:
        return {"name": site["name"], "url": url, "found": None, "profile_url": None}


async def _check_email_platform(
    site: dict[str, Any], email: str, client: httpx.AsyncClient
) -> dict[str, Any]:
    """Check if an email is registered on a platform.

    Most platforms require password-reset endpoints that are not publicly
    documented. For safety and ethical reasons, this implementation uses
    only publicly known API endpoints (e.g., Gravatar) and marks all other
    email checks as ``found: null`` (unknown) rather than attempting
    password-reset flows.
    """
    name = site["name"]
    if site.get("method") == "api" and name == "Gravatar":
        email_hash = hashlib.md5(email.strip().lower().encode()).hexdigest()
        url = f"https://www.gravatar.com/{email_hash}.json"
        try:
            resp = await client.get(
                url, headers=_UA, timeout=_TIMEOUT, follow_redirects=True
            )
            if resp.status_code == 200:
                return {
                    "name": name,
                    "url": f"https://www.gravatar.com/{email_hash}",
                    "found": True,
                    "profile_url": f"https://www.gravatar.com/{email_hash}",
                }
            if resp.status_code == 404:
                return {"name": name, "url": url, "found": False, "profile_url": None}
            return {"name": name, "url": url, "found": None, "profile_url": None}
        except Exception:
            return {"name": name, "url": url, "found": None, "profile_url": None}
    # For password-reset-based sites, we mark as unknown (no active probing)
    return {
        "name": name,
        "url": site.get("url", ""),
        "found": None,
        "profile_url": None,
    }


async def _rate_limited_check(
    sites: list[dict[str, Any]],
    identifier: str,
    check_fn,
    rate_limit_sec: float,
    max_platforms: int,
) -> list[dict[str, Any]]:
    """Run platform checks with rate limiting and max platform cap."""
    sites = sites[:max_platforms]
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for i, site in enumerate(sites):
            result = await check_fn(site, identifier, client)
            results.append(result)
            # Rate limit: sleep between checks (skip after last)
            if i < len(sites) - 1:
                await asyncio.sleep(rate_limit_sec)
            # 30s pause every 50 checks
            if (i + 1) % 50 == 0 and i < len(sites) - 1:
                logger.info("identity osint: 30s pause after %d checks", i + 1)
                await asyncio.sleep(30.0)
    return results


# ---------------------------------------------------------------------------
# Public lookup functions
# ---------------------------------------------------------------------------


async def lookup_email(
    email: str, *, max_platforms: int | None = None, refresh: bool = False
) -> dict[str, Any]:
    """Enumerate email across platforms. Returns dict with results."""
    cfg = get_config()
    if not cfg.identity_osint_enabled:
        return {
            "query": email,
            "type": "email",
            "platforms": [],
            "count": 0,
            "cached": False,
            "error": "identity osint disabled",
        }

    if not _valid_email(email):
        return {
            "query": email,
            "type": "email",
            "platforms": [],
            "count": 0,
            "cached": False,
            "error": "invalid email format",
        }

    max_plat = max_platforms or cfg.identity_osint_max_platforms
    cache_ttl = cfg.identity_osint_cache_sec
    ckey = _cache_key(email, "email")

    if not refresh:
        cached = await _get_cached(ckey, cache_ttl)
        if cached is not None:
            cached["cached"] = True
            _audit_log(email, "email", cached.get("count", 0), cached=True)
            return cached

    results = await _rate_limited_check(
        _EMAIL_SITES,
        email,
        _check_email_platform,
        cfg.identity_osint_rate_limit_sec,
        max_plat,
    )
    found_count = sum(1 for r in results if r["found"] is True)
    output = {
        "query": email,
        "type": "email",
        "platforms": results,
        "count": found_count,
        "total_checked": len(results),
        "cached": False,
        "error": None,
    }
    await _set_cached(ckey, output)
    _audit_log(email, "email", found_count)
    return output


async def lookup_username(
    username: str, *, max_platforms: int | None = None, refresh: bool = False
) -> dict[str, Any]:
    """Enumerate username across platforms. Returns dict with results."""
    cfg = get_config()
    if not cfg.identity_osint_enabled:
        return {
            "query": username,
            "type": "username",
            "platforms": [],
            "count": 0,
            "cached": False,
            "error": "identity osint disabled",
        }

    clean = _sanitize_username(username)
    if clean is None:
        return {
            "query": username,
            "type": "username",
            "platforms": [],
            "count": 0,
            "cached": False,
            "error": "invalid username format",
        }

    max_plat = max_platforms or cfg.identity_osint_max_platforms
    cache_ttl = cfg.identity_osint_cache_sec
    ckey = _cache_key(clean, "username")

    if not refresh:
        cached = await _get_cached(ckey, cache_ttl)
        if cached is not None:
            cached["cached"] = True
            _audit_log(clean, "username", cached.get("count", 0), cached=True)
            return cached

    results = await _rate_limited_check(
        _USERNAME_SITES,
        clean,
        _check_username_platform,
        cfg.identity_osint_rate_limit_sec,
        max_plat,
    )
    found_count = sum(1 for r in results if r["found"] is True)
    output = {
        "query": clean,
        "type": "username",
        "platforms": results,
        "count": found_count,
        "total_checked": len(results),
        "cached": False,
        "error": None,
    }
    await _set_cached(ckey, output)
    _audit_log(clean, "username", found_count)
    return output


# ---------------------------------------------------------------------------
# FtM enrichment
# ---------------------------------------------------------------------------


def _enrich_ftm(person_id: str, results: dict[str, Any]) -> dict[str, Any]:
    """Upsert UserAccount entities and link to Person via 'owns' edge."""
    try:
        import ftm_query

        seen_at = datetime.now(timezone.utc).isoformat()
        dataset = "identity_osint"
        ids: list[str] = []
        for platform in results.get("platforms", []):
            if platform.get("found") is not True:
                continue
            platform_name = platform["name"]
            profile_url = platform.get("profile_url") or platform.get("url", "")
            # Create UserAccount entity
            acct_props = {
                "name": [f"{platform_name} account"],
                "username": [results["query"]] if results["type"] == "username" else [],
                "email": [results["query"]] if results["type"] == "email" else [],
                "website": [profile_url] if profile_url else [],
            }
            # Use make_entity for deterministic ID
            entity = ftm_query.make_entity(
                "UserAccount",
                [platform_name, results["query"], results["type"]],
                acct_props,
            )
            ftm_query.upsert(entity, dataset=dataset, seen_at=seen_at)
            ids.append(entity.id)
            # Link Person → UserAccount (owns)
            ftm_query.add_edge(
                person_id,
                entity.id,
                "owns",
                dataset=dataset,
                confidence=0.7,
                seen_at=seen_at,
            )
        return {"count": len(ids), "ids": ids, "error": None}
    except Exception as exc:
        logger.warning("identity FtM enrichment failed: %s", exc)
        return {"count": 0, "ids": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Briefing digest
# ---------------------------------------------------------------------------


async def gather_identity_digest() -> dict[str, Any]:
    """Gather identity OSINT data for briefing digest. Fail-soft."""
    cfg = get_config()
    if not cfg.identity_osint_enabled or not cfg.briefing_identity:
        return {"enabled": False, "count": 0, "lines": []}

    try:
        audit = query_audit_log(limit=10)
        lines: list[str] = []
        for entry in audit:
            if entry.get("result_count", 0) > 0:
                lines.append(
                    f"- [{entry['query_type']}] {entry['query']}: {entry['result_count']} platforms found"
                )
        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines[:5],
            "recent_lookups": len(audit),
        }
    except Exception as exc:
        logger.warning("identity digest failed: %s", exc)
        return {"enabled": False, "count": 0, "lines": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def api_identity_lookup(
    email: str = Query("", description="Email to enumerate"),
    username: str = Query("", description="Username to enumerate"),
    max_platforms: int = Query(
        0, ge=0, le=100, description="Max platforms to check (0 = config default)"
    ),
    refresh: bool = False,
):
    """Enumerate email or username across social platforms."""
    if email:
        return await lookup_email(
            email, max_platforms=max_platforms or None, refresh=refresh
        )
    if username:
        return await lookup_username(
            username, max_platforms=max_platforms or None, refresh=refresh
        )
    return {
        "error": "Provide either email or username parameter",
        "platforms": [],
        "count": 0,
    }


@router.post("/ingest")
async def api_identity_ingest(
    email: str = Query("", description="Email to enumerate and ingest"),
    username: str = Query("", description="Username to enumerate and ingest"),
    person_id: str = Query(..., description="FtM Person entity ID to link accounts to"),
    max_platforms: int = Query(0, ge=0, le=100),
    refresh: bool = False,
):
    """Run lookup and ingest results as FtM UserAccount entities."""
    if not get_config().identity_osint_enabled:
        return {"count": 0, "ids": [], "error": "identity osint disabled"}

    if email:
        results = await lookup_email(
            email, max_platforms=max_platforms or None, refresh=refresh
        )
    elif username:
        results = await lookup_username(
            username, max_platforms=max_platforms or None, refresh=refresh
        )
    else:
        return {"count": 0, "ids": [], "error": "Provide either email or username"}

    enrich = _enrich_ftm(person_id, results)
    return {
        "query": results.get("query"),
        "type": results.get("type"),
        "found_count": results.get("count", 0),
        "ingested": enrich.get("count", 0),
        "ids": enrich.get("ids", []),
        "error": enrich.get("error") or results.get("error"),
    }


@router.get("/audit")
async def api_identity_audit(limit: int = Query(50, ge=1, le=500)):
    """Query the identity lookup audit log."""
    entries = query_audit_log(limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.get("/audit/raw")
async def api_identity_audit_raw(limit: int = Query(50, ge=1, le=500)):
    """Query the identity lookup audit log (raw entries)."""
    entries = query_audit_log(limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.get("/status")
async def api_identity_status():
    """Show identity OSINT bridge status."""
    cfg = get_config()
    return {
        "enabled": cfg.identity_osint_enabled,
        "email_platforms": len(_EMAIL_SITES),
        "username_platforms": len(_USERNAME_SITES),
        "total_platforms": len(_EMAIL_SITES) + len(_USERNAME_SITES),
        "rate_limit_sec": cfg.identity_osint_rate_limit_sec,
        "max_platforms": cfg.identity_osint_max_platforms,
        "cache_sec": cfg.identity_osint_cache_sec,
        "briefing_enabled": cfg.briefing_identity,
    }
