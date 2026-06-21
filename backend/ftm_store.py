"""FollowTheMoney canonical entity store, backed by DuckDB.

This is the spine of WorldBase's intelligence layer (PR 1). Every ingested
datum collapses into a FollowTheMoney (FtM) entity so the project stays
interoperable with the wider open investigative ecosystem (OpenSanctions,
Aleph, ICIJ, Yente, nomenklatura).

Provenance is a first-class citizen, per the WorldBase non-negotiables:

* ``entities``   - one row per FtM entity (merged view), denormalized lat/lon
                   for globe rendering and a roll-up of contributing datasets.
* ``statements`` - one row per (entity, property, value, dataset) so every
                   single fact is traceable to a source + timestamp.
* ``edges``      - relations between entities, each carrying ``confidence`` +
                   ``dataset`` + ``seen_at``.

The store is fail-soft: callers (legacy ``entity_store`` mirror, ingest
pipelines, sanctions adapter) wrap writes so a store error never breaks a feed.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

import duckdb
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from followthemoney import model

# ---------------------------------------------------------------------------
# Connection management (single in-process connection, lock-guarded)
# ---------------------------------------------------------------------------

_DB_PATH: str | None = None
_CONN: duckdb.DuckDBPyConnection | None = None
_LOCK = threading.RLock()
_INIT_ERROR: str | None = None


def _default_db_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "entities.duckdb")


def set_db_path(path: str | None = None) -> None:
    """Configure the DuckDB file path (call before init_store)."""
    global _DB_PATH
    _DB_PATH = path or os.getenv("WORLDBASE_FTM_DB_PATH") or _default_db_path()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> duckdb.DuckDBPyConnection:
    global _CONN, _INIT_ERROR
    if _CONN is not None:
        return _CONN
    if not _DB_PATH:
        set_db_path()
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)  # type: ignore[arg-type]
    try:
        _CONN = duckdb.connect(_DB_PATH)  # type: ignore[arg-type]
        _create_schema(_CONN)
        _INIT_ERROR = None
    except Exception as exc:
        _INIT_ERROR = str(exc)
        raise
    return _CONN


def store_ready() -> bool:
    """True when DuckDB is open in this process."""
    return _CONN is not None


def store_status() -> dict[str, Any]:
    """Compact readiness for /api/health and operator monitors."""
    if _CONN is not None:
        try:
            with _LOCK:
                n = _CONN.execute("SELECT count(*) FROM entities").fetchone()[0]
            return {"ready": True, "entities": int(n), "error": None}
        except Exception as exc:
            return {"ready": False, "entities": 0, "error": str(exc)}
    return {"ready": False, "entities": 0, "error": _INIT_ERROR or "not initialized"}


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
        CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
        CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
        """
    )


def init_store() -> bool:
    """Idempotent: open the connection and ensure the schema exists (fail-soft)."""
    global _INIT_ERROR
    try:
        with _LOCK:
            _conn()
        return True
    except Exception as exc:
        _INIT_ERROR = str(exc)
        print(f"[FTM] store unavailable: {exc}", flush=True)
        return False


def reset_store() -> bool:
    """Close and reopen DuckDB after a fatal/invalidated connection."""
    global _CONN, _INIT_ERROR
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None
        _INIT_ERROR = None
    return init_store()


def _is_invalidated_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "invalidated" in msg or "fatal error" in msg


def run_query(sql: str, params: list[Any] | tuple[Any, ...] | None = None) -> list:
    """Run a read query on the process store connection (same thread as init_store)."""
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            if not store_ready() and not init_store():
                raise RuntimeError(store_status().get("error") or "ftm store unavailable")
            with _LOCK:
                return _conn().execute(sql, list(params or ())).fetchall()
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_invalidated_error(exc):
                reset_store()
                continue
            raise
    if last_exc:
        raise last_exc
    return []


# ---------------------------------------------------------------------------
# FtM proxy helpers
# ---------------------------------------------------------------------------


