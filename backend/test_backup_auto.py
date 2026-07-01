"""Tests for DR Automation (backup_auto.py)."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add scripts dir to path — works in local dev (backend/../scripts) and Docker (/app/../scripts)
_scripts = Path(__file__).resolve().parent.parent / "scripts"
if not _scripts.is_dir():
    _scripts = Path("/scripts")
sys.path.insert(0, str(_scripts))

# Check if backup_auto is available (may be missing in Docker where scripts/ isn't copied)
_BACKUP_AUTO_AVAILABLE = (_scripts / "backup_auto.py").is_file()


@unittest.skipUnless(
    _BACKUP_AUTO_AVAILABLE, "backup_auto.py not in scripts/ (Docker context)"
)
class TestBackupAuto(unittest.TestCase):
    """Test backup_auto.py module."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)
        # Create a fake worldbase.db
        self._db_path = self._tmp / "worldbase.db"
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()

        # Create fake data dir
        data_dir = self._tmp / "data"
        data_dir.mkdir()
        # Fake JSON
        (data_dir / "intel_subgraph_latest.json").write_text('{"nodes":[],"edges":[]}')
        # Fake parquet (just a dummy file)
        (data_dir / "fusionEvents.parquet").write_bytes(b"PAR1")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_backup_sqlite_vacuum(self):
        import backup_auto

        dst = self._tmp / "backup_test.db"
        result = backup_auto.backup_sqlite_vacuum(self._db_path, dst)
        self.assertTrue(result)
        self.assertTrue(dst.is_file())

        # Verify the backup is a valid SQLite DB with data
        conn = sqlite3.connect(str(dst))
        rows = conn.execute("SELECT * FROM test").fetchall()
        conn.close()
        self.assertEqual(rows, [(1, "hello")])

    def test_backup_sqlite_vacuum_missing(self):
        import backup_auto

        dst = self._tmp / "nonexistent_backup.db"
        result = backup_auto.backup_sqlite_vacuum(self._tmp / "nope.db", dst)
        self.assertFalse(result)

    def test_copy_file(self):
        import backup_auto

        src = self._tmp / "intel_subgraph_latest.json"
        # Use the data dir version
        src = self._tmp / "data" / "intel_subgraph_latest.json"
        dst = self._tmp / "copy_test.json"
        result = backup_auto.copy_file(src, dst)
        self.assertTrue(result)
        self.assertTrue(dst.is_file())
        self.assertEqual(dst.read_text(), src.read_text())

    def test_copy_file_missing(self):
        import backup_auto

        dst = self._tmp / "nope_copy.txt"
        result = backup_auto.copy_file(self._tmp / "nope.txt", dst)
        self.assertFalse(result)

    def test_run_backup(self):
        import backup_auto

        # Patch _DATA_FILES to point to our temp files
        orig_data_files = backup_auto._DATA_FILES
        backup_auto._DATA_FILES = [
            {"path": self._db_path, "name": "sqlite-worldbase.db", "method": "vacuum"},
            {
                "path": self._tmp / "data" / "intel_subgraph_latest.json",
                "name": "intel_subgraph_latest.json",
                "method": "copy",
            },
        ]
        try:
            out_dir = self._tmp / "backups"
            manifest = backup_auto.run_backup(out_dir=out_dir)
            self.assertEqual(manifest["files_copied"], 2)
            self.assertEqual(manifest["files_skipped"], 0)
            self.assertIn("checksums", manifest)
            self.assertIn("sqlite-worldbase.db", manifest["checksums"])
            self.assertIn("intel_subgraph_latest.json", manifest["checksums"])

            # Verify manifest.json exists
            backup_dir = Path(manifest["backup_dir"])
            self.assertTrue((backup_dir / "manifest.json").is_file())
            self.assertTrue((backup_dir / "data" / "sqlite-worldbase.db").is_file())
        finally:
            backup_auto._DATA_FILES = orig_data_files

    def test_sha256(self):
        import backup_auto

        test_file = self._tmp / "hash_test.txt"
        test_file.write_text("hello world")
        h = backup_auto._sha256(test_file)
        self.assertEqual(len(h), 64)  # SHA-256 hex digest

    def test_file_size_mb(self):
        import backup_auto

        test_file = self._tmp / "size_test.bin"
        test_file.write_bytes(b"x" * (2 * 1024 * 1024))
        size = backup_auto._file_size_mb(test_file)
        self.assertGreater(size, 0)
        self.assertIsInstance(size, float)


