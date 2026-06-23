"""Provider catalog and configuration status (never exposes secret values)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_PLACEHOLDER_FRAGMENTS = (
    "your-key",
    "your_key",
    "your-",
    "your_",
    "sk-...",
    "gsk_...",
    "sk-ant-...",
    "sk-or-...",
    "changeme",
    "replace-me",
    "example",
    "xxx",
)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    category: str
    tier: str  # free | optional | required
    env_vars: tuple[str, ...]
    feeds: tuple[str, ...]
    docs_url: str
    license_note: str
    usage_policy: str
    geo_coverage: tuple[str, ...]
    notes: str = ""
    env_mode: str = "all"  # all = every var required; any = at least one

    def configured(self) -> bool:
        if not self.env_vars:
            return True
        ready = [_env_ready(v) for v in self.env_vars]
        if self.env_mode == "any":
            return any(ready)
        if len(self.env_vars) == 1:
            return ready[0]
        return all(ready)


def _env_ready(name: str) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return False
    low = raw.lower()
    return not any(p in low for p in _PLACEHOLDER_FRAGMENTS)


def get_env(provider_id: str, var: str | None = None) -> str:
    """Return env value for a provider (empty string if missing)."""
    p = PROVIDERS.get(provider_id)
    if not p:
        return os.getenv(var or "", "").strip()
    if var:
        return os.getenv(var, "").strip()
    if len(p.env_vars) == 1:
        return os.getenv(p.env_vars[0], "").strip()
    return ""


def is_configured(provider_id: str) -> bool:
    p = PROVIDERS.get(provider_id)
    return p.configured() if p else False


def provider_status(provider_id: str) -> dict[str, Any] | None:
    p = PROVIDERS.get(provider_id)
    if not p:
        return None
    missing = [v for v in p.env_vars if not _env_ready(v)]
    if p.env_mode == "any" and p.configured():
        missing = []
    return {
        "id": p.id,
        "name": p.name,
        "category": p.category,
        "tier": p.tier,
        "configured": p.configured(),
        "env_vars": list(p.env_vars),
        "missing_env": missing,
        "feeds": list(p.feeds),
        "docs_url": p.docs_url,
        "license_note": p.license_note,
        "usage_policy": p.usage_policy,
        "geo_coverage": list(p.geo_coverage),
        "notes": p.notes or None,
    }


def providers_status(*, category: str | None = None) -> dict[str, Any]:
    items = []
    for pid in sorted(PROVIDERS):
        p = PROVIDERS[pid]
        if category and p.category != category:
            continue
        items.append(provider_status(pid))
    configured_n = sum(1 for i in items if i and i["configured"])
    optional_n = sum(1 for i in items if i and i["tier"] == "optional")
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "usage_policy_default": "private_research",
        "operator_region": os.getenv("WORLDBASE_OPERATOR_REGION", "thailand").strip().lower(),
        "count": len(items),
        "configured": configured_n,
        "optional_total": optional_n,
        "providers": items,
    }


def provider_for_feed(feed_key: str) -> str | None:
    return FEED_PROVIDER_MAP.get(feed_key)


# ---------------------------------------------------------------------------
# Catalog — extend when adding bridges
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, Provider] = {
    "cesium_ion": Provider(
        id="cesium_ion",
        name="Cesium Ion",
        category="imagery",
        tier="required",
        env_vars=("VITE_CESIUM_ION_TOKEN",),
        feeds=(),
        docs_url="https://ion.cesium.com/tokens",
        license_note="Free tier; token in client bundle.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="Frontend .env only.",
    ),
    "windy_point": Provider(
        id="windy_point",
        name="Windy Point Forecast",
        category="weather",
        tier="optional",
        env_vars=("WINDY_POINT_API_KEY",),
        feeds=("weather", "windy_point", "windy_grid"),
        docs_url="https://api.windy.com",
        license_note="Windy API Terms.",
        usage_policy="private_research",
        geo_coverage=("global", "local", "regional"),
        notes="Falls back to Open-Meteo when missing.",
    ),
    "windy_map": Provider(
        id="windy_map",
        name="Windy Map Forecast",
        category="weather",
        tier="optional",
        env_vars=("WINDY_MAP_API_KEY",),
        feeds=("windy_map",),
        docs_url="https://api.windy.com",
        license_note="Windy API Terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "windy_webcam": Provider(
        id="windy_webcam",
        name="Windy Webcams v3",
        category="cams",
        tier="optional",
        env_vars=("WINDY_WEBCAM_API_KEY",),
        feeds=("webcams",),
        docs_url="https://api.windy.com/webcams/docs",
        license_note="Windy API Terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="YouTube static cams work without key.",
    ),
    "firms": Provider(
        id="firms",
        name="NASA FIRMS",
        category="geo",
        tier="optional",
        env_vars=("FIRMS_MAP_KEY",),
        feeds=("wildfires",),
        docs_url="https://firms.modaps.eosdis.nasa.gov/api/map_key",
        license_note="NASA open data.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="EONET wildfire fallback without key.",
    ),
    "cloudflare_radar": Provider(
        id="cloudflare_radar",
        name="Cloudflare Radar",
        category="network",
        tier="optional",
        env_vars=("CLOUDFLARE_API_TOKEN",),
        feeds=("outages",),
        docs_url="https://developers.cloudflare.com/radar/",
        license_note="Cloudflare API Terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="IODA outages without token.",
    ),
    "opensky": Provider(
        id="opensky",
        name="OpenSky Network OAuth",
        category="aviation",
        tier="optional",
        env_vars=("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"),
        feeds=("aircraft",),
        docs_url="https://opensky-network.org/my-opensky/account",
        license_note="OpenSky terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="adsb.fi / adsb.lol fallback.",
    ),
    "entsoe": Provider(
        id="entsoe",
        name="ENTSO-E Transparency",
        category="energy",
        tier="optional",
        env_vars=("ENTSOE_SECURITY_TOKEN",),
        feeds=("eu_energy",),
        docs_url="https://transparency.entsoe.eu",
        license_note="ENTSO-E terms.",
        usage_policy="private_research",
        geo_coverage=("regional",),
    ),
    "reliefweb": Provider(
        id="reliefweb",
        name="ReliefWeb v2",
        category="alerts",
        tier="optional",
        env_vars=("RELIEFWEB_APPNAME",),
        feeds=("geopolitics",),
        docs_url="https://apidoc.reliefweb.int/parameters#appname",
        license_note="ReliefWeb API terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="GDACS always on without key.",
    ),
    "blitzortung": Provider(
        id="blitzortung",
        name="Blitzortung",
        category="geo",
        tier="optional",
        env_vars=("BLITZORTUNG_USER", "BLITZORTUNG_PASSWORD"),
        feeds=("lightning",),
        docs_url="https://www.blitzortung.org",
        license_note="Station operator account.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "ais_maritime": Provider(
        id="ais_maritime",
        name="AIS Hub / MyShipTracking / AISstream",
        category="maritime",
        tier="optional",
        env_vars=("AISHUB_API_KEY", "AISSTREAM_API_KEY", "MYSHIPTRACKING_API_KEY"),
        env_mode="any",
        feeds=("maritime",),
        docs_url="https://aisstream.io/authenticate",
        license_note="Provider terms.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="Any one key enables live maritime; AISstream recommended for Thailand corridor.",
    ),
    "newsdata": Provider(
        id="newsdata",
        name="NewsData.io",
        category="intel",
        tier="optional",
        env_vars=("NEWSDATA_API_KEY",),
        feeds=("newsdata",),
        docs_url="https://newsdata.io/documentation",
        license_note="NewsData.io API terms.",
        usage_policy="private_research",
        geo_coverage=("global", "local", "regional"),
        notes="Complements GDELT; free tier article delay applies.",
    ),
    "opensanctions_api": Provider(
        id="opensanctions_api",
        name="OpenSanctions hosted API",
        category="intel",
        tier="optional",
        env_vars=("OPENSANCTIONS_API_KEY",),
        feeds=("sanctions",),
        docs_url="https://www.opensanctions.org/docs/api/",
        license_note="OpenSanctions license.",
        usage_policy="private_research",
        geo_coverage=("global",),
        notes="Local CSV default; no key required.",
    ),
    "lta_datamall": Provider(
        id="lta_datamall",
        name="LTA DataMall (Singapore)",
        category="traffic",
        tier="optional",
        env_vars=("LTA_DATAMALL_ACCOUNT_KEY",),
        feeds=("traffic_cams_lta",),
        docs_url="https://datamall.lta.gov.sg",
        license_note="Singapore Open Data Licence.",
        usage_policy="private_research",
        geo_coverage=("regional",),
        notes="Free registration. data.gov.sg v1 works without key.",
    ),
    "itic_thailand": Provider(
        id="itic_thailand",
        name="iTIC Thailand Traffic Cameras",
        category="traffic",
        tier="optional",
        env_vars=("ITIC_API_TOKEN",),
        feeds=("traffic_cams_th",),
        docs_url="https://iticfoundation.org",
        license_note="Application required.",
        usage_policy="private_research",
        geo_coverage=("local",),
        notes="Future connector; archive access via iTIC form.",
    ),
    "ollama": Provider(
        id="ollama",
        name="Ollama (local LLM)",
        category="ai",
        tier="free",
        env_vars=(),
        feeds=("briefing", "chat", "rag"),
        docs_url="https://ollama.com",
        license_note="Local inference.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "openai": Provider(
        id="openai",
        name="OpenAI",
        category="ai",
        tier="optional",
        env_vars=("OPENAI_API_KEY",),
        feeds=("chat",),
        docs_url="https://platform.openai.com",
        license_note="Paid API.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "anthropic": Provider(
        id="anthropic",
        name="Anthropic",
        category="ai",
        tier="optional",
        env_vars=("ANTHROPIC_API_KEY",),
        feeds=("chat",),
        docs_url="https://console.anthropic.com",
        license_note="Paid API.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "groq": Provider(
        id="groq",
        name="Groq",
        category="ai",
        tier="optional",
        env_vars=("GROQ_API_KEY",),
        feeds=("chat",),
        docs_url="https://console.groq.com",
        license_note="Freemium API.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "openrouter": Provider(
        id="openrouter",
        name="OpenRouter",
        category="ai",
        tier="optional",
        env_vars=("OPENROUTER_API_KEY",),
        feeds=("chat",),
        docs_url="https://openrouter.ai",
        license_note="Paid/freemium API.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
    "node_ingest": Provider(
        id="node_ingest",
        name="Pi node ingest token",
        category="edge",
        tier="optional",
        env_vars=("NODE_INGEST_TOKEN",),
        feeds=("nodes",),
        docs_url="https://github.com/worldbase/offgrid-raspi",
        license_note="Local HMAC secret.",
        usage_policy="private_research",
        geo_coverage=("local",),
        notes="scripts/setup-node-security.ps1",
    ),
    "worldbase_api": Provider(
        id="worldbase_api",
        name="WorldBase API key",
        category="security",
        tier="optional",
        env_vars=("WORLDBASE_API_KEY",),
        feeds=("osint", "briefing_generate"),
        docs_url="docs/SECURITY.md",
        license_note="Local operator secret.",
        usage_policy="private_research",
        geo_coverage=("global",),
    ),
}

FEED_PROVIDER_MAP: dict[str, str] = {
    "webcams": "windy_webcam",
    "wildfires": "firms",
    "outages": "cloudflare_radar",
    "aircraft": "opensky",
    "geopolitics": "reliefweb",
    "lightning": "blitzortung",
    "maritime": "ais_maritime",
    "newsdata": "newsdata",
    "traffic_cams": "data_gov_sg",
    "traffic_cams_regional": "data_gov_sg",
    "traffic_cams_global": "opentrafficcammap",
}

# Free providers not in PROVIDERS dict (no env vars)
FEED_PROVIDER_MAP.setdefault("weather", "windy_point")

# Register implicit free provider for Singapore traffic (no key)
PROVIDERS["data_gov_sg"] = Provider(
    id="data_gov_sg",
    name="data.gov.sg Traffic Images",
    category="traffic",
    tier="free",
    env_vars=(),
    feeds=("traffic_cams_regional",),
    docs_url="https://data.gov.sg/collections/354/view",
    license_note="Singapore Open Data Licence.",
    usage_policy="private_research",
    geo_coverage=("regional",),
    notes="ASEAN gateway; no API key.",
)

PROVIDERS["opentrafficcammap"] = Provider(
    id="opentrafficcammap",
    name="OpenTrafficCamMap",
    category="traffic",
    tier="free",
    env_vars=(),
    feeds=("traffic_cams_global",),
    docs_url="https://github.com/AidanWelch/OpenTrafficCamMap",
    license_note="Crowdsourced; verify per stream.",
    usage_policy="private_research",
    geo_coverage=("global",),
    notes="Currently USA.json in upstream repo.",
)
