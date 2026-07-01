"""Connector manifest catalog — scale feeds without iframe plugin sandbox.

Each connector describes a server-side bridge: endpoints, TTL, license, region,
and credential provider ids (see credentials.registry). Runtime cache rows come
from feed_registry / feed_cache; this module is the static catalog + export.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from config import get_config as _cfg
from typing import Any

# Per-feed max age (seconds) before marked stale in /api/health — single source of truth.
FEED_TTL_SEC: dict[str, float] = {
    "airquality": 3600,
    "gdacs": 900,
    "gdacs_v2": 900,
    "gdacs_v3": 900,
    "pegel": 900,
    "markets": 120,
    "military": 60,
    "spaceweather": 300,
    "radar": 600,
    "commodities": 300,
    "geopolitics": 600,
    "reliefweb": 600,
    "eonet": 1800,
    "wildfires": 600,
    "outages": 300,
    "energy_de": 900,
    "cve": 3600,
    "darkweb": 3600,
    "domain_intel": 3600,
    "onion_directory": 7200,
    "acled_events": 3600,
    "osm_infrastructure": 7200,
    "weather_forecast": 3600,
    "traffic_cams:regional": 120,
    "traffic_cams:global": 3600,
    "traffic_cams:all": 90,
}


def feed_ttl_sec(key: str) -> float:
    if key in FEED_TTL_SEC:
        return FEED_TTL_SEC[key]
    if key.startswith("weather:"):
        return 1800
    if key.startswith("quakes:"):
        return 300
    if key.startswith("traffic_cams:"):
        return 120
    return 600


@dataclass(frozen=True)
class ConnectorManifest:
    """Static connector definition (serializable to JSON/YAML)."""

    id: str
    name: str
    category: str
    endpoints: tuple[str, ...]
    ttl_sec: float
    license: str
    region: tuple[str, ...]
    credential_ids: tuple[str, ...] = ()
    cache_key: str | None = None
    bridge: str | None = None
    globe_layer: str | None = None
    ingest_mapping: str | None = None
    tier: str = "free"
    usage_policy: str = "private_research"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["endpoints"] = list(self.endpoints)
        d["region"] = list(self.region)
        d["credential_ids"] = list(self.credential_ids)
        return d


def _c(
    id: str,
    name: str,
    category: str,
    endpoints: tuple[str, ...],
    *,
    ttl_sec: float = 600,
    license: str = "Open data / operator research",
    region: tuple[str, ...] = ("global",),
    credential_ids: tuple[str, ...] = (),
    cache_key: str | None = None,
    bridge: str | None = None,
    globe_layer: str | None = None,
    ingest_mapping: str | None = None,
    tier: str = "free",
    notes: str = "",
) -> ConnectorManifest:
    return ConnectorManifest(
        id=id,
        name=name,
        category=category,
        endpoints=endpoints,
        ttl_sec=ttl_sec,
        license=license,
        region=region,
        credential_ids=credential_ids,
        cache_key=cache_key or id,
        bridge=bridge,
        globe_layer=globe_layer,
        ingest_mapping=ingest_mapping,
        tier=tier,
        notes=notes,
    )


CONNECTOR_CATALOG: dict[str, ConnectorManifest] = {
    "aircraft": _c(
        "aircraft",
        "Live aircraft (ADS-B)",
        "aviation",
        ("/api/aircraft",),
        ttl_sec=60,
        credential_ids=("opensky",),
        bridge="aircraft_provider.py",
        globe_layer="aircraft",
        tier="optional",
        notes="adsb.fi / adsb.lol fallback without OpenSky OAuth.",
    ),
    "airquality": _c(
        "airquality",
        "Open-Meteo air quality (CAMS)",
        "environment",
        ("/api/airquality",),
        ttl_sec=3600,
        region=("local", "regional", "global"),
        bridge="feeds_extra.py",
        globe_layer="airquality",
        notes="PM2.5, dust, aerosol optical depth via Open-Meteo/CAMS.",
    ),
    "cams_haze": _c(
        "cams_haze",
        "CAMS haze (Open-Meteo)",
        "environment",
        ("/api/cams/haze",),
        ttl_sec=3600,
        region=("local", "regional"),
        bridge="cams_bridge.py",
        cache_key="cams_haze",
        notes="Thailand + ASEAN cities; burning season / transboundary haze.",
    ),
    "briefing": _c(
        "briefing",
        "24h security briefing",
        "intel",
        ("/api/briefing", "/api/briefing/generate"),
        ttl_sec=21_600,
        credential_ids=("ollama",),
        bridge="operator_briefing.py",
        region=("local", "regional", "global"),
        cache_key=None,
        tier="free",
    ),
    "cve": _c(
        "cve",
        "CISA KEV catalog",
        "security",
        ("/api/cve",),
        ttl_sec=3600,
        license="US government open data",
        bridge="cve_bridge.py",
        cache_key="cve",
    ),
    "cii": _c(
        "cii",
        "Country Instability Index (CII)",
        "intel",
        ("/api/cii/country", "/api/cii/rankings"),
        ttl_sec=300,
        region=("global",),
        bridge="cii_engine.py",
        cache_key="cii",
        notes="Composite 0-100 instability score from GDELT, NewsData, ACLED. 4 signal families: conflict, economy, climate, governance.",
    ),
    "darkweb": _c(
        "darkweb",
        "Dark web / darknet OSINT monitor",
        "osint",
        (
            "/api/darkweb",
            "/api/darkweb/search",
            "/api/darkweb/status",
            "/api/darkweb/engines",
            "/api/darkweb/ingest",
            "/api/darkweb/match",
            "/api/darkweb/entities",
            "/api/darkweb/mentions",
            "/api/darkweb/scrape",
            "/api/darkweb/deep_search",
            "/api/darkweb/ransomware/groups",
            "/api/darkweb/ransomware/victims",
            "/api/darkweb/ransomware/refresh",
        ),
        ttl_sec=3600,
        region=("global",),
        bridge="darkweb_bridge.py",
        cache_key="darkweb",
        ingest_mapping="darkweb_mentions",
        globe_layer="darkweb",
        notes="Passive .onion search (Ahmia, DarkSearch, optional Tor engines). FtM Mention ingest. Low provenance reliability.",
    ),
    "domain_intel": _c(
        "domain_intel",
        "Domain intelligence (CT logs + Wayback + RDAP)",
        "osint",
        (
            "/api/domain/intel",
            "/api/domain/certs",
            "/api/domain/wayback",
            "/api/domain/rdap",
        ),
        ttl_sec=3600,
        region=("global",),
        bridge="domain_intel.py",
        cache_key="domain_intel",
        notes="crt.sh CT logs, Wayback CDX snapshots, RDAP registration. No API key required.",
    ),
    "thai_opendata": _c(
        "thai_opendata",
        "Thailand Open Data (data.go.th CKAN)",
        "government",
        (
            "/api/thai/opendata",
            "/api/thai/environmental",
            "/api/thai/ingest",
        ),
        ttl_sec=3600,
        region=("local",),
        bridge="thai_opendata.py",
        cache_key="thai_opendata",
        notes="Thai government open data portal (CKAN). Environmental, population, economic datasets. No API key required.",
    ),
    "identity_osint": _c(
        "identity_osint",
        "Identity OSINT (email/username enumeration)",
        "osint",
        (
            "/api/osint/identity",
            "/api/osint/identity/ingest",
            "/api/osint/identity/audit",
            "/api/osint/identity/status",
        ),
        ttl_sec=86400,
        region=("global",),
        bridge="identity_osint.py",
        cache_key="identity_osint",
        notes="Passive email/username existence checks across 50+ platforms. Opt-in only. No credential stuffing.",
    ),
    "onion_directory": _c(
        "onion_directory",
        "Onion directory (curated legitimate .onion services)",
        "osint",
        (
            "/api/onion-directory",
            "/api/onion-directory/ingest",
            "/api/onion-directory/status",
        ),
        ttl_sec=7200,
        region=("global",),
        bridge="onion_directory.py",
        cache_key="onion_directory",
        notes="Curated onion services from real-world-onion-sites (Alec Muffett) + SecureDrop directory. Journalism, NGO, tech, government. No illegal content.",
    ),
    "earthquakes": _c(
        "earthquakes",
        "USGS earthquakes",
        "geo",
        ("/api/earthquakes",),
        ttl_sec=300,
        license="USGS public domain",
        bridge="main.py",
        globe_layer="quakes",
        cache_key="quakes:day",
    ),
    "energy_de": _c(
        "energy_de",
        "SMARD Germany energy mix",
        "energy",
        ("/api/energy/de/globe",),
        ttl_sec=900,
        license="SMARD / Bundesnetzagentur terms",
        region=("regional",),
        bridge="smard_bridge.py",
        globe_layer="energy",
        cache_key="energy_de",
    ),
    "gdacs": _c(
        "gdacs",
        "GDACS disaster alerts",
        "alerts",
        ("/api/gdacs",),
        ttl_sec=900,
        license="GDACS open data",
        bridge="feeds_extra.py",
        globe_layer="gdacs",
        ingest_mapping="gdacs_alerts",
        cache_key="gdacs_v3",
    ),
    "gdelt_geo": _c(
        "gdelt_geo",
        "GDELT geo events (local bbox)",
        "intel",
        ("/api/gdelt/geo/local",),
        ttl_sec=600,
        license="GDELT terms",
        region=("local", "regional", "global"),
        bridge="gdelt_bridge.py",
        cache_key=None,
        tier="free",
        notes="Operator region bbox; rate-limit fail-soft.",
    ),
    "gdelt_pulse": _c(
        "gdelt_pulse",
        "GDELT pulse headlines (local)",
        "intel",
        ("/api/gdelt/pulse/local",),
        ttl_sec=600,
        license="GDELT terms",
        region=("local",),
        bridge="gdelt_bridge.py",
        cache_key=None,
    ),
    "geopolitics": _c(
        "geopolitics",
        "ReliefWeb + GDACS headlines",
        "alerts",
        ("/api/geopolitics",),
        ttl_sec=600,
        credential_ids=("reliefweb",),
        bridge="feeds_extra.py",
        globe_layer="geopolitics",
        tier="optional",
        notes="GDACS subset without ReliefWeb appname.",
    ),
    "humanitarian": _c(
        "humanitarian",
        "HDX humanitarian datasets",
        "humanitarian",
        ("/api/humanitarian",),
        ttl_sec=3600,
        region=("regional", "global"),
        bridge="humanitarian_bridge.py",
        cache_key="humanitarian",
        license="HDX / UN OCHA open data",
        notes="Myanmar border, displacement, regional crises.",
    ),
    "newsdata": _c(
        "newsdata",
        "NewsData.io headlines (multi-country preview profile)",
        "intel",
        ("/api/newsdata", "/api/newsdata/sources"),
        ttl_sec=900,
        region=("local", "regional", "global"),
        bridge="newsdata_bridge.py",
        cache_key="newsdata_local",
        credential_ids=("newsdata",),
        license="NewsData.io API terms",
        tier="optional",
        notes="GDELT complement; separate corroboration family. Free tier ~12h delay. Default filters: al,de,us,ir,th + de,en.",
    ),
    "hazards": _c(
        "hazards",
        "NWS + Meteoalarm active alerts",
        "alerts",
        ("/api/hazards",),
        ttl_sec=300,
        license="US NWS + Meteoalarm open CAP feeds",
        bridge="cap_bridge.py",
        globe_layer="hazards",
        cache_key="hazards",
        notes="Weather and hazard CAP; no API key.",
    ),
    "intel_ftm": _c(
        "intel_ftm",
        "FollowTheMoney entity graph",
        "intel",
        ("/api/intel/entities", "/api/intel/graph"),
        ttl_sec=120,
        license="FtM / dataset-specific",
        bridge="ftm_store.py",
        globe_layer="intelFt",
        cache_key=None,
        tier="free",
    ),
    "lightning": _c(
        "lightning",
        "Blitzortung lightning",
        "geo",
        ("/api/lightning",),
        ttl_sec=60,
        credential_ids=("blitzortung",),
        bridge="blitzortung_bridge.py",
        globe_layer="lightning",
        tier="optional",
        cache_key=None,
    ),
    "acled": _c(
        "acled",
        "ACLED conflict events (research access)",
        "conflict",
        ("/api/acled/events",),
        ttl_sec=3600,
        credential_ids=("acled",),
        bridge="acled_bridge.py",
        globe_layer="acled",
        region=("local", "regional"),
        tier="optional",
        cache_key="acled_events",
        notes="Free for non-commercial research. Register at developer.acleddata.com. ASEAN default.",
    ),
    "osm_infrastructure": _c(
        "osm_infrastructure",
        "OSM critical infrastructure POIs (Overpass)",
        "infrastructure",
        ("/api/osm/infrastructure",),
        ttl_sec=7200,
        bridge="osm_bridge.py",
        globe_layer="osm",
        region=("local", "regional"),
        tier="free",
        cache_key="osm_infrastructure",
        notes="Hospitals, power plants, airports, bridges, fire/police via Overpass. No key needed.",
    ),
    "weather_forecast": _c(
        "weather_forecast",
        "Open-Meteo 7-day weather forecast",
        "weather",
        ("/api/weather/forecast",),
        ttl_sec=3600,
        bridge="weather_forecast_bridge.py",
        globe_layer="weatherForecast",
        region=("local", "regional"),
        tier="free",
        cache_key="weather_forecast",
        notes="Key-less 7-day forecast for Thailand+ASEAN cities. Severe weather detection.",
    ),
    "maritime": _c(
        "maritime",
        "AIS vessel positions",
        "maritime",
        ("/api/maritime", "/api/maritime/ports"),
        ttl_sec=45,
        credential_ids=("ais_maritime",),
        bridge="ais_bridge.py",
        globe_layer="maritime",
        region=("local", "regional", "global"),
        tier="optional",
        ingest_mapping="ais_vessels",
        cache_key="maritime",
        notes="Malacca Strait, Laem Chabang, Bangkok, Phuket + global ports.",
    ),
    "markets": _c(
        "markets",
        "Market indices",
        "finance",
        ("/api/markets",),
        ttl_sec=120,
        bridge="stock_bridge.py",
        cache_key="markets",
    ),
    "military": _c(
        "military",
        "Military aircraft filter",
        "aviation",
        ("/api/military",),
        ttl_sec=60,
        bridge="feeds_extra.py",
        globe_layer="military",
        cache_key="military",
    ),
    "nodes": _c(
        "nodes",
        "Pi edge sensor nodes",
        "edge",
        ("/api/nodes", "/api/node/pull"),
        ttl_sec=120,
        credential_ids=("node_ingest",),
        bridge="node_sync.py",
        globe_layer="nodes",
        region=("local",),
        tier="optional",
        cache_key=None,
    ),
    "outages": _c(
        "outages",
        "Internet outages (IODA + Cloudflare)",
        "network",
        ("/api/outages",),
        ttl_sec=300,
        credential_ids=("cloudflare_radar",),
        bridge="outages_bridge.py",
        globe_layer="outages",
        tier="optional",
        notes="IODA works without Cloudflare token.",
    ),
    "pegel": _c(
        "pegel",
        "Pegelonline river gauges (DE)",
        "environment",
        ("/api/pegel",),
        ttl_sec=900,
        license="PEGELonline terms",
        region=("regional",),
        bridge="pegel_bridge.py",
        globe_layer="pegel",
        cache_key="pegel",
    ),
    "satellites": _c(
        "satellites",
        "CelesTrak TLE / Starlink",
        "space",
        ("/api/satellites",),
        ttl_sec=3600,
        license="CelesTrak terms",
        bridge="main.py",
        globe_layer="satellites",
        cache_key=None,
    ),
    "situations": _c(
        "situations",
        "Unified situations board",
        "intel",
        ("/api/situations",),
        ttl_sec=45,
        bridge="situations.py",
        cache_key=None,
    ),
    "spaceweather": _c(
        "spaceweather",
        "NOAA space weather",
        "space",
        ("/api/spaceweather",),
        ttl_sec=300,
        license="NOAA open data",
        bridge="feeds_extra.py",
        globe_layer="spaceweather",
        cache_key="spaceweather",
    ),
    "radar": _c(
        "radar",
        "RainViewer precipitation radar",
        "environment",
        ("/api/radar",),
        ttl_sec=600,
        license="RainViewer free API",
        region=("local", "regional", "global"),
        bridge="feeds_extra.py",
        globe_layer="radar",
        cache_key="radar",
        notes="Global precipitation radar tiles (past + nowcast). No key required.",
    ),
    "commodities": _c(
        "commodities",
        "Commodity prices (gold, silver, oil)",
        "finance",
        ("/api/commodities",),
        ttl_sec=300,
        license="ECB / Frankfurter open data",
        region=("global",),
        bridge="feeds_extra.py",
        cache_key="commodities",
        notes="Gold/silver via ECB reference rates, Brent/WTI via Commodities-API. No key.",
    ),
    "traffic_cams_regional": _c(
        "traffic_cams_regional",
        "Singapore traffic cameras",
        "traffic",
        ("/api/traffic/cams?scope=regional",),
        ttl_sec=120,
        license="Singapore Open Data Licence",
        region=("regional",),
        credential_ids=("data_gov_sg",),
        bridge="traffic_bridge.py",
        globe_layer="trafficCams",
        cache_key="traffic_cams:regional",
    ),
    "traffic_cams_merged": _c(
        "traffic_cams_merged",
        "Merged traffic cameras (all scopes)",
        "traffic",
        ("/api/traffic/cams?scope=all",),
        ttl_sec=90,
        license="Mixed; verify per source",
        region=("regional", "global"),
        credential_ids=("data_gov_sg", "opentrafficcammap"),
        bridge="traffic_bridge.py",
        globe_layer="trafficCams",
        cache_key="traffic_cams:all",
        tier="free",
        notes="Union of regional + global scopes.",
    ),
    "traffic_cams_global": _c(
        "traffic_cams_global",
        "OpenTrafficCamMap global",
        "traffic",
        ("/api/traffic/cams?scope=global",),
        ttl_sec=3600,
        license="Crowdsourced; verify per stream",
        credential_ids=("opentrafficcammap",),
        bridge="traffic_bridge.py",
        globe_layer="trafficCams",
        cache_key="traffic_cams:global",
    ),
    "weather_grid": _c(
        "weather_grid",
        "Windy / Open-Meteo weather grid",
        "weather",
        ("/api/weather",),
        ttl_sec=1800,
        credential_ids=("windy_point",),
        bridge="windy_bridge.py",
        globe_layer="weather",
        tier="optional",
        cache_key="weather",
        notes="Cache keys are weather:lat:lon per cell.",
    ),
    "webcams": _c(
        "webcams",
        "Windy webcams",
        "cams",
        ("/api/webcams",),
        ttl_sec=120,
        credential_ids=("windy_webcam",),
        bridge="webcam_bridge.py",
        tier="optional",
        cache_key=None,
    ),
    "wildfires": _c(
        "wildfires",
        "NASA FIRMS wildfires",
        "geo",
        ("/api/wildfires",),
        ttl_sec=600,
        credential_ids=("firms",),
        bridge="nasa_firms.py",
        globe_layer="wildfires",
        ingest_mapping="eonet_events",
        tier="optional",
        notes="EONET fallback without FIRMS key.",
    ),
    "ckan_harvester": _c(
        "ckan_harvester",
        "CKAN generic harvester (multi-portal)",
        "government",
        (
            "/api/ckan/portals",
            "/api/ckan/{portal_id}/search",
            "/api/ckan/{portal_id}/harvest",
            "/api/ckan/harvest-all",
            "/api/ckan/harvest/log",
        ),
        ttl_sec=3600,
        region=("local", "regional", "global"),
        bridge="ckan_harvester.py",
        cache_key="ckan_harvester",
        notes="Generic CKAN portal harvester. Portals configured in ingest/ckan_sources.yml. WORLDBASE_CKAN_HARVESTER=1 to enable harvest.",
    ),
}


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _read_feed_cache_keys() -> dict[str, dict[str, Any]]:
    """Return feed_cache rows keyed by cache key (best-effort)."""
    out: dict[str, dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(_db_path(), timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        cur = conn.cursor()
        cur.execute("SELECT key, value, cached_at FROM feed_cache ORDER BY key")
        for key, value_json, cached_at in cur.fetchall():
            meta: dict[str, Any] = {"cache_key": key, "cached_at": cached_at}
            if value_json and len(value_json) < 120_000:
                try:
                    val = json.loads(value_json)
                    if isinstance(val, dict):
                        meta["count"] = val.get("count")
                        meta["source"] = val.get("source") or val.get("sources")
                        meta["error"] = val.get("error")
                except Exception:
                    pass
            out[key] = meta
        conn.close()
    except Exception:
        pass
    return out


def _credentials_status(credential_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    if not credential_ids:
        return []
    try:
        from credentials.registry import provider_status

        rows = []
        for cid in credential_ids:
            st = provider_status(cid)
            if st:
                rows.append(
                    {
                        "id": cid,
                        "configured": st["configured"],
                        "tier": st["tier"],
                    }
                )
            else:
                rows.append({"id": cid, "configured": False, "tier": "unknown"})
        return rows
    except Exception:
        return [
            {"id": cid, "configured": False, "tier": "unknown"}
            for cid in credential_ids
        ]


def _match_cache(
    spec: ConnectorManifest, cache: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    ck = spec.cache_key
    if not ck:
        return None
    if ck in cache:
        return cache[ck]
    if ck == "weather":
        for k, v in cache.items():
            if k.startswith("weather:"):
                return {**v, "cache_key": k, "cache_key_pattern": "weather:*"}
        return None
    if ck == "quakes:day":
        for k, v in cache.items():
            if k.startswith("quakes:"):
                return {**v, "cache_key": k, "cache_key_pattern": "quakes:*"}
        return None
    return None


def _credential_mode(spec: ConnectorManifest, creds: list[dict[str, Any]]) -> str:
    """none | ok | fallback | key — for HUD creds column."""
    if not creds:
        return "none"
    if all(c.get("configured") for c in creds):
        return "ok"
    if spec.tier == "optional" or any(c.get("tier") == "optional" for c in creds):
        return "fallback"
    return "key"


def ingest_mapping_report() -> dict[str, Any]:
    """Link YAML ingest mappings to catalog entries; list orphans."""
    try:
        from ingest.mapping_runner import list_mappings

        yaml_names = list_mappings()
    except Exception:
        yaml_names = []
    linked: list[dict[str, str]] = []
    for spec in CONNECTOR_CATALOG.values():
        if spec.ingest_mapping:
            linked.append({"connector_id": spec.id, "mapping": spec.ingest_mapping})
    mapped = {row["mapping"] for row in linked}
    unmapped = [m for m in yaml_names if m not in mapped]
    return {"linked": linked, "unmapped": unmapped, "yaml_total": len(yaml_names)}


def connector_runtime_row(
    spec: ConnectorManifest, cache: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    creds = _credentials_status(spec.credential_ids)
    cache_hit = _match_cache(spec, cache)
    row = spec.to_dict()
    row["credentials"] = creds
    row["credentials_mode"] = _credential_mode(spec, creds)
    row["credentials_ready"] = row["credentials_mode"] in ("none", "ok", "fallback")
    row["cache"] = cache_hit
    return row


def connectors_snapshot(*, include_unlisted: bool = True) -> dict[str, Any]:
    cache = _read_feed_cache_keys()
    catalog_keys = {
        spec.cache_key for spec in CONNECTOR_CATALOG.values() if spec.cache_key
    }
    pattern_prefixes = ("weather:", "quakes:")

    connectors = [
        connector_runtime_row(spec, cache)
        for spec in sorted(CONNECTOR_CATALOG.values(), key=lambda s: s.id)
    ]

    unlisted: list[dict[str, Any]] = []
    if include_unlisted:
        for key, meta in sorted(cache.items()):
            if key in catalog_keys:
                continue
            if any(key.startswith(p) for p in pattern_prefixes):
                if "weather" in catalog_keys or "quakes:day" in catalog_keys:
                    continue
            unlisted.append(
                {
                    "cache_key": key,
                    "ttl_sec": feed_ttl_sec(key),
                    **{k: v for k, v in meta.items() if k != "cache_key"},
                }
            )

    try:
        from credentials.registry import providers_status

        cred_summary = providers_status()
        configured_n = cred_summary.get("configured", 0)
    except Exception:
        configured_n = 0

    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "operator_region": _cfg().operator_region,
        "count": len(connectors),
        "credentials_configured": configured_n,
        "connectors": connectors,
        "unlisted_cache_keys": unlisted,
        "ingest_mappings": ingest_mapping_report(),
    }


def export_manifest(*, include_runtime: bool = False) -> dict[str, Any]:
    """Static catalog export; optional runtime cache overlay."""
    if not include_runtime:
        return {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "operator_region": _cfg().operator_region,
            "connectors": [
                spec.to_dict()
                for spec in sorted(CONNECTOR_CATALOG.values(), key=lambda s: s.id)
            ],
        }
    snap = connectors_snapshot()
    return {
        "version": 1,
        "generated_at": snap["time"],
        "operator_region": snap["operator_region"],
        "connectors": snap["connectors"],
        "unlisted_cache_keys": snap["unlisted_cache_keys"],
    }


def export_manifest_yaml(*, include_runtime: bool = False) -> str:
    import yaml

    return yaml.safe_dump(
        export_manifest(include_runtime=include_runtime),
        sort_keys=False,
        allow_unicode=True,
    )


def export_manifest_json(*, include_runtime: bool = False, indent: int = 2) -> str:
    return json.dumps(
        export_manifest(include_runtime=include_runtime),
        indent=indent,
        ensure_ascii=False,
    )


def catalog_ids() -> list[str]:
    return sorted(CONNECTOR_CATALOG.keys())
