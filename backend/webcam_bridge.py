"""Public webcam aggregation.

Sources:
- Windy.com webcam API (free tier, requires API key)
- Webcam.Travel / Lookr (public tourist cameras)
- Curated static feeds: traffic, weather, space, nature

All cameras are publicly accessible — no unauthorized access.
"""

import os
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/webcams", tags=["webcams"])

WINDY_API_KEY = os.getenv("WINDY_WEBCAM_API_KEY", "")
WINDY_URL = "https://api.windy.com/webcams/api/v3/webcams"

_CACHE: tuple[float, dict] | None = None
TTL = 120  # 2 min

# Curated public webcam feeds — openly accessible, no auth required
STATIC_WEBCAMS: list[dict] = [
    # --- TRAFFIC ---
    {"id": "de-a7-hamburg", "name": "A7 Hamburg — Elbtunnel Nord", "country": "DE", "lat": 53.543, "lon": 9.966, "category": "traffic", "url": "https://verkehrshaus.de/webcams/hamburg-elbtunnel.jpg", "source": "static", "refresh": 60},
    {"id": "de-a9-muenchen", "name": "A9 München — Allianz Arena", "country": "DE", "lat": 48.176, "lon": 11.552, "category": "traffic", "url": "https://www.bayerninfo.de/webcams/images/500146134.jpg", "source": "static", "refresh": 60},
    {"id": "se-e4-stockholm", "name": "E4 Stockholm — Essingeleden", "country": "SE", "lat": 59.332, "lon": 18.029, "category": "traffic", "url": "https://api.trafikinfo.trafikverket.se/v2/images/2791?max-age=60", "source": "static", "refresh": 60},
    {"id": "fr-a1-paris", "name": "A1 Paris — Porte de la Chapelle", "country": "FR", "lat": 48.898, "lon": 2.359, "category": "traffic", "url": "https://www.sytadin.fr/cameras/camera?cameraId=5117", "source": "static", "refresh": 60},
    {"id": "us-i95-nyc", "name": "I-95 New York — George Washington Bridge", "country": "US", "lat": 40.851, "lon": -73.952, "category": "traffic", "url": "https://www.dot.ny.gov/traffic/cameras/camera?cameraId=5117", "source": "static", "refresh": 60},
    {"id": "uk-m25-london", "name": "M25 London — Dartford Crossing", "country": "GB", "lat": 51.464, "lon": 0.264, "category": "traffic", "url": "https://www.trafficengland.com/cameras/100013780.jpg", "source": "static", "refresh": 60},
    {"id": "jp-shuto-tokyo", "name": "Shuto Tokyo — Shibuya", "country": "JP", "lat": 35.659, "lon": 139.700, "category": "traffic", "url": "https://www.jartic.or.jp/img/camera/c0001.jpg", "source": "static", "refresh": 60},
    # --- WEATHER / NATURE ---
    {"id": "ch-zermatt", "name": "Zermatt — Matterhorn", "country": "CH", "lat": 45.976, "lon": 7.658, "category": "nature", "url": "https://www.zermatt.ch/webcams/matterhorn.jpg", "source": "static", "refresh": 300},
    {"id": "at-tirol", "name": "Tirol — Kitzbühel", "country": "AT", "lat": 47.449, "lon": 12.391, "category": "nature", "url": "https://www.bergfex.at/webcams/kitzbuehel.jpg", "source": "static", "refresh": 300},
    {"id": "is-reykjavik", "name": "Reykjavik — Hallgrímskirkja", "country": "IS", "lat": 64.146, "lon": -21.942, "category": "nature", "url": "https://www.livefromiceland.is/webcams/reykjavik.jpg", "source": "static", "refresh": 300},
    {"id": "no-tromso", "name": "Tromsø — Northern Lights", "country": "NO", "lat": 69.649, "lon": 18.955, "category": "nature", "url": "https://www.tromso-webcam.com/image.jpg", "source": "static", "refresh": 60},
    {"id": "nz-queenstown", "name": "Queenstown — Lake Wakatipu", "country": "NZ", "lat": -45.031, "lon": 168.662, "category": "nature", "url": "https://www.queenstownnz.co.nz/webcam/", "source": "static", "refresh": 300},
    {"id": "ca-banff", "name": "Banff — Lake Louise", "country": "CA", "lat": 51.425, "lon": -116.216, "category": "nature", "url": "https://www.banfflakelouise.com/webcams/lake-louise.jpg", "source": "static", "refresh": 300},
    # --- SPACE ---
    {"id": "nasa-iss", "name": "NASA ISS — HDEV Live", "country": "SPACE", "lat": 0, "lon": 0, "category": "space", "url": "https://images-assets.nasa.gov/video/iss-hdev/iss-hdev~thumb.jpg", "embed": "https://www.youtube.com/embed/86YLFOog4GM?autoplay=1", "source": "static", "refresh": 0},
    {"id": "nasa-earth", "name": "NASA DSCOVR — Earth Polychromatic", "country": "SPACE", "lat": 0, "lon": 0, "category": "space", "url": "https://epic.gsfc.nasa.gov/archive/natural/latest/png/epic_1b_20250101.png", "source": "static", "refresh": 3600},
    {"id": "spacex-starbase", "name": "Starbase Boca Chica", "country": "US", "lat": 25.997, "lon": -97.156, "category": "space", "url": "https://www.spacex.com/static/images/backgrounds/starbase_cam.jpg", "source": "static", "refresh": 60},
    # --- CITYSCAPE ---
    {"id": "de-berlin-brandenburg", "name": "Berlin — Brandenburger Tor", "country": "DE", "lat": 52.516, "lon": 13.377, "category": "city", "url": "https://www.berlin.de/webcams/brandenburgertor.jpg", "source": "static", "refresh": 300},
    {"id": "fr-paris-eiffel", "name": "Paris — Eiffelturm", "country": "FR", "lat": 48.858, "lon": 2.294, "category": "city", "url": "https://www.paris-webcam.com/eiffel.jpg", "source": "static", "refresh": 300},
    {"id": "jp-tokyo-shibuya", "name": "Tokyo — Shibuya Crossing", "country": "JP", "lat": 35.659, "lon": 139.700, "category": "city", "url": "https://www.shibuya-webcam.com/image.jpg", "source": "static", "refresh": 60},
    {"id": "us-nyc-times-square", "name": "NYC — Times Square", "country": "US", "lat": 40.758, "lon": -73.985, "category": "city", "url": "https://www.earthcam.com/cams/newyork/timessquare/", "embed": "https://www.youtube.com/embed/1EiC9bvVGnk", "source": "static", "refresh": 0},
    {"id": "br-rio-copacabana", "name": "Rio — Copacabana", "country": "BR", "lat": -22.971, "lon": -43.182, "category": "city", "url": "https://www.rio-webcam.com/copacabana.jpg", "source": "static", "refresh": 300},
    {"id": "au-sydney-harbour", "name": "Sydney — Harbour Bridge", "country": "AU", "lat": -33.852, "lon": 151.211, "category": "city", "url": "https://www.sydney-webcam.com/harbour.jpg", "source": "static", "refresh": 300},
]


