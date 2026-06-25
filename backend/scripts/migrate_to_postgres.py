#!/usr/bin/env python3
"""
WorldBase SQLite → PostgreSQL Migration Script

Migrates all tables from SQLite to PostgreSQL with proper type conversions:
- SQLite TEXT timestamps → PostgreSQL TIMESTAMP
- SQLite JSON text → PostgreSQL JSONB
- Proper handling of auto-increment IDs

Usage:
    python backend/scripts/migrate_to_postgres.py \
        --sqlite-path backend/worldbase.db \
        --postgres-url postgresql://user:pass@localhost/worldbase \
        --dry-run  # optional
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone

import sqlite3

# Try to import psycopg2, provide helpful error if missing
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("Error: psycopg2 is required. Install with: pip install psycopg2-binary")
    sys.exit(1)

# Optional: tqdm for progress bars
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Table Definitions (in dependency order)
# ============================================================================

# Tables with no foreign keys first
NO_FK_TABLES = [
    "node_state",
    "feed_cache",
    "aircraft",
    "satellites",
    "entities",
]

# Tables with foreign keys (order matters!)
FK_TABLES = [
    "briefings",
    "sensor_alerts",
    "node_commands",
    "sensor_history",
    "entity_links",
    "rag_chunks",
    "aircraft_trail",
    "river_models",
    "river_scores",
]

# All tables in migration order
MIGRATION_ORDER = NO_FK_TABLES + FK_TABLES


# PostgreSQL CREATE TABLE statements (with proper types)
PG_SCHEMA = {
    "node_state": """
        CREATE TABLE IF NOT EXISTS node_state (
            node_id TEXT PRIMARY KEY,
            name TEXT,
            lat REAL,
            lon REAL,
            updated_at TIMESTAMP,
            payload JSONB
        );
    """,
    "feed_cache": """
        CREATE TABLE IF NOT EXISTS feed_cache (
            key TEXT PRIMARY KEY,
            value_json JSONB,
            cached_at TIMESTAMP,
            ttl_seconds INTEGER DEFAULT 300
        );
        CREATE INDEX IF NOT EXISTS idx_feed_cache_cached_at
            ON feed_cache(cached_at);
        CREATE INDEX IF NOT EXISTS idx_feed_cache_ttl
            ON feed_cache(ttl_seconds);
    """,
    "aircraft": """
        CREATE TABLE IF NOT EXISTS aircraft (
            id SERIAL PRIMARY KEY,
            icao24 TEXT,
            callsign TEXT,
            origin_country TEXT,
            latitude REAL,
            longitude REAL,
            altitude REAL,
            velocity REAL,
            heading REAL,
            recorded_at TIMESTAMP
        );
    """,
    "satellites": """
        CREATE TABLE IF NOT EXISTS satellites (
            id SERIAL PRIMARY KEY,
            name TEXT,
            tle1 TEXT,
            tle2 TEXT,
            recorded_at TIMESTAMP
        );
    """,
    "entities": """
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            label TEXT,
            lat REAL,
            lon REAL,
            source_feed TEXT,
            external_id TEXT,
            meta_json JSONB,
            updated_at TIMESTAMP
        );
    """,
    "briefings": """
        CREATE TABLE IF NOT EXISTS briefings (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP,
            text TEXT,
            sources JSONB
        );
    """,
    "sensor_alerts": """
        CREATE TABLE IF NOT EXISTS sensor_alerts (
            id SERIAL PRIMARY KEY,
            node_id TEXT REFERENCES node_state(node_id),
            sensor TEXT,
            severity TEXT,
            value REAL,
            threshold REAL,
            message TEXT,
            created_at TIMESTAMP
        );
    """,
    "node_commands": """
        CREATE TABLE IF NOT EXISTS node_commands (
            id SERIAL PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES node_state(node_id),
            command TEXT NOT NULL,
            args JSONB,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP,
            acked_at TIMESTAMP,
            result TEXT
        );
    """,
    "sensor_history": """
        CREATE TABLE IF NOT EXISTS sensor_history (
            id SERIAL PRIMARY KEY,
            node_id TEXT NOT NULL REFERENCES node_state(node_id),
            sensor TEXT NOT NULL,
            value REAL,
            recorded_at TIMESTAMP
        );
    """,
    "entity_links": """
        CREATE TABLE IF NOT EXISTS entity_links (
            id SERIAL PRIMARY KEY,
            from_id TEXT NOT NULL REFERENCES entities(id),
            to_id TEXT NOT NULL REFERENCES entities(id),
            relation TEXT NOT NULL,
            meta_json JSONB,
            created_at TIMESTAMP,
            UNIQUE(from_id, to_id, relation)
        );
    """,
    "rag_chunks": """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id SERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT,
            text TEXT NOT NULL,
            embedding_json JSONB NOT NULL,
            meta_json JSONB,
            created_at TIMESTAMP NOT NULL,
            UNIQUE(source, source_id)
        );
    """,
    "aircraft_trail": """
        CREATE TABLE IF NOT EXISTS aircraft_trail (
            id SERIAL PRIMARY KEY,
            icao24 TEXT NOT NULL,
            callsign TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            alt REAL,
            speed REAL,
            heading REAL,
            recorded_at REAL NOT NULL
        );
    """,
    "river_models": """
        CREATE TABLE IF NOT EXISTS river_models (
            feed_key TEXT PRIMARY KEY,
            model_json JSONB NOT NULL,
            sample_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP
        );
    """,
    "river_scores": """
        CREATE TABLE IF NOT EXISTS river_scores (
            id SERIAL PRIMARY KEY,
            feed_key TEXT NOT NULL,
            value REAL NOT NULL,
            score REAL NOT NULL,
            is_anomaly INTEGER NOT NULL,
            recorded_at TIMESTAMP NOT NULL
        );
    """,
}


# ============================================================================
# Data Transformations
# ============================================================================

def parse_timestamp(ts: str | None) -> datetime | None:
    """Parse SQLite timestamp string to datetime object."""
    if not ts:
        return None
    try:
        # Handle ISO format with or without timezone
        ts = ts.replace('Z', '+00:00')
        if '+' in ts or ts.endswith('Z'):
            return datetime.fromisoformat(ts)
        # Assume UTC if no timezone
        return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        try:
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
                try:
                    return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        except Exception:
            pass
        logger.warning(f"Could not parse timestamp: {ts}")
        return None


def transform_json_column(value: str | None) -> dict | list | None:
    """Transform SQLite JSON text to Python object for PostgreSQL JSONB."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.warning(f"Invalid JSON: {value[:100]}...")
        return None


