"""OpenSanctions / FollowTheMoney bridge — local-first, no paid API required.

WorldBase keeps its "no purchase" philosophy: we ship a free, offline-first
sanctions matcher that downloads the public OpenSanctions ``default`` dataset
CSV (CC-BY) once a day, caches it on disk and does in-memory fuzzy matching.

Optional paths (no code change needed, just env vars):

* ``OPENSANCTIONS_API_KEY`` — use the hosted /match REST API for very high
  recall fuzzy matching (0.10 EUR / call, only for users who already pay).
* ``OPENSANCTIONS_YENTE_URL`` — point at a self-hosted yente Docker stack
  (free for unlimited queries; the operator runs it themselves).

Endpoints:

* ``GET /api/sanctions/status`` — dataset freshness + entry counts
* ``POST /api/sanctions/refresh`` — force a re-download (background)
* ``GET /api/sanctions/search?q=...&schema=...&limit=...`` — local fuzzy search
* ``GET /api/sanctions/screen/vessels`` — cross-match current AIS feed against
  the watchlist; returns vessels flagged with reasons + datasets

This is intentionally read-only / non-destructive: a missed match is preferred
over a false positive, and the dataset itself is never written back to disk
outside of ``data/sanctions/``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Query

router = APIRouter(prefix="/api/sanctions", tags=["sanctions"])

_DATA_DIR = Path(os.getenv("WORLDBASE_SANCTIONS_DIR") or (Path(__file__).resolve().parent.parent / "data" / "sanctions"))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_CSV_PATH = _DATA_DIR / "targets.simple.csv"
_META_PATH = _DATA_DIR / "targets.meta.json"

# OpenSanctions default dataset = consolidated sanctions list (no PEPs).
# CSV is ~30 MB, refreshed daily. CC-BY 4.0 license.
_DEFAULT_CSV = os.getenv(
    "OPENSANCTIONS_CSV_URL",
    "https://data.opensanctions.org/datasets/latest/default/targets.simple.csv",
)
_DOWNLOAD_TIMEOUT = 120.0
_REFRESH_INTERVAL = 24 * 3600

_YENTE_URL = os.getenv("OPENSANCTIONS_YENTE_URL", "").rstrip("/")
_API_KEY = os.getenv("OPENSANCTIONS_API_KEY", "")
_API_URL = os.getenv("OPENSANCTIONS_API_URL", "https://api.opensanctions.org").rstrip("/")

_UA = {"User-Agent": "WorldBase/1.0 (sanctions screener; CC-BY default dataset)"}

# In-memory index:
#   {"by_name": {normalized: [row,...]}, "by_id_token": {identifier: row}, "rows": [...]}
_INDEX: dict[str, Any] = {"by_name": {}, "by_id_token": {}, "rows": [], "loaded_at": 0.0}
_INDEX_LOCK = asyncio.Lock()


def _normalize_name(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _name_tokens(s: str) -> set[str]:
    return {t for t in _normalize_name(s).split(" ") if len(t) >= 3}


def _row_names(row: dict) -> list[str]:
    primary = (row.get("name") or "").strip()
    aliases = (row.get("aliases") or "").strip()
    names = [primary] if primary else []
    if aliases:
        names.extend([a.strip() for a in re.split(r";\s*|\|\s*", aliases) if a.strip()])
    return names


def _row_identifiers(row: dict) -> list[str]:
    out: list[str] = []
    for field in ("identifiers", "registration_number", "tax_number", "imo_number", "mmsi"):
        v = (row.get(field) or "").strip()
        if not v:
            continue
        out.extend([t.strip() for t in re.split(r"[;,|\s]+", v) if t.strip()])
    return out


def _is_csv_fresh() -> bool:
    if not _CSV_PATH.exists():
        return False
    return (time.time() - _CSV_PATH.stat().st_mtime) < _REFRESH_INTERVAL


async def _download_csv() -> dict:
    """Download the OpenSanctions default targets CSV (best-effort)."""
    started = time.time()
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, headers=_UA, follow_redirects=True) as client:
            r = await client.get(_DEFAULT_CSV)
            r.raise_for_status()
            blob = r.content
    except Exception as e:
        return {"ok": False, "error": str(e), "url": _DEFAULT_CSV}
    _CSV_PATH.write_bytes(blob)
    meta = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "bytes": len(blob),
        "url": _DEFAULT_CSV,
        "elapsed_sec": round(time.time() - started, 2),
    }
    _META_PATH.write_text(__import__("json").dumps(meta))
    return {"ok": True, **meta}


def _load_index_from_disk() -> dict:
    """(Re)build the in-memory index from the cached CSV file."""
    if not _CSV_PATH.exists():
        return {"by_name": {}, "by_id_token": {}, "rows": [], "loaded_at": 0.0}
    rows: list[dict] = []
    by_name: dict[str, list[dict]] = {}
    by_id: dict[str, dict] = {}
    with _CSV_PATH.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = {
                "id": raw.get("id") or "",
                "schema": raw.get("schema") or "",
                "name": raw.get("name") or "",
                "aliases": raw.get("aliases") or "",
                "countries": raw.get("countries") or "",
                "topics": raw.get("topics") or "",
                "datasets": raw.get("dataset") or raw.get("datasets") or "",
                "sanctions": raw.get("sanctions") or "",
                "first_seen": raw.get("first_seen") or "",
                "last_seen": raw.get("last_seen") or "",
                "identifiers": raw.get("identifiers") or "",
                "registration_number": raw.get("registration_number") or "",
                "tax_number": raw.get("tax_number") or "",
                "imo_number": raw.get("imo_number") or "",
                "mmsi": raw.get("mmsi") or "",
                "addresses": raw.get("addresses") or "",
            }
            rows.append(row)
            for name in _row_names(row):
                norm = _normalize_name(name)
                if norm:
                    by_name.setdefault(norm, []).append(row)
            for ident in _row_identifiers(row):
                by_id.setdefault(ident.lower(), row)
    return {
        "by_name": by_name,
        "by_id_token": by_id,
        "rows": rows,
        "loaded_at": time.time(),
    }


async def _ensure_index(refresh: bool = False) -> dict:
    """Lazy: download once, parse once, keep in memory."""
    async with _INDEX_LOCK:
        if _INDEX["rows"] and not refresh:
            return _INDEX
        if refresh or not _is_csv_fresh():
            await _download_csv()
        new_idx = _load_index_from_disk()
        _INDEX["by_name"] = new_idx["by_name"]
        _INDEX["by_id_token"] = new_idx["by_id_token"]
        _INDEX["rows"] = new_idx["rows"]
        _INDEX["loaded_at"] = new_idx["loaded_at"]
    return _INDEX


def _serialize_row(row: dict, score: float | None = None, reasons: list[str] | None = None) -> dict:
    out = {
        "entity_id": row.get("id"),
        "schema": row.get("schema"),
        "caption": row.get("name"),
        "aliases": [a.strip() for a in re.split(r";\s*|\|\s*", row.get("aliases") or "") if a.strip()],
        "countries": [c.strip() for c in re.split(r";\s*|,\s*", row.get("countries") or "") if c.strip()],
        "topics": [t.strip() for t in re.split(r";\s*|,\s*", row.get("topics") or "") if t.strip()],
        "datasets": [d.strip() for d in re.split(r";\s*|,\s*", row.get("datasets") or "") if d.strip()],
        "sanctions": row.get("sanctions"),
        "identifiers": _row_identifiers(row),
        "first_seen": row.get("first_seen"),
        "last_seen": row.get("last_seen"),
        "url": f"https://www.opensanctions.org/entities/{row.get('id', '')}/" if row.get("id") else None,
    }
    if score is not None:
        out["score"] = round(float(score), 4)
    if reasons:
        out["reasons"] = reasons
    return out


def _fuzzy_score(query_norm: str, candidate_norm: str) -> float:
    """Jaccard token overlap + substring boost — cheap, no extra deps."""
    if not query_norm or not candidate_norm:
        return 0.0
    if query_norm == candidate_norm:
        return 1.0
    qt = set(query_norm.split())
    ct = set(candidate_norm.split())
    if not qt or not ct:
        return 0.0
    inter = qt & ct
    if not inter:
        return 0.0
    jacc = len(inter) / len(qt | ct)
    boost = 0.15 if query_norm in candidate_norm or candidate_norm in query_norm else 0.0
    # Require that at least one significant token overlaps to keep precision
    if all(len(t) < 4 for t in inter):
        return min(0.55, jacc + boost)
    return min(1.0, jacc + boost)


async def _local_search(q: str, schema: str | None, limit: int) -> list[dict]:
    idx = await _ensure_index()
    if not idx["rows"]:
        return []
    qnorm = _normalize_name(q)
    if not qnorm:
        return []
    # 1. Identifier match (IMO/MMSI/reg)
    ident_hit = idx["by_id_token"].get(q.strip().lower())
    out: list[tuple[float, list[str], dict]] = []
    if ident_hit:
        if not schema or ident_hit.get("schema", "").lower() == schema.lower():
            out.append((1.0, [f"identifier match: {q}"], ident_hit))
    # 2. Exact normalized name hit
    for row in idx["by_name"].get(qnorm, []):
        if schema and row.get("schema", "").lower() != schema.lower():
            continue
        out.append((1.0, ["exact name match"], row))
    # 3. Token fuzzy
    qt = _name_tokens(q)
    if qt:
        seen = {r["id"] for _, _, r in out if r.get("id")}
        for cand_norm, rows in idx["by_name"].items():
            if not (qt & _name_tokens(cand_norm)):
                continue
            score = _fuzzy_score(qnorm, cand_norm)
            if score < 0.55:
                continue
            for r in rows:
                if r.get("id") in seen:
                    continue
                if schema and r.get("schema", "").lower() != schema.lower():
                    continue
                out.append((score, [f"fuzzy match ({cand_norm})"], r))
                seen.add(r.get("id"))
    out.sort(key=lambda x: -x[0])
    return [_serialize_row(r, score=s, reasons=rs) for s, rs, r in out[:limit]]


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
async def sanctions_status():
    """Report dataset freshness, entry count, and which backend is active."""
    backend = "local-csv"
    if _YENTE_URL:
        backend = "yente"
    elif _API_KEY:
        backend = "opensanctions-hosted"
    csv_exists = _CSV_PATH.exists()
    csv_size = _CSV_PATH.stat().st_size if csv_exists else 0
    age = (time.time() - _CSV_PATH.stat().st_mtime) if csv_exists else None
    idx_rows = len(_INDEX.get("rows") or [])
    return {
        "backend": backend,
        "yente_url": _YENTE_URL or None,
        "hosted_api_configured": bool(_API_KEY),
        "csv": {
            "exists": csv_exists,
            "path": str(_CSV_PATH),
            "size_mb": round(csv_size / 1_048_576, 2),
            "age_sec": round(age, 1) if age else None,
            "fresh": _is_csv_fresh(),
        },
        "index_rows": idx_rows,
        "source_url": _DEFAULT_CSV,
        "license": "CC-BY 4.0 (OpenSanctions default dataset)",
    }


@router.post("/refresh")
async def sanctions_refresh(background_tasks: BackgroundTasks):
    """Trigger a (background) re-download of the default CSV."""
    async def _do():
        await _ensure_index(refresh=True)
    background_tasks.add_task(_do)
    return {"queued": True, "url": _DEFAULT_CSV}


@router.get("/search")
async def sanctions_search(
    q: str = Query(..., min_length=2, description="name, alias, IMO or MMSI"),
    schema: str | None = Query(None, description="filter: Person, Company, Vessel, Organization, Address"),
    limit: int = Query(10, ge=1, le=50),
):
    """Local-first sanctions search. Falls back to yente if configured."""
    if _YENTE_URL:
        url = f"{_YENTE_URL}/search/default"
        params = {"q": q, "limit": limit}
        if schema:
            params["schema"] = schema
        try:
            async with httpx.AsyncClient(timeout=15.0, headers=_UA) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                return {"backend": "yente", **r.json()}
        except Exception as e:
            # graceful fallback to local
            local = await _local_search(q, schema, limit)
            return {"backend": "yente->local", "error": str(e), "query": q, "count": len(local), "results": local}
    results = await _local_search(q, schema, limit)
    return {"backend": "local-csv", "query": q, "schema": schema, "count": len(results), "results": results}


def _vessel_query_terms(vessel: dict) -> list[str]:
    terms = []
    if vessel.get("name"):
        terms.append(str(vessel["name"]).strip())
    if vessel.get("mmsi"):
        terms.append(str(vessel["mmsi"]).strip())
    if vessel.get("imo"):
        terms.append(str(vessel["imo"]).strip())
    return [t for t in terms if t and t.lower() != "unknown"]


async def screen_vessels(vessels: list[dict], min_score: float = 0.75) -> list[dict]:
    """Match each vessel against the local index. Returns only hits (>= min_score)."""
    idx = await _ensure_index()
    if not idx["rows"] or not vessels:
        return []
    hits: list[dict] = []
    for v in vessels:
        for term in _vessel_query_terms(v):
            results = await _local_search(term, schema="Vessel", limit=3)
            best = None
            for r in results:
                score = r.get("score", 0.0)
                if score >= min_score and (best is None or score > best.get("score", 0.0)):
                    best = r
            if not best:
                # also try without schema filter to catch Organization-shaped ship operators
                results = await _local_search(term, schema=None, limit=3)
                for r in results:
                    score = r.get("score", 0.0)
                    if score >= min_score and (best is None or score > best.get("score", 0.0)):
                        best = r
            if best:
                hits.append({
                    "vessel": {
                        "mmsi": v.get("mmsi"),
                        "name": v.get("name"),
                        "flag": v.get("flag"),
                        "type": v.get("type"),
                        "lat": v.get("lat"),
                        "lon": v.get("lon"),
                        "destination": v.get("destination"),
                    },
                    "matched_term": term,
                    "sanction": best,
                })
                break  # one hit per vessel is enough
    return hits


@router.get("/screen/vessels")
async def sanctions_screen_vessels(
    min_score: float = Query(0.80, ge=0.0, le=1.0),
    limit: int = Query(200, ge=1, le=2000),
):
    """Cross-match the live AIS feed against the sanctions index."""
    import ais_bridge
    try:
        maritime = await ais_bridge.get_maritime()
    except Exception as e:
        return {"error": f"AIS feed unavailable: {e}", "matches": []}
    vessels = (maritime.get("vessels") or [])[:limit]
    hits = await screen_vessels(vessels, min_score=min_score)
    return {
        "scanned": len(vessels),
        "min_score": min_score,
        "matches": hits,
        "count": len(hits),
        "demo_mode": maritime.get("demo_mode", False),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
