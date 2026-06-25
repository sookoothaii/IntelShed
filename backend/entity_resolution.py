"""Splink entity resolution -> provenance-aware ``sameAs`` edges in FtM.

Matches duplicate Person / Organization / Company / Vessel records across
datasets and writes ``sameAs`` edges with ``confidence`` + ``method`` metadata.
Deterministic exact-name matches run first; Splink adds fuzzy pairs when enough
rows exist. Splink is lazy-imported (``pip install splink``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import ftm_store

logger = logging.getLogger(__name__)

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
_PIPELINE_MODE = os.getenv("WORLDBASE_ENTITY_RESOLUTION_PIPELINE", "single").strip().lower()

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

# ---------------------------------------------------------------------------
# Model persistence (P2+ dual-pipeline)
# ---------------------------------------------------------------------------

_MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_AMBIGUOUS_MIN = float(os.getenv("WORLDBASE_ENTITY_RESOLUTION_AMBIGUOUS_MIN", "0.60"))
_AMBIGUOUS_MAX = float(os.getenv("WORLDBASE_ENTITY_RESOLUTION_AMBIGUOUS_MAX", "0.84"))


def _model_path(schema: str) -> str:
    return os.path.join(_MODEL_DIR, f"splink_model_{schema}.json")


def _model_exists(schema: str) -> bool:
    return os.path.isfile(_model_path(schema))


def _should_run_splink(schema: str) -> bool:
    """True if Splink should run for this schema.

    If a trained model exists, prediction is cheap (no retraining) → run even
    when ``_SPLINK_ENABLED`` is off.  Otherwise fall back to the env gate.
    """
    return _SPLINK_ENABLED or _model_exists(schema)


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
        email = _normalize_token(_first(props.get("email")))
        alias = _normalize_token(_first(props.get("alias")) or _first(props.get("weakAlias")))
        rows.append({
            "unique_id": ent["id"],
            "entity_id": ent["id"],
            "name": name,
            "name_last": toks[-1] if toks else name,
            "country": country or None,
            "imo_number": imo or None,
            "email": email or None,
            "username": alias or None,
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


def _build_comparisons_and_blocking(schema: str, df: "pd.DataFrame") -> tuple[list, list]:
    """Build Splink comparisons and blocking rules for a schema.

    Extracted so both ``train_model`` and ``_run_splink_schema`` share the same
    comparison configuration.  OSINT comparisons (JaroWinkler on username,
    Levenshtein on email) are added when the column has usable data.
    """
    import splink.comparison_library as cl
    from splink import block_on

    comparisons = [cl.NameComparison("name")]
    blocking = [block_on("substr(name, 1, 4)"), block_on("name_last")]
    if schema == "Vessel":
        comparisons.append(cl.ExactMatch("imo_number"))
        blocking.append(block_on("imo_number"))
    if df["country"].notna().any() and (df["country"] != "").any():
        comparisons.append(cl.ExactMatch("country"))
        blocking.append(block_on("country"))
    if "email" in df.columns and df["email"].notna().any() and (df["email"] != "").any():
        comparisons.append(cl.LevenshteinAtThresholds("email"))
        blocking.append(block_on("substr(email, 1, 4)"))
    if "username" in df.columns and df["username"].notna().any() and (df["username"] != "").any():
        comparisons.append(cl.JaroWinklerAtThresholds("username"))
        blocking.append(block_on("substr(username, 1, 3)"))
    return comparisons, blocking


def train_model(schema: str) -> dict:
    """Train Splink model for a schema and persist settings to JSON.

    Runs u-sampling + EM on all entities of the given schema, then saves the
    trained settings to ``data/splink_model_{schema}.json``.  Future resolution
    runs will load this model instead of retraining.
    """
    entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA)
    rows = _rows_for_schema(schema, entities)
    if len(rows) < _MIN_ROWS_SPLINK:
        return {"ok": False, "error": f"insufficient rows: {len(rows)} < {_MIN_ROWS_SPLINK}", "schema": schema}

    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker, SettingsCreator
    except ImportError as exc:
        raise RuntimeError("splink not installed — pip install 'splink>=4.0,<5'") from exc

    global _SPLINK_VERSION
    import splink as _splink_mod
    _SPLINK_VERSION = getattr(_splink_mod, "__version__", None)

    df = pd.DataFrame(rows)
    comparisons, blocking = _build_comparisons_and_blocking(schema, df)

    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=blocking,
        probability_two_random_records_match=0.02,
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())

    if len(df) >= _EM_MIN_ROWS:
        linker.training.estimate_u_using_random_sampling(
            max_pairs=min(1_000_000, len(df) * 20)
        )
        try:
            linker.training.estimate_parameters_using_expectation_maximization(
                blocking_rules_to_train_blocking=blocking,
            )
        except Exception:
            logger.warning("EM training failed for %s — continuing with u-sampling only", schema)

    path = _model_path(schema)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    linker.misc.save_model_to_json(path)

    return {
        "ok": True,
        "schema": schema,
        "rows": len(rows),
        "model_path": path,
        "splink_version": _SPLINK_VERSION,
    }


def _run_splink_schema(schema: str, rows: list[dict], seen_pairs: set[tuple[str, str, str]]) -> int:
    if len(rows) < _MIN_ROWS_SPLINK:
        return 0
    try:
        import pandas as pd
        from splink import DuckDBAPI, Linker, SettingsCreator
    except ImportError as exc:
        raise RuntimeError("splink not installed — pip install 'splink>=4.0,<5'") from exc

    global _SPLINK_VERSION
    import splink as _splink_mod

    _SPLINK_VERSION = getattr(_splink_mod, "__version__", None)

    df = pd.DataFrame(rows)
    model_path = _model_path(schema)
    if os.path.isfile(model_path):
        linker = Linker(df, model_path, db_api=DuckDBAPI())
    else:
        comparisons, blocking = _build_comparisons_and_blocking(schema, df)
        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=comparisons,
            blocking_rules_to_generate_predictions=blocking,
            probability_two_random_records_match=0.02,
        )
        linker = Linker(df, settings, db_api=DuckDBAPI())
        if len(df) >= _EM_MIN_ROWS:
            linker.training.estimate_u_using_random_sampling(
                max_pairs=min(1_000_000, len(df) * 20)
            )

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


def _run_splink_cross_dataset(
    schema: str,
    rows_a: list[dict],
    rows_b: list[dict],
    seen_pairs: set[tuple[str, str, str]],
) -> int:
    """Splink ``link_only`` between two dataset groups (cross-dataset linking).

    Unlike ``_run_splink_schema`` which uses ``dedupe_only``, this expects two
    pre-filtered row sets from different datasets and only looks for cross-
    dataset matches (no within-dataset duplicates).
    """
    if len(rows_a) < _MIN_ROWS_SPLINK or len(rows_b) < _MIN_ROWS_SPLINK:
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

    df_a = pd.DataFrame(rows_a)
    df_b = pd.DataFrame(rows_b)
    df_a["source_dataset"] = "a"
    df_b["source_dataset"] = "b"
    df = pd.concat([df_a, df_b], ignore_index=True)

    comparisons = [cl.NameComparison("name")]
    blocking = [block_on("substr(name, 1, 4)"), block_on("name_last")]
    if schema == "Vessel":
        comparisons.append(cl.ExactMatch("imo_number"))
        blocking.append(block_on("imo_number"))
    if df["country"].notna().any() and (df["country"] != "").any():
        comparisons.append(cl.ExactMatch("country"))
        blocking.append(block_on("country"))

    settings = SettingsCreator(
        link_type="link_only",
        comparisons=comparisons,
        blocking_rules_to_generate_predictions=blocking,
        probability_two_random_records_match=0.02,
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())

    if len(df) >= _EM_MIN_ROWS:
        linker.training.estimate_u_using_random_sampling(
            max_pairs=min(1_000_000, len(df) * 20)
        )

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
            left, right, confidence=prob, method="splink:cross", schema=schema, seen_pairs=seen_pairs,
        ):
            added += 1
    return added


def _run_two_stage_schema(
    schema: str,
    seen_pairs: set[tuple[str, str, str]],
    errors: list[str],
) -> tuple[int, int, int, int]:
    """Two-stage resolution for one schema.

    Stage 1: Per-dataset dedupe — exact + subset + splink(dedupe_only) within
    each dataset independently.
    Stage 2: Cross-dataset link — splink(link_only) between coherent dataset
    pairs to find the same entity across feeds.

    Returns (exact_edges, subset_edges, splink_edges, cross_edges).
    """
    datasets = ftm_store.list_datasets_for_schema([schema])
    if not datasets:
        # No dataset labels — fall back to single-mode behaviour
        entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA)
        rows = _rows_for_schema(schema, entities)
        exact = _run_exact_matches(schema, entities, seen_pairs)
        subset = _run_subset_matches(schema, entities, seen_pairs)
        splink = 0
        if _should_run_splink(schema):
            try:
                splink = _run_splink_schema(schema, rows, seen_pairs)
            except Exception:
                if len(errors) < 5:
                    errors.append(f"{schema}: dedupe splink failed")
                logger.exception("splink dedupe failed for schema %s", schema)
        return exact, subset, splink, 0

    total_exact = 0
    total_subset = 0
    total_splink = 0
    total_cross = 0

    # Stage 1: per-dataset dedupe
    dataset_rows: dict[str, list[dict]] = {}
    for ds in datasets:
        entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA, dataset=ds)
        if not entities:
            continue
        rows = _rows_for_schema(schema, entities)
        dataset_rows[ds] = rows
        total_exact += _run_exact_matches(schema, entities, seen_pairs)
        total_subset += _run_subset_matches(schema, entities, seen_pairs)
        if _should_run_splink(schema) and len(rows) >= _MIN_ROWS_SPLINK:
            try:
                total_splink += _run_splink_schema(schema, rows, seen_pairs)
            except Exception:
                if len(errors) < 5:
                    errors.append(f"{schema}/{ds}: dedupe splink failed")
                logger.exception("splink dedupe failed for %s/%s", schema, ds)

    # Stage 2: cross-dataset link
    # Run deterministic exact+subset across dataset pairs first (always-on),
    # then Splink link_only if enabled.
    viable = list(dataset_rows.keys())
    for i in range(len(viable)):
        for j in range(i + 1, len(viable)):
            ds_a, ds_b = viable[i], viable[j]
            entities_a = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA, dataset=ds_a)
            entities_b = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA, dataset=ds_b)
            combined = entities_a + entities_b
            total_exact += _run_exact_matches(schema, combined, seen_pairs)
            total_subset += _run_subset_matches(schema, combined, seen_pairs)
            if _should_run_splink(schema):
                try:
                    total_cross += _run_splink_cross_dataset(
                        schema, dataset_rows[ds_a], dataset_rows[ds_b], seen_pairs,
                    )
                except Exception:
                    if len(errors) < 5:
                        errors.append(f"{schema}: cross {ds_a}↔{ds_b} failed")
                    logger.exception(
                        "splink cross-dataset failed for %s (%s ↔ %s)",
                        schema, ds_a, ds_b,
                    )

    return total_exact, total_subset, total_splink, total_cross


def run_resolution(
    *,
    schemas: tuple[str, ...] | None = None,
    pipeline_mode: str | None = None,
) -> dict:
    """Run deterministic + Splink resolution for configured schemas.

    *pipeline_mode* overrides the env default. ``"single"`` runs the classic
    all-entities-mixed path. ``"two_stage"`` runs per-dataset dedupe first,
    then cross-dataset ``link_only`` Splink between coherent dataset pairs.
    """
    global _LAST_RUN, _LAST_ERROR
    mode = (pipeline_mode or _PIPELINE_MODE).strip().lower()
    schema_list = schemas or RESOLUTION_SCHEMAS
    started = _now()
    seen_pairs: set[tuple[str, str, str]] = set()
    per_schema: dict[str, dict[str, int]] = {}
    total_exact = 0
    total_subset = 0
    total_splink = 0
    total_cross = 0
    errors: list[str] = []

    with _LOCK:
        try:
            for schema in schema_list:
                if mode == "two_stage":
                    _exact, _subset, _splink, _cross = _run_two_stage_schema(
                        schema, seen_pairs, errors,
                    )
                else:
                    entities = ftm_store.list_entities_for_resolution([schema], _LIMIT_PER_SCHEMA)
                    rows = _rows_for_schema(schema, entities)
                    _exact = _run_exact_matches(schema, entities, seen_pairs)
                    _subset = _run_subset_matches(schema, entities, seen_pairs)
                    _splink = 0
                    if _should_run_splink(schema):
                        try:
                            _splink = _run_splink_schema(schema, rows, seen_pairs)
                        except Exception:
                            if len(errors) < 5:
                                errors.append(f"{schema}: resolution failed")
                            logger.exception("splink resolution failed for schema %s", schema)
                    _cross = 0

                per_schema[schema] = {
                    "candidates": 0,
                    "rows": 0,
                    "exact_edges": _exact,
                    "subset_edges": _subset,
                    "splink_edges": _splink,
                    "cross_edges": _cross,
                }
                total_exact += _exact
                total_subset += _subset
                total_splink += _splink
                total_cross += _cross

            result = {
                "ok": True,
                "started_at": started,
                "finished_at": _now(),
                "pipeline_mode": mode,
                "threshold": _THRESHOLD,
                "exact_confidence": _EXACT_CONFIDENCE,
                "subset_confidence": _SUBSET_CONFIDENCE,
                "splink_enabled": _SPLINK_ENABLED,
                "schemas": list(schema_list),
                "per_schema": per_schema,
                "edges_added": total_exact + total_subset + total_splink + total_cross,
                "exact_edges": total_exact,
                "subset_edges": total_subset,
                "splink_edges": total_splink,
                "cross_edges": total_cross,
                "resolution_edges_total": ftm_store.count_edges_for_dataset(RESOLUTION_DATASET),
                "splink_version": _SPLINK_VERSION,
                "errors": errors,
            }
            _LAST_RUN = result
            _LAST_ERROR = errors[0] if errors else None
            return result
        except Exception:
            _LAST_ERROR = "resolution run failed"
            logger.exception("resolution run failed")
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
    models = {}
    for s in RESOLUTION_SCHEMAS:
        if _model_exists(s):
            models[s] = _model_path(s)
    return {
        "available": splink_ok,
        "splink_enabled": _SPLINK_ENABLED,
        "splink_version": splink_version,
        "models": models,
        "autopilot": autopilot_on(),
        "interval_sec": _AUTOPILOT_INTERVAL,
        "threshold": _THRESHOLD,
        "ambiguous_range": [_AMBIGUOUS_MIN, _AMBIGUOUS_MAX],
        "schemas": list(RESOLUTION_SCHEMAS),
        "resolution_edges": ftm_store.count_edges_for_dataset(RESOLUTION_DATASET),
        "last_run": _LAST_RUN,
        "last_error": _LAST_ERROR,
    }


# ---------------------------------------------------------------------------
# Human-in-the-loop Grauzonen (P2+)
# ---------------------------------------------------------------------------

def list_ambiguous_pairs(
    schema: str | None = None,
    *,
    min_prob: float | None = None,
    max_prob: float | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return resolution edges in the Grauzonen (ambiguous) confidence band.

    Pairs with confidence between ``_AMBIGUOUS_MIN`` and ``_AMBIGUOUS_MAX``
    that have not yet been labeled.  These are candidates for human review.
    """
    lo = min_prob if min_prob is not None else _AMBIGUOUS_MIN
    hi = max_prob if max_prob is not None else _AMBIGUOUS_MAX
    from ftm_connection import _LOCK, _conn
    schema_clause = ""
    params: list = [RESOLUTION_DATASET, lo, hi]
    if schema:
        schema_clause = " AND json_extract_string(properties, '$.schema') = ?"
        params.append(schema)
    params.append(int(limit))
    with _LOCK:
        rows = _conn().execute(
            f"""
            SELECT source_id, target_id, confidence,
                   json_extract_string(properties, '$.method') AS method,
                   json_extract_string(properties, '$.schema') AS schema
            FROM edges
            WHERE dataset = ?
              AND confidence >= ?
              AND confidence <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM resolution_labels rl
                  WHERE rl.source_id = edges.source_id
                    AND rl.target_id = edges.target_id
              )
              {schema_clause}
            ORDER BY confidence DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "source_id": r[0],
            "target_id": r[1],
            "confidence": r[2],
            "method": r[3],
            "schema": r[4],
        }
        for r in rows
    ]


def label_pair(source_id: str, target_id: str, confirmed: bool, *, schema: str | None = None) -> dict:
    """Record a human label for an ambiguous pair.

    If ``confirmed`` is True, the edge is kept (and confidence bumped to
    ``_EXACT_CONFIDENCE``).  If False, the edge is deleted.
    """
    pair_id = f"{source_id}::{target_id}"
    from ftm_connection import _LOCK, _conn
    with _LOCK:
        _conn().execute(
            """
            INSERT OR REPLACE INTO resolution_labels
                (pair_id, source_id, target_id, schema, confidence, confirmed, labeled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [pair_id, source_id, target_id, schema, 0.0, confirmed, _now()],
        )
    if confirmed:
        with _LOCK:
            _conn().execute(
                "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND dataset = ?",
                [source_id, target_id, RESOLUTION_DATASET],
            )
        ftm_store.add_edge(
            source_id, target_id, RESOLUTION_KIND,
            dataset=RESOLUTION_DATASET,
            confidence=_EXACT_CONFIDENCE,
            properties={"method": "human-confirmed", "schema": schema or ""},
        )
    else:
        with _LOCK:
            _conn().execute(
                "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND dataset = ?",
                [source_id, target_id, RESOLUTION_DATASET],
            )
    return {"ok": True, "pair_id": pair_id, "confirmed": confirmed}


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException  # noqa: E402

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/intel/resolution", tags=["intel"])


@router.get("/status")
async def resolution_status():
    return status()


@router.post("/run")
async def resolution_run(
    pipeline: str | None = None,
    _auth: str | None = Depends(verify_lan_auth),
):
    try:
        return await asyncio.to_thread(run_resolution, pipeline_mode=pipeline)
    except Exception as exc:
        logger.exception("entity resolution failed")
        raise HTTPException(status_code=503, detail="entity resolution failed") from exc


@router.post("/train")
async def resolution_train(
    schema: str = "Person",
    _auth: str | None = Depends(verify_lan_auth),
):
    """Train and persist a Splink model for the given schema."""
    try:
        return await asyncio.to_thread(train_model, schema)
    except Exception as exc:
        logger.exception("model training failed for %s", schema)
        raise HTTPException(status_code=503, detail=f"training failed: {exc}") from exc


@router.get("/ambiguous")
async def resolution_ambiguous(
    schema: str | None = None,
    min: float | None = None,
    max: float | None = None,
    limit: int = 50,
):
    """List ambiguous pairs in the Grauzonen confidence band."""
    return list_ambiguous_pairs(schema, min_prob=min, max_prob=max, limit=limit)


@router.post("/label")
async def resolution_label(
    source_id: str,
    target_id: str,
    confirmed: bool = True,
    schema: str | None = None,
    _auth: str | None = Depends(verify_lan_auth),
):
    """Record a human label for an ambiguous pair."""
    try:
        return await asyncio.to_thread(label_pair, source_id, target_id, confirmed, schema=schema)
    except Exception as exc:
        logger.exception("labeling failed")
        raise HTTPException(status_code=503, detail="labeling failed") from exc


@router.post("/reset")
async def resolution_reset(_auth: str | None = Depends(verify_lan_auth)):
    """Delete all sameAs edges produced by resolution (append-only reset)."""
    try:
        deleted = await asyncio.to_thread(ftm_store.delete_edges_for_dataset, RESOLUTION_DATASET)
        return {"ok": True, "deleted_edges": deleted, "dataset": RESOLUTION_DATASET}
    except Exception as exc:
        logger.exception("resolution reset failed")
        raise HTTPException(status_code=503, detail="resolution reset failed") from exc