def transform_row(row: sqlite3.Row, table_name: str) -> tuple:
    """Transform a SQLite row to PostgreSQL-compatible format."""
    row_dict = dict(row)
    transformed = {}
    
    for key, value in row_dict.items():
        # Handle JSON columns
        if key in ("payload", "value", "sources", "args", "result",
                   "meta_json", "embedding_json", "model_json"):
            if isinstance(value, str):
                transformed[key] = transform_json_column(value)
            else:
                transformed[key] = value
        # Handle timestamp columns
        elif key in ("updated_at", "created_at", "cached_at", 
                     "recorded_at", "acked_at"):
            if table_name == "aircraft_trail" and key == "recorded_at":
                # aircraft_trail uses REAL (Unix timestamp)
                transformed[key] = value
            else:
                transformed[key] = parse_timestamp(value)
        else:
            transformed[key] = value
    
    return tuple(transformed.values())


# Column mappings (source -> destination, for conflict resolution)
CONFLICT_COLUMNS = {
    "node_state": "node_id",
    "feed_cache": "key",
    "aircraft": "id",
    "satellites": "id",
    "entities": "id",
    "briefings": "id",
    "sensor_alerts": "id",
    "node_commands": "id",
    "sensor_history": "id",
    "entity_links": "id",
    "rag_chunks": "(source, source_id)",
    "aircraft_trail": "id",
    "river_models": "feed_key",
    "river_scores": "id",
}


# ============================================================================
# Database Connections
# ============================================================================

