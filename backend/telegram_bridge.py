"""Telegram SOCMINT bridge (K3) for WorldBase.

Public-channel scanner using Telethon. Only allow-listed public channels are
read; no private groups or DMs. Posts are kept as lightweight cached records,
pruned after 90 days by default, and can be ingested into the FtM graph as
`Event` / `Mention` entities.

Environment variables:
    WORLDBASE_TELEGRAM=1              enable router
    TELEGRAM_API_ID=1234567           Telegram API id (required to scan)
    TELEGRAM_API_HASH=...             Telegram API hash (required)
    TELEGRAM_SESSION_STRING=...       optional string session for headless use
    TELEGRAM_PHONE=...                fallback phone for interactive login
    WORLDBASE_TELEGRAM_CHANNELS=...   comma-separated public channel usernames
    WORLDBASE_TELEGRAM_POST_LIMIT=50   messages per channel per scan
    WORLDBASE_TELEGRAM_CACHE_SEC=600   in-process cache for /posts
    WORLDBASE_TELEGRAM_RETENTION_DAYS=90  prune old posts
    WORLDBASE_BRIEFING_TELEGRAM=1     include in 24h digest
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth.security import verify_api_key
from config import get_config
from middleware.rate_limit import rate_limit_general

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram")

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


class TelegramConfig:
    """Runtime Telegram configuration (not cached; reads env on each access)."""

    @property
    def enabled(self) -> bool:
        return get_config().telegram_enabled

    @property
    def api_id(self) -> int | None:
        raw = os.getenv("TELEGRAM_API_ID", "").strip()
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    @property
    def api_hash(self) -> str:
        return os.getenv("TELEGRAM_API_HASH", "").strip()

    @property
    def session_string(self) -> str:
        return os.getenv("TELEGRAM_SESSION_STRING", "").strip()

    @property
    def phone(self) -> str:
        return os.getenv("TELEGRAM_PHONE", "").strip()

    @property
    def channels(self) -> list[str]:
        return _split_channels(os.getenv("WORLDBASE_TELEGRAM_CHANNELS", ""))

    @property
    def post_limit(self) -> int:
        return int(os.getenv("WORLDBASE_TELEGRAM_POST_LIMIT", "50"))

    @property
    def cache_sec(self) -> int:
        return int(os.getenv("WORLDBASE_TELEGRAM_CACHE_SEC", "600"))

    @property
    def retention_days(self) -> int:
        return int(os.getenv("WORLDBASE_TELEGRAM_RETENTION_DAYS", "90"))

    @property
    def session_path(self) -> str:
        base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, "data", "telegram_session.session")

    def configured(self) -> bool:
        return self.enabled and self.api_id is not None and bool(self.api_hash)


_tg_config = TelegramConfig()


def _split_channels(raw: str) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        c = part.strip().lstrip("@").strip()
        if c:
            out.append(c)
    return out


# ---------------------------------------------------------------------------
# In-memory post cache (replaced by FtM store after ingest)
# ---------------------------------------------------------------------------

_POSTS: list[dict[str, Any]] = []
_LAST_SCAN: datetime | None = None
_SCAN_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Telethon client wrapper
# ---------------------------------------------------------------------------


def _make_client() -> Any:
    """Build a Telethon client. Fail-soft when credentials are missing."""
    if not _tg_config.configured():
        return None
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession, SQLiteSession

        if _tg_config.session_string:
            session = StringSession(_tg_config.session_string)
        else:
            os.makedirs(os.path.dirname(_tg_config.session_path), exist_ok=True)
            session = SQLiteSession(_tg_config.session_path)
        return TelegramClient(
            session,
            _tg_config.api_id,
            _tg_config.api_hash,
            connection_retries=2,
            request_retries=2,
        )
    except Exception as exc:
        logger.warning("telegram client build failed: %s", exc)
        return None


async def _with_client(func, *args, **kwargs) -> Any:
    """Connect, run an async function, disconnect."""
    client = _make_client()
    if client is None:
        return None
    try:
        await client.connect()
        if not await client.is_user_authorized():
            # Headless server requires a pre-authorized session string.
            logger.warning(
                "telegram session not authorized; set TELEGRAM_SESSION_STRING"
            )
            return None
        return await func(client, *args, **kwargs)
    except Exception as exc:
        logger.warning("telegram operation failed: %s", exc)
        return None
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


async def _scan_channel(client, channel: str, limit: int) -> list[dict[str, Any]]:
    """Fetch recent messages from a single public channel."""
    posts: list[dict[str, Any]] = []
    try:
        entity = await client.get_entity(channel)
    except Exception as exc:
        logger.warning("telegram cannot resolve channel %s: %s", channel, exc)
        return posts

    try:
        async for message in client.iter_messages(entity, limit=limit):
            if not message or not message.text:
                continue
            post = _parse_message(message, entity, channel)
            if post:
                posts.append(post)
    except Exception as exc:
        logger.warning("telegram iter_messages %s failed: %s", channel, exc)

    return posts


def _parse_message(message, entity, channel: str) -> dict[str, Any] | None:
    """Convert a Telethon Message into a lightweight post dict."""
    text = (message.text or "").strip()
    if not text or len(text) < 4:
        return None
    date = message.date
    if date is None or not date.tzinfo:
        date = date.replace(tzinfo=timezone.utc) if date else datetime.now(timezone.utc)
    else:
        date = date.astimezone(timezone.utc)

    msg_id = int(message.id or 0)
    username = getattr(entity, "username", None) or channel
    channel_title = getattr(entity, "title", None) or username
    channel_url = f"https://t.me/{username}" if username else ""
    post_url = f"{channel_url}/{msg_id}" if channel_url else ""

    media_type = None
    if message.media:
        media_type = type(message.media).__name__

    # Extract plain URLs and Telegram-internal links.
    urls = _extract_urls(text)
    if post_url and post_url not in urls:
        urls.append(post_url)

    return {
        "id": _post_id(channel, msg_id),
        "channel": channel,
        "channel_title": channel_title,
        "channel_url": channel_url,
        "message_id": msg_id,
        "url": post_url,
        "text": text,
        "date": date.isoformat(),
        "views": int(message.views or 0),
        "forwards": int(message.forwards or 0),
        "replies": int((message.replies and message.replies.replies) or 0),
        "media_type": media_type,
        "urls": urls,
        "hashtags": _extract_hashtags(text),
        "mentions": _extract_mentions(text),
        "lang": "",
        "countries": [],
        "cities": [],
        "keywords": [],
        "score": 0.0,
        "ingested": False,
    }


def _post_id(channel: str, message_id: int) -> str:
    return hashlib.sha256(f"{channel}:{message_id}".encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


_URL_RE = re.compile(
    r"https?://[^\s\]\)\>\"\']+",
    re.IGNORECASE,
)
_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)
_MENTION_RE = re.compile(r"@\w+", re.UNICODE)


def _extract_urls(text: str) -> list[str]:
    urls = _URL_RE.findall(text)
    return list(dict.fromkeys(urls))[:10]


def _extract_hashtags(text: str) -> list[str]:
    tags = [t.lower() for t in _HASHTAG_RE.findall(text)]
    return list(dict.fromkeys(tags))[:20]


def _extract_mentions(text: str) -> list[str]:
    return list(dict.fromkeys(_MENTION_RE.findall(text)))[:20]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def refresh_telegram_posts() -> dict[str, Any]:
    """Force scan all allow-listed channels."""
    async with _SCAN_LOCK:
        if not _tg_config.configured():
            return {"enabled": False, "count": 0, "channels": [], "error": None}

        channels = _tg_config.channels
        if not channels:
            return {
                "enabled": True,
                "count": 0,
                "channels": [],
                "error": "no channels configured",
            }

        all_posts: list[dict[str, Any]] = []
        channel_status: list[dict[str, Any]] = []
        limit = _tg_config.post_limit

        async def _scan_one(channel: str) -> tuple[str, list[dict[str, Any]]]:
            posts = await _with_client(_scan_channel, channel, limit)
            return channel, posts or []

        results = await asyncio.gather(
            *[_scan_one(c) for c in channels], return_exceptions=True
        )
        for item in results:
            if isinstance(item, Exception):
                logger.warning("telegram scan channel exception: %s", item)
                continue
            channel, posts = item
            for p in posts:
                p["ingested"] = False
            all_posts.extend(posts)
            channel_status.append(
                {
                    "channel": channel,
                    "ok": bool(posts),
                    "count": len(posts),
                }
            )

        _apply_geo_enrichment(all_posts)
        _apply_sea_scoring(all_posts)
        _prune_old_posts()

        # Merge with existing posts by id, preferring fresh scan.
        existing = {p["id"]: p for p in _POSTS}
        for p in all_posts:
            existing[p["id"]] = p
        _POSTS[:] = sorted(
            existing.values(), key=lambda x: x.get("date", ""), reverse=True
        )

        global _LAST_SCAN
        _LAST_SCAN = datetime.now(timezone.utc)

        return {
            "enabled": True,
            "count": len(all_posts),
            "channels": channel_status,
            "error": None,
        }


async def get_cached_posts(
    *, channel: str | None = None, limit: int = 100, min_score: float | None = None
) -> dict[str, Any]:
    """Return cached posts with optional filters."""
    if not _tg_config.configured():
        return {"enabled": False, "count": 0, "posts": [], "error": None}

    posts = list(_POSTS)
    if channel:
        posts = [p for p in posts if p.get("channel") == channel]
    if min_score is not None:
        posts = [p for p in posts if float(p.get("score") or 0) >= min_score]
    posts = sorted(posts, key=lambda x: x.get("date", ""), reverse=True)[:limit]

    return {
        "enabled": True,
        "count": len(posts),
        "total_cached": len(_POSTS),
        "last_scan": _LAST_SCAN.isoformat() if _LAST_SCAN else None,
        "posts": posts,
        "error": None,
    }


async def get_channel_status() -> dict[str, Any]:
    """List allow-listed channels and their last scan status."""
    if not _tg_config.configured():
        return {"enabled": False, "channels": [], "error": None}
    channels = _tg_config.channels
    seen = {p["channel"]: p for p in _POSTS}
    out = []
    for c in channels:
        out.append(
            {
                "channel": c,
                "allowlisted": True,
                "cached_posts": sum(1 for p in _POSTS if p.get("channel") == c),
                "last_post": seen.get(c, {}).get("date"),
            }
        )
    return {"enabled": True, "channels": out, "error": None}


# ---------------------------------------------------------------------------
# Geo / SEA enrichment
# ---------------------------------------------------------------------------


_SEA_COUNTRIES = {
    "thailand",
    "thai",
    "th",
    "myanmar",
    "burma",
    "mm",
    "cambodia",
    "khmer",
    "kh",
    "vietnam",
    "vietnamese",
    "vn",
    "laos",
    "lao",
    "la",
    "malaysia",
    "my",
    "singapore",
    "sg",
    "indonesia",
    "id",
    "philippines",
    "ph",
    "brunei",
    "bn",
    "east timor",
    "timor-leste",
    "tl",
}

_SEA_CITIES = [
    "bangkok",
    "yangon",
    "mandalay",
    "phnom penh",
    "siem reap",
    "hanoi",
    "ho chi minh",
    "vientiane",
    "luang prabang",
    "kuala lumpur",
    "jakarta",
    "manila",
    "singapore",
    "bali",
    "chiang mai",
    "pattaya",
    "phuket",
    "naypyidaw",
    "bago",
    "mawlamyine",
    "sittwe",
    "myeik",
    "dawei",
    "mae sot",
    "mae sai",
    "tachileik",
    "myawaddy",
    "kawthoung",
]

_THREAT_KEYWORDS = [
    "protest",
    "demonstration",
    "raid",
    "arrest",
    "crackdown",
    "curfew",
    "embassy",
    "evacuation",
    "safety",
    "security",
    "conflict",
    "fighting",
    "airstrike",
    "drone",
    "bomb",
    "explosion",
    "casualties",
    "killed",
    "scam",
    "fraud",
    "cyber",
    "syndicate",
    "trafficking",
    "border",
    "earthquake",
    "flood",
    "typhoon",
    "haze",
    "pm2.5",
    "fire",
    "tsunami",
    "military",
    "coup",
    "junta",
    "sanction",
    "visa",
    "travel warning",
]


def _apply_geo_enrichment(posts: list[dict[str, Any]]) -> None:
    """Lightweight rule-based country/city/keyword extraction."""
    lower_cities = [c.lower() for c in _SEA_CITIES]
    # Check longer names first so "myanmar" wins over "my", "thailand" over "th".
    country_terms = sorted(_SEA_COUNTRIES, key=lambda x: -len(x))
    for p in posts:
        text = f"{p.get('text', '')} {' '.join(p.get('hashtags', []))}".lower()
        countries = list(p.get("countries") or [])
        for c in country_terms:
            if c in text and c not in countries:
                countries.append(c)
        p["countries"] = list(dict.fromkeys(countries))[:5]
        cities = list(p.get("cities") or [])
        for c in lower_cities:
            if c in text and c not in cities:
                cities.append(c)
        p["cities"] = list(dict.fromkeys(cities))[:5]
        keywords = list(p.get("keywords") or [])
        for kw in _THREAT_KEYWORDS:
            if kw in text and kw not in keywords:
                keywords.append(kw)
        p["keywords"] = list(dict.fromkeys(keywords))[:10]


def _apply_sea_scoring(posts: list[dict[str, Any]]) -> None:
    """Score posts by SEA relevance and urgency."""
    for p in posts:
        score = 0.0
        if p.get("countries"):
            score += 0.35
        if p.get("cities"):
            score += 0.25
        if p.get("keywords"):
            score += min(0.25, len(p["keywords"]) * 0.05)
        if int(p.get("views") or 0) > 10000:
            score += 0.1
        if int(p.get("forwards") or 0) > 100:
            score += 0.1
        if p.get("media_type"):
            score += 0.05
        p["score"] = round(min(1.0, score), 3)


def _prune_old_posts() -> None:
    """Drop cached posts older than retention window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_tg_config.retention_days)
    global _POSTS
    _POSTS = [p for p in _POSTS if _parse_iso(p.get("date")) > cutoff]


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# FtM ingest + entity matching (3.5)
# ---------------------------------------------------------------------------


