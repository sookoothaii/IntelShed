"""Track 3 — spatial FtM subgraph (GraphRAG-lite) for briefing and MCP."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import ftm_store

_DEFAULT_EXCLUDE = ("Airplane", "Thing")


def _decay_floor() -> float:
    """Minimum decay_weight for an edge to appear in the prompt subgraph. Default 0.3."""
    try:
        return max(
            0.0,
            min(
                1.0,
                float(
                    os.getenv("WORLDBASE_INTEL_SUBGRAPH_DECAY_FLOOR", "0.3") or "0.3"
                ),
            ),
        )
    except ValueError:
        return 0.3


def _communities_enabled() -> bool:
    return os.getenv("WORLDBASE_INTEL_SUBGRAPH_COMMUNITIES", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_PROMPT_EDGE_CAP = 20


def _edge_decay_half_life_days() -> float:
    """Half-life for temporal edge decay (days). Default 30."""
    try:
        return max(
            1.0, float(os.getenv("WORLDBASE_INTEL_EDGE_DECAY_DAYS", "30") or "30")
        )
    except ValueError:
        return 30.0


def decay_weight(age_days: float, half_life_days: float | None = None) -> float:
    """Exponential decay weight for an edge based on its age in days.

    Returns a factor in (0, 1]:
    - age=0 -> 1.0 (fresh)
    - age=half_life -> 0.5
    - age=2*half_life -> 0.25

    Edges older than ~5 half-lives are effectively negligible (<0.03).
    """
    hl = half_life_days if half_life_days is not None else _edge_decay_half_life_days()
    if age_days < 1.0:
        return 1.0
    return round(0.5 ** (age_days / max(1.0, hl)), 4)


def _edge_age_days(seen_at: str | None) -> float | None:
    """Parse seen_at ISO timestamp and return age in days, or None if unparseable."""
    if not seen_at:
        return None
    try:
        ts = datetime.fromisoformat(seen_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def subgraph_enabled() -> bool:
    return os.getenv("WORLDBASE_BRIEFING_INTEL_SUBGRAPH", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def default_hops() -> int:
    try:
        return max(
            1, min(3, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_HOPS", "2") or "2"))
        )
    except ValueError:
        return 2


def default_seed_limit() -> int:
    try:
        return max(
            5,
            min(
                80, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_SEED_LIMIT", "30") or "30")
            ),
        )
    except ValueError:
        return 30


def default_node_limit() -> int:
    try:
        return max(
            10,
            min(
                200, int(os.getenv("WORLDBASE_INTEL_SUBGRAPH_NODE_LIMIT", "80") or "80")
            ),
        )
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
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    ).isoformat()
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
        seeds.append(
            {
                "id": row[0],
                "schema": row[1],
                "caption": row[2] or row[0][:12],
                "lat": _json_num(row[3]),
                "lon": _json_num(row[4]),
                "datasets": json.loads(row[5] or "[]"),
                "last_seen": row[6],
                "in_bbox": True,
                "hop": 0,
            }
        )
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
            raw_conf = _json_num(confidence) or 1.0
            age_days = _edge_age_days(seen_at)
            decay = decay_weight(age_days) if age_days is not None else 1.0
            decayed_conf = round(raw_conf * decay, 4)
            edges_out.append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "kind": kind,
                    "confidence": raw_conf,
                    "decayed_confidence": decayed_conf,
                    "decay_weight": decay,
                    "age_days": round(age_days, 1) if age_days is not None else None,
                    "dataset": dataset,
                    "seen_at": seen_at,
                }
            )
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
    st = ftm_store.store_status()
    if not st.get("ready"):
        return {
            "available": False,
            "reason": st.get("error") or "ftm store unavailable",
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
        nodes.append(
            {
                "id": ent["id"],
                "schema": ent.get("schema"),
                "caption": ent.get("caption") or ent["id"][:12],
                "lat": _json_num(ent.get("lat")),
                "lon": _json_num(ent.get("lon")),
                "datasets": ent.get("datasets") or [],
                "in_bbox": _in_bbox(ent.get("lat"), ent.get("lon"), target_bbox),
                "hop": hop_depth.get(nid, 99),
            }
        )

    node_ids = {n["id"] for n in nodes}
    pruned_edges = [
        e for e in edges if e["source_id"] in node_ids and e["target_id"] in node_ids
    ]

    # I5: aggregate duplicate edges between same node pair
    aggregated_edges = _aggregate_edges(pruned_edges)

    # I5: graph density scoring + hub tagging
    density_map = _graph_density(nodes, aggregated_edges)
    for node in nodes:
        score = density_map.get(node["id"], 0.0)
        node["density_score"] = round(score, 3)
        node["hub"] = score > 0.5

    # I5: optional community detection
    if _communities_enabled() and len(nodes) >= 3:
        comm_map = _detect_communities(nodes, aggregated_edges)
        for node in nodes:
            if node["id"] in comm_map:
                node["community_id"] = comm_map[node["id"]]

    return {
        "available": True,
        "bbox": target_bbox,
        "region": region,
        "hops": hop_n,
        "window_hours": window_hours,
        "seed_count": len(seeds),
        "seeds": [s["id"] for s in seeds],
        "nodes": nodes,
        "edges": aggregated_edges,
        "node_count": len(nodes),
        "edge_count": len(aggregated_edges),
        "raw_edge_count": len(pruned_edges),
    }


def _aggregate_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate multiple edges between the same node pair into a single edge.

    Multiple `relatedEvent` or other edges between the same source→target pair
    are collapsed into one edge with:
    - count: number of original edges
    - avg_confidence: mean of raw confidence values
    - combined_weight: mean of decayed_confidence values
    - source_types: set of edge kinds
    - datasets: set of datasets
    """
    pair_map: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in edges:
        pair = (edge["source_id"], edge["target_id"])
        if pair not in pair_map:
            pair_map[pair] = {
                "source_id": edge["source_id"],
                "target_id": edge["target_id"],
                "kind": edge.get("kind") or "linked",
                "confidence": edge.get("confidence", 1.0),
                "decayed_confidence": edge.get("decayed_confidence", 1.0),
                "decay_weight": edge.get("decay_weight", 1.0),
                "age_days": edge.get("age_days"),
                "dataset": edge.get("dataset"),
                "seen_at": edge.get("seen_at"),
                "_count": 1,
                "_confidences": [edge.get("confidence", 1.0)],
                "_decayed": [edge.get("decayed_confidence", 1.0)],
                "_kinds": {edge.get("kind") or "linked"},
                "_datasets": set(),
            }
            if edge.get("dataset"):
                pair_map[pair]["_datasets"].add(edge["dataset"])
        else:
            agg = pair_map[pair]
            agg["_count"] += 1
            agg["_confidences"].append(edge.get("confidence", 1.0))
            agg["_decayed"].append(edge.get("decayed_confidence", 1.0))
            agg["_kinds"].add(edge.get("kind") or "linked")
            if edge.get("dataset"):
                agg["_datasets"].add(edge["dataset"])
            # Keep the most recent seen_at
            if edge.get("seen_at") and (
                not agg.get("seen_at") or edge["seen_at"] > agg["seen_at"]
            ):
                agg["seen_at"] = edge["seen_at"]
                agg["age_days"] = edge.get("age_days")
                agg["decay_weight"] = edge.get("decay_weight", 1.0)

    result: list[dict[str, Any]] = []
    for agg in pair_map.values():
        count = agg.pop("_count")
        confidences = agg.pop("_confidences")
        decayed = agg.pop("_decayed")
        kinds = agg.pop("_kinds")
        datasets = agg.pop("_datasets")
        agg["count"] = count
        agg["avg_confidence"] = round(sum(confidences) / len(confidences), 4)
        agg["combined_weight"] = round(sum(decayed) / len(decayed), 4)
        agg["source_types"] = sorted(kinds)
        agg["datasets"] = sorted(datasets) if datasets else []
        # Use the primary kind (most common, or first alphabetically as tiebreaker)
        agg["kind"] = (
            sorted(kinds)[0] if len(kinds) == 1 else "|".join(sorted(kinds)[:3])
        )
        result.append(agg)
    return result


