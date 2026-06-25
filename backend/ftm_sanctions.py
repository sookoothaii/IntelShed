"""OpenSanctions adapter and legacy entity_store schema mapping.

Converts ``targets.simple.csv`` rows into FtM entities and provides the
``_LEGACY_SCHEMA`` mapping used by ``upsert_legacy``.
"""

from __future__ import annotations

import csv
import os


from ftm_query import upsert, _proxy_with_id


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
    from ftm_connection import _LOCK

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
