"""Schema creation and index management for the FtM DuckDB store.

All DDL lives here so connection code (``ftm_connection``) stays clean and
index drift workarounds (DuckDB 1.5.x) are isolated.
"""

from __future__ import annotations

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
        CREATE INDEX IF NOT EXISTS idx_entities_schema ON entities(schema);
        CREATE INDEX IF NOT EXISTS idx_stmt_entity ON statements(entity_id);
        CREATE TABLE IF NOT EXISTS resolution_labels (
            pair_id     VARCHAR PRIMARY KEY,
            source_id   VARCHAR NOT NULL,
            target_id   VARCHAR NOT NULL,
            schema      VARCHAR,
            confidence  DOUBLE,
            confirmed   BOOLEAN,
            labeled_at  VARCHAR
        );
        """
    )
    _ensure_edge_indexes(con)


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


def _drop_edge_indexes(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP INDEX IF EXISTS idx_edges_source")
    con.execute("DROP INDEX IF EXISTS idx_edges_target")


# ---------------------------------------------------------------------------
# Entity schema index (DuckDB 1.5.x index drift workaround)
# ---------------------------------------------------------------------------


def _drop_entity_schema_index(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DROP INDEX IF EXISTS idx_entities_schema")


def _ensure_entity_schema_index(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE INDEX IF NOT EXISTS idx_entities_schema ON entities(schema)")


def _is_index_delete_error(exc: BaseException) -> bool:
    return "delete all rows from index" in str(exc).lower()


def _delete_entity_rows(con: duckdb.DuckDBPyConnection, entity_id: str) -> None:
    """Remove entity + statements; drop schema index first (DuckDB 1.5.x index drift)."""
    _drop_entity_schema_index(con)
    con.execute("DELETE FROM statements WHERE entity_id = ?", [entity_id])
    try:
        con.execute("DELETE FROM entities WHERE id = ?", [entity_id])
    except Exception as exc:
        if not _is_index_delete_error(exc) and not _is_invalidated_error(exc):
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
