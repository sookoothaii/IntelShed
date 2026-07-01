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
    duckdb_queue_enabled: bool = True
    admin_flags_enabled: bool = True
    node_pull_delta: bool = True
    node_conflict_check: bool = True
    feed_cache_ttl: int = 604800
    ftm_archive_days: int = 0
    rbac_enabled: bool = False
    websocket_enabled: bool = False
    prompt_registry_enabled: bool = False
    lineage_enabled: bool = False
    ftm_statements_enabled: bool = False
    agent_orchestrator_enabled: bool = False
    agent_orchestrator_max_workers: int = 8
    agent_orchestrator_phase_timeout: float = 10.0
    agent_orchestrator_circuit_breaker_threshold: int = 3
    agent_orchestrator_circuit_breaker_window: int = 60
    blackboard_enabled: bool = False
    two_pass_enabled: bool = False
    route_ledger_enabled: bool = True
    route_ledger_recompute_n: int = 50
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
    darkweb_tor_rotate_identity: bool = False
    darkweb_tor_control_host: str = "127.0.0.1:9051"
    darkweb_tor_control_password: str = ""
    darkweb_exit_blocklist: str = "CN,RU,IR"
    briefing_darkweb: bool = False
    ransomware_enabled: bool = False
    ransomware_cache_sec: int = 3600
    ransomware_max_results: int = 100
    briefing_ransomware: bool = False
    breach_enabled: bool = False
    breach_cache_sec: int = 3600
    briefing_breach: bool = False
    hibp_api_key: str = ""
    telegram_enabled: bool = False
    telegram_cache_sec: int = 600
    telegram_post_limit: int = 50
    telegram_retention_days: int = 90
    briefing_telegram: bool = False
    identity_osint_enabled: bool = False
    identity_osint_rate_limit_sec: float = 2.0
    identity_osint_max_platforms: int = 50
    identity_osint_cache_sec: int = 86400
    briefing_identity: bool = False
    domain_intel_enabled: bool = True
    briefing_domain: bool = False
    cyber_bridge_enabled: bool = True
    thai_opendata_enabled: bool = False
    briefing_thai: bool = False
    onion_dir_enabled: bool = False
    onion_dir_cache_sec: int = 7200
    briefing_onion_dir: bool = False
    feed_circuit_breaker_enabled: bool = True
    feed_circuit_breaker_failure_threshold: int = 5
    feed_circuit_breaker_reset_timeout_sec: float = 60.0
    feed_circuit_breaker_max_backoff_sec: float = 900.0
    task_watchdog_enabled: bool = True
    task_watchdog_timeout_multiplier: float = 2.5
    auth_audit_enabled: bool = True
    auth_audit_retention_days: int = 90
    secrets_manager_enabled: bool = False
    secrets_provider: str = "env"
    mcp_policy_enabled: bool = False
    mcp_quota_enabled: bool = False
    mcp_conformance_enabled: bool = False
    task_queue: str = "lifespan"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"
    celery_backend_url: str = "http://127.0.0.1:8002"
    smart_router_enabled: bool = False
    cloud_ai_enabled: bool = False
    anomaly_detection_enabled: bool = False
    briefing_anomaly: bool = False
    acled_enabled: bool = False
    briefing_acled: bool = False
    osm_enabled: bool = False
    briefing_osm: bool = False
    weather_forecast_enabled: bool = False
    briefing_weather_forecast: bool = False
    relationship_explorer_enabled: bool = True
    entity_timeline_enabled: bool = True
    credential_manager_enabled: bool = True
    whisper_bridge_enabled: bool = False
    tts_bridge_enabled: bool = False
    react_agent_enabled: bool = False
    react_agent_max_steps: int = 5
    react_agent_step_timeout: float = 15.0
    multi_hypothesis_enabled: bool = False
    multi_hypothesis_num_drafts: int = 3
    temporal_engine_enabled: bool = False
    temporal_engine_max_lag: int = 3
    temporal_engine_min_points: int = 5
    gdpr_enabled: bool = True
    retention_enabled: bool = True
    retention_prune_interval: int = 3600
    classification_enabled: bool = True
    classification_default: str = "UNCLASSIFIED"
    bitemporal_enabled: bool = True
    sar_enabled: bool = False
    push_delivery_enabled: bool = False
    subgraph_ab_enabled: bool = False
    benchmark_enabled: bool = False
    llm_ab_enabled: bool = False
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = 60
    rate_limit_window_sec: float = 60.0
    cache_coalesce_enabled: bool = True

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
            duckdb_queue_enabled=_truthy(os.getenv("WORLDBASE_DUCKDB_QUEUE", "1")),
            admin_flags_enabled=_truthy(os.getenv("WORLDBASE_ADMIN_FLAGS", "1")),
            node_pull_delta=_truthy(os.getenv("WORLDBASE_NODE_PULL_DELTA", "1")),
            node_conflict_check=_truthy(
                os.getenv("WORLDBASE_NODE_CONFLICT_CHECK", "1")
            ),
            feed_cache_ttl=int(os.getenv("WORLDBASE_FEED_CACHE_TTL", "604800")),
            ftm_archive_days=int(os.getenv("WORLDBASE_FTM_ARCHIVE_DAYS", "0")),
            rbac_enabled=_truthy(os.getenv("WORLDBASE_RBAC", "0")),
            websocket_enabled=_truthy(os.getenv("WORLDBASE_WEBSOCKET", "0")),
            prompt_registry_enabled=_truthy(
                os.getenv("WORLDBASE_PROMPT_REGISTRY", "0")
            ),
            lineage_enabled=_truthy(os.getenv("WORLDBASE_LINEAGE", "0")),
            ftm_statements_enabled=_truthy(os.getenv("WORLDBASE_FTM_STATEMENTS", "0")),
            agent_orchestrator_enabled=_truthy(
                os.getenv("WORLDBASE_AGENT_ORCHESTRATOR", "0")
            ),
            agent_orchestrator_max_workers=max(
                1,
                min(
                    64,
                    int(os.getenv("WORLDBASE_AGENT_ORCHESTRATOR_MAX_WORKERS", "8")),
                ),
            ),
            agent_orchestrator_phase_timeout=max(
                1.0,
                float(os.getenv("WORLDBASE_AGENT_ORCHESTRATOR_PHASE_TIMEOUT", "10.0")),
            ),
            agent_orchestrator_circuit_breaker_threshold=max(
                1,
                int(
                    os.getenv(
                        "WORLDBASE_AGENT_ORCHESTRATOR_CIRCUIT_BREAKER_THRESHOLD", "3"
                    )
                ),
            ),
            agent_orchestrator_circuit_breaker_window=max(
                10,
                int(
                    os.getenv(
                        "WORLDBASE_AGENT_ORCHESTRATOR_CIRCUIT_BREAKER_WINDOW", "60"
                    )
                ),
            ),
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
            darkweb_tor_rotate_identity=_truthy(
                os.getenv("WORLDBASE_DARKWEB_TOR_ROTATE_IDENTITY", "0")
            ),
            darkweb_tor_control_host=os.getenv(
                "WORLDBASE_DARKWEB_TOR_CONTROL_HOST", "127.0.0.1:9051"
            ),
            darkweb_tor_control_password=os.getenv(
                "WORLDBASE_DARKWEB_TOR_CONTROL_PASSWORD", ""
            ),
            darkweb_exit_blocklist=os.getenv(
                "WORLDBASE_DARKWEB_EXIT_BLOCKLIST", "CN,RU,IR"
            ),
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
            breach_enabled=_truthy(os.getenv("WORLDBASE_BREACH", "0")),
            breach_cache_sec=int(os.getenv("WORLDBASE_BREACH_CACHE_SEC", "3600")),
            briefing_breach=_truthy(os.getenv("WORLDBASE_BRIEFING_BREACH", "0")),
            hibp_api_key=os.getenv("WORLDBASE_HIBP_API_KEY", ""),
            telegram_enabled=_truthy(os.getenv("WORLDBASE_TELEGRAM", "0")),
            telegram_cache_sec=int(os.getenv("WORLDBASE_TELEGRAM_CACHE_SEC", "600")),
            telegram_post_limit=int(os.getenv("WORLDBASE_TELEGRAM_POST_LIMIT", "50")),
            telegram_retention_days=int(
                os.getenv("WORLDBASE_TELEGRAM_RETENTION_DAYS", "90")
            ),
            briefing_telegram=_truthy(os.getenv("WORLDBASE_BRIEFING_TELEGRAM", "0")),
            identity_osint_enabled=_truthy(os.getenv("WORLDBASE_IDENTITY_OSINT", "0")),
            identity_osint_rate_limit_sec=float(
                os.getenv("WORLDBASE_IDENTITY_OSINT_RATE_LIMIT_SEC", "2")
            ),
            identity_osint_max_platforms=int(
                os.getenv("WORLDBASE_IDENTITY_OSINT_MAX_PLATFORMS", "50")
            ),
            identity_osint_cache_sec=int(
                os.getenv("WORLDBASE_IDENTITY_OSINT_CACHE_SEC", "86400")
            ),
            briefing_identity=_truthy(os.getenv("WORLDBASE_BRIEFING_IDENTITY", "0")),
            domain_intel_enabled=_truthy(os.getenv("WORLDBASE_DOMAIN_INTEL", "1")),
            briefing_domain=_truthy(os.getenv("WORLDBASE_BRIEFING_DOMAIN", "0")),
            cyber_bridge_enabled=_truthy(os.getenv("WORLDBASE_CYBER_BRIDGE", "1")),
            thai_opendata_enabled=_truthy(os.getenv("WORLDBASE_THAI_OPENDATA", "0")),
            briefing_thai=_truthy(os.getenv("WORLDBASE_BRIEFING_THAI", "0")),
            onion_dir_enabled=_truthy(os.getenv("WORLDBASE_ONION_DIR", "0")),
            onion_dir_cache_sec=int(os.getenv("WORLDBASE_ONION_DIR_CACHE_SEC", "7200")),
            briefing_onion_dir=_truthy(os.getenv("WORLDBASE_BRIEFING_ONION_DIR", "0")),
            feed_circuit_breaker_enabled=_truthy(
                os.getenv("WORLDBASE_FEED_CIRCUIT_BREAKER", "1")
            ),
            feed_circuit_breaker_failure_threshold=max(
                1, int(os.getenv("WORLDBASE_FEED_CB_FAILURE_THRESHOLD", "5"))
            ),
            feed_circuit_breaker_reset_timeout_sec=max(
                10.0, float(os.getenv("WORLDBASE_FEED_CB_RESET_TIMEOUT_SEC", "60"))
            ),
            feed_circuit_breaker_max_backoff_sec=max(
                60.0, float(os.getenv("WORLDBASE_FEED_CB_MAX_BACKOFF_SEC", "900"))
            ),
            task_watchdog_enabled=_truthy(os.getenv("WORLDBASE_TASK_WATCHDOG", "1")),
            task_watchdog_timeout_multiplier=max(
                1.0,
                float(os.getenv("WORLDBASE_TASK_WATCHDOG_TIMEOUT_MULTIPLIER", "2.5")),
            ),
            auth_audit_enabled=_truthy(os.getenv("WORLDBASE_AUTH_AUDIT", "1")),
            auth_audit_retention_days=max(
                1, int(os.getenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "90"))
            ),
            secrets_manager_enabled=_truthy(
                os.getenv("WORLDBASE_SECRETS_MANAGER", "0")
            ),
            secrets_provider=os.getenv("WORLDBASE_SECRET_BACKEND", "env")
            .strip()
            .lower(),
            mcp_policy_enabled=_truthy(os.getenv("WORLDBASE_MCP_POLICY", "0")),
            mcp_quota_enabled=_truthy(os.getenv("WORLDBASE_MCP_QUOTA", "0")),
            mcp_conformance_enabled=_truthy(
                os.getenv("WORLDBASE_MCP_CONFORMANCE", "0")
            ),
            blackboard_enabled=_truthy(os.getenv("WORLDBASE_BLACKBOARD", "0")),
            two_pass_enabled=_truthy(os.getenv("WORLDBASE_TWO_PASS", "0")),
            route_ledger_enabled=_truthy(os.getenv("WORLDBASE_ROUTE_LEDGER", "1")),
            route_ledger_recompute_n=max(
                10, int(os.getenv("WORLDBASE_ROUTE_LEDGER_RECOMPUTE_N", "50"))
            ),
            task_queue=os.getenv("WORLDBASE_TASK_QUEUE", "lifespan").strip().lower(),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
            celery_result_backend=os.getenv(
                "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
            ),
            celery_backend_url=os.getenv(
                "WORLDBASE_BACKEND_URL", "http://127.0.0.1:8002"
            ),
            smart_router_enabled=_truthy(os.getenv("WORLDBASE_SMART_ROUTER", "0")),
            cloud_ai_enabled=_truthy(os.getenv("WORLDBASE_CLOUD_AI", "0")),
            anomaly_detection_enabled=_truthy(
                os.getenv("WORLDBASE_ANOMALY_DETECTION", "0")
            ),
            briefing_anomaly=_truthy(os.getenv("WORLDBASE_BRIEFING_ANOMALY", "0")),
            acled_enabled=_truthy(os.getenv("WORLDBASE_ACLED", "0")),
            briefing_acled=_truthy(os.getenv("WORLDBASE_BRIEFING_ACLED", "0")),
            osm_enabled=_truthy(os.getenv("WORLDBASE_OSM", "0")),
            briefing_osm=_truthy(os.getenv("WORLDBASE_BRIEFING_OSM", "0")),
            weather_forecast_enabled=_truthy(
                os.getenv("WORLDBASE_WEATHER_FORECAST", "0")
            ),
            briefing_weather_forecast=_truthy(
                os.getenv("WORLDBASE_BRIEFING_WEATHER_FORECAST", "0")
            ),
            relationship_explorer_enabled=_truthy(
                os.getenv("WORLDBASE_RELATIONSHIP_EXPLORER", "1")
            ),
            entity_timeline_enabled=_truthy(
                os.getenv("WORLDBASE_ENTITY_TIMELINE", "1")
            ),
            credential_manager_enabled=_truthy(
                os.getenv("WORLDBASE_CREDENTIAL_MANAGER", "1")
            ),
            whisper_bridge_enabled=_truthy(os.getenv("WORLDBASE_WHISPER_BRIDGE", "0")),
            tts_bridge_enabled=_truthy(os.getenv("WORLDBASE_TTS_BRIDGE", "0")),
            react_agent_enabled=_truthy(os.getenv("WORLDBASE_REACT_AGENT", "0")),
            react_agent_max_steps=max(
                1, int(os.getenv("WORLDBASE_REACT_AGENT_MAX_STEPS", "5"))
            ),
            react_agent_step_timeout=max(
                1.0, float(os.getenv("WORLDBASE_REACT_AGENT_STEP_TIMEOUT", "15.0"))
            ),
            multi_hypothesis_enabled=_truthy(
                os.getenv("WORLDBASE_MULTI_HYPOTHESIS", "0")
            ),
            multi_hypothesis_num_drafts=max(
                2, int(os.getenv("WORLDBASE_MULTI_HYPOTHESIS_DRAFTS", "3"))
            ),
            temporal_engine_enabled=_truthy(
                os.getenv("WORLDBASE_TEMPORAL_ENGINE", "0")
            ),
            temporal_engine_max_lag=max(
                1, int(os.getenv("WORLDBASE_TEMPORAL_ENGINE_MAX_LAG", "3"))
            ),
            temporal_engine_min_points=max(
                3, int(os.getenv("WORLDBASE_TEMPORAL_ENGINE_MIN_POINTS", "5"))
            ),
            gdpr_enabled=_truthy(os.getenv("WORLDBASE_GDPR", "1")),
            retention_enabled=_truthy(os.getenv("WORLDBASE_RETENTION", "1")),
            retention_prune_interval=max(
                60, int(os.getenv("WORLDBASE_RETENTION_PRUNE_INTERVAL", "3600"))
            ),
            classification_enabled=_truthy(os.getenv("WORLDBASE_CLASSIFICATION", "1")),
            classification_default=os.getenv(
                "WORLDBASE_DEFAULT_CLASSIFICATION", "UNCLASSIFIED"
            )
            .strip()
            .upper(),
            bitemporal_enabled=_truthy(os.getenv("WORLDBASE_BITEMPORAL", "1")),
            sar_enabled=_truthy(os.getenv("WORLDBASE_SAR", "0")),
            push_delivery_enabled=_truthy(os.getenv("WORLDBASE_PUSH", "0")),
            subgraph_ab_enabled=_truthy(os.getenv("WORLDBASE_SUBGRAPH_AB", "0")),
            benchmark_enabled=_truthy(os.getenv("WORLDBASE_BENCHMARK", "0")),
            llm_ab_enabled=_truthy(os.getenv("WORLDBASE_LLM_AB", "0")),
            rate_limit_enabled=_truthy(os.getenv("WORLDBASE_RATE_LIMIT", "1")),
            rate_limit_rpm=max(1, int(os.getenv("WORLDBASE_RATE_LIMIT_RPM", "60"))),
            rate_limit_window_sec=max(
                1.0, float(os.getenv("WORLDBASE_RATE_LIMIT_WINDOW_SEC", "60"))
            ),
            cache_coalesce_enabled=_truthy(os.getenv("WORLDBASE_CACHE_COALESCE", "1")),
        )


def _env_hash() -> int:
    """Hash of all WORLDBASE_* environment variables.

    Used to invalidate the cached config when the environment changes
    (e.g. during tests that patch os.environ). We avoid sorting because the
    order of ``os.environ`` is stable within a process; the hash only needs
    to change when the environment changes, not be deterministic across runs.
    """
    return hash(
        tuple((k, v) for k, v in os.environ.items() if k.startswith("WORLDBASE_"))
    )


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