def _annotate_static() -> list[dict]:
    """Return static webcam list with timestamp."""
    return [{**w, "fetched_at": datetime.now(timezone.utc).isoformat()} for w in STATIC_WEBCAMS]


async def _fetch_windy() -> list[dict]:
    """Fetch nearby webcams from Windy API if key is configured."""
    if not WINDY_API_KEY:
        return []
    try:
        # Bounding box for Europe + Americas (demo)
        params = {
            "key": WINDY_API_KEY,
            "limit": 20,
            "show": "webcams:image,location",
            "lang": "en",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(WINDY_URL, params=params)
            r.raise_for_status()
            data = r.json()
            cams = []
            for w in data.get("result", {}).get("webcams", []):
                cams.append({
                    "id": f"windy-{w.get('id')}",
                    "name": w.get("title", "Unknown"),
                    "country": w.get("location", {}).get("country_code", "??"),
                    "lat": w.get("location", {}).get("latitude"),
                    "lon": w.get("location", {}).get("longitude"),
                    "category": w.get("category", "unknown"),
                    "url": w.get("image", {}).get("current", {}).get("preview", ""),
                    "source": "windy",
                    "refresh": 300,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                })
            return cams
    except Exception:
        return []


@router.get("")
async def list_webcams(category: str = ""):
    """Return public webcam feeds. Optionally filter by category."""
    global _CACHE
    if _CACHE and (time.time() - _CACHE[0]) < TTL:
        result = _CACHE[1]
    else:
        static = _annotate_static()
        windy = await _fetch_windy()
        result = {
            "count": len(static) + len(windy),
            "static_count": len(static),
            "windy_count": len(windy),
            "categories": sorted({w["category"] for w in static}),
            "webcams": static + windy,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        _CACHE = (time.time(), result)

    if category:
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
