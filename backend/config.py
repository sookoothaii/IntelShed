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
    maritime_trajectory_enabled: bool = False
    spatial_reasoning_enabled: bool = False

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
            duckdb_queue_enabled=_truthy(
                os.getenv("WORLDBASE_DUCKDB_QUEUE", "0")
            ),
            admin_flags_enabled=_truthy(
                os.getenv("WORLDBASE_ADMIN_FLAGS", "1")
            ),
            node_pull_delta=_truthy(
                os.getenv("WORLDBASE_NODE_PULL_DELTA", "1")
            ),
            feed_cache_ttl=int(
                os.getenv("WORLDBASE_FEED_CACHE_TTL", "604800")
            ),
            ftm_archive_days=int(
                os.getenv("WORLDBASE_FTM_ARCHIVE_DAYS", "0")
            ),
            rbac_enabled=_truthy(
                os.getenv("WORLDBASE_RBAC", "0")
            ),
            websocket_enabled=_truthy(
                os.getenv("WORLDBASE_WEBSOCKET", "0")
            ),
            prompt_registry_enabled=_truthy(
                os.getenv("WORLDBASE_PROMPT_REGISTRY", "0")
            ),
            lineage_enabled=_truthy(
                os.getenv("WORLDBASE_LINEAGE", "0")
            ),
            ftm_statements_enabled=_truthy(
                os.getenv("WORLDBASE_FTM_STATEMENTS", "0")
            ),
            dynamic_graph_enabled=_truthy(
                os.getenv("WORLDBASE_DYNAMIC_GRAPH", "0")
            ),
            maritime_trajectory_enabled=_truthy(
                os.getenv("WORLDBASE_MARITIME_TRAJECTORY", "0")
            ),
            spatial_reasoning_enabled=_truthy(
                os.getenv("WORLDBASE_SPATIAL_REASONING", "0")
            ),
        )


@lru_cache(maxsize=1)
def get_config() -> WorldBaseConfig:
    """Return the process-wide configuration.

    Cached so repeated lookups are cheap. Tests that need to change the active
    config should clear the cache with ``get_config.cache_clear()`` before
    calling it again.
    """
    return WorldBaseConfig.from_env()
