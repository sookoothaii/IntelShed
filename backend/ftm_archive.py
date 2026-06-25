"""FtM tiered archival — export stale entities to Parquet, reload on demand (I6).

Entities with zero edges older than WORLDBASE_FTM_ARCHIVE_DAYS are exported
to monthly Parquet files in data/archive/ and deleted from DuckDB.
Archive manifest tracked in data/archive/manifest.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_config as _cfg

_ARCHIVE_DIR = Path(
    os.getenv("WORLDBASE_ARCHIVE_DIR", "")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "archive")
).resolve()


def archive_dir() -> Path:
    return _ARCHIVE_DIR


def manifest_path() -> Path:
    return _ARCHIVE_DIR / "manifest.json"


def _load_manifest() -> dict[str, Any]:
    try:
        return json.loads(manifest_path().read_text(encoding="utf-8"))
    except Exception:
        return {"archives": []}


def _save_manifest(manifest: dict[str, Any]) -> None:
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8"
    )


def _duckdb_path() -> str:
    raw = os.getenv("WORLDBASE_DUCKDB_PATH", "").strip()
    if raw:
        return raw
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.duckdb"
    )


def archive_stale_entities(dry_run: bool = False) -> dict[str, Any]:
    """Export entities with zero edges older than archive_days to Parquet.

    Returns summary dict with counts and file paths.
    """
    cfg = _cfg()
    archive_days = cfg.ftm_archive_days
    if archive_days <= 0:
        return {"enabled": False, "reason": "WORLDBASE_FTM_ARCHIVE_DAYS=0 (off)"}

    try:
        import duckdb
    except ImportError:
        return {"enabled": False, "error": "duckdb not installed"}

    db_path = _duckdb_path()
    if not os.path.exists(db_path):
        return {"enabled": False, "error": f"duckdb not found: {db_path}"}

    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    cutoff = (now - _dt_days(archive_days)).isoformat()

    con = duckdb.connect(db_path, read_only=True)

    # Find entities with zero edges, older than cutoff
    stale = con.execute(
        """
        SELECT e.id, e.schema, e.caption, e.properties, e.datasets,
               e.first_seen, e.last_seen, e.lat, e.lon
        FROM entities e
        WHERE e.last_seen < ?
          AND e.id NOT IN (SELECT source_id FROM edges)
          AND e.id NOT IN (SELECT target_id FROM edges)
        """,
        [cutoff],
    ).fetchall()

    if not stale:
        con.close()
        return {
            "enabled": True,
            "archived": 0,
            "dry_run": dry_run,
            "cutoff": cutoff,
        }

    # Group by schema + month for file naming
    rows: list[dict[str, Any]] = []
    for r in stale:
        rows.append(
            {
                "id": r[0],
                "schema": r[1],
                "caption": r[2],
                "properties": r[3],
                "datasets": r[4],
                "first_seen": r[5],
                "last_seen": r[6],
                "lat": r[7],
                "lon": r[8],
            }
        )

    con.close()

    # Write Parquet files grouped by schema
    by_schema: dict[str, list[dict]] = {}
    for row in rows:
        by_schema.setdefault(row["schema"] or "Unknown", []).append(row)

    month_tag = now.strftime("%Y-%m")
    files_written: list[str] = []
    total_archived = 0

    for schema, group in by_schema.items():
        safe_schema = schema.replace(" ", "_").replace("/", "_")
        fname = f"ftm_{safe_schema}_{month_tag}.parquet"
        fpath = _ARCHIVE_DIR / fname

        try:
            con_write = duckdb.connect(db_path)
            con_write.execute(
                f"""
                COPY (
                    SELECT * FROM (VALUES {','.join(['(?,?,?,?,?,?,?,?,?)'] * len(group))})
                    AS t(id, schema, caption, properties, datasets, first_seen, last_seen, lat, lon)
                ) TO '{fpath.as_posix()}' (FORMAT PARQUET);
                """,
                [v for row in group for v in (
                    row["id"], row["schema"], row["caption"], row["properties"],
                    row["datasets"], row["first_seen"], row["last_seen"],
                    row["lat"], row["lon"],
                )],
            )
            con_write.close()
            files_written.append(str(fpath))
            total_archived += len(group)
        except Exception as e:
            # Fail-soft: skip this schema group
            print(f"[ARCHIVE] write failed for {schema}: {e}", flush=True)

    if dry_run:
        return {
            "enabled": True,
            "dry_run": True,
            "would_archive": total_archived,
            "cutoff": cutoff,
            "files": files_written,
        }

    # Delete archived entities from DuckDB
    archived_ids = [r["id"] for r in rows]
    try:
        con_del = duckdb.connect(db_path)
        for eid in archived_ids:
            con_del.execute("DELETE FROM statements WHERE entity_id = ?", [eid])
            con_del.execute("DELETE FROM entities WHERE id = ?", [eid])
        con_del.close()
    except Exception as e:
        print(f"[ARCHIVE] delete failed: {e}", flush=True)
        return {
            "enabled": True,
            "archived": 0,
            "exported": total_archived,
            "error": f"export ok, delete failed: {e}",
            "files": files_written,
        }

    # Update manifest
    manifest = _load_manifest()
    manifest["archives"].append(
        {
            "month": month_tag,
            "archived_at": now.isoformat(),
            "entity_count": total_archived,
            "files": files_written,
            "cutoff": cutoff,
            "schemas": list(by_schema.keys()),
        }
    )
    _save_manifest(manifest)

    return {
        "enabled": True,
        "archived": total_archived,
        "cutoff": cutoff,
        "files": files_written,
        "schemas": list(by_schema.keys()),
    }


def reload_archive(month: str) -> dict[str, Any]:
    """Reload archived entities from Parquet back into DuckDB."""
    try:
        import duckdb
    except ImportError:
        return {"error": "duckdb not installed"}

    db_path = _duckdb_path()
    if not os.path.exists(db_path):
        return {"error": f"duckdb not found: {db_path}"}

    manifest = _load_manifest()
    entry = None
    for a in manifest.get("archives", []):
        if a.get("month") == month:
            entry = a
            break

    if not entry:
        return {"error": f"no archive found for month {month}"}

    files = entry.get("files", [])
    if not files:
        return {"error": f"no files in archive for month {month}"}

    total_reloaded = 0
    errors: list[str] = []

    for fpath in files:
        if not os.path.exists(fpath):
            errors.append(f"file missing: {fpath}")
            continue
        try:
            con = duckdb.connect(db_path)
            con.execute(
                f"""
                INSERT OR REPLACE INTO entities
                SELECT id, schema, caption, properties, datasets, first_seen, last_seen, lat, lon
                FROM read_parquet('{fpath}')
                """
            )
            count = con.execute(
                f"SELECT count(*) FROM read_parquet('{fpath}')"
            ).fetchone()[0]
            total_reloaded += count
            con.close()
        except Exception as e:
            errors.append(f"{fpath}: {e}")

    return {
        "reloaded": total_reloaded,
        "month": month,
        "files_processed": len(files) - len(errors),
        "errors": errors or None,
    }


def archive_stats() -> dict[str, Any]:
    """Return archive directory stats for health endpoint."""
    manifest = _load_manifest()
    total_size = 0
    file_count = 0
    if _ARCHIVE_DIR.exists():
        for f in _ARCHIVE_DIR.glob("*.parquet"):
            total_size += f.stat().st_size
            file_count += 1
    return {
        "dir": str(_ARCHIVE_DIR),
        "file_count": file_count,
        "size_mb": round(total_size / (1024 * 1024), 2),
        "archive_entries": len(manifest.get("archives", [])),
    }


def duckdb_size_mb() -> float:
    """Return DuckDB file size in MB."""
    db_path = _duckdb_path()
    try:
        return round(os.path.getsize(db_path) / (1024 * 1024), 2)
    except Exception:
        return 0.0


def _dt_days(days: int):
    from datetime import timedelta

    return timedelta(days=days)
