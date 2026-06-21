"""Apply declarative FtM YAML mappings to flat feed records."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

import ftm_store

_MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"


def list_mappings() -> list[str]:
    return sorted(p.stem for p in _MAPPINGS_DIR.glob("*.yml"))


def load_mapping(name: str) -> dict[str, Any]:
    path = _MAPPINGS_DIR / f"{name}.yml"
    if not path.is_file():
        raise FileNotFoundError(f"mapping not found: {name}")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError(f"mapping {name} must have exactly one top-level key")
    return data


def _prop_values(spec: Any, record: dict) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, str):
        spec = {"column": spec}
    if not isinstance(spec, dict):
        return []
    if "column" in spec:
        val = record.get(spec["column"])
        return [str(val)] if val not in (None, "") else []
    cols = spec.get("columns") or []
    parts = [str(record.get(c)) for c in cols if record.get(c) not in (None, "")]
    if not parts:
        return []
    if len(parts) == 1:
        return parts
    return ["; ".join(parts)]


def _entity_stable_id(dataset: str, entity_alias: str, spec: dict, record: dict) -> str:
    keys = spec.get("keys") or ["id"]
    parts: list[str] = []
    for key in keys:
        val = record.get(key)
        if val in (None, ""):
            val = record.get("id") or entity_alias
        parts.append(str(val))
    raw = f"{dataset}|{entity_alias}|{'|'.join(parts)}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{dataset}:{digest}"


def apply_mapping(
    records: list[dict],
    mapping_name: str,
    *,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Upsert entities (+ optional links) from *records* using a YAML mapping."""
    root = load_mapping(mapping_name)
    mapping_key = next(iter(root))
    queries = (root.get(mapping_key) or {}).get("queries") or []
    ds = dataset or mapping_key.replace("_", "-")
    entities_written = 0
    edges_written = 0
    skipped = 0
    errors: list[str] = []

    for record in records:
        if not isinstance(record, dict):
            skipped += 1
            continue
        for query in queries:
            req_cols = query.get("require_any") or []
            if req_cols and not any(record.get(c) not in (None, "") for c in req_cols):
                continue
            entity_specs: dict[str, dict] = query.get("entities") or {}
            alias_ids: dict[str, str] = {}
            try:
                for alias, spec in entity_specs.items():
                    schema = spec.get("schema") or "Thing"
                    props: dict[str, list[str]] = {}
                    for prop_name, col_spec in (spec.get("properties") or {}).items():
                        vals = _prop_values(col_spec, record)
                        if vals:
                            props[prop_name] = vals
                    if not props.get("name") and record.get("title"):
                        props.setdefault("name", [str(record["title"])[:500]])
                    eid = _entity_stable_id(ds, alias, spec, record)
                    lat = record.get("lat")
                    lon = record.get("lon")
                    try:
                        lat_f = float(lat) if lat is not None else None
                    except (TypeError, ValueError):
                        lat_f = None
                    try:
                        lon_f = float(lon) if lon is not None else None
                    except (TypeError, ValueError):
                        lon_f = None
                    proxy = ftm_store._proxy_with_id(eid, schema, props)
                    ftm_store.upsert(proxy, ds, lat=lat_f, lon=lon_f)
                    alias_ids[alias] = eid
                    entities_written += 1

                for link in query.get("links") or []:
                    src_alias = link.get("source")
                    tgt_alias = link.get("target")
                    kind = link.get("kind") or "relatedEntity"
                    src_id = alias_ids.get(src_alias)
                    tgt_id = alias_ids.get(tgt_alias)
                    if src_id and tgt_id:
                        ftm_store.add_edge(
                            src_id,
                            tgt_id,
                            kind,
                            dataset=ds,
                            confidence=float(link.get("confidence", 0.85)),
                            properties={"method": "feed-mapping"},
                        )
                        edges_written += 1
            except Exception as exc:
                if len(errors) < 10:
                    errors.append(str(exc))
                skipped += 1

    return {
        "mapping": mapping_name,
        "dataset": ds,
        "records": len(records),
        "entities_written": entities_written,
        "edges_written": edges_written,
        "skipped": skipped,
        "errors": errors,
    }
