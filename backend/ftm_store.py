"""FollowTheMoney canonical entity store — compatibility re-export layer.

Split (Phase 3, 2026-06-24) into:
  - ``ftm_connection.py`` — DuckDB connection management + FATAL recovery
  - ``ftm_schema.py``      — schema creation + index drift workarounds
  - ``ftm_query.py``       — CRUD, graph traversal, briefing queries
  - ``ftm_sanctions.py``   — OpenSanctions adapter + legacy schema mapping
  - ``routes/ftm_api.py``  — HTTP router (9 endpoints)

This module re-exports every public symbol so existing ``import ftm_store``
callers (25 modules) continue to work without changes.
"""

from __future__ import annotations

# Connection management
from ftm_connection import (  # noqa: F401
    _CONN,
    _DB_PATH,
    _INIT_ERROR,
    _LOCK,
    _configure_connection,
    _conn,
    _default_db_path,
    _is_invalidated_error,
    _run_with_recovery,
    init_store,
    reset_store,
    run_query,
    set_db_path,
    store_ready,
    store_status,
)

# Schema + index management
from ftm_schema import (  # noqa: F401
    _create_schema,
    _delete_entity_rows,
    _drop_edge_indexes,
    _drop_entity_schema_index,
    _ensure_edge_indexes,
    _ensure_entity_schema_index,
    _is_index_delete_error,
)

# CRUD + graph + briefing queries
from ftm_query import (  # noqa: F401
    _apply_props,
    _first_float,
    _merge_props,
    _now,
    _proxy_with_id,
    _same_as_neighbour_map,
    add_edge,
    count_edges_for_dataset,
    delete_edges_for_dataset,
    entities_for_briefing,
    get_entity,
    get_entity_full,
    graph_overview,
    graph_stats,
    graph_view,
    import_entities,
    import_ndjson,
    list_entities_for_resolution,
    list_entities_recent,
    make_entity,
    stats,
    upsert,
    upsert_legacy,
)

# Sanctions adapter + legacy schema mapping
from ftm_sanctions import (  # noqa: F401
    _LEGACY_SCHEMA,
    _sanctions_csv_path,
    _split_multi,
    ftm_from_sanctions_row,
    import_sanctions_csv,
)

# HTTP router
from routes.ftm_api import router  # noqa: F401
