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
_SUBSET_CONFIDENCE = float(os.getenv("WORLDBASE_ENTITY_RESOLUTION_SUBSET_CONF", "0.88"))
_AUTOPILOT_INTERVAL = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_INTERVAL", "86400"))
# Splink fuzzy stage is OFF by default: the current single full-name comparison
# (no term-frequency adjustments) over-matches common given names on real-world
# data (every "Mohammad *" / "Jose *" pair from same country crosses 0.85). The
# deterministic exact + token-subset stages stay always-on. Re-enable once the
# comparison is calibrated (forename/surname split + TF). See progress notes.
_SPLINK_ENABLED = os.getenv("WORLDBASE_ENTITY_RESOLUTION_SPLINK", "0").strip().lower() in ("1", "true", "yes", "on")

# Generic head/tail tokens that must not, on their own, trigger a single-token
# subset match (e.g. "authorities" sub of "local authorities"). Proper nouns
# such as "erdogan" or "cavusoglu" are not in this list, so they still match.
_GENERIC_TOKENS = frozenset({
    "authorities", "authority", "government", "ministry", "commission",
    "committee", "department", "agency", "council", "office", "forces",
    "police", "army", "navy", "group", "states", "state", "union", "people",
    "citizens", "students", "journalists", "researchers", "professionals",
    "managers", "organisation", "organisations", "organization",
    "organizations", "company", "limited", "ltd", "inc", "corp", "corporation",
    "llc", "gmbh", "group", "team", "service", "services", "system", "systems",
})
# Tokens shared by more than this many entities are too common to seed a
# subset candidate pair (keeps candidate generation near-linear at scale).
_SUBSET_TOKEN_FANOUT_CAP = int(os.getenv("WORLDBASE_ENTITY_RESOLUTION_SUBSET_FANOUT", "400"))

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
        toks = _name_token_list(name)
        rows.append({
            "unique_id": ent["id"],
            "entity_id": ent["id"],
            "name": name,
            "name_last": toks[-1] if toks else name,
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


def _name_token_list(name: str) -> list[str]:
    return [t for t in re.split(r"\s+", name) if t]


def _contiguous_subseq(short: list[str], long_: list[str]) -> bool:
    """True if ``short`` appears as a contiguous run of tokens inside ``long_``.

    Contiguity is what separates real partial names ("Erdogan" suffix of
    "Recep Tayyip Erdogan"; "University of Alaska" prefix of "... Fairbanks")
    from scattered common-name coincidences ("Jose Hernandez" sharing only the
    1st and last token of "Ricardo Jose Moron Hernandez").
    """
    n, m = len(short), len(long_)
    if n == 0 or n > m:
        return False
    for i in range(m - n + 1):
        if long_[i:i + n] == short:
            return True
    return False


def _run_subset_matches(schema: str, entities: list[dict], seen_pairs: set[tuple[str, str, str]]) -> int:
    """Deterministic token-subset matches for partial-name duplicates.

    Links entities whose name tokens form a contiguous run inside another's
    (e.g. "erdogan" suffix of "recep tayyip erdogan", "university of alaska"
    prefix of "university of alaska fairbanks"). This is the precise fix for
    partial names that string-similarity (Splink ``NameComparison`` on the full
    name) cannot catch. Contiguity rejects scattered common-name coincidences,
    and single-token matches are further guarded by length + a generic-token
    stoplist to avoid linking generic words like "authorities".
    """
    recs: list[dict] = []
    token_index: dict[str, list[int]] = defaultdict(list)
    for ent in entities:
        props = ent.get("properties") or {}
        name = _normalize_name(_first(props.get("name")) or ent.get("caption") or "")
        toks = _name_token_list(name)
        if len(name) < 2 or not toks:
            continue
        idx = len(recs)
        recs.append({"id": ent["id"], "name": name, "toks": toks, "ntok": len(toks)})
        for tok in set(toks):
            token_index[tok].append(idx)

    checked: set[tuple[int, int]] = set()
    added = 0
    for tok, idxs in token_index.items():
        if len(idxs) < 2 or len(idxs) > _SUBSET_TOKEN_FANOUT_CAP:
            continue
        for a_pos in range(len(idxs)):
            for b_pos in range(a_pos + 1, len(idxs)):
                i, j = idxs[a_pos], idxs[b_pos]
                pair = (i, j) if i < j else (j, i)
                if pair in checked:
                    continue
                checked.add(pair)
                ra, rb = recs[pair[0]], recs[pair[1]]
                if ra["name"] == rb["name"]:
                    continue  # exact duplicates handled by _run_exact_matches
                short, long_ = (ra, rb) if ra["ntok"] <= rb["ntok"] else (rb, ra)
                if not _contiguous_subseq(short["toks"], long_["toks"]):
                    continue
                if short["ntok"] == 1:
                    only = short["toks"][0]
                    if len(only) < 4 or only in _GENERIC_TOKENS:
                        continue
                if _record_edge(
                    short["id"], long_["id"], confidence=_SUBSET_CONFIDENCE,
                    method="subset:token", schema=schema, seen_pairs=seen_pairs,
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
    # Block on first 4 chars AND on the last name token, so records whose names
    # share a surname/head token but differ in prefix (e.g. "Erdogan" vs
    # "Recep Tayyip Erdogan") still land in a common comparison block.
    blocking = [block_on("substr(name, 1, 4)"), block_on("name_last")]
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
        # u (agreement among non-matches) from random sampling only. We do NOT
        # run EM m-estimation: with a single full-name comparison and no term-
        # frequency adjustments, EM over-fits common given names (every
        # "Mohammad *" / "Jose *" pair) and floods false-positive matches. The
        # conservative default m keeps precision high; real fuzzy duplicates with
        # distinctive names still clear the threshold. Proper EM needs a
        # forename/surname split + term-frequency adjustments (future work).
        linker.training.estimate_u_using_random_sampling(max_pairs=min(1_000_000, len(df) * 20))

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
    total_subset = 0
    total_splink = 0
    errors: list[str] = []

    with _LOCK:
        try:
            for schema in schema_list:
                entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA)
                rows = _rows_for_schema(schema, entities)
                exact = _run_exact_matches(schema, entities, seen_pairs)
                subset = _run_subset_matches(schema, entities, seen_pairs)
                splink_added = 0
                if _SPLINK_ENABLED:
                    try:
                        splink_added = _run_splink_schema(schema, rows, seen_pairs)
                    except Exception as exc:
                        if len(errors) < 5:
                            errors.append(f"{schema}: {exc}")
                per_schema[schema] = {
                    "candidates": len(entities),
                    "rows": len(rows),
                    "exact_edges": exact,
                    "subset_edges": subset,
                    "splink_edges": splink_added,
                }
                total_exact += exact
                total_subset += subset
                total_splink += splink_added

            result = {
                "ok": True,
                "started_at": started,
                "finished_at": _now(),
                "threshold": _THRESHOLD,
                "exact_confidence": _EXACT_CONFIDENCE,
                "subset_confidence": _SUBSET_CONFIDENCE,
                "splink_enabled": _SPLINK_ENABLED,
                "schemas": list(schema_list),
                "per_schema": per_schema,
                "edges_added": total_exact + total_subset + total_splink,
                "exact_edges": total_exact,
                "subset_edges": total_subset,
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
        "splink_enabled": _SPLINK_ENABLED,
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


@router.post("/reset")
async def resolution_reset():
    """Delete all sameAs edges produced by resolution (append-only reset)."""
    try:
        deleted = await asyncio.to_thread(ftm_store.delete_edges_for_dataset, RESOLUTION_DATASET)
        return {"ok": True, "deleted_edges": deleted, "dataset": RESOLUTION_DATASET}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"resolution reset failed: {exc}") from exc
