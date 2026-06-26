"""Chat Context Enricher — query-aware deep grounding for WorldBase AI.

Extracts entities from the user's query (locations, magnitudes, event types,
CVEs, coordinates, vessel names), then filters live feed caches, GDELT events,
ReliefWeb crises, and fusion hotspots by query relevance.

All rule-based, 0 VRAM, <50ms latency (cache reads + string matching).

Env:
  WORLDBASE_CHAT_CONTEXT_ENRICH=1 (default on)
  WORLDBASE_CHAT_BRIEFING_CHARS=2500 (briefing truncation for chat context)
"""

from __future__ import annotations

import math
import os
import re
from typing import Any

from runtime_cache import cache_get


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------


def _enrich_enabled() -> bool:
    return os.getenv("WORLDBASE_CHAT_CONTEXT_ENRICH", "1").strip() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _briefing_chars() -> int:
    try:
        return int(os.getenv("WORLDBASE_CHAT_BRIEFING_CHARS", "2500"))
    except ValueError:
        return 2500


# ---------------------------------------------------------------------------
# Query entity extraction
# ---------------------------------------------------------------------------

# Countries — subset of common ones for matching (full list would be too large
# for inline; this covers the most likely query targets)
_COUNTRIES = {
    "venezuela",
    "thailand",
    "myanmar",
    "burma",
    "china",
    "japan",
    "indonesia",
    "philippines",
    "taiwan",
    "vietnam",
    "laos",
    "cambodia",
    "malaysia",
    "singapore",
    "india",
    "pakistan",
    "afghanistan",
    "iran",
    "iraq",
    "syria",
    "yemen",
    "libya",
    "egypt",
    "sudan",
    "ethiopia",
    "somalia",
    "nigeria",
    "russia",
    "ukraine",
    "turkey",
    "israel",
    "palestine",
    "gaza",
    "lebanon",
    "germany",
    "france",
    "uk",
    "united kingdom",
    "spain",
    "italy",
    "greece",
    "mexico",
    "colombia",
    "brazil",
    "argentina",
    "chile",
    "peru",
    "ecuador",
    "united states",
    "usa",
    "canada",
    "australia",
    "new zealand",
    "fiji",
    "papua new guinea",
    "solomon islands",
    "tonga",
    "vanuatu",
    "south korea",
    "north korea",
    "korea",
    "mongolia",
    "kazakhstan",
    "saudi arabia",
    "uae",
    "qatar",
    "oman",
    "yemen",
    "jordan",
    "bangladesh",
    "nepal",
    "bhutan",
    "sri lanka",
    "maldives",
}

# Event type keywords
_EVENT_KEYWORDS = {
    "earthquake": "earthquake",
    "quake": "earthquake",
    "seismic": "earthquake",
    "eruption": "volcano",
    "volcano": "volcano",
    "volcanic": "volcano",
    "fire": "fire",
    "wildfire": "fire",
    "bushfire": "fire",
    "flood": "flood",
    "flooding": "flood",
    "cyclone": "cyclone",
    "typhoon": "cyclone",
    "hurricane": "cyclone",
    "storm": "storm",
    "tornado": "storm",
    "tsunami": "tsunami",
    "protest": "protest",
    "protests": "protest",
    "riot": "protest",
    "conflict": "conflict",
    "war": "conflict",
    "clash": "conflict",
    "attack": "attack",
    "explosion": "attack",
    "bombing": "attack",
    "drone": "attack",
    "missile": "attack",
    "vessel": "vessel",
    "ship": "vessel",
    "tanker": "vessel",
    "cargo": "vessel",
    "aircraft": "aircraft",
    "plane": "aircraft",
    "helicopter": "aircraft",
    "cyber": "cyber",
    "ransomware": "cyber",
    "hack": "cyber",
    "breach": "cyber",
}

# Intent keywords
_INTENT_KEYWORDS = {
    "analyze": "analysis",
    "analysis": "analysis",
    "assess": "analysis",
    "assessment": "analysis",
    "investigate": "analysis",
    "what is": "lookup",
    "what's": "lookup",
    "status": "monitoring",
    "monitor": "monitoring",
    "track": "monitoring",
    "situation": "analysis",
    "brief": "analysis",
    "summary": "analysis",
}