def _graph_density(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, float]:
    """Compute per-node density score = edge_count / (node_count - 1).

    High-density nodes (>0.5) are convergence points (hubs).
    """
    n = len(nodes)
    if n <= 1:
        return {node["id"]: 0.0 for node in nodes}
    degree: dict[str, int] = {node["id"]: 0 for node in nodes}
    for edge in edges:
        sid = edge.get("source_id")
        tid = edge.get("target_id")
        if sid in degree:
            degree[sid] += 1
        if tid in degree:
            degree[tid] += 1
    denom = n - 1
    return {nid: deg / denom for nid, deg in degree.items()}


def _prune_stale_edges(
    edges: list[dict[str, Any]], floor: float | None = None
) -> list[dict[str, Any]]:
    """Filter out edges with decay_weight below the floor (not from DB, just from prompt)."""
    threshold = floor if floor is not None else _decay_floor()
    if threshold <= 0:
        return edges
    return [e for e in edges if (e.get("decay_weight") or 1.0) >= threshold]


def _prioritize_edges(
    edges: list[dict[str, Any]],
    density_map: dict[str, float],
    cap: int = _PROMPT_EDGE_CAP,
) -> list[dict[str, Any]]:
    """Sort edges by priority: decayed_confidence * count * (1 + 0.1 * hub_bonus).

    Keeps the most relevant, well-corroborated, and structurally important edges.
    """

    def priority(e: dict[str, Any]) -> float:
        decayed = e.get("combined_weight") or e.get("decayed_confidence") or 0.0
        count = e.get("count", 1)
        src_hub = 1.0 if density_map.get(e.get("source_id", ""), 0) > 0.5 else 0.0
        tgt_hub = 1.0 if density_map.get(e.get("target_id", ""), 0) > 0.5 else 0.0
        hub_bonus = max(src_hub, tgt_hub)
        return decayed * count * (1.0 + 0.1 * hub_bonus)

    return sorted(edges, key=priority, reverse=True)[:cap]


