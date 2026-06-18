"""Public webcam aggregation.

Sources:
- Windy.com Webcams API v3 (requires WINDY_WEBCAM_API_KEY)
- Curated public YouTube / embed live streams (no auth)

All cameras are publicly accessible — no unauthorized access.
"""

import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/webcams", tags=["webcams"])

WINDY_URL = "https://api.windy.com/webcams/api/v3/webcams"


def _windy_api_key() -> str:
    return os.getenv("WINDY_WEBCAM_API_KEY", "").strip()

OPERATOR_LAT = float(os.getenv("WORLDBASE_OPERATOR_LAT", "9.55"))
OPERATOR_LON = float(os.getenv("WORLDBASE_OPERATOR_LON", "100.05"))

_CACHE: tuple[float, dict] | None = None
TTL = 120  # 2 min — Windy image tokens expire in 10 min (free tier)

# Public 24/7 YouTube live streams — IDs verified via i.ytimg.com (404 = removed)
NASA_YT_CHANNEL = "UCM0sc1nrJp_t-5tQGk4gRsw"


def _youtube_cam(
    cam_id: str,
    name: str,
    country: str,
    lat: float,
    lon: float,
    category: str,
    *,
    video_id: str | None = None,
    channel_id: str | None = None,
) -> dict:
    """Build a static YouTube webcam entry. Use channel_id when video ID rotates (e.g. NASA)."""
    if channel_id:
        embed = f"https://www.youtube.com/embed/live_stream?channel={channel_id}&autoplay=1&mute=1"
        return {
            "id": cam_id,
            "name": name,
            "country": country,
            "lat": lat,
            "lon": lon,
            "category": category,
            "url": "",
            "embed": embed,
            "source": "youtube",
            "refresh": 0,
        }
    vid = video_id or ""
    return {
        "id": cam_id,
        "name": name,
        "country": country,
        "lat": lat,
        "lon": lon,
        "category": category,
        "url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else "",
        "embed": f"https://www.youtube.com/embed/{vid}?autoplay=1&mute=1" if vid else "",
        "source": "youtube",
        "refresh": 0,
    }


STATIC_WEBCAMS: list[dict] = [
    _youtube_cam(
        "nasa-iss",
        "NASA — Live Space/Earth",
        "SPACE",
        0,
        0,
        "space",
        channel_id=NASA_YT_CHANNEL,
    ),
    _youtube_cam(
        "us-nyc-times-square",
        "NYC — Times Square 4K",
        "US",
        40.758,
        -73.985,
        "city",
        video_id="QTTTY_ra2Tg",
    ),
    _youtube_cam(
        "uk-london-abbey-road",
        "London — Abbey Road Live",
        "GB",
        51.532,
        -0.177,
        "city",
        video_id="M7FIvfx5J10",
    ),
    _youtube_cam(
        "au-sydney-harbour",
        "Sydney — Harbour Live",
        "AU",
        -33.852,
        151.211,
        "city",
        video_id="ggy1-vP7CIw",
    ),
    _youtube_cam(
        "ae-dubai-palm",
        "Dubai — Fairmont The Palm",
        "AE",
        25.112,
        55.139,
        "city",
        video_id="7dE4IjDQJmE",
    ),
    _youtube_cam(
        "na-namib-desert",
        "Namibia — Namib Desert Live",
        "NA",
        -24.750,
        15.292,
        "nature",
        video_id="ydYDqZQpim8",
    ),
]

_WINDY_CATEGORY_MAP = {
    "traffic": "traffic",
    "airport": "traffic",
    "harbor": "traffic",
    "city": "city",
    "building": "city",
    "beach": "nature",
    "lake": "nature",
    "mountain": "nature",
    "landscape": "nature",
    "meteo": "nature",
    "water": "nature",
    "forest": "nature",
    "volcano": "nature",
    "space": "space",
}


def _windy_headers() -> dict[str, str]:
    return {"x-windy-api-key": _windy_api_key()}


def _map_windy_category(categories: list) -> str:
    for cat in categories:
        cid = cat.get("id") if isinstance(cat, dict) else str(cat)
        if cid in _WINDY_CATEGORY_MAP:
            return _WINDY_CATEGORY_MAP[cid]
    return "nature"


def _pick_player_embed(player: dict) -> str:
    if not player:
        return ""
    for key in ("live", "day", "month", "year", "lifetime"):
        url = player.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""


def _pick_thumb(images: dict) -> str:
    current = images.get("current") or {}
    for key in ("preview", "icon", "thumbnail", "small"):
        url = current.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    return ""


