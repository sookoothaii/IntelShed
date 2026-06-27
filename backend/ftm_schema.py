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
    _migrate_statements_schema(con)
    _ensure_edge_indexes(con)
    _ensure_entity_geo_indexes(con)
    _repair_pk_index_drift(con)


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
    """Indexes for bbox + last_seen seed queries in intel_subgraph."""
    try:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_lat_lon ON entities(lat, lon)"
        )
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_last_seen ON entities(last_seen)"
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


def _ensure_entity_schema_index(con: duckdb.DuckDBPyConnection) -> None:
    # Fast path: check metadata before issuing DDL. DuckDB 1.5.x parses/plans the
    # CREATE INDEX statement even with IF NOT EXISTS, which adds ~20-30ms per call.
    row = con.execute(
        "SELECT 1 FROM duckdb_indexes() WHERE index_name = 'idx_entities_schema'"
    ).fetchone()
    if not row:
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_schema ON entities(schema)"
        )


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
        log.info("pk_index_drift_repaired", entities="recreated")
    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        log.warning("pk_index_drift_repair_skipped", error=str(exc)[:200])
