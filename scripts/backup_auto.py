#!/usr/bin/env python3
"""intelshed DR Automation — backup, S3/MinIO upload, restore test.

Usage:
    python scripts/backup_auto.py                    # local backup only
    python scripts/backup_auto.py --upload-s3        # backup + upload to S3/MinIO
    python scripts/backup_auto.py --restore-test     # backup + verify restore
    python scripts/backup_auto.py --upload-s3 --restore-test

S3/MinIO config (env vars):
    WORLDBASE_S3_ENDPOINT   — e.g. http://127.0.0.1:9000 (MinIO) or https://s3.amazonaws.com
    WORLDBASE_S3_BUCKET     — bucket name
    WORLDBASE_S3_ACCESS_KEY — access key
    WORLDBASE_S3_SECRET_KEY — secret key
    WORLDBASE_S3_REGION     — region (default: us-east-1)

Exit codes:
    0 — success
    1 — backup failed
    2 — upload failed (backup ok)
    3 — restore test failed (backup ok)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _PROJECT_ROOT / "backend"
_DATA_DIR = _BACKEND / "data"

_DATA_FILES = [
    {"path": _BACKEND / "worldbase.db", "name": "sqlite-worldbase.db", "method": "vacuum"},
    {"path": _DATA_DIR / "entities.duckdb", "name": "duckdb-entities.duckdb", "method": "copy"},
    {"path": _DATA_DIR / "entities.duckdb.wal", "name": "duckdb-entities.duckdb.wal", "method": "copy"},
    {"path": _DATA_DIR / "fusion_events.parquet", "name": "fusion_events.parquet", "method": "copy"},
    {"path": _DATA_DIR / "intel_subgraph_latest.json", "name": "intel_subgraph_latest.json", "method": "copy"},
]

_ENV_FILE = _BACKEND / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[backup_auto] [{ts}] [{level}] {msg}", flush=True)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_size_mb(path: Path) -> float:
    return round(path.stat().st_size / (1024 * 1024), 2)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_sqlite_vacuum(src: Path, dst: Path) -> bool:
    """VACUUM INTO — consistent snapshot without locking the DB."""
    if not src.is_file():
        _log(f"SKIP (not found): {src}", "WARN")
        return False
    try:
        conn = sqlite3.connect(str(src))
        escaped = str(dst).replace("'", "''")
        conn.execute(f"VACUUM INTO '{escaped}'")
        conn.close()
        _log(f"OK ({_file_size_mb(dst)} MB): {src.name} -> {dst.name} (VACUUM INTO)")
        return True
    except Exception as exc:
        _log(f"VACUUM INTO failed, falling back to copy: {exc}", "WARN")
        return copy_file(src, dst)


def copy_file(src: Path, dst: Path) -> bool:
    if not src.is_file():
        _log(f"SKIP (not found): {src}", "WARN")
        return False
    shutil.copy2(src, dst)
    _log(f"OK ({_file_size_mb(dst)} MB): {src.name} -> {dst.name}")
    return True


def run_backup(out_dir: Path | None = None, include_env: bool = False) -> dict:
    """Create a timestamped backup. Returns manifest dict."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = (out_dir or _PROJECT_ROOT / "backups") / f"worldbase-{stamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "data").mkdir(exist_ok=True)

    _log(f"Starting backup -> {backup_root}")
    t0 = time.monotonic()

    copied = 0
    skipped = 0
    checksums: dict[str, str] = {}

    for entry in _DATA_FILES:
        src = entry["path"]
        dst_name = entry["name"]
        dst = backup_root / "data" / dst_name
        if not dst.parent.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)

        ok = False
        if entry["method"] == "vacuum":
            ok = backup_sqlite_vacuum(src, dst)
        else:
            ok = copy_file(src, dst)

        if ok:
            copied += 1
            checksums[dst_name] = _sha256(dst)
        else:
            skipped += 1

    # .env (opt-in)
    if include_env and _ENV_FILE.is_file():
        env_dst = backup_root / ".env"
        shutil.copy2(_ENV_FILE, env_dst)
        copied += 1
        checksums[".env"] = _sha256(env_dst)
        _log(".env copied — contains secrets!", "WARN")

    # Write manifest
    manifest = {
        "timestamp": stamp,
        "project": "intelshed",
        "backup_dir": str(backup_root),
        "files_copied": copied,
        "files_skipped": skipped,
        "include_env": include_env,
        "checksums": checksums,
        "created_by": os.getenv("USERNAME", os.getenv("USER", "unknown")),
        "hostname": os.getenv("COMPUTERNAME", os.getenv("HOSTNAME", "unknown")),
        "duration_sec": round(time.monotonic() - t0, 2),
    }
    manifest_path = backup_root / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    _log(f"Manifest: {manifest_path}")
    _log(f"Backup done: {copied} copied, {skipped} skipped, {manifest['duration_sec']}s")
    return manifest


# ---------------------------------------------------------------------------
# S3 / MinIO upload
# ---------------------------------------------------------------------------


