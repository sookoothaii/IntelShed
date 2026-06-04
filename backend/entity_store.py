"""Lightweight entity graph — links feeds, OSINT, and situations by stable IDs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

DB_PATH: str | None = None


def set_db_path(path: str) -> None:
    global DB_PATH
    DB_PATH = path


def _conn():
    if not DB_PATH:
        raise RuntimeError("entity_store DB_PATH not set")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_entity_db():
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT,
                lat REAL,
                lon REAL,
                source_feed TEXT,
                external_id TEXT,
                meta_json TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS entity_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT,
                UNIQUE(from_id, to_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_entity_links_from ON entity_links(from_id);
            CREATE INDEX IF NOT EXISTS idx_entity_links_to ON entity_links(to_id);
        """)
        conn.commit()


def upsert_entity(
    entity_id: str,
    entity_type: str,
    *,
    label: str = "",
    lat: float | None = None,
    lon: float | None = None,
    source_feed: str = "",
    external_id: str = "",
    meta: dict | None = None,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO entities (id, type, label, lat, lon, source_feed, external_id, meta_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                label=excluded.label,
                lat=COALESCE(excluded.lat, entities.lat),
                lon=COALESCE(excluded.lon, entities.lon),
                source_feed=excluded.source_feed,
                external_id=excluded.external_id,
                meta_json=excluded.meta_json,
                updated_at=excluded.updated_at
            """,
            (
                entity_id,
                entity_type,
                label,
                lat,
                lon,
                source_feed,
                external_id,
                json.dumps(meta or {}),
                now,
            ),
        )
        conn.commit()
    return entity_id


def link_entities(from_id: str, to_id: str, relation: str, meta: dict | None = None):
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO entity_links (from_id, to_id, relation, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (from_id, to_id, relation, json.dumps(meta or {}), now),
        )
        conn.commit()


def get_entity(entity_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not row:
        return None
    return _row_entity(row)


def get_entity_context(entity_id: str) -> dict:
    entity = get_entity(entity_id)
    if not entity:
        return {"error": "entity not found", "id": entity_id}

    with _conn() as conn:
        links_out = conn.execute(
            "SELECT * FROM entity_links WHERE from_id = ? OR to_id = ?",
            (entity_id, entity_id),
        ).fetchall()

    related_ids = set()
    links = []
    for r in links_out:
        other = r["to_id"] if r["from_id"] == entity_id else r["from_id"]
        if other != entity_id:
            related_ids.add(other)
        links.append({
            "from_id": r["from_id"],
            "to_id": r["to_id"],
            "relation": r["relation"],
            "meta": json.loads(r["meta_json"] or "{}"),
        })

    related = []
    for rid in related_ids:
        e = get_entity(rid)
        if e:
            related.append(e)

    return {
        "entity": entity,
        "links": links,
        "related": related,
    }


def _row_entity(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "label": row["label"],
        "lat": row["lat"],
        "lon": row["lon"],
        "source_feed": row["source_feed"],
        "external_id": row["external_id"],
        "meta": json.loads(row["meta_json"] or "{}"),
        "updated_at": row["updated_at"],
    }


def entity_id_for_pin(tool: str, query: str) -> str:
    return f"osint:{tool}:{query}"


def entity_id_for_aircraft(icao24: str) -> str:
    return f"aircraft:{icao24.lower()}"


def entity_id_for_pegel(uuid: str) -> str:
    return f"pegel:{uuid}"


def entity_id_for_situation(source: str, idx: str) -> str:
    return f"situation:{source}:{idx}"