@contextmanager
def sqlite_connection(db_path: str):
    """Context manager for SQLite connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def postgres_connection(dsn: str):
    """Context manager for PostgreSQL connection."""
    conn = psycopg2.connect(dsn)
    try:
        yield conn
    finally:
        conn.close()


# ============================================================================
# Migration Logic
# ============================================================================

def create_postgres_schema(pg_conn, dry_run: bool = False) -> None:
    """Create PostgreSQL schema (tables, indexes)."""
    logger.info("Creating PostgreSQL schema...")
    
    if dry_run:
        logger.info("[DRY RUN] Would create tables: %s", ", ".join(MIGRATION_ORDER))
        return
    
    with pg_conn.cursor() as cur:
        # Create tables
        for table in MIGRATION_ORDER:
            cur.execute(PG_SCHEMA[table])
            logger.debug(f"Created table: {table}")
        
        # Create additional indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sensor_alerts_node ON sensor_alerts(node_id);",
            "CREATE INDEX IF NOT EXISTS idx_sensor_history_node_sensor ON sensor_history(node_id, sensor);",
            "CREATE INDEX IF NOT EXISTS idx_sensor_history_time ON sensor_history(recorded_at);",
            "CREATE INDEX IF NOT EXISTS idx_entity_links_from ON entity_links(from_id);",
            "CREATE INDEX IF NOT EXISTS idx_entity_links_to ON entity_links(to_id);",
            "CREATE INDEX IF NOT EXISTS idx_rag_source ON rag_chunks(source);",
            "CREATE INDEX IF NOT EXISTS idx_trail_icao_time ON aircraft_trail(icao24, recorded_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_trail_time ON aircraft_trail(recorded_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_river_scores_feed ON river_scores(feed_key, recorded_at);",
        ]
        for idx_sql in indexes:
            cur.execute(idx_sql)
        
        pg_conn.commit()
    
    logger.info("PostgreSQL schema created successfully")


def get_sqlite_row_count(sqlite_conn, table: str) -> int:
    """Get row count from SQLite table."""
    cur = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def get_postgres_row_count(pg_conn, table: str) -> int:
    """Get row count from PostgreSQL table."""
    with pg_conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]


def migrate_table(
    sqlite_conn,
    pg_conn,
    table: str,
    batch_size: int = 1000,
    dry_run: bool = False,
    conflict_strategy: str = "update",
) -> dict:
    """Migrate a single table from SQLite to PostgreSQL."""
    
    source_count = get_sqlite_row_count(sqlite_conn, table)
    logger.info(f"Migrating {table}: {source_count:,} rows")
    
    if source_count == 0:
        return {"table": table, "source_count": 0, "dest_count": 0, "migrated": 0}
    
    if dry_run:
        logger.info(f"[DRY RUN] Would migrate {source_count:,} rows to {table}")
        return {"table": table, "source_count": source_count, "dest_count": 0, "migrated": 0}
    
    # Get column names from SQLite
    cur = sqlite_conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cur.fetchall()]
    column_str = ", ".join(columns)
    
    # Build INSERT SQL with conflict handling
    conflict_col = CONFLICT_COLUMNS.get(table, "id")
    if conflict_strategy == "update":
        if table == "rag_chunks":
            # Special case for rag_chunks with composite unique key
            sql = f"""
                INSERT INTO {table} ({column_str})
                VALUES %s
                ON CONFLICT (source, source_id) DO UPDATE SET
                    text = EXCLUDED.text,
                    embedding_json = EXCLUDED.embedding_json,
                    meta_json = EXCLUDED.meta_json,
                    created_at = EXCLUDED.created_at
            """
        elif table == "entity_links":
            # Special case for entity_links with composite unique key
            sql = f"""
                INSERT INTO {table} ({column_str})
                VALUES %s
                ON CONFLICT (from_id, to_id, relation) DO NOTHING
            """
        else:
            # Get primary key column
            pk = conflict_col if conflict_col != "(source, source_id)" and conflict_col != "(from_id, to_id, relation)" else None
            if pk and pk != "id":
                # For tables with non-id primary keys
                set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != pk])
                sql = f"""
                    INSERT INTO {table} ({column_str})
                    VALUES %s
                    ON CONFLICT ({pk}) DO UPDATE SET {set_clause}
                """
            else:
                # Default for id primary keys
                set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != "id"])
                sql = f"""
                    INSERT INTO {table} ({column_str})
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET {set_clause}
                """
    else:  # skip
        sql = f"""
            INSERT INTO {table} ({column_str})
            VALUES %s
            ON CONFLICT DO NOTHING
        """
    
    # Stream rows from SQLite and batch insert to PostgreSQL
    total_migrated = 0
    batch = []
    
    progress_desc = f"Migrating {table}"
    progress_iter = sqlite_conn.execute(f"SELECT * FROM {table}")
    
    if HAS_TQDM:
        progress_iter = tqdm(progress_iter, total=source_count, desc=progress_desc, unit="rows")
    else:
        logger.info(f"Processing {source_count:,} rows...")
    
    with pg_conn.cursor() as pg_cur:
        for row in progress_iter:
            transformed = transform_row(row, table)
            batch.append(transformed)
            
            if len(batch) >= batch_size:
                execute_values(pg_cur, sql, batch, page_size=batch_size)
                total_migrated += len(batch)
                batch = []
        
        # Insert remaining rows
        if batch:
            execute_values(pg_cur, sql, batch, page_size=len(batch))
            total_migrated += len(batch)
        
        pg_conn.commit()
    
    # Verify
    dest_count = get_postgres_row_count(pg_conn, table)
    
    logger.info(f"✓ {table}: migrated {total_migrated:,} rows (source: {source_count:,}, dest: {dest_count:,})")
    
    return {
        "table": table,
        "source_count": source_count,
        "dest_count": dest_count,
        "migrated": total_migrated,
    }


def verify_migration(results: list[dict]) -> bool:
    """Verify migration results."""
    logger.info("\n" + "=" * 60)
    logger.info("Migration Verification")
    logger.info("=" * 60)
    
    all_ok = True
    for result in results:
        table = result["table"]
        source = result["source_count"]
        dest = result["dest_count"]
        
        if source == 0:
            status = "EMPTY"
        elif dest >= source:
            status = "✓ OK"
        else:
            status = "⚠ MISMATCH"
            all_ok = False
        
        logger.info(f"{table:20s} | source: {source:8,} | dest: {dest:8,} | {status}")
    
    logger.info("=" * 60)
    if all_ok:
        logger.info("Verification passed!")
    else:
        logger.warning("Some tables have row count mismatches (this may be expected with ON CONFLICT DO NOTHING)")
    
    return all_ok


def reset_postgres_sequences(pg_conn) -> None:
    """Reset serial sequences after migration."""
    serial_tables = [
        "aircraft", "satellites", "briefings", "sensor_alerts",
        "node_commands", "sensor_history", "entity_links", "rag_chunks",
        "aircraft_trail", "river_scores",
    ]
    
    with pg_conn.cursor() as cur:
        for table in serial_tables:
            cur.execute(f"""
                SELECT setval(pg_get_serial_sequence('{table}', 'id'), 
                             COALESCE((SELECT MAX(id) FROM {table}), 1), true);
            """)
        pg_conn.commit()
    
    logger.info("PostgreSQL sequences reset")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Migrate WorldBase data from SQLite to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Dry run (no actual changes)
    python %(prog)s --sqlite-path backend/worldbase.db --postgres-url postgresql://user:pass@localhost/worldbase --dry-run
    
    # Actual migration
    python %(prog)s --sqlite-path backend/worldbase.db --postgres-url postgresql://user:pass@localhost/worldbase
    
    # Skip on conflict (don't update existing rows)
    python %(prog)s --sqlite-path backend/worldbase.db --postgres-url postgresql://user:pass@localhost/worldbase --on-conflict skip
        """
    )
    parser.add_argument(
        "--sqlite-path",
        required=True,
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--postgres-url",
        required=True,
        help="PostgreSQL connection URL (e.g., postgresql://user:pass@localhost/worldbase)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for inserts (default: 1000)",
    )
    parser.add_argument(
        "--on-conflict",
        choices=["update", "skip"],
        default="update",
        help="Conflict resolution strategy (default: update)",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        choices=MIGRATION_ORDER,
        help="Migrate only specific tables",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip verification step",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine which tables to migrate
    tables_to_migrate = args.tables or MIGRATION_ORDER
    
    logger.info("=" * 60)
    logger.info("WorldBase SQLite → PostgreSQL Migration")
    logger.info("=" * 60)
    logger.info(f"SQLite source: {args.sqlite_path}")
    logger.info(f"PostgreSQL target: {args.postgres_url.replace('://', '://***:***@')}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Conflict strategy: {args.on_conflict}")
    logger.info(f"Tables: {', '.join(tables_to_migrate)}")
    logger.info("=" * 60)
    
    try:
        # Open connections
        with sqlite_connection(args.sqlite_path) as sqlite_conn:
            # Verify SQLite is accessible
            sqlite_conn.execute("SELECT 1")
            logger.info("✓ SQLite connection successful")
            
            with postgres_connection(args.postgres_url) as pg_conn:
                # Verify PostgreSQL is accessible
                with pg_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                logger.info("✓ PostgreSQL connection successful")
                
                # Create schema
                create_postgres_schema(pg_conn, dry_run=args.dry_run)
                
                # Migrate tables
                results = []
                for table in tables_to_migrate:
                    try:
                        result = migrate_table(
                            sqlite_conn,
                            pg_conn,
                            table,
                            batch_size=args.batch_size,
                            dry_run=args.dry_run,
                            conflict_strategy=args.on_conflict,
                        )
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Failed to migrate {table}: {e}")
                        results.append({
                            "table": table,
                            "source_count": 0,
                            "dest_count": 0,
                            "migrated": 0,
                            "error": str(e),
                        })
                        if not args.dry_run:
                            pg_conn.rollback()
                
                # Reset sequences
                if not args.dry_run:
                    reset_postgres_sequences(pg_conn)
                
                # Verify
                if not args.no_verify and not args.dry_run:
                    verify_migration(results)
                
                logger.info("\n" + "=" * 60)
                if args.dry_run:
                    logger.info("Dry run completed. No changes were made.")
                else:
                    total_migrated = sum(r["migrated"] for r in results)
                    logger.info(f"Migration completed! {total_migrated:,} rows migrated.")
                logger.info("=" * 60)
                
                return 0 if not any("error" in r for r in results) else 1
                
    except sqlite3.Error as e:
        logger.error(f"SQLite error: {e}")
        return 1
    except psycopg2.Error as e:
        logger.error(f"PostgreSQL error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