# Regex patterns
_MAGNITUDE_RE = re.compile(r"\bM(\d+\.?\d*)\b", re.IGNORECASE)
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_COORD_RE = re.compile(
    r"(\d+\.?\d*)\s*[°]\s*([NSns])[/\s,]+(\d+\.?\d*)\s*[°]\s*([EWew])"
)
_DECIMAL_COORD_RE = re.compile(
    r"(?:lat[:\s]+(-?\d+\.?\d*)[,\s]+lon[:\s]+(-?\d+\.?\d*))"
    r"|(?:(-?\d+\.?\d*),\s*(-?\d+\.?\d*)\s*[°°])",
    re.IGNORECASE,
)


def extract_query_entities(query: str) -> dict[str, Any]:
    """Extract structured signals from a user query string.

    Returns dict with keys: locations, coordinates, magnitude, event_type,
    entity_names, cve_ids, temporal, intent.
    """
    if not query:
        return _empty_extraction()

    text = query.strip()
    text_lower = text.lower()

    # Locations — match known country names in the query
    locations: list[str] = []
    for country in _COUNTRIES:
        if country in text_lower:
            locations.append(country.title())

    # Also extract capitalized words that might be place names (heuristic)
    # e.g. "Morón", "Caracas", "Bangkok" — supports Unicode accented chars
    cap_words = re.findall(
        r"\b([A-Z\u00C0-\u017F][a-z\u00C0-\u017F]{2,}(?:\s+[A-Z\u00C0-\u017F][a-z\u00C0-\u017F]+)?)\b",
        text,
    )
    for word in cap_words:
        w_lower = word.lower()
        # Skip common English words that aren't place names
        if w_lower in {
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "what",
            "how",
            "why",
            "when",
            "where",
            "analyze",
            "analysis",
            "assess",
            "show",
            "tell",
            "give",
            "me",
            "please",
            "could",
            "would",
            "should",
            "about",
            "near",
            "around",
            "within",
            "km",
            "miles",
            "north",
            "south",
            "east",
            "west",
            "ws",
            "ne",
            "se",
            "nw",
            "sw",
            "of",
        }:
            continue
        if word not in locations:
            locations.append(word)

    # Coordinates
    coordinates: tuple[float, float] | None = None
    coord_match = _COORD_RE.search(text)
    if coord_match:
        lat = float(coord_match.group(1))
        lat_dir = coord_match.group(2).upper()
        lon = float(coord_match.group(3))
        lon_dir = coord_match.group(4).upper()
        if lat_dir == "S":
            lat = -lat
        if lon_dir == "W":
            lon = -lon
        coordinates = (lat, lon)
    else:
        dec_match = _DECIMAL_COORD_RE.search(text)
        if dec_match:
            lat_str = dec_match.group(1) or dec_match.group(3)
            lon_str = dec_match.group(2) or dec_match.group(4)
            if lat_str and lon_str:
                try:
                    coordinates = (float(lat_str), float(lon_str))
                except ValueError:
                    pass

    # Magnitude
    magnitude: float | None = None
    mag_match = _MAGNITUDE_RE.search(text)
    if mag_match:
        try:
            magnitude = float(mag_match.group(1))
        except ValueError:
            pass

    # Event type — check more specific keywords first (cyber before conflict)
    # Order matters: "ransomware attack" should be cyber, not conflict
    _event_priority = [
        ("ransomware", "cyber"),
        ("cyber", "cyber"),
        ("hack", "cyber"),
        ("breach", "cyber"),
        ("earthquake", "earthquake"),
        ("quake", "earthquake"),
        ("seismic", "earthquake"),
        ("eruption", "volcano"),
        ("volcano", "volcano"),
        ("volcanic", "volcano"),
        ("wildfire", "fire"),
        ("bushfire", "fire"),
        ("fire", "fire"),
        ("flooding", "flood"),
        ("flood", "flood"),
        ("cyclone", "cyclone"),
        ("typhoon", "cyclone"),
        ("hurricane", "cyclone"),
        ("tornado", "storm"),
        ("storm", "storm"),
        ("tsunami", "tsunami"),
        ("protests", "protest"),
        ("protest", "protest"),
        ("riot", "protest"),
        ("war", "conflict"),
        ("conflict", "conflict"),
        ("clash", "conflict"),
        ("explosion", "attack"),
        ("bombing", "attack"),
        ("drone", "attack"),
        ("missile", "attack"),
        ("attack", "attack"),
        ("vessel", "vessel"),
        ("ship", "vessel"),
        ("tanker", "vessel"),
        ("cargo", "vessel"),
        ("aircraft", "aircraft"),
        ("plane", "aircraft"),
        ("helicopter", "aircraft"),
    ]
    event_type: str | None = None
    for keyword, etype in _event_priority:
        if keyword in text_lower:
            event_type = etype
            break

    # CVE IDs
    cve_ids = [m.upper() for m in _CVE_RE.findall(text)]

    # Intent
    intent = "general"
    for keyword, itype in _INTENT_KEYWORDS.items():
        if keyword in text_lower:
            intent = itype
            break

    # Temporal
    temporal: str | None = None
    if "today" in text_lower:
        temporal = "today"
    elif "yesterday" in text_lower:
        temporal = "yesterday"
    elif "last 24" in text_lower or "24h" in text_lower:
        temporal = "24h"
    elif "last 72" in text_lower or "72h" in text_lower:
        temporal = "72h"
    elif "this week" in text_lower:
        temporal = "week"
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        temporal = date_match.group(1)

    return {
        "locations": locations,
        "coordinates": coordinates,
        "magnitude": magnitude,
        "event_type": event_type,
        "entity_names": [],  # P3: extract from FtM graph
        "cve_ids": cve_ids,
        "temporal": temporal,
        "intent": intent,
    }