def _detect_communities(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> dict[str, int]:
    """Optional: detect communities using networkx greedy modularity.

    Returns mapping of node_id → community_id (0-indexed).
    """
    try:
        import networkx as nx
    except ImportError:
        return {}

    g = nx.Graph()
    for node in nodes:
        g.add_node(node["id"])
    for edge in edges:
        sid = edge.get("source_id")
        tid = edge.get("target_id")
        if sid and tid:
            weight = (
                edge.get("combined_weight") or edge.get("decayed_confidence") or 1.0
            )
            g.add_edge(sid, tid, weight=weight)

    if g.number_of_edges() == 0:
        return {}

    try:
        communities = nx.community.greedy_modularity_communities(g, weight="weight")
    except Exception:
        return {}

    result: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node_id in community:
            result[node_id] = idx
    return result


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

    # I5: prune stale edges below decay floor before prompt
    prompt_edges = _prune_stale_edges(edges)

    # I5: compute density for prioritization
    density_map = _graph_density(nodes, prompt_edges)

    # I5: prioritize edges when over cap
    if len(prompt_edges) > _PROMPT_EDGE_CAP:
        prompt_edges = _prioritize_edges(prompt_edges, density_map, _PROMPT_EDGE_CAP)

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
        if node.get("hub"):
            tags.append("hub" if lang.startswith("en") else "Knotenpunkt")
        if node.get("community_id") is not None:
            tags.append(f"c{node['community_id']}")
        ds = (node.get("datasets") or [])[:2]
        if ds:
            tags.append(",".join(ds))
        suffix = f" ({'; '.join(tags)})" if tags else ""
        node_lines.append(f"- {label}{suffix}")

    edge_lines: list[str] = []
    for edge in prompt_edges:
        src = id_to_label.get(edge["source_id"], edge["source_id"][:10])
        tgt = id_to_label.get(edge["target_id"], edge["target_id"][:10])
        kind = edge.get("kind") or "linked"
        ds = edge.get("dataset") or "?"
        decay = edge.get("decay_weight")
        if decay is not None and decay < 0.5:
            kind = f"{kind} (stale)"
        count = edge.get("count", 1)
        if count > 1:
            kind = f"{kind} x{count}"
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
