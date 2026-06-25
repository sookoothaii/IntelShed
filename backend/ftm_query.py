"""FtM entity CRUD, graph traversal, and briefing query functions.

All read/write operations on the DuckDB store. Uses ``ftm_connection`` for
connection management and ``ftm_schema`` for index/DDL helpers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from followthemoney import model

from ftm_connection import _LOCK, _conn, _run_with_recovery
from ftm_schema import (
    _delete_entity_rows,
    _drop_edge_indexes,
    _ensure_edge_indexes,
    _ensure_entity_schema_index,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


# ---------------------------------------------------------------------------
# FtM proxy helpers
# ---------------------------------------------------------------------------


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


def _upsert_impl(
    proxy,
    dataset: str,
    *,
    seen_at: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> str | None:
    """Merge an FtM entity into the store and record per-value provenance."""
    eid = proxy.id
    if not eid:
        return None
    seen_at = seen_at or _now()
    incoming = proxy.to_dict().get("properties", {}) or {}
    schema_name = proxy.schema.name

    def _do(con) -> str:
        try:
            row = con.execute(
                "SELECT properties, datasets, first_seen, lat, lon FROM entities WHERE id = ?",
                [eid],
            ).fetchone()
            if row:
                existing_props = json.loads(row[0] or "{}")
                datasets = set(json.loads(row[1] or "[]"))
                first_seen = row[2] or seen_at
                use_lat = lat if lat is not None else row[3]
                use_lon = lon if lon is not None else row[4]
                merged_props = _merge_props(existing_props, incoming)
            else:
                datasets = set()
                first_seen = seen_at
                use_lat = lat
                use_lon = lon
                merged_props = incoming
            datasets.add(dataset)

            merged_proxy = model.get_proxy(
                {"id": eid, "schema": schema_name, "properties": merged_props}
            )
            if use_lat is None:
                use_lat = _first_float(merged_props.get("latitude"))
            if use_lon is None:
                use_lon = _first_float(merged_props.get("longitude"))

            if row:
                _delete_entity_rows(con, eid)

            con.execute(
                """
                INSERT INTO entities
                    (id, schema, caption, properties, datasets, lat, lon, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    eid,
                    merged_proxy.schema.name,
                    merged_proxy.caption,
                    json.dumps(merged_props),
                    json.dumps(sorted(datasets)),
                    use_lat,
                    use_lon,
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
        finally:
            _ensure_entity_schema_index(con)

    return _run_with_recovery(_do)


def upsert(
    proxy,
    dataset: str,
    *,
    seen_at: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> str | None:
    """Merge an FtM entity into the store (routes through DuckDB queue when enabled)."""
    try:
        from duckdb_queue import is_enabled, get_queue
        if is_enabled():
            return get_queue().enqueue_sync("upsert", {
                "entity_dict": proxy.to_dict(),
                "dataset": dataset,
                "seen_at": seen_at,
                "lat": lat,
                "lon": lon,
            })
    except ImportError:
        pass
    return _upsert_impl(proxy, dataset, seen_at=seen_at, lat=lat, lon=lon)


def upsert_legacy(
    entity_id: str,
    entity_type: str,
    *,
    label: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    source_feed: str | None = None,
    external_id: str | None = None,
    meta: dict | None = None,
) -> str | None:
    """Mirror a legacy entity_store node into the FtM graph (best-effort)."""
    from ftm_sanctions import _LEGACY_SCHEMA

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


def _add_edge_impl(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str = "worldbase",
    *,
    confidence: float = 1.0,
    properties: dict | None = None,
    seen_at: str | None = None,
) -> None:
    if not source_id or not target_id:
        return

    def _do(con) -> None:
        con.execute(
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

    _run_with_recovery(_do)


def add_edge(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str = "worldbase",
    *,
    confidence: float = 1.0,
    properties: dict | None = None,
    seen_at: str | None = None,
) -> None:
    """Add an edge (routes through DuckDB queue when enabled)."""
    if not source_id or not target_id:
        return
    try:
        from duckdb_queue import is_enabled, get_queue
        if is_enabled():
            get_queue().enqueue_sync("add_edge", {
                "source_id": source_id,
                "target_id": target_id,
                "kind": kind,
                "dataset": dataset,
                "confidence": confidence,
                "properties": properties,
                "seen_at": seen_at,
            })
            return
    except ImportError:
        pass
    _add_edge_impl(source_id, target_id, kind, dataset,
                   confidence=confidence, properties=properties, seen_at=seen_at)


def get_entity(entity_id: str) -> dict | None:
    with _LOCK:
        row = (
            _conn()
            .execute(
                """
            SELECT id, schema, caption, properties, datasets, first_seen, last_seen, lat, lon
            FROM entities WHERE id = ?
            """,
                [entity_id],
            )
            .fetchone()
        )
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
        edges.append(
            {
                "source_id": e[0],
                "target_id": e[1],
                "kind": e[2],
                "properties": json.loads(e[3] or "{}"),
                "confidence": e[4],
                "dataset": e[5],
                "seen_at": e[6],
            }
        )
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
                        seen_edges.append(
                            {
                                "source_id": e[0],
                                "target_id": e[1],
                                "kind": e[2],
                                "confidence": e[3],
                                "dataset": e[4],
                                "seen_at": e[5],
                            }
                        )
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
            rows = (
                _conn()
                .execute(
                    f"""
                SELECT source_id, target_id, kind, confidence, dataset, seen_at
                FROM edges
                WHERE source_id IN ({placeholders}) AND target_id IN ({placeholders})
                """,
                    node_ids + node_ids,
                )
                .fetchall()
            )
        for e in rows:
            edges.append(
                {
                    "source_id": e[0],
                    "target_id": e[1],
                    "kind": e[2],
                    "confidence": e[3],
                    "dataset": e[4],
                    "seen_at": e[5],
                }
            )

    return {
        "root": None,
        "found": bool(nodes),
        "mode": "overview",
        "nodes": nodes,
        "edges": edges,
    }


def _import_entities_impl(
    dicts: Iterable[dict], dataset: str, seen_at: str | None = None
) -> dict:
    imported = 0
    ids: list[str] = []
    errors: list[str] = []
    for d in dicts:
        try:
            proxy = model.get_proxy(d)
            if not proxy.id:
                errors.append("entity without id skipped")
                continue
            _upsert_impl(proxy, dataset, seen_at=seen_at)
            imported += 1
            if len(ids) < 1000:
                ids.append(proxy.id)
        except Exception as exc:  # fail-soft per-entity
            if len(errors) < 25:
                errors.append(str(exc))
    return {"imported": imported, "ids": ids, "errors": errors}


def import_entities(
    dicts: Iterable[dict], dataset: str, seen_at: str | None = None
) -> dict:
    """Import entities (routes through DuckDB queue when enabled)."""
    try:
        from duckdb_queue import is_enabled, get_queue
        if is_enabled():
            return get_queue().enqueue_sync("import_entities", {
                "dicts": list(dicts),
                "dataset": dataset,
                "seen_at": seen_at,
            })
    except ImportError:
        pass
    return _import_entities_impl(dicts, dataset, seen_at=seen_at)


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
    dataset: str | None = None,
) -> list[dict]:
    """Return recent entities for Splink / deterministic resolution.

    If *dataset* is given, only entities whose ``datasets`` JSON array
    contains that value are returned (used by the two-stage pipeline).
    """
    schema_list = [s for s in schemas if s]
    if not schema_list or limit <= 0:
        return []
    placeholders = ", ".join("?" * len(schema_list))
    params: list = [*schema_list]
    dataset_clause = ""
    if dataset:
        dataset_clause = " AND EXISTS (SELECT 1 FROM json_each(datasets) je WHERE TRIM(je.value::VARCHAR, '\"') = ?)"
        params.append(dataset)
    params.append(int(limit))
    with _LOCK:
        rows = (
            _conn()
            .execute(
                f"""
            SELECT id, schema, caption, properties, datasets
            FROM entities
            WHERE schema IN ({placeholders}){dataset_clause}
            ORDER BY last_seen DESC
            LIMIT ?
            """,
                params,
            )
            .fetchall()
        )
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


def list_datasets_for_schema(schemas: Iterable[str]) -> list[str]:
    """Return distinct dataset names that appear on entities of the given schemas."""
    schema_list = [s for s in schemas if s]
    if not schema_list:
        return []
    placeholders = ", ".join("?" * len(schema_list))
    with _LOCK:
        rows = (
            _conn()
            .execute(
                f"""
            SELECT DISTINCT TRIM(je.value::VARCHAR, '"') AS ds
            FROM entities, json_each(datasets) AS je
            WHERE schema IN ({placeholders})
              AND datasets != '[]'
            ORDER BY ds
            """,
                schema_list,
            )
            .fetchall()
        )
    return [r[0] for r in rows if r[0]]


def count_edges_for_dataset(dataset: str) -> int:
    with _LOCK:
        row = (
            _conn()
            .execute(
                "SELECT count(*) FROM edges WHERE dataset = ?",
                [dataset],
            )
            .fetchone()
        )
    return int(row[0] if row else 0)


def _delete_edges_impl(dataset: str) -> int:
    """Remove every edge from one provenance dataset; returns the count deleted.

    Entity resolution is append-only, so this is the supported way to reset a
    resolution run (e.g. after a config change) without touching ingested data.

    DuckDB 1.5.x can FATAL on bulk DELETE when secondary edge indexes drift;
    drop indexes first, then rebuild (same class of bug as upsert schema change).
    """

    def _do(con) -> int:
        before = con.execute(
            "SELECT count(*) FROM edges WHERE dataset = ?", [dataset]
        ).fetchone()
        count = int(before[0] if before else 0)
        if count == 0:
            return 0
        _drop_edge_indexes(con)
        try:
            con.execute("DELETE FROM edges WHERE dataset = ?", [dataset])
        except Exception:
            con.execute(
                """
                CREATE OR REPLACE TEMP TABLE _ftm_edges_keep AS
                SELECT * FROM edges WHERE dataset != ?
                """,
                [dataset],
            )
            con.execute("DELETE FROM edges")
            con.execute("INSERT INTO edges SELECT * FROM _ftm_edges_keep")
            con.execute("DROP TABLE IF EXISTS _ftm_edges_keep")
        finally:
            _ensure_edge_indexes(con)
        return count

    return _run_with_recovery(_do)


def delete_edges_for_dataset(dataset: str) -> int:
    """Delete edges for a dataset (routes through DuckDB queue when enabled)."""
    try:
        from duckdb_queue import is_enabled, get_queue
        if is_enabled():
            return get_queue().enqueue_sync("delete_edges_for_dataset", {
                "dataset": dataset,
            })
    except ImportError:
        pass
    return _delete_edges_impl(dataset)


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
        rows = (
            _conn()
            .execute(
                f"""
            SELECT source_id, target_id, confidence
            FROM edges
            WHERE kind = 'sameAs'
              AND (source_id IN ({placeholders}) OR target_id IN ({placeholders}))
            ORDER BY confidence DESC NULLS LAST
            """,
                params,
            )
            .fetchall()
        )
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
            out[eid].append(
                {
                    "id": neighbour["id"],
                    "schema": neighbour["schema"],
                    "caption": neighbour.get("caption") or neighbour["id"][:12],
                    "confidence": confidence,
                }
            )
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
        entities.append(
            {
                "id": row[0],
                "schema": row[1],
                "caption": row[2] or row[0][:12],
                "lat": row[3],
                "lon": row[4],
                "datasets": datasets,
                "last_seen": row[6],
            }
        )

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
# DuckDB Queue — operation handlers + registration
# ---------------------------------------------------------------------------


def _op_upsert(params: dict) -> str | None:
    proxy = model.get_proxy(params["entity_dict"])
    return _upsert_impl(
        proxy,
        dataset=params["dataset"],
        seen_at=params.get("seen_at"),
        lat=params.get("lat"),
        lon=params.get("lon"),
    )


def _op_add_edge(params: dict) -> None:
    _add_edge_impl(
        params["source_id"],
        params["target_id"],
        params["kind"],
        params.get("dataset", "worldbase"),
        confidence=params.get("confidence", 1.0),
        properties=params.get("properties"),
        seen_at=params.get("seen_at"),
    )


def _op_delete_edges(params: dict) -> int:
    return _delete_edges_impl(params["dataset"])


def _op_import_entities(params: dict) -> dict:
    return _import_entities_impl(
        params["dicts"],
        params["dataset"],
        seen_at=params.get("seen_at"),
    )


try:
    from duckdb_queue import register_op as _register_op

    _register_op("upsert", _op_upsert)
    _register_op("add_edge", _op_add_edge)
    _register_op("delete_edges_for_dataset", _op_delete_edges)
    _register_op("import_entities", _op_import_entities)
except ImportError:
    pass


# ---------------------------------------------------------------------------
# P5 — FtM 4.0 StatementEntity: per-value provenance query helpers
# ---------------------------------------------------------------------------


def get_statements(entity_id: str) -> list[dict]:
    """Get all per-value statements for an entity.

    Returns list of {prop, value, dataset, seen_at, lang} dicts.
    """
    def _do(con):
        rows = con.execute(
            "SELECT prop, value, dataset, seen_at, lang FROM statements WHERE entity_id = ? ORDER BY prop, dataset",
            [entity_id],
        ).fetchall()
        return [
            {"prop": r[0], "value": r[1], "dataset": r[2], "seen_at": r[3], "lang": r[4]}
            for r in rows
        ]
    return _run_with_recovery(_do) or []


def query_by_provenance(dataset: str, prop: str | None = None, limit: int = 100) -> list[dict]:
    """Query statements by source dataset, optionally filtered by property.

    Returns list of {entity_id, prop, value, seen_at} dicts.
    """
    def _do(con):
        if prop:
            rows = con.execute(
                "SELECT entity_id, prop, value, seen_at FROM statements WHERE dataset = ? AND prop = ? LIMIT ?",
                [dataset, prop, limit],
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT entity_id, prop, value, seen_at FROM statements WHERE dataset = ? LIMIT ?",
                [dataset, limit],
            ).fetchall()
        return [
            {"entity_id": r[0], "prop": r[1], "value": r[2], "seen_at": r[3]}
            for r in rows
        ]
    return _run_with_recovery(_do) or []


def statement_stats() -> dict:
    """Get statement table statistics."""
    def _do(con):
        total = con.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
        by_dataset = con.execute(
            "SELECT dataset, COUNT(*) as c FROM statements GROUP BY dataset ORDER BY c DESC LIMIT 20"
        ).fetchall()
        by_prop = con.execute(
            "SELECT prop, COUNT(*) as c FROM statements GROUP BY prop ORDER BY c DESC LIMIT 20"
        ).fetchall()
        return {
            "total_statements": total,
            "by_dataset": {r[0]: r[1] for r in by_dataset},
            "by_prop": {r[0]: r[1] for r in by_prop},
        }
    return _run_with_recovery(_do) or {"total_statements": 0, "by_dataset": {}, "by_prop": {}}


# ---------------------------------------------------------------------------
# P5+ — Dynamic Knowledge Graph: external edge support
# ---------------------------------------------------------------------------

import os as _os

_MAX_EXT_CONF = float(_os.getenv("WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE", "0.7"))


def add_external_edge(
    source_id: str,
    target_id: str,
    kind: str,
    dataset: str = "user-query",
    *,
    confidence: float = 0.6,
    properties: dict | None = None,
    seen_at: str | None = None,
) -> None:
    """Add an external (user-derived) edge with confidence cap.

    Confidence is capped at WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE (default 0.7).
    The edge is marked with external=true in properties.
    """
    capped = min(confidence, _MAX_EXT_CONF)
    props = dict(properties or {})
    props["external"] = True
    props["confirmed"] = False
    add_edge(
        source_id, target_id, kind, dataset,
        confidence=capped, properties=props, seen_at=seen_at,
    )


def list_external_edges(confirmed: bool | None = None, limit: int = 100) -> list[dict]:
    """List external edges, optionally filtered by confirmation status."""
    def _do(con):
        rows = con.execute(
            """
            SELECT source_id, target_id, kind, properties, confidence, dataset, seen_at
            FROM edges
            WHERE properties LIKE '%\"external\": true%'
            ORDER BY seen_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchall()
        results = []
        for r in rows:
            props = json.loads(r[3] or "{}")
            is_confirmed = props.get("confirmed", False)
            if confirmed is not None and is_confirmed != confirmed:
                continue
            results.append({
                "source_id": r[0],
                "target_id": r[1],
                "kind": r[2],
                "properties": props,
                "confidence": r[4],
                "dataset": r[5],
                "seen_at": r[6],
                "external": props.get("external", False),
                "confirmed": is_confirmed,
            })
        return results
    return _run_with_recovery(_do) or []


def approve_external_edge(source_id: str, target_id: str, kind: str, dataset: str) -> bool:
    """Approve an external edge — sets confirmed=true and raises confidence to 0.9."""
    def _do(con):
        row = con.execute(
            "SELECT properties FROM edges WHERE source_id = ? AND target_id = ? AND kind = ? AND dataset = ?",
            [source_id, target_id, kind, dataset],
        ).fetchone()
        if not row:
            return False
        props = json.loads(row[0] or "{}")
        props["confirmed"] = True
        props["external"] = True
        con.execute(
            "UPDATE edges SET properties = ?, confidence = 0.9 WHERE source_id = ? AND target_id = ? AND kind = ? AND dataset = ?",
            [json.dumps(props), source_id, target_id, kind, dataset],
        )
        return True
    result = _run_with_recovery(_do)
    return bool(result)


def reject_external_edge(source_id: str, target_id: str, kind: str, dataset: str) -> bool:
    """Reject an external edge — deletes it from the graph."""
    def _do(con):
        con.execute(
            "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND kind = ? AND dataset = ?",
            [source_id, target_id, kind, dataset],
        )
        return True
    result = _run_with_recovery(_do)
    return bool(result)