def _empty_extraction() -> dict[str, Any]:
    return {
        "locations": [],
        "coordinates": None,
        "magnitude": None,
        "event_type": None,
        "entity_names": [],
        "cve_ids": [],
        "temporal": None,
        "intent": "general",
    }


# ---------------------------------------------------------------------------
# Spatial utilities
# ---------------------------------------------------------------------------


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _location_matches(
    place_str: str,
    query_locations: list[str],
    query_coords: tuple[float, float] | None,
    event_lat: float | None = None,
    event_lon: float | None = None,
    max_km: float = 500.0,
) -> bool:
    """Check if a feed event's place string or coordinates match the query."""
    if not place_str and not (event_lat is not None and event_lon is not None):
        return False

    # String matching against query locations
    if place_str and query_locations:
        place_lower = place_str.lower()
        for loc in query_locations:
            if loc.lower() in place_lower:
                return True

    # Coordinate-based matching
    if query_coords and event_lat is not None and event_lon is not None:
        km = _haversine_km(query_coords[0], query_coords[1], event_lat, event_lon)
        if km <= max_km:
            return True

    return False


# ---------------------------------------------------------------------------
# Feed detail enrichment
# ---------------------------------------------------------------------------


def _enrich_quakes(
    query_entities: dict[str, Any],
) -> str | None:
    """Format full details for query-matched earthquakes from USGS cache."""
    qu = cache_get("quakes:day:2.5", ttl=999999)
    if not qu:
        return None

    features = qu.get("features") or []
    if not features:
        return None

    locations = query_entities.get("locations") or []
    coords = query_entities.get("coordinates")
    magnitude = query_entities.get("magnitude")

    matched: list[str] = []
    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords_arr = geom.get("coordinates") or []
        if len(coords_arr) < 2:
            continue

        place = props.get("place") or ""
        event_lat = float(coords_arr[1])
        event_lon = float(coords_arr[0])
        mag = props.get("mag")
        depth = coords_arr[2] if len(coords_arr) > 2 else None
        tsunami = props.get("tsunami", 0)
        felt = props.get("felt")
        event_time = props.get("time")

        # Match by location string or coordinates
        is_match = _location_matches(place, locations, coords, event_lat, event_lon)

        # Also match by magnitude if specified
        if not is_match and magnitude is not None and mag is not None:
            try:
                if abs(float(mag) - magnitude) < 0.3:
                    is_match = True
            except (ValueError, TypeError):
                pass

        if not is_match:
            continue

        lines = [f"  Earthquake: M{mag}, depth={depth} km, {place}"]
        if event_time:
            lines.append(f"    Time: {event_time}")
        lines.append(f"    Coordinates: {event_lat:.2f}°N, {event_lon:.2f}°E")
        lines.append(f"    Tsunami risk: {'yes' if tsunami else 'no'}")
        if felt:
            lines.append(f"    Felt reports: {felt}")
        matched.extend(lines)

    if not matched:
        return None

    return "QUERY-MATCHED EVENTS:\n" + "\n".join(matched)


