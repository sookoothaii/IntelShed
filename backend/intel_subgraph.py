"""Track 3 — spatial FtM subgraph (GraphRAG-lite) for briefing and MCP."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import ftm_store

_DEFAULT_EXCLUDE = ("Airplane", "Thing")


def subgraph_enabled() -> bool:
    return os.getenv("WORLDBASE_BRIEFING_INTEL_SUBGRAPH", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def default_hops() -> int:
    try:
        return max(1, min(3, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_HOPS", "2") or "2")))
    except ValueError:
        return 2


def default_seed_limit() -> int:
    try:
        return max(5, min(80, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_SEED_LIMIT", "30") or "30")))
    except ValueError:
        return 30


def default_node_limit() -> int:
    try:
        return max(10, min(200, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_NODE_LIMIT", "80") or "80")))
    except ValueError:
        return 80


def parse_bbox(raw: str | None) -> list[float] | None:
    if not raw or not str(raw).strip():
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    if len(parts) != 4:
        return None
    try:
        west, south, east, north = (float(p) for p in parts)
    except ValueError:
        return None
    if west >= east or south >= north:
        return None
    return [west, south, east, north]


def operator_bbox(region: str | None = None) -> list[float]:
    from operator_briefing import OPERATOR_REGION, _ASEAN_BBOX, _region_bbox

    key = (region or OPERATOR_REGION or "thailand").strip().lower()
    preset = _region_bbox(key)
    if preset:
        return list(preset)
    if key == "thailand":
        return list(_ASEAN_BBOX)
    return list(_ASEAN_BBOX)


def _exclude_schemas() -> set[str]:
    raw = os.getenv(
        "WORLDBASE_BRIEFING_INTEL_EXCLUDE_SCHEMAS",
        ",".join(_DEFAULT_EXCLUDE),
    )
    return {s.strip() for s in raw.split(",") if s.strip()}


def _json_num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _in_bbox(lat: float | None, lon: float | None, bbox: list[float]) -> bool:
    if lat is None or lon is None:
        return False
    west, south, east, north = bbox
    return south <= float(lat) <= north and west <= float(lon) <= east


def _seed_entities_in_bbox(
    bbox: list[float],
    *,
    window_hours: int,
    seed_limit: int,
    exclude_schemas: set[str],
) -> list[dict[str, Any]]:
    west, south, east, north = bbox
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))).isoformat()
    clauses = [
        "e.lat IS NOT NULL",
        "e.lon IS NOT NULL",
        "e.last_seen IS NOT NULL",
        "e.last_seen >= ?",
        "e.lat BETWEEN ? AND ?",
        "e.lon BETWEEN ? AND ?",
    ]
    params: list[Any] = [cutoff, south, north, west, east]
    if exclude_schemas:
        placeholders = ", ".join("?" * len(exclude_schemas))
        clauses.append(f"e.schema NOT IN ({placeholders})")
        params.extend(sorted(exclude_schemas))
    params.append(max(1, seed_limit))
    sql = f"""
        SELECT e.id, e.schema, e.caption, e.lat, e.lon, e.datasets, e.last_seen
        FROM entities e
        WHERE {" AND ".join(clauses)}
        ORDER BY e.last_seen DESC
        LIMIT ?
    """
    rows = ftm_store.run_query(sql, params)
    seeds: list[dict[str, Any]] = []
    for row in rows:
        seeds.append({
            "id": row[0],
            "schema": row[1],
            "caption": row[2] or row[0][:12],
            "lat": _json_num(row[3]),
            "lon": _json_num(row[4]),
            "datasets": json.loads(row[5] or "[]"),
            "last_seen": row[6],
            "in_bbox": True,
            "hop": 0,
        })
    return seeds


def _expand_edges(
    frontier: set[str],
    *,
    visited: set[str],
    edges_out: list[dict[str, Any]],
    edge_keys: set[tuple[str, str, str, str]],
    node_limit: int,
) -> set[str]:
    if not frontier:
        return set()
    next_frontier: set[str] = set()
    placeholders = ", ".join("?" * len(frontier))
    params = [*frontier, *frontier]
    rows = ftm_store.run_query(
        f"""
        SELECT source_id, target_id, kind, confidence, dataset, seen_at
        FROM edges
        WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})
        """,
        params,
    )
    for source_id, target_id, kind, confidence, dataset, seen_at in rows:
        key = (source_id, target_id, kind, dataset or "")
        if key not in edge_keys:
            edge_keys.add(key)
            edges_out.append({
                "source_id": source_id,
                "target_id": target_id,
                "kind": kind,
                "confidence": _json_num(confidence),
                "dataset": dataset,
                "seen_at": seen_at,
            })
        for other in (source_id, target_id):
            if other in visited or len(visited) + len(next_frontier) >= node_limit:
                continue
            next_frontier.add(other)
    return next_frontier


def build_subgraph(
    *,
    bbox: list[float] | None = None,
    region: str | None = None,
    hops: int | None = None,
    window_hours: int = 24,
    seed_limit: int | None = None,
    node_limit: int | None = None,
) -> dict[str, Any]:
    """2-hop (configurable) subgraph seeded by geolocated entities in bbox."""
    if not ftm_store.init_store():
        err = (ftm_store.store_status().get("error") or "ftm store unavailable")
        if "invalidated" in str(err).lower() or "fatal" in str(err).lower():
            ftm_store.reset_store()
        if not ftm_store.init_store():
            return {
                "available": False,
                "reason": ftm_store.store_status().get("error") or err,
                "nodes": [],
                "edges": [],
                "seeds": [],
            }

    target_bbox = list(bbox) if bbox else operator_bbox(region)
    hop_n = hops if hops is not None else default_hops()
    hop_n = max(1, min(3, int(hop_n)))
    seeds = _seed_entities_in_bbox(
        target_bbox,
        window_hours=window_hours,
        seed_limit=seed_limit or default_seed_limit(),
        exclude_schemas=_exclude_schemas(),
    )
    if not seeds:
        return {
            "available": False,
            "reason": "no geolocated seeds in bbox/window",
            "bbox": target_bbox,
            "hops": hop_n,
            "window_hours": window_hours,
            "nodes": [],
            "edges": [],
            "seeds": [],
        }

    cap = node_limit or default_node_limit()
    visited: set[str] = {s["id"] for s in seeds}
    hop_depth: dict[str, int] = {s["id"]: 0 for s in seeds}
    frontier: set[str] = set(visited)
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str, str]] = set()

    for hop in range(1, hop_n + 1):
        if not frontier or len(visited) >= cap:
            break
        next_ids = _expand_edges(
            frontier,
            visited=visited,
            edges_out=edges,
            edge_keys=edge_keys,
            node_limit=cap,
        )
        next_frontier: set[str] = set()
        for nid in next_ids:
            if nid in visited or len(visited) >= cap:
                continue
            visited.add(nid)
            hop_depth[nid] = hop
            next_frontier.add(nid)
        frontier = next_frontier

    seed_map = {s["id"]: s for s in seeds}
    nodes: list[dict[str, Any]] = []
    for nid in sorted(visited, key=lambda x: (hop_depth.get(x, 99), x))[:cap]:
        if nid in seed_map:
            nodes.append(dict(seed_map[nid]))
            continue
        ent = ftm_store.get_entity(nid)
        if not ent:
            continue
        nodes.append({
            "id": ent["id"],
            "schema": ent.get("schema"),
            "caption": ent.get("caption") or ent["id"][:12],
            "lat": _json_num(ent.get("lat")),
            "lon": _json_num(ent.get("lon")),
            "datasets": ent.get("datasets") or [],
            "in_bbox": _in_bbox(ent.get("lat"), ent.get("lon"), target_bbox),
            "hop": hop_depth.get(nid, 99),
        })

    node_ids = {n["id"] for n in nodes}
    pruned_edges = [
        e for e in edges
        if e["source_id"] in node_ids and e["target_id"] in node_ids
    ]

    return {
        "available": True,
        "bbox": target_bbox,
        "region": region,
        "hops": hop_n,
        "window_hours": window_hours,
        "seed_count": len(seeds),
        "seeds": [s["id"] for s in seeds],
        "nodes": nodes,
        "edges": pruned_edges,
        "node_count": len(nodes),
        "edge_count": len(pruned_edges),
    }


def format_subgraph_prompt_block(subgraph: dict[str, Any], lang: str = "en") -> str:
    """Compact subgraph text for the LLM prompt (fewer tokens than flat entity dump)."""
    if not subgraph.get("available"):
        if lang.startswith("de"):
            return "- FtM-Subgraph leer (keine Seeds im Operator-Bbox-Fenster)."
        return "- FtM subgraph empty (no seeds in operator bbox window)."

    nodes = subgraph.get("nodes") or []
    edges = subgraph.get("edges") or []
    if not nodes:
        if lang.startswith("de"):
            return "- FtM-Subgraph ohne Knoten."
        return "- FtM subgraph has no nodes."

    id_to_label: dict[str, str] = {}
    node_lines: list[str] = []
    for node in nodes[:24]:
        label = f"[{node.get('schema') or '?'}] {node.get('caption') or node.get('id', '')[:12]}"
        id_to_label[node["id"]] = label
        tags: list[str] = []
        if node.get("in_bbox") or node.get("hop") == 0:
            tags.append("seed" if lang.startswith("en") else "Seed")
        elif node.get("hop") is not None:
            tags.append(f"{node['hop']}-hop")
        ds = (node.get("datasets") or [])[:2]
        if ds:
            tags.append(",".join(ds))
        suffix = f" ({'; '.join(tags)})" if tags else ""
        node_lines.append(f"- {label}{suffix}")

    edge_lines: list[str] = []
    for edge in edges[:20]:
        src = id_to_label.get(edge["source_id"], edge["source_id"][:10])
        tgt = id_to_label.get(edge["target_id"], edge["target_id"][:10])
        kind = edge.get("kind") or "linked"
        ds = edge.get("dataset") or "?"
        edge_lines.append(f"- {src} --{kind}--> {tgt} [{ds}]")

    hop_n = subgraph.get("hops", 2)
    if lang.startswith("de"):
        header = f"INTEL SUBGRAPH ({hop_n}-Hop um Operator-Bbox, {subgraph.get('node_count', len(nodes))} Knoten):"
        nodes_hdr = "Knoten:"
        edges_hdr = "Kanten:"
    else:
        header = f"INTEL SUBGRAPH ({hop_n}-hop around operator bbox, {subgraph.get('node_count', len(nodes))} nodes):"
        nodes_hdr = "Nodes:"
        edges_hdr = "Links:"

    parts = [header, nodes_hdr, "\n".join(node_lines)]
    if edge_lines:
        parts.extend([edges_hdr, "\n".join(edge_lines)])
    return "\n".join(parts)