def upload_to_s3(backup_dir: Path, manifest: dict) -> dict:
    """Upload backup files to S3/MinIO. Returns upload result dict."""
    endpoint = os.getenv("WORLDBASE_S3_ENDPOINT", "")
    bucket = os.getenv("WORLDBASE_S3_BUCKET", "")
    access_key = os.getenv("WORLDBASE_S3_ACCESS_KEY", "")
    secret_key = os.getenv("WORLDBASE_S3_SECRET_KEY", "")
    region = os.getenv("WORLDBASE_S3_REGION", "us-east-1")

    if not endpoint or not bucket:
        return {"ok": False, "error": "S3 env vars not configured (WORLDBASE_S3_ENDPOINT / WORLDBASE_S3_BUCKET)"}
    if not access_key or not secret_key:
        return {"ok": False, "error": "S3 credentials not configured (WORLDBASE_S3_ACCESS_KEY / WORLDBASE_S3_SECRET_KEY)"}

    try:
        import boto3
        from botocore.client import Config as BotoConfig

        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(signature_version="s3v4"),
        )

        # Ensure bucket exists
        try:
            s3.head_bucket(Bucket=bucket)
        except Exception:
            s3.create_bucket(Bucket=bucket)

        stamp = manifest["timestamp"]
        prefix = f"worldbase-backups/{stamp}"
        uploaded = 0
        errors: list[str] = []

        # Upload all files in backup dir
        for fpath in backup_dir.rglob("*"):
            if fpath.is_file():
                rel = fpath.relative_to(backup_dir)
                key = f"{prefix}/{rel.as_posix()}"
                try:
                    s3.upload_file(str(fpath), bucket, key)
                    uploaded += 1
                    _log(f"Uploaded: {key}")
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    _log(f"Upload failed: {key}: {exc}", "ERROR")

        return {
            "ok": len(errors) == 0,
            "uploaded": uploaded,
            "errors": errors,
            "bucket": bucket,
            "prefix": prefix,
            "endpoint": endpoint,
        }
    except ImportError:
        return {"ok": False, "error": "boto3 not installed. Run: pip install boto3"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Restore test
# ---------------------------------------------------------------------------


def restore_test(backup_dir: Path, manifest: dict) -> dict:
    """Verify backup integrity by restoring to a temp dir and checking checksums.

    For SQLite: open the restored DB and run a simple query.
    For DuckDB: verify file exists and size matches.
    For JSON: parse and check structure.
    """
    _log("Starting restore test...")
    checks: list[dict] = []
    all_ok = True

    with tempfile.TemporaryDirectory(prefix="worldbase-restore-test-") as tmp:
        tmp_dir = Path(tmp)

        for entry in _DATA_FILES:
            name = entry["name"]
            src = backup_dir / "data" / name
            if not src.is_file():
                checks.append({"file": name, "ok": False, "error": "not found in backup"})
                all_ok = False
                continue

            dst = tmp_dir / name
            shutil.copy2(src, dst)

            # Verify checksum
            expected_sha = manifest.get("checksums", {}).get(name)
            actual_sha = _sha256(dst)
            if expected_sha and expected_sha != actual_sha:
                checks.append({"file": name, "ok": False, "error": "checksum mismatch"})
                all_ok = False
                continue

            # File-specific integrity checks
            if name == "sqlite-worldbase.db":
                try:
                    conn = sqlite3.connect(str(dst))
                    tables = conn.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='table'"
                    ).fetchone()
                    conn.close()
                    checks.append({
                        "file": name,
                        "ok": True,
                        "tables": tables[0] if tables else 0,
                        "checksum": "ok",
                    })
                except Exception as exc:
                    checks.append({"file": name, "ok": False, "error": f"SQLite open failed: {exc}"})
                    all_ok = False
            elif name.endswith(".duckdb"):
                try:
                    import duckdb

                    conn = duckdb.connect(str(dst), read_only=True)
                    conn.execute("SELECT 1").fetchone()
                    conn.close()
                    checks.append({"file": name, "ok": True, "checksum": "ok"})
                except ImportError:
                    # duckdb not available in test env — just verify file exists
                    checks.append({"file": name, "ok": True, "checksum": "ok", "note": "duckdb not installed, file check only"})
                except Exception as exc:
                    checks.append({"file": name, "ok": False, "error": f"DuckDB open failed: {exc}"})
                    all_ok = False
            elif name.endswith(".json"):
                try:
                    with open(dst, encoding="utf-8") as f:
                        json.load(f)
                    checks.append({"file": name, "ok": True, "checksum": "ok"})
                except Exception as exc:
                    checks.append({"file": name, "ok": False, "error": f"JSON parse failed: {exc}"})
                    all_ok = False
            else:
                checks.append({"file": name, "ok": True, "checksum": "ok"})

    result = {
        "ok": all_ok,
        "checks": checks,
        "backup_dir": str(backup_dir),
    }
    if all_ok:
        _log(f"Restore test PASSED ({len(checks)} files verified)")
    else:
        _log(f"Restore test FAILED ({sum(1 for c in checks if not c['ok'])} failures)", "ERROR")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="intelshed DR Automation")
    parser.add_argument("--out-dir", type=Path, default=None, help="Backup output directory")
    parser.add_argument("--include-env", action="store_true", help="Include .env (secrets)")
    parser.add_argument("--upload-s3", action="store_true", help="Upload to S3/MinIO")
    parser.add_argument("--restore-test", action="store_true", help="Verify restore integrity")
    args = parser.parse_args()

    # Step 1: Backup
    try:
        manifest = run_backup(out_dir=args.out_dir, include_env=args.include_env)
    except Exception as exc:
        _log(f"Backup failed: {exc}", "ERROR")
        return 1

    backup_dir = Path(manifest["backup_dir"])
    exit_code = 0

    # Step 2: S3 upload
    if args.upload_s3:
        _log("Uploading to S3/MinIO...")
        result = upload_to_s3(backup_dir, manifest)
        if result.get("ok"):
            _log(f"S3 upload OK: {result['uploaded']} files -> {result['bucket']}/{result['prefix']}")
        else:
            _log(f"S3 upload FAILED: {result.get('error')}", "ERROR")
            exit_code = max(exit_code, 2)

    # Step 3: Restore test
    if args.restore_test:
        result = restore_test(backup_dir, manifest)
        if not result["ok"]:
            exit_code = max(exit_code, 3)

    _log(f"Done (exit={exit_code})")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