def _list_person_org_entities(limit: int = 2000) -> list[dict[str, Any]]:
    """Load Person and Organization entities for matching."""
    try:
        import ftm_query

        rows = ftm_query.list_entities(limit=limit)
        return [r for r in rows if r.get("schema") in ("Person", "Organization")]
    except Exception:
        return []


def match_post_to_entities(
    post: dict[str, Any], entities: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Match a Telegram post text against FtM Person/Organization names.

    Returns list of {entity_id, schema, name, matched_alias}.
    """
    text = (post.get("text", "") + " " + " ".join(post.get("hashtags", []))).lower()
    if not text.strip():
        return []

    matches: list[dict[str, Any]] = []
    for ent in entities:
        name = (ent.get("name") or ent.get("caption") or "").strip()
        if not name or len(name) < 3:
            continue
        aliases = [name]
        raw_props = ent.get("properties") or {}
        if isinstance(raw_props, dict):
            for key in ("alias", "weakAlias", "previousName"):
                vals = raw_props.get(key)
                if isinstance(vals, list):
                    aliases.extend(
                        v.strip() for v in vals if isinstance(v, str) and v.strip()
                    )
                elif isinstance(vals, str) and vals.strip():
                    aliases.append(vals.strip())

        for alias in aliases:
            if alias.lower() in text:
                matches.append(
                    {
                        "entity_id": ent.get("id", ""),
                        "schema": ent.get("schema", ""),
                        "name": name,
                        "matched_alias": alias,
                    }
                )
                break
    return matches


def ingest_posts(
    posts: list[dict[str, Any]] | None = None, dataset: str = "telegram"
) -> dict[str, Any]:
    """Ingest selected posts as FtM Event / Mention entities."""
    if not _tg_config.configured():
        return {"enabled": False, "count": 0, "ids": [], "error": None}
    posts = posts or list(_POSTS)
    if not posts:
        return {"enabled": True, "count": 0, "ids": [], "error": None}

    try:
        import ftm_query
    except Exception as exc:
        return {
            "enabled": True,
            "count": 0,
            "ids": [],
            "error": f"ftm import failed: {exc}",
        }

    seen_at = datetime.now(timezone.utc).isoformat()
    ids: list[str] = []
    linked_entities: list[dict[str, Any]] = []

    # Load Person/Organization entities for matching
    entities = _list_person_org_entities()

    for p in posts:
        try:
            event = _post_to_event(p)
            ftm_query.upsert(event, dataset=dataset, seen_at=seen_at)
            ids.append(event.id)
            mention = _post_to_mention(p, event.id)
            ftm_query.upsert(mention, dataset=dataset, seen_at=seen_at)
            ids.append(mention.id)

            # 3.5: Match post to Person/Organization entities and create edges
            matches = match_post_to_entities(p, entities)
            for m in matches:
                try:
                    ftm_query.add_edge(
                        source_id=mention.id,
                        target_id=m["entity_id"],
                        kind="mentioned",
                        dataset=dataset,
                        confidence=0.7,
                        properties={"matched_alias": m["matched_alias"]},
                        seen_at=seen_at,
                    )
                    linked_entities.append(
                        {
                            "post_id": p.get("id"),
                            "mention_id": mention.id,
                            "entity_id": m["entity_id"],
                            "entity_name": m["name"],
                            "entity_schema": m["schema"],
                            "matched_alias": m["matched_alias"],
                        }
                    )
                except Exception as exc:
                    logger.debug("telegram edge failed: %s", exc)

            p["ingested"] = True
        except Exception as exc:
            logger.warning("telegram ingest post %s failed: %s", p.get("id"), exc)

    return {
        "enabled": True,
        "count": len(ids),
        "ids": ids,
        "linked_entities": linked_entities,
        "error": None,
    }


def _post_to_event(p: dict[str, Any]) -> Any:
    """Map a post to an FtM Event."""
    import ftm_query

    name = _first_sentence(p.get("text", ""))
    if not name:
        name = f"Telegram post {p.get('channel', '')}"
    props: dict[str, list[str]] = {
        "name": [name[:160]],
        "description": [p.get("text", "")[:2000]],
        "publishedAt": [p.get("date", "")],
        "sourceUrl": [p.get("url", "")],
        "topics": list(p.get("hashtags", [])) or [],
    }
    if p.get("countries"):
        props["country"] = [
            c[:3].upper() if len(c) <= 3 else c for c in p["countries"]
        ][:1]
    if p.get("keywords"):
        props["keywords"] = list(p["keywords"])[:10]
    proxy = ftm_query.make_entity("Event", [p.get("id")], props)
    return proxy


def _post_to_mention(p: dict[str, Any], event_id: str) -> Any:
    """Map a post to an FtM Mention that links it to the channel source."""
    import ftm_query

    props: dict[str, list[str]] = {
        "name": [f"Telegram mention in {p.get('channel', '')}"],
        "source": [p.get("channel_title", "") or p.get("channel", "")],
        "url": [p.get("url", "")],
        "snippet": [p.get("text", "")[:500]],
        "query": [p.get("channel", "")],
        "publishedAt": [p.get("date", "")],
    }
    proxy = ftm_query.make_entity("Mention", [p.get("id"), "telegram"], props)
    return proxy


def _first_sentence(text: str, max_len: int = 140) -> str:
    text = text.strip().replace("\n", " ")
    if not text:
        return ""
    # Split on sentence-ending punctuation, keep the first chunk.
    for sep in ".!?":
        if sep in text:
            idx = text.find(sep)
            if idx > 10:
                sent = text[: idx + 1].strip()
                return sent[:max_len]
    return text[:max_len]


# ---------------------------------------------------------------------------
# Pydantic models for HTTP endpoints
# ---------------------------------------------------------------------------


class RefreshResponse(BaseModel):
    enabled: bool
    count: int
    channels: list[dict[str, Any]]
    error: str | None = None


class IngestRequest(BaseModel):
    post_ids: list[str] | None = None
    all_cached: bool = False


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@router.get("/channels")
@rate_limit_general()
async def api_telegram_channels(
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    """List allow-listed Telegram channels and scan status."""
    return await get_channel_status()


@router.get("/posts")
@rate_limit_general()
async def api_telegram_posts(
    request: Request,
    channel: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    min_score: float | None = Query(None, ge=0.0, le=1.0),
    api_key: str = Depends(verify_api_key),
):
    """Return cached Telegram posts from the last scan."""
    return await get_cached_posts(channel=channel, limit=limit, min_score=min_score)


@router.post("/refresh")
@rate_limit_general()
async def api_telegram_refresh(
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    """Force-scan all allow-listed public Telegram channels."""
    result = await refresh_telegram_posts()
    if not result["enabled"]:
        raise HTTPException(
            status_code=503, detail="telegram bridge disabled or not configured"
        )
    return result


@router.post("/ingest")
@rate_limit_general()
async def api_telegram_ingest(
    request: Request,
    req: IngestRequest,
    api_key: str = Depends(verify_api_key),
):
    """Ingest posts into the FtM graph as Event / Mention entities."""
    if not _tg_config.configured():
        raise HTTPException(
            status_code=503, detail="telegram bridge disabled or not configured"
        )

    posts = list(_POSTS)
    if req.post_ids:
        posts = [p for p in posts if p.get("id") in req.post_ids]
    elif not req.all_cached:
        posts = []
    result = ingest_posts(posts, dataset="telegram")
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/mentions")
@rate_limit_general()
async def api_telegram_mentions(
    request: Request,
    entity_id: str | None = Query(None, description="Filter by linked FtM entity ID"),
    channel: str | None = Query(None, description="Filter by Telegram channel"),
    limit: int = Query(50, ge=1, le=500),
    api_key: str = Depends(verify_api_key),
):
    """Query Telegram Mention entities and their linked Person/Organization entities.

    3.5 Graph query integration: traverses `mentioned` edges from Mention → Person/Org.
    """
    try:
        import ftm_query
    except Exception:
        return {"enabled": False, "mentions": [], "error": "ftm unavailable"}

    with ftm_query._LOCK if hasattr(ftm_query, "_LOCK") else _noop_ctx():
        con = ftm_query._conn()
        # Find Mention entities from telegram dataset
        schema_clause = "schema = 'Mention'"
        dataset_clause = ""
        if channel:
            dataset_clause = " AND EXISTS (SELECT 1 FROM json_each(datasets) je WHERE TRIM(je.value::VARCHAR, '\"') = 'telegram')"
        else:
            dataset_clause = " AND EXISTS (SELECT 1 FROM json_each(datasets) je WHERE TRIM(je.value::VARCHAR, '\"') = 'telegram')"

        rows = con.execute(
            f"""
            SELECT id, caption, properties, datasets, first_seen, last_seen
            FROM entities
            WHERE {schema_clause}{dataset_clause}
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()

    mentions: list[dict[str, Any]] = []
    for r in rows:
        mid = r[0]
        # Get edges for this mention
        edge_rows = con.execute(
            "SELECT target_id, kind, properties, confidence FROM edges WHERE source_id = ? AND kind = 'mentioned'",
            [mid],
        ).fetchall()

        linked: list[dict[str, Any]] = []
        for e in edge_rows:
            ent = ftm_query.get_entity(e[0])
            if ent:
                linked.append(
                    {
                        "entity_id": e[0],
                        "schema": ent.get("schema", ""),
                        "name": ent.get("name") or ent.get("caption", ""),
                        "confidence": e[3],
                        "matched_alias": (
                            json.loads(e[2] or "{}").get("matched_alias")
                            if e[2]
                            else None
                        ),
                    }
                )

        # Filter by entity_id if provided
        if entity_id and not any(lnk["entity_id"] == entity_id for lnk in linked):
            continue

        props = json.loads(r[2] or "{}")
        mentions.append(
            {
                "mention_id": mid,
                "name": r[1] or "",
                "source": (props.get("source") or [""])[0]
                if isinstance(props.get("source"), list)
                else props.get("source", ""),
                "url": (props.get("url") or [""])[0]
                if isinstance(props.get("url"), list)
                else props.get("url", ""),
                "snippet": (props.get("snippet") or [""])[0]
                if isinstance(props.get("snippet"), list)
                else props.get("snippet", ""),
                "published_at": (props.get("publishedAt") or [""])[0]
                if isinstance(props.get("publishedAt"), list)
                else props.get("publishedAt", ""),
                "first_seen": r[4],
                "last_seen": r[5],
                "linked_entities": linked,
            }
        )

    return {
        "enabled": True,
        "count": len(mentions),
        "mentions": mentions,
        "error": None,
    }


class _noop_ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


# ---------------------------------------------------------------------------
# Helpers used by telegram_briefing.py
# ---------------------------------------------------------------------------


def get_cached_posts_sync() -> list[dict[str, Any]]:
    """Synchronous read of the in-memory post cache (for briefing bridge)."""
    return list(_POSTS)


async def gather_telegram_digest() -> dict[str, Any]:
    """Collect recent posts for the briefing pipeline.

    Fail-soft: returns empty structure when disabled or not configured.
    """
    if not _tg_config.configured():
        return {"enabled": False, "count": 0, "lines": [], "posts": []}
    posts = await get_cached_posts(limit=200)
    recent = [p for p in posts.get("posts", []) if _is_recent(p, hours=24)]
    return {
        "enabled": True,
        "count": len(recent),
        "lines": [_format_post_line(p) for p in recent[:8]],
        "posts": recent,
    }


def _is_recent(p: dict[str, Any], hours: int = 24) -> bool:
    try:
        dt = datetime.fromisoformat(p.get("date", ""))
        return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)
    except Exception:
        return False


def _format_post_line(p: dict[str, Any]) -> str:
    ch = p.get("channel", "")
    txt = _first_sentence(p.get("text", ""), 120)
    flags = []
    if p.get("countries"):
        flags.append(",".join(p["countries"][:2]))
    if p.get("score"):
        flags.append(f"score={p['score']}")
    tail = f" ({', '.join(flags)})" if flags else ""
    return f"Telegram {ch}: {txt}{tail}"