def _normalize_windy(w: dict) -> dict:
    loc = w.get("location") or {}
    player = w.get("player") or {}
    urls = w.get("urls") or {}
    embed = _pick_player_embed(player)
    windy_id = w.get("webcamId")
    category = _map_windy_category(w.get("categories") or [])
    return {
        "id": f"windy-{windy_id}",
        "windy_id": windy_id,
        "name": w.get("title", "Unknown"),
        "country": loc.get("country_code") or loc.get("countryCode") or "??",
        "lat": loc.get("latitude"),
        "lon": loc.get("longitude"),
        "category": category,
        "url": _pick_thumb(w.get("images") or {}),
        "embed": embed or None,
        "detail_url": urls.get("detail"),
        "live": bool(player.get("live")),
        "source": "windy",
        "refresh": 600,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _annotate_static() -> list[dict]:
    return [{**w, "fetched_at": datetime.now(timezone.utc).isoformat()} for w in STATIC_WEBCAMS]


def _static_by_id(cam_id: str) -> dict | None:
    for w in STATIC_WEBCAMS:
        if w["id"] == cam_id:
            return {**w, "fetched_at": datetime.now(timezone.utc).isoformat()}
    return None


async def _windy_query(client: httpx.AsyncClient, params: dict) -> list[dict]:
    params.setdefault("include", "categories,images,location,player,urls")
    params.setdefault("lang", "en")
    r = await client.get(WINDY_URL, params=params, headers=_windy_headers())
    r.raise_for_status()
    data = r.json()
    items = data.get("webcams") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [_normalize_windy(w) for w in items if w.get("status", "active") == "active"]


async def _fetch_windy_single(windy_id: int | str) -> dict | None:
    if not _windy_api_key():
        return None
    url = f"{WINDY_URL}/{windy_id}"
    params = {"include": "categories,images,location,player,urls", "lang": "en"}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params=params, headers=_windy_headers())
            r.raise_for_status()
            w = r.json()
            if isinstance(w, dict) and w.get("webcamId"):
                return _normalize_windy(w)
    except Exception:
        return None
    return None


async def _fetch_windy() -> list[dict]:
    """Fetch nearby + global popular webcams from Windy API v3."""
    if not _windy_api_key():
        return []
    seen: set[int] = set()
    merged: list[dict] = []
    queries = [
        {
            "nearby": f"{OPERATOR_LAT},{OPERATOR_LON},250",
            "limit": 50,
            "sortKey": "popularity",
            "sortDirection": "desc",
        },
        {
            "limit": 50,
            "sortKey": "popularity",
            "sortDirection": "desc",
            "offset": 0,
        },
    ]
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for params in queries:
                for cam in await _windy_query(client, params):
                    wid = cam.get("windy_id")
                    if wid is None or wid in seen:
                        continue
                    seen.add(wid)
                    merged.append(cam)
    except Exception:
        return merged
    return merged


@router.get("")
async def list_webcams(category: str = ""):
    """Return public webcam feeds. Optionally filter by category."""
    global _CACHE
    if _CACHE and (time.time() - _CACHE[0]) < TTL:
        result = _CACHE[1]
    else:
        static = _annotate_static()
        windy = await _fetch_windy()
        all_cats = sorted({w["category"] for w in static + windy})
        result = {
            "count": len(static) + len(windy),
            "static_count": len(static),
            "windy_count": len(windy),
            "windy_configured": bool(_windy_api_key()),
            "categories": all_cats,
            "webcams": static + windy,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _CACHE = (time.time(), result)

    if category and category.lower() != "all":
        filtered = [w for w in result["webcams"] if w["category"] == category.lower()]
        return {
            **result,
            "count": len(filtered),
            "webcams": filtered,
        }
    return result


@router.get("/categories")
def list_categories():
    return {"categories": ["traffic", "nature", "space", "city"]}


@router.get("/{cam_id}")
async def get_webcam(cam_id: str):
    """Fresh stream URL for one webcam (Windy tokens expire; static is cached)."""
    static = _static_by_id(cam_id)
    if static:
        return {"webcam": static}

    if cam_id.startswith("windy-"):
        windy_id = cam_id[6:]
        cam = await _fetch_windy_single(windy_id)
        if cam:
            return {"webcam": cam}
        raise HTTPException(status_code=404, detail="Windy webcam not found")

    raise HTTPException(status_code=404, detail="Webcam not found")
