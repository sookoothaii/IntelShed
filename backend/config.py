"""Centralized, read-only configuration for WorldBase.

This module is the single source of truth for environment-variable defaults.
It is intentionally lightweight (no heavy imports) so it can be imported by
any backend module without side effects.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Self

from pydantic import BaseModel, ConfigDict


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


class WorldBaseConfig(BaseModel):
    """Immutable runtime configuration.

    Defaults are production-safe for a single-operator workstation. Values are
    read from environment variables when ``from_env()`` is called; callers that
    need deterministic settings in tests can instantiate the model directly.
    """

    model_config = ConfigDict(validate_assignment=True, frozen=True)

    feed_ingest_interval: int = 600
    operator_region: str = "thailand"
    feed_ingest_autopilot: bool = True
    entity_resolution_after_feeds: bool = False
    rag_feed_ingest: bool = True
    query_router_enabled: bool = True
    query_router_fallback: str = "vector"
    provenance_enabled: bool = True
    chat_agentic_enabled: bool = False
    chat_agentic_max_rounds: int = 3
    intel_semantic_edges_enabled: bool = True
    intel_sanction_edges_enabled: bool = True
    intel_semantic_max_km: float = 120.0
    intel_semantic_max_entities: int = 120
    intel_event_corr_max_km: float = 500.0
    intel_event_corr_min_words: int = 1
    briefing_intel_enabled: bool = True
    briefing_autopilot: bool = True
    briefing_intel_subgraph_enabled: bool = True
    briefing_intel_exclude_schemas: str = "Airplane,Thing"
    rag_autopilot: bool = True
    intel_subgraph_decay_floor: float = 0.3
    intel_subgraph_communities: bool = False
    intel_edge_decay_days: float = 30.0
    intel_subgraph_hops: int = 2
    intel_subgraph_seed_limit: int = 30
    intel_subgraph_node_limit: int = 80
    briefing_interval: int = 21600
    briefing_lang: str = "en"
    entity_resolution_interval: int = 86400
    entity_resolution_autopilot: bool = False
    entity_resolution_splink_enabled: bool = False
    entity_resolution_pipeline_mode: str = "single"
    duckdb_queue_enabled: bool = False
    admin_flags_enabled: bool = True
    node_pull_delta: bool = True
    feed_cache_ttl: int = 604800
    ftm_archive_days: int = 0
    rbac_enabled: bool = False
    websocket_enabled: bool = False
    prompt_registry_enabled: bool = False
    lineage_enabled: bool = False
    ftm_statements_enabled: bool = False
    dynamic_graph_enabled: bool = False
    dynamic_graph_max_confidence: float = 0.7
    maritime_trajectory_enabled: bool = False
    maritime_trajectory_retention_h: int = 24
    maritime_anomaly_threshold: float = 0.6
    spatial_reasoning_enabled: bool = False
    spatial_near_default_km: float = 25.0
    darkweb_enabled: bool = False
    darkweb_engines: str = "ahmia"
    darkweb_cache_sec: int = 3600
    darkweb_max_results: int = 50
    darkweb_tor_proxy: str = ""
    darkweb_timeout_sec: float = 15.0
    briefing_darkweb: bool = False
    ransomware_enabled: bool = False
    ransomware_cache_sec: int = 3600
    ransomware_max_results: int = 100
    briefing_ransomware: bool = False
    telegram_enabled: bool = False
    telegram_cache_sec: int = 600
    telegram_post_limit: int = 50
    telegram_retention_days: int = 90
    briefing_telegram: bool = False

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            feed_ingest_interval=int(
                os.getenv("WORLDBASE_FEED_INGEST_INTERVAL", "600")
            ),
            operator_region=os.getenv("WORLDBASE_OPERATOR_REGION", "thailand")
            .strip()
            .lower(),
            feed_ingest_autopilot=_truthy(
                os.getenv("WORLDBASE_FEED_INGEST_AUTOPILOT", "1")
            ),
            entity_resolution_after_feeds=_truthy(
                os.getenv("WORLDBASE_ENTITY_RESOLUTION_AFTER_FEEDS", "0")
            ),
            rag_feed_ingest=_truthy(os.getenv("RAG_FEED_INGEST", "1")),
            query_router_enabled=_truthy(os.getenv("WORLDBASE_QUERY_ROUTER", "1")),
            query_router_fallback=os.getenv("WORLDBASE_QUERY_ROUTER_FALLBACK", "vector")
            .strip()
            .lower(),
            provenance_enabled=_truthy(os.getenv("WORLDBASE_PROVENANCE", "1")),
            chat_agentic_enabled=_truthy(os.getenv("WORLDBASE_CHAT_AGENTIC", "0")),
            chat_agentic_max_rounds=int(
                os.getenv("WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS", "3")
            ),
            intel_semantic_edges_enabled=_truthy(
                os.getenv("WORLDBASE_INTEL_SEMANTIC_EDGES", "1")
            ),
            intel_sanction_edges_enabled=_truthy(
                os.getenv("WORLDBASE_INTEL_SANCTION_EDGES", "1")
            ),
            intel_semantic_max_km=float(
                os.getenv("WORLDBASE_INTEL_SEMANTIC_MAX_KM", "120")
            ),
            intel_semantic_max_entities=int(
                os.getenv("WORLDBASE_INTEL_SEMANTIC_MAX_ENTITIES", "120")
            ),
            intel_event_corr_max_km=float(
                os.getenv("WORLDBASE_INTEL_EVENT_CORR_MAX_KM", "500")
            ),
            intel_event_corr_min_words=int(
                os.getenv("WORLDBASE_INTEL_EVENT_CORR_MIN_WORDS", "1")
            ),
            briefing_intel_enabled=_truthy(os.getenv("WORLDBASE_BRIEFING_INTEL", "1")),
            briefing_autopilot=_truthy(os.getenv("WORLDBASE_BRIEFING_AUTOPILOT", "1")),
            briefing_intel_subgraph_enabled=_truthy(
                os.getenv("WORLDBASE_BRIEFING_INTEL_SUBGRAPH", "1")
            ),
            briefing_intel_exclude_schemas=os.getenv(
                "WORLDBASE_BRIEFING_INTEL_EXCLUDE_SCHEMAS", "Airplane,Thing"
            ),
            rag_autopilot=_truthy(os.getenv("WORLDBASE_RAG_AUTOPILOT", "1")),
            intel_subgraph_decay_floor=float(
                os.getenv("WORLDBASE_INTEL_SUBGRAPH_DECAY_FLOOR", "0.3")
            ),
            intel_subgraph_communities=_truthy(
                os.getenv("WORLDBASE_INTEL_SUBGRAPH_COMMUNITIES", "0")
            ),
            intel_edge_decay_days=float(
                os.getenv("WORLDBASE_INTEL_EDGE_DECAY_DAYS", "30")
            ),
            intel_subgraph_hops=int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_HOPS", "2")),
            intel_subgraph_seed_limit=int(
                os.getenv("WORLDBASE_INTEL_SUBGRAPH_SEED_LIMIT", "30")
            ),
            intel_subgraph_node_limit=int(
                os.getenv("WORLDBASE_INTEL_SUBGRAPH_NODE_LIMIT", "80")
            ),
            briefing_interval=int(os.getenv("WORLDBASE_BRIEFING_INTERVAL", "21600")),
            briefing_lang=os.getenv("WORLDBASE_BRIEFING_LANG", "en").strip().lower(),
            entity_resolution_interval=int(
                os.getenv("WORLDBASE_ENTITY_RESOLUTION_INTERVAL", "86400")
            ),
            entity_resolution_autopilot=_truthy(
                os.getenv("WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT", "0")
            ),
            entity_resolution_splink_enabled=_truthy(
                os.getenv("WORLDBASE_ENTITY_RESOLUTION_SPLINK", "0")
            ),
            entity_resolution_pipeline_mode=os.getenv(
                "WORLDBASE_ENTITY_RESOLUTION_PIPELINE", "single"
            )
            .strip()
            .lower(),
            duckdb_queue_enabled=_truthy(os.getenv("WORLDBASE_DUCKDB_QUEUE", "0")),
            admin_flags_enabled=_truthy(os.getenv("WORLDBASE_ADMIN_FLAGS", "1")),
            node_pull_delta=_truthy(os.getenv("WORLDBASE_NODE_PULL_DELTA", "1")),
            feed_cache_ttl=int(os.getenv("WORLDBASE_FEED_CACHE_TTL", "604800")),
            ftm_archive_days=int(os.getenv("WORLDBASE_FTM_ARCHIVE_DAYS", "0")),
            rbac_enabled=_truthy(os.getenv("WORLDBASE_RBAC", "0")),
            websocket_enabled=_truthy(os.getenv("WORLDBASE_WEBSOCKET", "0")),
            prompt_registry_enabled=_truthy(
                os.getenv("WORLDBASE_PROMPT_REGISTRY", "0")
            ),
            lineage_enabled=_truthy(os.getenv("WORLDBASE_LINEAGE", "0")),
            ftm_statements_enabled=_truthy(os.getenv("WORLDBASE_FTM_STATEMENTS", "0")),
            dynamic_graph_enabled=_truthy(os.getenv("WORLDBASE_DYNAMIC_GRAPH", "0")),
            dynamic_graph_max_confidence=float(
                os.getenv("WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE", "0.7")
            ),
            maritime_trajectory_enabled=_truthy(
                os.getenv("WORLDBASE_MARITIME_TRAJECTORY", "0")
            ),
            maritime_trajectory_retention_h=int(
                os.getenv("WORLDBASE_MARITIME_TRAJECTORY_RETENTION_H", "24")
            ),
            maritime_anomaly_threshold=float(
                os.getenv("WORLDBASE_MARITIME_ANOMALY_THRESHOLD", "0.6")
            ),
            spatial_reasoning_enabled=_truthy(
                os.getenv("WORLDBASE_SPATIAL_REASONING", "0")
            ),
            spatial_near_default_km=float(
                os.getenv("WORLDBASE_SPATIAL_NEAR_DEFAULT_KM", "25")
            ),
            darkweb_enabled=_truthy(os.getenv("WORLDBASE_DARKWEB", "0")),
            darkweb_engines=os.getenv("WORLDBASE_DARKWEB_ENGINES", "ahmia"),
            darkweb_cache_sec=int(os.getenv("WORLDBASE_DARKWEB_CACHE_SEC", "3600")),
            darkweb_max_results=int(os.getenv("WORLDBASE_DARKWEB_MAX_RESULTS", "50")),
            darkweb_tor_proxy=os.getenv("WORLDBASE_DARKWEB_TOR_PROXY", ""),
            darkweb_timeout_sec=float(os.getenv("WORLDBASE_DARKWEB_TIMEOUT_SEC", "15")),
            briefing_darkweb=_truthy(os.getenv("WORLDBASE_BRIEFING_DARKWEB", "0")),
            ransomware_enabled=_truthy(os.getenv("WORLDBASE_RANSOMWARE", "0")),
            ransomware_cache_sec=int(
                os.getenv("WORLDBASE_RANSOMWARE_CACHE_SEC", "3600")
            ),
            ransomware_max_results=int(
                os.getenv("WORLDBASE_RANSOMWARE_MAX_RESULTS", "100")
            ),
            briefing_ransomware=_truthy(
                os.getenv("WORLDBASE_BRIEFING_RANSOMWARE", "0")
            ),
            telegram_enabled=_truthy(os.getenv("WORLDBASE_TELEGRAM", "0")),
            telegram_cache_sec=int(os.getenv("WORLDBASE_TELEGRAM_CACHE_SEC", "600")),
            telegram_post_limit=int(os.getenv("WORLDBASE_TELEGRAM_POST_LIMIT", "50")),
            telegram_retention_days=int(
                os.getenv("WORLDBASE_TELEGRAM_RETENTION_DAYS", "90")
            ),
            briefing_telegram=_truthy(os.getenv("WORLDBASE_BRIEFING_TELEGRAM", "0")),
        )


def _env_hash() -> int:
    """Hash of all WORLDBASE_* environment variables.

    Used to invalidate the cached config when the environment changes
    (e.g. during tests that patch os.environ).
    """
    items = sorted((k, v) for k, v in os.environ.items() if k.startswith("WORLDBASE_"))
    return hash(tuple(items))


@lru_cache(maxsize=1)
def _get_config_impl(_env_hash: int) -> WorldBaseConfig:
    return WorldBaseConfig.from_env()


def get_config() -> WorldBaseConfig:
    """Return the process-wide configuration.

    Cached so repeated lookups are cheap. The cache is keyed on a hash of all
    WORLDBASE_* environment variables, so it automatically refreshes when the
    environment changes. Tests may still clear the cache explicitly with
    ``get_config.cache_clear()`` if needed.
    """
    return _get_config_impl(_env_hash())


# Backwards-compatible cache_clear for tests
def _cache_clear() -> None:
    _get_config_impl.cache_clear()


get_config.cache_clear = _cache_clear