def _first_float(values: Any) -> float | None:
    if not values:
        return None
    seq = values if isinstance(values, (list, tuple, set)) else [values]
    for v in seq:
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def make_entity(schema: str, id_parts: Any, properties: dict | None = None):
    """Build an FtM entity with a content-derived id (hash of id_parts)."""
    if not model.get(schema):
        schema = "Thing"
    proxy = model.make_entity(schema)
    parts = id_parts if isinstance(id_parts, (list, tuple)) else [id_parts]
    proxy.make_id(*[str(p) for p in parts if p is not None])
    _apply_props(proxy, properties)
    return proxy


def _proxy_with_id(entity_id: str, schema: str, properties: dict | None = None):
    """Build an FtM entity that keeps an externally supplied id (provenance)."""
    if not model.get(schema):
        schema = "Thing"
    proxy = model.make_entity(schema)
    proxy.id = str(entity_id)
    _apply_props(proxy, properties)
    return proxy


def _apply_props(proxy, properties: dict | None) -> None:
    for key, value in (properties or {}).items():
        if value is None:
            continue
        vals = value if isinstance(value, (list, tuple, set)) else [value]
        for item in vals:
            if item is None or item == "":
                continue
            # quiet=True drops props/values invalid for the schema instead of raising
            proxy.add(key, str(item), quiet=True)


def _merge_props(existing: dict, incoming: dict) -> dict:
    merged = {k: list(v) for k, v in (existing or {}).items()}
    for key, values in (incoming or {}).items():
        bucket = merged.setdefault(key, [])
        for v in values:
            if v not in bucket:
                bucket.append(v)
    return merged


# ---------------------------------------------------------------------------
# Core write/read
# ---------------------------------------------------------------------------


def upsert(proxy, dataset: str, *, seen_at: str | None = None,
           lat: float | None = None, lon: float | None = None) -> str | None:
    """Merge an FtM entity into the store and record per-value provenance."""
    eid = proxy.id
    if not eid:
        return None
    seen_at = seen_at or _now()
    incoming = proxy.to_dict().get("properties", {}) or {}
    schema_name = proxy.schema.name
    with _LOCK:
        con = _conn()
        row = con.execute(
            "SELECT properties, datasets, first_seen, lat, lon FROM entities WHERE id = ?",
            [eid],
        ).fetchone()
        if row:
            existing_props = json.loads(row[0] or "{}")
            datasets = set(json.loads(row[1] or "[]"))
            first_seen = row[2] or seen_at
            lat = lat if lat is not None else row[3]
            lon = lon if lon is not None else row[4]
            merged_props = _merge_props(existing_props, incoming)
        else:
            datasets = set()
            first_seen = seen_at
            merged_props = incoming
        datasets.add(dataset)

        merged_proxy = model.get_proxy(
            {"id": eid, "schema": schema_name, "properties": merged_props}
        )
        if lat is None:
            lat = _first_float(merged_props.get("latitude"))
        if lon is None:
            lon = _first_float(merged_props.get("longitude"))

        con.execute(
            """
            INSERT OR REPLACE INTO entities
                (id, schema, caption, properties, datasets, lat, lon, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                eid,
                merged_proxy.schema.name,
                merged_proxy.caption,
                json.dumps(merged_props),
                json.dumps(sorted(datasets)),
                lat,
                lon,
                first_seen,
                seen_at,
            ],
        )
        for prop, values in incoming.items():
            for v in values:
                if v is None or v == "":
                    continue
                con.execute(
                    """
                    INSERT OR IGNORE INTO statements
                        (entity_id, prop, value, dataset, seen_at, lang)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [eid, prop, str(v), dataset, seen_at, None],
                )
    return eid


