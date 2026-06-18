"""Inspect entity-resolution sameAs edges via running HTTP API (no DuckDB lock)."""
from __future__ import annotations

import json
import os
import re
import sys

import httpx

BASE = os.getenv("WORLDBASE_SELF", "http://127.0.0.1:8002").rstrip("/")
RES_DATASET = "entity-resolution"
KEYWORDS = ("erdogan", "cavusoglu", "cakmak", "university of alaska")


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def fetch_entities(client: httpx.Client, dataset: str | None) -> list[dict]:
    url = f"{BASE}/api/intel/entities?limit=500"
    if dataset:
        url += f"&dataset={dataset}"
    r = client.get(url, timeout=30.0)
    r.raise_for_status()
    return list(r.json().get("entities") or [])


def entity_full(client: httpx.Client, eid: str) -> dict:
    r = client.get(f"{BASE}/api/entity/{eid}", timeout=30.0)
    r.raise_for_status()
    return r.json()


def entity_graph(client: httpx.Client, eid: str) -> dict:
    r = client.get(
        f"{BASE}/api/entity/{eid}/graph",
        params={"depth": 1, "limit": 80},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()


def resolution_edges_for_entity(client: httpx.Client, eid: str) -> list[dict]:
    """Prefer full entity payload — graph route omits edge properties (method)."""
    full = entity_full(client, eid)
    out = []
    for edge in full.get("edges") or []:
        if edge.get("kind") == "sameAs" and edge.get("dataset") == RES_DATASET:
            out.append(edge)
    return out


def edge_props(edge: dict) -> dict:
    props = edge.get("properties") or {}
    if isinstance(props, str):
        try:
            return json.loads(props)
        except json.JSONDecodeError:
            return {}
    return props if isinstance(props, dict) else {}


def classify_pair(a: dict, b: dict) -> str:
    da = set(a.get("datasets") or [])
    db = set(b.get("datasets") or [])
    if not da or not db:
        return "unknown-provenance"
    return "CROSS-SOURCE" if da.isdisjoint(db) else "SAME-SOURCE"


def main() -> int:
    client = httpx.Client()
    datasets = [
        None,
        "intel-ingest",
        "gdacs",
        "gdelt-pulse",
        "gdelt-geo",
        "eonet",
        "ais",
        "sanctions",
        "opensanctions",
    ]

    by_id: dict[str, dict] = {}
    for ds in datasets:
        try:
            for ent in fetch_entities(client, ds):
                by_id[ent["id"]] = ent
        except Exception as exc:
            print(f"[warn] dataset={ds!r}: {exc}", file=sys.stderr)

    # Enrich keyword hits with full entity (datasets live on entity row)
    hits: dict[str, dict] = {}
    for eid, ent in by_id.items():
        cap = norm(ent.get("caption"))
        if any(k in cap for k in KEYWORDS):
            full = entity_full(client, eid)
            if full.get("found"):
                hits[eid] = full

    print(f"keyword entity hits: {len(hits)}")

    pairs: dict[tuple[str, str], tuple[dict, dict, dict]] = {}
    for eid, ent in hits.items():
        for edge in resolution_edges_for_entity(client, eid):
            other_id = edge["target_id"] if edge["source_id"] == eid else edge["source_id"]
            other = entity_full(client, other_id)
            if not other.get("found"):
                continue
            key = tuple(sorted([eid, other_id]))
            pairs[key] = (ent, other, edge)

    # Full scan: all sameAs edges among recent Person/Org overview nodes
    ov = client.get(
        f"{BASE}/api/intel/graph/overview",
        params={"limit": 500, "schemas": "Person,Organization"},
        timeout=30.0,
    ).json()
    for node in ov.get("nodes") or []:
        nid = node["id"]
        for edge in resolution_edges_for_entity(client, nid):
            other_id = edge["target_id"] if edge["source_id"] == nid else edge["source_id"]
            key = tuple(sorted([nid, other_id]))
            if key in pairs:
                continue
            a = entity_full(client, nid)
            b = entity_full(client, other_id)
            if a.get("found") and b.get("found"):
                pairs[key] = (a, b, edge)

    subset_pairs = {
        k: v for k, v in pairs.items() if edge_props(v[2]).get("method") == "subset:token"
    }
    if not subset_pairs and pairs:
        subset_pairs = pairs  # graph/full mismatch — report all resolution pairs
    print(f"subset:token pairs found: {len(subset_pairs)}\n")

    for i, (a, b, edge) in enumerate(subset_pairs.values(), 1):
        props = edge_props(edge)
        kind = classify_pair(a, b)
        print(f"#{i} {kind}  method={props.get('method')}  conf={edge.get('confidence')}")
        print(f"   A: {a.get('caption')}  datasets={sorted(set(a.get('datasets') or []))}")
        print(f"   B: {b.get('caption')}  datasets={sorted(set(b.get('datasets') or []))}")
        print()

    st = client.get(f"{BASE}/api/intel/resolution/status", timeout=15.0).json()
    print(
        f"resolution_edges (status): {st.get('resolution_edges')}  "
        f"splink_enabled: {st.get('splink_enabled')}  "
        f"last subset_edges: {(st.get('last_run') or {}).get('subset_edges')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
