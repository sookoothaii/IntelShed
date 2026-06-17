"""Splink entity resolution -> provenance-aware ``sameAs`` edges in FtM.

Matches duplicate Person / Organization / Company / Vessel records across
datasets and writes ``sameAs`` edges with ``confidence`` + ``method`` metadata.
Deterministic exact-name matches run first; Splink adds fuzzy pairs when enough
rows exist. Splink is lazy-imported (``pip install splink``).
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import ftm_store

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RESOLUTION_DATASET = "entity-resolution"
RESOLUTION_KIND = "sameAs"
RESOLUTION_SCHEMAS = ("Person", "Organization", "Company", "Vessel")
_MIN_ROWS_SPLINK = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_MIN_ROWS", "3"))
_EM_MIN_ROWS = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_EM_MIN_ROWS", "80"))
_LIMIT_PER_SCHEMA = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_LIMIT", "3000"))
_THRESHOLD = float(os.getenv("WORLDBASE_ENTITY_RESOLUTION_THRESHOLD", "0.85"))
_EXACT_CONFIDENCE = float(os.getenv("WORLDBASE_ENTITY_RESOLUTION_EXACT_CONF", "0.98"))
_AUTOPILOT_INTERVAL = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_INTERVAL", "86400"))

_LOCK = threading.RLock()
_LAST_RUN: dict[str, Any] | None = None
_LAST_ERROR: str | None = None
_SPLINK_VERSION: str | None = None


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def autopilot_on() -> bool:
    return _truthy_env("WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT", "0")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(values: Any) -> str:
    if isinstance(values, list):
        return str(values[0]).strip() if values else ""
    if values is None:
        return ""
    return str(values).strip()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def _canonical_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _record_edge(
    source_id: str,
    target_id: str,
    *,
    confidence: float,
    method: str,
    schema: str,
    seen_pairs: set[tuple[str, str, str]],
) -> bool:
    if not source_id or not target_id or source_id == target_id:
        return False
    src, tgt = _canonical_pair(source_id, target_id)
    key = (src, tgt, RESOLUTION_DATASET)
    if key in seen_pairs:
        return False
    seen_pairs.add(key)
    ftm_store.add_edge(
        src,
        tgt,
        RESOLUTION_KIND,
        dataset=RESOLUTION_DATASET,
        confidence=float(confidence),
        properties={"method": method, "schema": schema},
    )
    return True


def _rows_for_schema(schema: str, entities: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for ent in entities:
        props = ent.get("properties") or {}
        name = _normalize_name(_first(props.get("name")) or ent.get("caption") or "")
        if len(name) < 2:
            continue
        country = _normalize_token(_first(props.get("country")))
        imo = _normalize_token(_first(props.get("imoNumber")))
        rows.append({
            "unique_id": ent["id"],
            "entity_id": ent["id"],
            "name": name,
            "country": country or None,
            "imo_number": imo or None,
            "schema": schema,
        })
    return rows


def _run_exact_matches(schema: str, entities: list[dict], seen_pairs: set[tuple[str, str, str]]) -> int:
    """High-confidence exact keys before fuzzy Splink."""
    groups: dict[tuple, list[str]] = defaultdict(list)
    for ent in entities:
        props = ent.get("properties") or {}
        name = _normalize_name(_first(props.get("name")) or ent.get("caption") or "")
        if len(name) < 2:
            continue
        country = _normalize_token(_first(props.get("country")))
        imo = _normalize_token(_first(props.get("imoNumber")))
        if schema == "Vessel" and imo:
            groups[(schema, "imo", imo)].append(ent["id"])
        elif country:
            groups[(schema, "name_country", name, country)].append(ent["id"])
        else:
            groups[(schema, "name_only", name)].append(ent["id"])

    added = 0
    for key, ids in groups.items():
        uniq = sorted(set(ids))
        if len(uniq) < 2:
            continue
        method = key[1]
        conf = _EXACT_CONFIDENCE if method != "name_only" else min(_EXACT_CONFIDENCE, 0.92)
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                if _record_edge(
                    uniq[i], uniq[j], confidence=conf, method=f"exact:{method}", schema=schema, seen_pairs=seen_pairs
                ):
                    added += 1
    return added


def _run_splink_schema(schema: str, rows: list[dict], seen_pairs: set[tuple[str, str, str]]) -> int:
    if len(rows) < _MIN_ROWS_SPLINK:
        return 0
    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker, SettingsCreator, block_on
        import splink.comparison_library as cl
    except ImportError as exc:
        raise RuntimeError("splink not installed — pip install 'splink>=4.0,<5'") from exc

    global _SPLINK_VERSION
    import splink as _splink_mod

    _SPLINK_VERSION = getattr(_splink_mod, "__version__", None)

    df = pd.DataFrame(rows)
    comparisons = [cl.NameComparison("name")]
    blocking = [block_on("substr(name, 1, 4)")]
    if schema == "Vessel":
        comparisons.append(cl.ExactMatch("imo_number"))
        blocking.append(block_on("imo_number"))
    if df["country"].notna().any() and (df["country"] != "").any():
        comparisons.append(cl.ExactMatch("country"))
        blocking.append(block_on("country"))

    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=blocking,
        probability_two_random_records_match=0.02,
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())

    if len(df) >= _EM_MIN_ROWS:
        linker.training.estimate_u_using_random_sampling(max_pairs=min(1_000_000, len(df) * 20))
        linker.training.estimate_parameters_using_expectation_maximisation(blocking[0])

    pred = linker.inference.predict(threshold_match_probability=_THRESHOLD)
    out = pred.as_pandas_dataframe()

    added = 0
    for _, row in out.iterrows():
        left = str(row.get("unique_id_l") or "")
        right = str(row.get("unique_id_r") or "")
        prob = float(row.get("match_probability") or 0.0)
        if prob < _THRESHOLD:
            continue
        if _record_edge(
            left, right, confidence=prob, method="splink", schema=schema, seen_pairs=seen_pairs
        ):
            added += 1
    return added


def run_resolution(*, schemas: tuple[str, ...] | None = None) -> dict:
    """Run deterministic + Splink resolution for configured schemas."""
    global _LAST_RUN, _LAST_ERROR
    schema_list = schemas or RESOLUTION_SCHEMAS
    started = _now()
    seen_pairs: set[tuple[str, str, str]] = set()
    per_schema: dict[str, dict[str, int]] = {}
    total_exact = 0
    total_splink = 0
    errors: list[str] = []

    with _LOCK:
        try:
            for schema in schema_list:
                entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA)
                rows = _rows_for_schema(schema, entities)
                exact = _run_exact_matches(schema, entities, seen_pairs)
                splink_added = 0
                try:
                    splink_added = _run_splink_schema(schema, rows, seen_pairs)
                except Exception as exc:
                    if len(errors) < 5:
                        errors.append(f"{schema}: {exc}")
                per_schema[schema] = {
                    "candidates": len(entities),
                    "rows": len(rows),
                    "exact_edges": exact,
                    "splink_edges": splink_added,
                }
                total_exact += exact
                total_splink += splink_added

            result = {
                "ok": True,
                "started_at": started,
                "finished_at": _now(),
                "threshold": _THRESHOLD,
                "exact_confidence": _EXACT_CONFIDENCE,
                "schemas": list(schema_list),
                "per_schema": per_schema,
                "edges_added": total_exact + total_splink,
                "exact_edges": total_exact,
                "splink_edges": total_splink,
                "resolution_edges_total": ftm_store.count_edges_for_dataset(RESOLUTION_DATASET),
                "splink_version": _SPLINK_VERSION,
                "errors": errors,
            }
            _LAST_RUN = result
            _LAST_ERROR = errors[0] if errors else None
            return result
        except Exception as exc:
            _LAST_ERROR = str(exc)
            raise


def status() -> dict:
    splink_ok = False
    splink_version = _SPLINK_VERSION
    try:
        import splink  # noqa: F401

        splink_ok = True
        if not splink_version:
            import splink as sm

            splink_version = getattr(sm, "__version__", None)
    except ImportError:
        pass
    return {
        "available": splink_ok,
        "splink_version": splink_version,
        "autopilot": autopilot_on(),
        "interval_sec": _AUTOPILOT_INTERVAL,
        "threshold": _THRESHOLD,
        "schemas": list(RESOLUTION_SCHEMAS),
        "resolution_edges": ftm_store.count_edges_for_dataset(RESOLUTION_DATASET),
        "last_run": _LAST_RUN,
        "last_error": _LAST_ERROR,
    }


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

from fastapi import APIRouter, HTTPException  # noqa: E402

router = APIRouter(prefix="/api/intel/resolution", tags=["intel"])


@router.get("/status")
async def resolution_status():
    return status()


@router.post("/run")
async def resolution_run():
    try:
        return await asyncio.to_thread(run_resolution)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"resolution failed: {exc}") from exc