@unittest.skipUnless(
    _BACKUP_AUTO_AVAILABLE, "backup_auto.py not in scripts/ (Docker context)"
)
class TestRestoreTest(unittest.TestCase):
    """Test restore verification."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)

        # Create a backup dir with files
        self._backup_dir = self._tmp / "backup"
        data_dir = self._backup_dir / "data"
        data_dir.mkdir(parents=True)

        # Create SQLite backup
        db_path = data_dir / "sqlite-worldbase.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE foo (id INTEGER)")
        conn.execute("INSERT INTO foo VALUES (42)")
        conn.commit()
        conn.close()

        # Create JSON backup
        json_path = data_dir / "intel_subgraph_latest.json"
        json_path.write_text('{"nodes": [], "edges": []}')

        # Compute checksums
        import backup_auto

        self._manifest = {
            "timestamp": "20240101-000000",
            "checksums": {
                "sqlite-worldbase.db": backup_auto._sha256(db_path),
                "intel_subgraph_latest.json": backup_auto._sha256(json_path),
            },
        }

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_restore_test_passes(self):
        import backup_auto

        # Patch _DATA_FILES to only include our test files
        orig = backup_auto._DATA_FILES
        backup_auto._DATA_FILES = [
            {"path": Path("dummy"), "name": "sqlite-worldbase.db", "method": "vacuum"},
            {
                "path": Path("dummy"),
                "name": "intel_subgraph_latest.json",
                "method": "copy",
            },
        ]
        try:
            result = backup_auto.restore_test(self._backup_dir, self._manifest)
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["checks"]), 2)
            for check in result["checks"]:
                self.assertTrue(check["ok"])
        finally:
            backup_auto._DATA_FILES = orig

    def test_restore_test_checksum_mismatch(self):
        import backup_auto

        bad_manifest = dict(self._manifest)
        bad_manifest["checksums"] = {
            "sqlite-worldbase.db": "0000000000000000000000000000000000000000000000000000000000000000",
            "intel_subgraph_latest.json": self._manifest["checksums"][
                "intel_subgraph_latest.json"
            ],
        }

        orig = backup_auto._DATA_FILES
        backup_auto._DATA_FILES = [
            {"path": Path("dummy"), "name": "sqlite-worldbase.db", "method": "vacuum"},
            {
                "path": Path("dummy"),
                "name": "intel_subgraph_latest.json",
                "method": "copy",
            },
        ]
        try:
            result = backup_auto.restore_test(self._backup_dir, bad_manifest)
            self.assertFalse(result["ok"])
        finally:
            backup_auto._DATA_FILES = orig


@unittest.skipUnless(
    _BACKUP_AUTO_AVAILABLE, "backup_auto.py not in scripts/ (Docker context)"
)
class TestS3Upload(unittest.TestCase):
    """Test S3 upload (mocked)."""

    def test_upload_no_config(self):
        import backup_auto

        # Clear S3 env vars
        with patch.dict(os.environ, {}, clear=True):
            result = backup_auto.upload_to_s3(Path("/tmp"), {"timestamp": "test"})
            self.assertFalse(result["ok"])
            self.assertIn("not configured", result["error"])

    def test_upload_no_credentials(self):
        import backup_auto

        with patch.dict(
            os.environ,
            {
                "WORLDBASE_S3_ENDPOINT": "http://localhost:9000",
                "WORLDBASE_S3_BUCKET": "test-bucket",
            },
            clear=True,
        ):
            result = backup_auto.upload_to_s3(Path("/tmp"), {"timestamp": "test"})
            self.assertFalse(result["ok"])
            self.assertIn("credentials", result["error"])

    def test_upload_boto3_missing(self):
        import backup_auto

        with patch.dict(
            os.environ,
            {
                "WORLDBASE_S3_ENDPOINT": "http://localhost:9000",
                "WORLDBASE_S3_BUCKET": "test-bucket",
                "WORLDBASE_S3_ACCESS_KEY": "test",
                "WORLDBASE_S3_SECRET_KEY": "test",
            },
            clear=True,
        ):
            with patch.dict(sys.modules, {"boto3": None}):
                result = backup_auto.upload_to_s3(Path("/tmp"), {"timestamp": "test"})
                # Will fail either with ImportError or module error
                self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