def upsert_legacy(entity_id: str, entity_type: str, *, label: str | None = None,
                  lat: float | None = None, lon: float | None = None,
                  source_feed: str | None = None, external_id: str | None = None,
                  meta: dict | None = None) -> str | None:
    """Mirror a legacy entity_store node into the FtM graph (best-effort)."""
    schema = _LEGACY_SCHEMA.get((entity_type or "").lower(), "Thing")
    props: dict[str, list[str]] = {}
    if label:
        props["name"] = [str(label)]
    if external_id:
        props["idNumber"] = [str(external_id)]
    if schema in ("Address", "RealEstate"):
        if lat is not None:
            props["latitude"] = [str(lat)]
        if lon is not None:
            props["longitude"] = [str(lon)]
    if meta:
        note = "; ".join(
            f"{k}={v}" for k, v in meta.items() if v not in (None, "", {}, [])
        )
        if note:
            props["notes"] = [note[:1000]]
    proxy = _proxy_with_id(entity_id, schema, props)
    return upsert(proxy, dataset=source_feed or "worldbase", lat=lat, lon=lon)


def add_edge(source_id: str, target_id: str, kind: str, dataset: str = "worldbase",
             *, confidence: float = 1.0, properties: dict | None = None,
             seen_at: str | None = None) -> None:
    if not source_id or not target_id:
        return
    with _LOCK:
        _conn().execute(
            """
            INSERT OR IGNORE INTO edges
                (source_id, target_id, kind, properties, confidence, dataset, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                source_id,
                target_id,
                kind,
                json.dumps(properties or {}),
                float(confidence),
                dataset,
                seen_at or _now(),
            ],
        )


def get_entity(entity_id: str) -> dict | None:
    with _LOCK:
        row = _conn().execute(
            """
            SELECT id, schema, caption, properties, datasets, first_seen, last_seen, lat, lon
            FROM entities WHERE id = ?
            """,
            [entity_id],
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "schema": row[1],
        "caption": row[2],
        "properties": json.loads(row[3] or "{}"),
        "datasets": json.loads(row[4] or "[]"),
        "first_seen": row[5],
        "last_seen": row[6],
        "lat": row[7],
        "lon": row[8],
    }


def get_entity_full(entity_id: str) -> dict | None:
    ent = get_entity(entity_id)
    if not ent:
        return None
    with _LOCK:
        con = _conn()
        stmts = con.execute(
            """
            SELECT prop, value, dataset, seen_at, lang FROM statements
            WHERE entity_id = ? ORDER BY prop, dataset
            """,
            [entity_id],
        ).fetchall()
        edge_rows = con.execute(
            """
            SELECT source_id, target_id, kind, properties, confidence, dataset, seen_at
            FROM edges WHERE source_id = ? OR target_id = ?
            """,
            [entity_id, entity_id],
        ).fetchall()
    ent["statements"] = [
        {"prop": s[0], "value": s[1], "dataset": s[2], "seen_at": s[3], "lang": s[4]}
        for s in stmts
    ]
    edges = []
    neighbour_ids: set[str] = set()
    for e in edge_rows:
        edges.append({
            "source_id": e[0],
            "target_id": e[1],
            "kind": e[2],
            "properties": json.loads(e[3] or "{}"),
            "confidence": e[4],
            "dataset": e[5],
            "seen_at": e[6],
        })
        other = e[1] if e[0] == entity_id else e[0]
        if other != entity_id:
            neighbour_ids.add(other)
    ent["edges"] = edges
    ent["neighbours"] = [n for n in (get_entity(nid) for nid in neighbour_ids) if n]
    return ent


def graph_view(entity_id: str, depth: int = 1, limit: int = 200) -> dict:
    """BFS over edges up to ``depth`` hops. Returns nodes + edges for INTEL view."""
    if not get_entity(entity_id):
        return {"root": entity_id, "found": False, "nodes": [], "edges": []}
    seen_nodes: dict[str, dict] = {}
    seen_edges: list[dict] = []
    edge_keys: set[tuple] = set()
    frontier = {entity_id}
    visited: set[str] = set()
    with _LOCK:
        con = _conn()
        for _ in range(max(1, depth)):
            if not frontier or len(seen_nodes) >= limit:
                break
            next_frontier: set[str] = set()
            for nid in frontier:
                if nid in visited:
                    continue
                visited.add(nid)
                rows = con.execute(
                    """
                    SELECT source_id, target_id, kind, confidence, dataset, seen_at
                    FROM edges WHERE source_id = ? OR target_id = ?
                    """,
                    [nid, nid],
                ).fetchall()
                for e in rows:
                    key = (e[0], e[1], e[2], e[4])
                    if key not in edge_keys:
                        edge_keys.add(key)
                        seen_edges.append({
                            "source_id": e[0], "target_id": e[1], "kind": e[2],
                            "confidence": e[3], "dataset": e[4], "seen_at": e[5],
                        })
                    for other in (e[0], e[1]):
                        if other not in visited:
                            next_frontier.add(other)
            frontier = next_frontier
        for nid in visited | frontier:
            if len(seen_nodes) >= limit:
                break
            if nid in seen_nodes:
                continue
            node = get_entity(nid)
            if node:
                seen_nodes[nid] = node
    return {
        "root": entity_id,
        "found": True,
        "depth": depth,
        "nodes": list(seen_nodes.values()),
        "edges": seen_edges,
    }


def graph_overview(
    limit: int = 100,
    datasets: list[str] | None = None,
    schemas: list[str] | None = None,
) -> dict:
    """Recent entities (+ edges among them) for feed-sync overview without a root id."""
    limit = max(1, min(int(limit), 500))
    with _LOCK:
        con = _conn()
        clauses: list[str] = []
        params: list[Any] = []
        if datasets:
            placeholders = ", ".join("?" * len(datasets))
            clauses.append(f"s.dataset IN ({placeholders})")
            params.extend(datasets)
        if schemas:
            placeholders = ", ".join("?" * len(schemas))
            clauses.append(f"e.schema IN ({placeholders})")
            params.extend(schemas)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"""
            SELECT DISTINCT e.id
            FROM entities e
            INNER JOIN statements s ON s.entity_id = e.id
            {where}
            ORDER BY CASE WHEN e.schema = 'Airplane' THEN 1 ELSE 0 END, s.seen_at DESC
            LIMIT ?
        """
        params.append(limit)
        id_rows = con.execute(sql, params).fetchall()
        node_ids = [r[0] for r in id_rows]
        if not node_ids:
            id_rows = con.execute(
                "SELECT id FROM entities ORDER BY last_seen DESC LIMIT ?",
                [limit],
            ).fetchall()
            node_ids = [r[0] for r in id_rows]

    nodes: list[dict] = []
    id_set = set(node_ids)
    for nid in node_ids:
        ent = get_entity(nid)
        if ent:
            nodes.append(ent)

    edges: list[dict] = []
    if len(id_set) > 1:
        placeholders = ", ".join("?" * len(node_ids))
        with _LOCK:
            rows = _conn().execute(
                f"""
                SELECT source_id, target_id, kind, confidence, dataset, seen_at
                FROM edges
                WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                """,
                node_ids + node_ids,
            ).fetchall()
        for e in rows:
            edges.append({
                "source_id": e[0], "target_id": e[1], "kind": e[2],
                "confidence": e[3], "dataset": e[4], "seen_at": e[5],
            })

    return {
        "root": None,
        "found": bool(nodes),
        "mode": "overview",
        "nodes": nodes,
        "edges": edges,
    }


def import_entities(dicts: Iterable[dict], dataset: str,
                    seen_at: str | None = None) -> dict:
    imported = 0
    ids: list[str] = []
    errors: list[str] = []
    for d in dicts:
        try:
            proxy = model.get_proxy(d)
            if not proxy.id:
                errors.append("entity without id skipped")
                continue
            upsert(proxy, dataset, seen_at=seen_at)
            imported += 1
            if len(ids) < 1000:
                ids.append(proxy.id)
        except Exception as exc:  # fail-soft per-entity
            if len(errors) < 25:
                errors.append(str(exc))
    return {"imported": imported, "ids": ids, "errors": errors}


def import_ndjson(text: str, dataset: str = "import") -> dict:
    text = (text or "").strip()
    if not text:
        return {"imported": 0, "ids": [], "errors": ["empty body"]}
    dicts: list[dict] = []
    errors: list[str] = []
    if text[0] == "[":
        try:
            payload = json.loads(text)
            dicts = payload if isinstance(payload, list) else [payload]
        except Exception as exc:
            return {"imported": 0, "ids": [], "errors": [f"json array parse: {exc}"]}
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                dicts.append(json.loads(line))
            except Exception as exc:
                if len(errors) < 25:
                    errors.append(f"line parse: {exc}")
    result = import_entities(dicts, dataset)
    result["errors"] = errors + result["errors"]
    return result


def list_entities_for_resolution(
    schemas: Iterable[str],
    limit: int = 3000,
) -> list[dict]:
    """Return recent entities for Splink / deterministic resolution."""
    schema_list = [s for s in schemas if s]
    if not schema_list or limit <= 0:
        return []
    placeholders = ", ".join("?" * len(schema_list))
    with _LOCK:
        rows = _conn().execute(
            f"""
            SELECT id, schema, caption, properties, datasets
            FROM entities
            WHERE schema IN ({placeholders})
            ORDER BY last_seen DESC
            LIMIT ?
            """,
            [*schema_list, int(limit)],
        ).fetchall()
    return [
        {
            "id": r[0],
            "schema": r[1],
            "caption": r[2],
            "properties": json.loads(r[3] or "{}"),
            "datasets": json.loads(r[4] or "[]"),
        }
        for r in rows
    ]


def count_edges_for_dataset(dataset: str) -> int:
    with _LOCK:
        row = _conn().execute(
            "SELECT count(*) FROM edges WHERE dataset = ?",
            [dataset],
        ).fetchone()
    return int(row[0] if row else 0)


def delete_edges_for_dataset(dataset: str) -> int:
    """Remove every edge from one provenance dataset; returns the count deleted.

    Entity resolution is append-only, so this is the supported way to reset a
    resolution run (e.g. after a config change) without touching ingested data.
    """
    with _LOCK:
        con = _conn()
        before = con.execute(
            "SELECT count(*) FROM edges WHERE dataset = ?", [dataset]
        ).fetchone()
        con.execute("DELETE FROM edges WHERE dataset = ?", [dataset])
        return int(before[0] if before else 0)


def list_entities_recent(limit: int = 50, dataset: str | None = None) -> dict:
    """Compact entity list for monitors and compatibility routes."""
    limit = max(1, min(int(limit), 500))
    with _LOCK:
        con = _conn()
        if dataset:
            rows = con.execute(
                """
                SELECT DISTINCT e.id, e.schema, e.caption, e.lat, e.lon, e.last_seen
                FROM entities e
                INNER JOIN statements s ON s.entity_id = e.id
                WHERE s.dataset = ?
                ORDER BY e.last_seen DESC
                LIMIT ?
                """,
                [dataset, limit],
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT id, schema, caption, lat, lon, last_seen
                FROM entities
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
    entities = [
        {
            "id": r[0],
            "schema": r[1],
            "caption": r[2],
            "lat": r[3],
            "lon": r[4],
            "last_seen": r[5],
        }
        for r in rows
    ]
    return {"count": len(entities), "entities": entities}


def _same_as_neighbour_map(
    entity_ids: list[str],
    *,
    per_entity: int = 2,
) -> dict[str, list[dict]]:
    """Map entity id -> linked sameAs neighbours (caption + schema), capped per entity."""
    if not entity_ids or per_entity <= 0:
        return {}
    out: dict[str, list[dict]] = {eid: [] for eid in entity_ids}
    placeholders = ", ".join("?" * len(entity_ids))
    params = [*entity_ids, *entity_ids]
    with _LOCK:
        rows = _conn().execute(
            f"""
            SELECT source_id, target_id, confidence
            FROM edges
            WHERE kind = 'sameAs'
              AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
            ORDER BY confidence DESC NULLS LAST
            """,
            params,
        ).fetchall()
    seen_pairs: dict[str, set[str]] = {eid: set() for eid in entity_ids}
    for source_id, target_id, confidence in rows:
        for eid, other in ((source_id, target_id), (target_id, source_id)):
            if eid not in out or other in seen_pairs[eid]:
                continue
            if len(out[eid]) >= per_entity:
                continue
            neighbour = get_entity(other)
            if not neighbour:
                continue
            seen_pairs[eid].add(other)
            out[eid].append({
                "id": neighbour["id"],
                "schema": neighbour["schema"],
                "caption": neighbour.get("caption") or neighbour["id"][:12],
                "confidence": confidence,
            })
    return out


def entities_for_briefing(
    *,
    window_hours: int = 24,
    fetch_limit: int = 200,
    exclude_schemas: Iterable[str] | None = None,
    include_same_as: bool = True,
    same_as_per_entity: int = 2,
) -> list[dict]:
    """Geolocated FtM entities seen recently — ranked candidates for the 24h digest."""
    from datetime import timedelta

    fetch_limit = max(1, min(int(fetch_limit), 500))
    window_hours = max(1, int(window_hours))
    excluded = {s.strip() for s in (exclude_schemas or []) if s and str(s).strip()}
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    clauses = [
        "e.lat IS NOT NULL",
        "e.lon IS NOT NULL",
        "e.last_seen IS NOT NULL",
        "e.last_seen >= ?",
    ]
    params: list[Any] = [cutoff]
    if excluded:
        placeholders = ", ".join("?" * len(excluded))
        clauses.append(f"e.schema NOT IN ({placeholders})")
        params.extend(sorted(excluded))

    sql = f"""
        SELECT e.id, e.schema, e.caption, e.lat, e.lon, e.datasets, e.last_seen
        FROM entities e
        WHERE {" AND ".join(clauses)}
        ORDER BY e.last_seen DESC
        LIMIT ?
    """
    params.append(fetch_limit)

    with _LOCK:
        rows = _conn().execute(sql, params).fetchall()

    entities: list[dict] = []
    for row in rows:
        datasets = json.loads(row[5] or "[]")
        entities.append({
            "id": row[0],
            "schema": row[1],
            "caption": row[2] or row[0][:12],
            "lat": row[3],
            "lon": row[4],
            "datasets": datasets,
            "last_seen": row[6],
        })

    if include_same_as and entities:
        neighbour_map = _same_as_neighbour_map(
            [e["id"] for e in entities],
            per_entity=same_as_per_entity,
        )
        for ent in entities:
            links = neighbour_map.get(ent["id"]) or []
            if links:
                ent["same_as"] = links

    return entities


def graph_stats() -> dict:
    """Store roll-up plus graph-specific counters (compat for external monitors)."""
    base = stats()
    base["resolution_edges"] = count_edges_for_dataset("entity-resolution")
    base["graph_endpoints"] = {
        "overview": "/api/intel/graph/overview",
        "entity_graph": "/api/entity/{id}/graph",
        "entity_list": "/api/intel/entities",
    }
    return base


def stats() -> dict:
    with _LOCK:
        con = _conn()
        n_entities = con.execute("SELECT count(*) FROM entities").fetchone()[0]
        n_statements = con.execute("SELECT count(*) FROM statements").fetchone()[0]
        n_edges = con.execute("SELECT count(*) FROM edges").fetchone()[0]
        by_schema = con.execute(
            "SELECT schema, count(*) FROM entities GROUP BY schema ORDER BY 2 DESC"
        ).fetchall()
        by_dataset = con.execute(
            "SELECT dataset, count(*) FROM statements GROUP BY dataset ORDER BY 2 DESC LIMIT 20"
        ).fetchall()
    return {
        "entities": n_entities,
        "statements": n_statements,
        "edges": n_edges,
        "by_schema": {k: v for k, v in by_schema},
        "by_dataset": {k: v for k, v in by_dataset},
    }


# ---------------------------------------------------------------------------
# Legacy entity_store -> FtM schema mapping (mirror)
# ---------------------------------------------------------------------------

_LEGACY_SCHEMA = {
    "person": "Person",
    "organization": "Organization",
    "company": "Company",
    "investigation": "Thing",
    "situation": "Event",
    "aircraft": "Airplane",
    "vessel": "Vessel",
    "pegel": "Thing",
    "volcano": "Thing",
    "address": "Address",
    "ip": "Thing",
    "domain": "Thing",
    "email": "Person",
    "username": "Person",
    "osint": "Thing",
}


# ---------------------------------------------------------------------------
# OpenSanctions adapter (targets.simple.csv -> FtM). Explicit / bounded only.
# ---------------------------------------------------------------------------

def _sanctions_csv_path() -> str:
    base = os.getenv("WORLDBASE_SANCTIONS_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sanctions"
    )
    return os.path.join(base, "targets.simple.csv")


def _split_multi(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    for part in str(value).replace("|", ";").split(";"):
        part = part.strip()
        if part:
            out.append(part)
    return out


def ftm_from_sanctions_row(row: dict):
    """Convert one OpenSanctions targets.simple.csv row to an FtM entity."""
    rid = (row.get("id") or "").strip()
    if not rid:
        return None
    schema = (row.get("schema") or "LegalEntity").strip()
    props: dict[str, list[str]] = {}
    if row.get("name"):
        props["name"] = [row["name"].strip()]
    if row.get("aliases"):
        props["alias"] = _split_multi(row.get("aliases"))
    if row.get("countries"):
        props["country"] = _split_multi(row.get("countries"))
    if row.get("addresses"):
        props["address"] = _split_multi(row.get("addresses"))
    if row.get("identifiers"):
        props["idNumber"] = _split_multi(row.get("identifiers"))
    if row.get("phones"):
        props["phone"] = _split_multi(row.get("phones"))
    if row.get("emails"):
        props["email"] = _split_multi(row.get("emails"))
    if row.get("birth_date"):
        props["birthDate"] = [row["birth_date"].strip()]
    if row.get("program_ids"):
        props["program"] = _split_multi(row.get("program_ids"))
    if row.get("sanctions"):
        props["notes"] = [str(row["sanctions"])[:1000]]
    return _proxy_with_id(rid, schema, props)


def import_sanctions_csv(limit: int = 5000, schema_filter: str | None = None,
                         csv_path: str | None = None) -> dict:
    path = csv_path or _sanctions_csv_path()
    if not os.path.exists(path):
        return {"ok": False, "error": "csv not found", "path": path}
    imported = 0
    skipped = 0
    with _LOCK, open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            if schema_filter and (raw.get("schema") or "") != schema_filter:
                continue
            proxy = ftm_from_sanctions_row(raw)
            if proxy is None:
                skipped += 1
                continue
            upsert(proxy, dataset="opensanctions", seen_at=(raw.get("last_seen") or None))
            imported += 1
            if limit and imported >= limit:
                break
    return {"ok": True, "imported": imported, "skipped": skipped,
            "limit": limit, "schema": schema_filter, "dataset": "opensanctions"}


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api", tags=["intel"])


@router.get("/intel/stats")
async def api_intel_stats():
    try:
        return stats()
    except Exception as exc:  # fail-soft
        return {"entities": 0, "statements": 0, "edges": 0, "error": str(exc)}


@router.get("/intel/entities")
async def api_intel_entities(
    limit: int = Query(50, ge=1, le=500),
    dataset: str | None = Query(None, description="Filter by provenance dataset tag"),
    geolocated: bool = Query(False, description="Only entities with lat/lon seen in window_hours"),
    window_hours: int = Query(24, ge=1, le=168),
):
    """Recent entities (compat route). Set geolocated=1 for FtM globe layer."""
    try:
        if geolocated:
            ents = entities_for_briefing(
                window_hours=window_hours,
                fetch_limit=limit,
                exclude_schemas=["Airplane"],
                include_same_as=False,
            )
            return {"count": len(ents), "entities": ents, "window_hours": window_hours}
        return list_entities_recent(limit, dataset)
    except Exception as exc:
        return {"count": 0, "entities": [], "error": str(exc)}


@router.get("/intel/subgraph")
async def api_intel_subgraph(
    bbox: str | None = Query(None, description="west,south,east,north — default operator region"),
    hops: int = Query(2, ge=1, le=3),
    window_hours: int = Query(24, ge=1, le=168),
    region: str | None = Query(None, description="Operator region preset when bbox omitted"),
):
    """2-hop FtM subgraph seeded by geolocated entities in bbox (Track 3)."""
    import intel_subgraph

    try:
        parsed = intel_subgraph.parse_bbox(bbox)
        return intel_subgraph.build_subgraph(
            bbox=parsed,
            region=region,
            hops=hops,
            window_hours=window_hours,
        )
    except Exception as exc:
        return {
            "available": False,
            "reason": str(exc)[:200],
            "error": str(exc)[:200],
            "nodes": [],
            "edges": [],
            "seeds": [],
        }


@router.get("/intel/graph/stats")
async def api_intel_graph_stats():
    """Graph + store roll-up (compat alias — prefer /api/intel/stats for counts only)."""
    try:
        return graph_stats()
    except Exception as exc:
        return {"entities": 0, "edges": 0, "error": str(exc)}


@router.post("/entity/import")
async def api_entity_import(request: Request, dataset: str = Query("import")):
    """Round-trip an FtM entity stream (NDJSON, one JSON per line, or a JSON array)."""
    body = await request.body()
    text = body.decode("utf-8", "ignore")
    return await asyncio.to_thread(import_ndjson, text, dataset)


@router.post("/intel/import/sanctions")
async def api_import_sanctions(
    limit: int = Query(5000, ge=1, le=2_000_000),
    schema: str | None = Query(None, description="filter, e.g. Person/Company/Vessel"),
):
    return await asyncio.to_thread(import_sanctions_csv, limit, schema)


@router.get("/intel/graph/overview")
async def api_graph_overview(
    limit: int = Query(100, ge=1, le=500),
    datasets: str | None = Query(None, description="Comma-separated dataset tags"),
    schemas: str | None = Query(None, description="Comma-separated FtM schemas"),
):
    ds = [d.strip() for d in datasets.split(",") if d.strip()] if datasets else None
    sch = [s.strip() for s in schemas.split(",") if s.strip()] if schemas else None
    try:
        return graph_overview(limit, ds, sch)
    except Exception as exc:
        return {"found": False, "nodes": [], "edges": [], "error": str(exc)}


@router.get("/entity/{entity_id}/graph")
async def api_entity_graph(
    entity_id: str,
    depth: int = Query(1, ge=1, le=3),
    limit: int = Query(200, ge=1, le=1000),
):
    try:
        return graph_view(entity_id, depth, limit)
    except Exception as exc:
        return {"root": entity_id, "found": False, "nodes": [], "edges": [], "error": str(exc)}


@router.get("/entity/{entity_id}")
async def api_get_entity(entity_id: str):
    """Canonical FtM JSON for one entity (additive to /entity/{id}/context)."""
    try:
        ent = get_entity_full(entity_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:200]}, status_code=503)
    if not ent:
        return {"id": entity_id, "found": False}
    return {**ent, "found": True}