def _enrich_eonet(
    query_entities: dict[str, Any],
) -> str | None:
    """Format query-matched EONET natural events."""
    ev = cache_get("eonet", ttl=999999)
    if not ev:
        return None

    events = ev.get("events") or []
    if not events:
        return None

    locations = query_entities.get("locations") or []
    coords = query_entities.get("coordinates")
    event_type = query_entities.get("event_type")

    matched: list[str] = []
    for evt in events:
        title = evt.get("title") or ""
        categories = evt.get("categories") or []
        cat_id = ""
        for cat in categories:
            cat_id = cat.get("id") or ""
            break

        geometries = evt.get("geometry") or []
        if not geometries:
            continue
        geom = geometries[-1] if isinstance(geometries, list) else geometries
        geom_coords = geom.get("coordinates") or []
        if isinstance(geom_coords, list) and len(geom_coords) >= 2:
            event_lon = float(geom_coords[0])
            event_lat = float(geom_coords[1])
        else:
            event_lat = event_lon = None

        # Match by event type
        type_match = False
        if event_type:
            type_map = {
                "earthquake": {"earthquake"},
                "volcano": {"volcanoes", "volcano"},
                "fire": {"wildfires", "fire"},
                "flood": {"floods", "flood", "severe storms"},
                "cyclone": {"severe storms", "tropical cyclone"},
                "storm": {"severe storms", "tornado"},
                "tsunami": {"tsunami"},
            }
            target_set = type_map.get(event_type, set())
            if cat_id in target_set:
                type_match = True

        # Match by location
        loc_match = _location_matches(title, locations, coords, event_lat, event_lon)

        if not (type_match or loc_match):
            continue

        lines = [f"  Natural Event: {title} (type: {cat_id})"]
        if event_lat is not None:
            lines.append(f"    Coordinates: {event_lat:.2f}°N, {event_lon:.2f}°E")
        status = evt.get("status", "open")
        lines.append(f"    Status: {status}")
        matched.extend(lines)

    if not matched:
        return None

    header = "QUERY-MATCHED NATURAL EVENTS:\n"
    return header + "\n".join(matched)


def _enrich_reliefweb(
    query_entities: dict[str, Any],
) -> str | None:
    """Filter ReliefWeb crises by query region."""
    rw = cache_get("reliefweb", ttl=999999)
    if not rw:
        return None

    disasters = rw.get("data") or []
    if not disasters:
        return None

    locations = query_entities.get("locations") or []
    if not locations:
        return None

    matched: list[str] = []
    for d in disasters:
        f = d.get("fields") or {}
        name = f.get("name") or ""
        country_names = [c.get("name", "") for c in (f.get("country") or [])]
        all_text = (name + " " + " ".join(country_names)).lower()

        for loc in locations:
            if loc.lower() in all_text:
                status = f.get("status", "unknown")
                date = f.get("date", {}).get("created", "?")
                matched.append(f"  {name} — {status} (since {date})")
                break

    if not matched:
        return None

    return "QUERY-REGION CRISES (ReliefWeb):\n" + "\n".join(matched)


async def _enrich_gdelt(
    query_entities: dict[str, Any],
) -> str | None:
    """Format GDELT events matching query location from GDELT bridge."""
    locations = query_entities.get("locations") or []
    if not locations:
        return None

    # GDELT bridge has its own internal cache, not runtime_cache
    try:
        from gdelt_bridge import gdelt_pulse_local_data, gdelt_geo_local_data
    except Exception:
        return None

    matched: list[str] = []

    # Try pulse local (articles)
    try:
        pulse = await gdelt_pulse_local_data(refresh=False)
        articles = pulse.get("articles") or []
        for art in articles[:20]:
            title = art.get("title") or ""
            url = art.get("url") or ""
            for loc in locations:
                if loc.lower() in title.lower():
                    matched.append(f"  [{art.get('domain', '?')}] {title[:120]}")
                    if url:
                        matched.append(f"    URL: {url[:100]}")
                    break
    except Exception:
        pass

    # Try geo local (events with coordinates)
    try:
        geo = await gdelt_geo_local_data(refresh=False)
        events = geo.get("events") or []
        for evt in events[:20]:
            title = evt.get("title") or ""
            for loc in locations:
                if loc.lower() in title.lower():
                    matched.append(f"  [GDELT GEO] {title[:120]}")
                    break
    except Exception:
        pass

    if not matched:
        return None

    return "QUERY-REGION GDELT EVENTS:\n" + "\n".join(matched[:10])


