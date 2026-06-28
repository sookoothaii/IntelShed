"""Schema creation and index management for the FtM DuckDB store.

All DDL lives here so connection code (``ftm_connection``) stays clean and
index drift workarounds (DuckDB 1.5.x) are isolated.
"""

from __future__ import annotations

import os

import duckdb

from ftm_connection import _is_invalidated_error


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _create_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id          VARCHAR PRIMARY KEY,
            schema      VARCHAR NOT NULL,
            caption     VARCHAR,
            properties  VARCHAR,
            datasets    VARCHAR,
            lat         DOUBLE,
            lon         DOUBLE,
            first_seen  VARCHAR,
            last_seen   VARCHAR
        );
        CREATE TABLE IF NOT EXISTS statements (
            entity_id   VARCHAR NOT NULL,
            prop        VARCHAR NOT NULL,
            value       VARCHAR NOT NULL,
            dataset     VARCHAR NOT NULL,
            seen_at     VARCHAR,
            lang        VARCHAR,
            UNIQUE (entity_id, prop, value, dataset)
        );
        CREATE TABLE IF NOT EXISTS edges (
            source_id   VARCHAR NOT NULL,
            target_id   VARCHAR NOT NULL,
            kind        VARCHAR NOT NULL,
            properties  VARCHAR,
            confidence  DOUBLE,
            dataset     VARCHAR NOT NULL,
            seen_at     VARCHAR,
            UNIQUE (source_id, target_id, kind, dataset)
        );
        -- idx_entities_schema intentionally NOT created: DuckDB 1.5.x ART index
        -- drift bug (duckdb/duckdb#21394) causes FATAL on DELETE. The schema
        -- column is low-cardinality; columnar scan on 49k rows is <1ms.
        DROP INDEX IF EXISTS idx_entities_schema;
        CREATE INDEX IF NOT EXISTS idx_stmt_entity ON statements(entity_id);
        CREATE TABLE IF NOT EXISTS resolution_labels (
            pair_id             VARCHAR PRIMARY KEY,
            source_id           VARCHAR NOT NULL,
            target_id           VARCHAR NOT NULL,
            schema              VARCHAR,
            confidence          DOUBLE,
            confirmed           BOOLEAN,
            labeled_at          VARCHAR,
            model_version       VARCHAR,
            confidence_timestamp VARCHAR
        );
        """
    )
    _migrate_statements_schema(con)
    _migrate_resolution_labels_schema(con)
    _ensure_edge_indexes(con)
    # Drop any R-Tree index from a previous run (DuckDB 1.5.x bug #769)
    _drop_rtree_index_if_present(con)
    _ensure_entity_geo_indexes(con)


def _drop_rtree_index_if_present(con: duckdb.DuckDBPyConnection) -> None:
    """Drop R-Tree index if it exists from a previous run.

    DuckDB 1.5.x has a FATAL bug (duckdb-spatial #769) where the R-Tree index
    causes "flat vector" internal errors on writes, invalidating the entire
    connection. This must be called before _ensure_entity_geo_indexes to
    clean up any index created by a prior version of this code.
    """
    try:
        con.execute("DROP INDEX IF EXISTS idx_entities_geom")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# P5 — FtM 4.0 StatementEntity schema migration
# ---------------------------------------------------------------------------

_STMT_NEW_COLUMNS: list[tuple[str, str]] = [
    ("stmt_id", "VARCHAR"),
    ("canonical_id", "VARCHAR"),
    ("schema", "VARCHAR"),
    ("original_value", "VARCHAR"),
    ("external", "BOOLEAN DEFAULT FALSE"),
    ("first_seen", "VARCHAR"),
    ("last_seen", "VARCHAR"),
    ("origin", "VARCHAR"),
]


def _migrate_statements_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Add FtM 4.0 StatementEntity columns to the statements table (idempotent).

    The original statements table has: entity_id, prop, value, dataset, seen_at, lang.
    P5 adds: stmt_id, canonical_id, schema, original_value, external,
    first_seen, last_seen, origin.
    """
    try:
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'statements'"
            ).fetchall()
        }
    except Exception:
        cols = set()

    for col_name, col_type in _STMT_NEW_COLUMNS:
        if col_name not in cols:
            try:
                con.execute(f"ALTER TABLE statements ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_stmt_dataset ON statements(dataset)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_stmt_entity_prop ON statements(entity_id, prop)"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Edge indexes
# ---------------------------------------------------------------------------


def _ensure_edge_indexes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        """
    )


def _ensure_entity_geo_indexes(con: duckdb.DuckDBPyConnection) -> None:
    """Indexes for bbox + last_seen seed queries in intel_subgraph.

    When the DuckDB spatial extension is available, adds a GEOMETRY column
    (``geom``) backed by an R-Tree index for ~100x faster spatial predicate
    queries (ST_Within / ST_Intersects) compared to lat/lon BETWEEN scans.
    Falls back to the legacy compound index when spatial is unavailable.
    """
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_lat_lon ON entities(lat, lon)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen)"
        )
    except Exception:
        pass
    _ensure_spatial_geom_index(con)


def _ensure_spatial_geom_index(con: duckdb.DuckDBPyConnection) -> None:
    """Add ``geom GEOMETRY`` column when spatial extension is loaded.

    .. note::
        The R-Tree index (``USING RTREE``) is **not** created on DuckDB 1.5.x
        due to a FATAL "flat vector" bug (duckdb-spatial #769) that
        invalidates the entire DB connection on writes. The ``geom`` column
        is still added and populated for future use when the bug is fixed.
        Set ``WORLDBASE_DUCKDB_RTREE=1`` to force-enable the index.
    """
    from ftm_connection import spatial_available

    if not spatial_available():
        return

    # Allow explicit opt-in for testing / future DuckDB versions
    force_rtree = os.environ.get("WORLDBASE_DUCKDB_RTREE", "0") == "1"
    if force_rtree:
        _create_rtree_index(con)
        return

    # Only add geom column, skip R-Tree index (DuckDB 1.5.x bug)
    try:
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'entities'"
            ).fetchall()
        }
    except Exception:
        return

    if "geom" not in cols:
        try:
            con.execute("ALTER TABLE entities ADD COLUMN geom GEOMETRY")
        except Exception:
            return
        try:
            con.execute(
                "UPDATE entities SET geom = ST_MakePoint(lon, lat) "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL AND geom IS NULL"
            )
        except Exception:
            pass


def _create_rtree_index(con: duckdb.DuckDBPyConnection) -> None:
    """Create R-Tree index on geom column. Only called when explicitly enabled."""
    try:
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'entities'"
            ).fetchall()
        }
    except Exception:
        return

    if "geom" not in cols:
        try:
            con.execute("ALTER TABLE entities ADD COLUMN geom GEOMETRY")
        except Exception:
            return
        try:
            con.execute(
                "UPDATE entities SET geom = ST_MakePoint(lon, lat) "
                "WHERE lat IS NOT NULL AND lon IS NOT NULL AND geom IS NULL"
            )
        except Exception:
            pass

    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_geom ON entities USING RTREE(geom)"
        )
    except Exception:
        pass


def _drop_edge_indexes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP INDEX IF EXISTS idx_edges_source")
    con.execute("DROP INDEX IF EXISTS idx_edges_target")


# ---------------------------------------------------------------------------
# Entity schema index (DuckDB 1.5.x index drift workaround)
# ---------------------------------------------------------------------------


def _drop_entity_schema_index(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP INDEX IF EXISTS idx_entities_schema")


# ---------------------------------------------------------------------------
# Resolution labels schema migration — model_version + confidence_timestamp
# ---------------------------------------------------------------------------

_RESOLUTION_LABEL_NEW_COLUMNS: list[tuple[str, str]] = [
    ("model_version", "VARCHAR"),
    ("confidence_timestamp", "VARCHAR"),
]


def _migrate_resolution_labels_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Add model_version and confidence_timestamp columns to resolution_labels.

    Idempotent: checks information_schema before ALTER TABLE.
    Fail-soft: catches per-column errors.
    """
    try:
        cols = {
            r[0]
            for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'resolution_labels'"
            ).fetchall()
        }
    except Exception:
        cols = set()

    for col_name, col_type in _RESOLUTION_LABEL_NEW_COLUMNS:
        if col_name not in cols:
            try:
                con.execute(
                    f"ALTER TABLE resolution_labels ADD COLUMN {col_name} {col_type}"
                )
            except Exception:
                pass


def _ensure_entity_schema_index(con: duckdb.DuckDBPyConnection) -> None:
    """No-op: idx_entities_schema was removed due to DuckDB 1.5.x index drift.

    Kept for backward compatibility with callers in ftm_query.py.
    """
    pass


def _is_index_delete_error(exc: BaseException) -> bool:
    return "delete all rows from index" in str(exc).lower()


def _delete_entity_rows(con: duckdb.DuckDBPyConnection, entity_id: str) -> None:
    """Remove entity + statements.

    Defensive path: only drop/recreate the schema index if DuckDB raises the
    1.5.x "delete all rows from index" drift error. The happy path avoids the
    DDL overhead on every update.
    """
    con.execute("DELETE FROM statements WHERE entity_id = ?", [entity_id])
    try:
        con.execute("DELETE FROM entities WHERE id = ?", [entity_id])
    except Exception as exc:
        if not _is_index_delete_error(exc) and not _is_invalidated_error(exc):
            raise
        _drop_entity_schema_index(con)
        con.execute("DELETE FROM statements WHERE entity_id = ?", [entity_id])
        try:
            con.execute("DELETE FROM entities WHERE id = ?", [entity_id])
        except Exception as exc2:
            if not _is_index_delete_error(exc2) and not _is_invalidated_error(exc2):
                raise
            con.execute(
                """
                CREATE OR REPLACE TEMP TABLE _ftm_entities_keep AS
                SELECT * FROM entities WHERE id != ?
                """,
                [entity_id],
            )
            con.execute("DELETE FROM entities")
            con.execute("INSERT INTO entities SELECT * FROM _ftm_entities_keep")
            con.execute("DROP TABLE IF EXISTS _ftm_entities_keep")
        _ensure_entity_schema_index(con)


def _repair_pk_index_drift(con: duckdb.DuckDBPyConnection) -> None:
    """One-time repair: recreate entities table to fix DuckDB 1.5.x PK index drift.

    DuckDB 1.5.x has a bug where the internal PK index drifts after many
    DELETE+INSERT cycles, causing FATAL errors and severe latency degradation.
    The PK index cannot be dropped directly, so we recreate the table.

    Fast (~100ms for 49k rows), runs once at startup.
    """
    import logging

    log = logging.getLogger("ftm_schema")
    try:
        con.execute("BEGIN TRANSACTION")
        con.execute(
            "CREATE OR REPLACE TEMP TABLE _entities_repair AS SELECT * FROM entities"
        )
        con.execute("DROP TABLE entities")
        con.execute(
            """
            CREATE TABLE entities (
                id          VARCHAR PRIMARY KEY,
                schema      VARCHAR NOT NULL,
                caption     VARCHAR,
                properties  VARCHAR,
                datasets    VARCHAR,
                lat         DOUBLE,
                lon         DOUBLE,
                first_seen  VARCHAR,
                last_seen   VARCHAR
            )
            """
        )
        con.execute("INSERT INTO entities SELECT * FROM _entities_repair")
        con.execute("DROP TABLE _entities_repair")
        con.execute("COMMIT")
        # Re-add geom column + R-Tree index after table recreation
        _ensure_spatial_geom_index(con)
        log.info("pk_index_drift_repaired", entities="recreated")
    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        log.warning("pk_index_drift_repair_skipped", error=str(exc)[:200])