async def _enrich_fusion_hotspots(
    query_entities: dict[str, Any],
) -> str | None:
    """Check if query location is in a fusion hotspot."""
    coords = query_entities.get("coordinates")
    locations = query_entities.get("locations") or []
    if not coords and not locations:
        return None

    try:
        import fusion_heatmap

        # Use top_hotspots_for_llm which handles the async endpoint call
        hotspots, _text, _deltas = await fusion_heatmap.top_hotspots_for_llm(
            top=20, compare_hours=None
        )
        cells = hotspots
    except Exception:
        return None

    if not cells:
        return None

    matched: list[str] = []
    for cell in cells:
        cell_lat = cell.get("lat")
        cell_lon = cell.get("lon")
        if cell_lat is None or cell_lon is None:
            continue

        is_match = False
        if coords:
            km = _haversine_km(coords[0], coords[1], float(cell_lat), float(cell_lon))
            if km <= 200:
                is_match = True

        if not is_match:
            # Check samples for location mentions
            samples = cell.get("samples") or []
            for s in samples:
                label = (s.get("label") or "").lower()
                for loc in locations:
                    if loc.lower() in label:
                        is_match = True
                        break
                if is_match:
                    break

        if not is_match:
            continue

        score = cell.get("score", 0)
        sources = ", ".join(cell.get("sources") or [])
        samples_str = "; ".join(
            (s.get("label") or "")[:60]
            for s in (cell.get("samples") or [])[:2]
            if s.get("label")
        )
        matched.append(
            f"  Cell [{cell_lat:.1f}°N, {cell_lon:.1f}°E] "
            f"score={score:.2f} [{sources}]"
            + (f" — {samples_str}" if samples_str else "")
        )

    if not matched:
        return None

    return "QUERY-LOCATED FUSION HOTSPOT:\n" + "\n".join(matched[:3])


# ---------------------------------------------------------------------------
# Main enrichment entry point
# ---------------------------------------------------------------------------


async def enrich_query_context(query: str) -> str | None:
    """Build a query-aware enriched context block.

    Extracts entities from the query, then filters live feed caches,
    GDELT events, ReliefWeb crises, and fusion hotspots by relevance.

    Returns formatted text block, or None if no enrichment possible.
    """
    if not _enrich_enabled() or not query or len(query) < 5:
        return None

    entities = extract_query_entities(query)
    if not any(
        [
            entities["locations"],
            entities["coordinates"],
            entities["magnitude"],
            entities["event_type"],
            entities["cve_ids"],
        ]
    ):
        return None

    blocks: list[str] = []

    # Sync enrichers (cache-only reads)
    sync_enrichers = [
        lambda: _enrich_quakes(entities),
        lambda: _enrich_eonet(entities),
        lambda: _enrich_reliefweb(entities),
    ]
    for enricher in sync_enrichers:
        try:
            block = enricher()
            if block:
                blocks.append(block)
        except Exception:
            continue

    # Async enrichers (need await for API/cache calls)
    async_enrichers = [
        _enrich_gdelt(entities),
        _enrich_fusion_hotspots(entities),
    ]
    for enricher in async_enrichers:
        try:
            block = await enricher
            if block:
                blocks.append(block)
        except Exception:
            continue

    if not blocks:
        return None

    return "\n\n".join(blocks)


def get_query_intent(query: str) -> str:
    """Quick intent classification for system prompt adaptation."""
    entities = extract_query_entities(query)
    return entities.get("intent", "general")


def get_query_event_type(query: str) -> str | None:
    """Extract event type for domain template selection."""
    entities = extract_query_entities(query)
    return entities.get("event_type")
