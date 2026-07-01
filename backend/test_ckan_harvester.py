"""Tests for CKAN Harvester module."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import sys

# Ensure backend is on path
_backend = Path(__file__).resolve().parent
sys.path.insert(0, str(_backend))


class TestCKANSourcesYAML(unittest.TestCase):
    """Test YAML config loading."""

    def test_load_sources(self):
        import ckan_harvester

        sources = ckan_harvester.load_sources()
        self.assertIsInstance(sources, dict)
        self.assertGreater(
            len(sources), 0, "Should have at least one portal configured"
        )

    def test_list_portals(self):
        import ckan_harvester

        portals = ckan_harvester.list_portals()
        self.assertIsInstance(portals, list)
        for p in portals:
            self.assertIn("id", p)
            self.assertIn("name", p)
            self.assertIn("url", p)
            self.assertIn("region", p)

    def test_known_portals(self):
        import ckan_harvester

        sources = ckan_harvester.load_sources()
        self.assertIn("data_go_th", sources)
        self.assertIn("data_gov_uk", sources)

    def test_portal_has_url(self):
        import ckan_harvester

        sources = ckan_harvester.load_sources()
        for pid, cfg in sources.items():
            self.assertTrue(cfg.get("url"), f"Portal {pid} missing url")


class TestCKANNormalizeDataset(unittest.TestCase):
    """Test dataset normalization."""

    def test_normalize_basic(self):
        import ckan_harvester

        pkg = {
            "id": "abc-123",
            "title": "Test Dataset",
            "name": "test-dataset",
            "notes": "Some description",
            "organization": {"title": "Test Org", "id": "org-1"},
            "resources": [
                {
                    "id": "r1",
                    "name": "CSV",
                    "format": "CSV",
                    "url": "http://example.com/r1",
                }
            ],
            "tags": [{"name": "environment"}, {"name": "water"}],
            "groups": [{"name": "env"}],
            "metadata_created": "2024-01-01T00:00:00",
            "metadata_modified": "2024-06-01T00:00:00",
        }
        result = ckan_harvester._normalize_dataset(pkg)
        self.assertEqual(result["id"], "abc-123")
        self.assertEqual(result["title"], "Test Dataset")
        self.assertEqual(result["org"], "Test Org")
        self.assertEqual(len(result["resources"]), 1)
        self.assertEqual(result["resources"][0]["format"], "CSV")
        self.assertEqual(result["tags"], ["environment", "water"])
        self.assertEqual(result["groups"], ["env"])

    def test_normalize_empty(self):
        import ckan_harvester

        result = ckan_harvester._normalize_dataset({})
        self.assertIsNone(result["id"])
        self.assertEqual(result["resources"], [])
        self.assertEqual(result["tags"], [])

    def test_normalize_notes_truncation(self):
        import ckan_harvester

        long_notes = "x" * 2000
        result = ckan_harvester._normalize_dataset({"notes": long_notes})
        self.assertLessEqual(len(result["notes"]), 800)

    def test_normalize_extras(self):
        import ckan_harvester

        pkg = {
            "id": "x",
            "extras": [
                {"key": "spatial", "value": "Thailand"},
                {"key": "temporal", "value": "2024"},
            ],
        }
        result = ckan_harvester._normalize_dataset(pkg)
        self.assertEqual(result["extras"]["spatial"], "Thailand")
        self.assertEqual(result["extras"]["temporal"], "2024")


class TestCKANHarvestLog(unittest.TestCase):
    """Test harvest log SQLite table."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._orig_db = os.environ.get("WORLDBASE_DB_PATH")
        os.environ["WORLDBASE_DB_PATH"] = str(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()
        if self._orig_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._orig_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)

    def test_init_harvest_log(self):
        import ckan_harvester

        ckan_harvester.init_harvest_log()
        db_path = os.environ["WORLDBASE_DB_PATH"]
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ckan_harvest_log'"
        ).fetchall()
        conn.close()
        self.assertEqual(len(tables), 1)

    def test_log_start_and_finish(self):
        import ckan_harvester

        ckan_harvester.init_harvest_log()
        row_id = ckan_harvester._log_harvest_start("test_portal")
        self.assertGreater(row_id, 0)

        ckan_harvester._log_harvest_finish(
            row_id,
            status="ok",
            datasets_found=10,
            datasets_harvested=10,
            error=None,
            duration_ms=123.4,
        )

        logs = ckan_harvester.get_harvest_log(limit=10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["portal_id"], "test_portal")
        self.assertEqual(logs[0]["status"], "ok")
        self.assertEqual(logs[0]["datasets_found"], 10)

    def test_get_harvest_log_empty(self):
        import ckan_harvester

        ckan_harvester.init_harvest_log()
        logs = ckan_harvester.get_harvest_log(limit=5)
        self.assertEqual(logs, [])


class TestCKANSearchPortal(unittest.TestCase):
    """Test search_portal with mocked HTTP."""

    def setUp(self):
        self._orig_env = os.environ.get("WORLDBASE_CKAN_HARVESTER")
        os.environ["WORLDBASE_CKAN_HARVESTER"] = "1"

    def tearDown(self):
        if self._orig_env is not None:
            os.environ["WORLDBASE_CKAN_HARVESTER"] = self._orig_env
        else:
            os.environ.pop("WORLDBASE_CKAN_HARVESTER", None)

    def test_search_unknown_portal(self):
        import ckan_harvester

        result = asyncio.run(ckan_harvester.search_portal("nonexistent_portal"))
        self.assertIn("error", result)
        self.assertIn("Unknown portal", result["error"])

    def test_search_with_mocked_response(self):
        import ckan_harvester

        mock_result = {
            "count": 2,
            "results": [
                {
                    "id": "ds-1",
                    "title": "Dataset 1",
                    "name": "dataset-1",
                    "notes": "First",
                    "resources": [],
                    "tags": [],
                    "groups": [],
                    "organization": {},
                },
                {
                    "id": "ds-2",
                    "title": "Dataset 2",
                    "name": "dataset-2",
                    "notes": "Second",
                    "resources": [],
                    "tags": [],
                    "groups": [],
                    "organization": {},
                },
            ],
        }

        with patch.object(
            ckan_harvester, "_ckan_request", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = mock_result
            result = asyncio.run(
                ckan_harvester.search_portal("data_go_th", limit=2, refresh=True)
            )

        self.assertEqual(result["count"], 2)
        datasets = result["datasets"]
        self.assertEqual(len(datasets), 2)
        self.assertEqual(datasets[0]["id"], "ds-1")
        self.assertEqual(datasets[1]["title"], "Dataset 2")

    def test_search_error_handling(self):
        import ckan_harvester

        with patch.object(
            ckan_harvester, "_ckan_request", new_callable=AsyncMock
        ) as mock_req:
            mock_req.return_value = {"error": "Connection refused", "results": []}
            result = asyncio.run(
                ckan_harvester.search_portal("data_go_th", refresh=True)
            )

        self.assertIn("error", result)
        self.assertEqual(result["count"], 0)


class TestCKANHarvestPortal(unittest.TestCase):
    """Test harvest_portal with mocked dependencies."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._orig_db = os.environ.get("WORLDBASE_DB_PATH")
        os.environ["WORLDBASE_DB_PATH"] = str(Path(self._tmpdir.name) / "test.db")
        os.environ["WORLDBASE_CKAN_HARVESTER"] = "1"

    def tearDown(self):
        self._tmpdir.cleanup()
        if self._orig_db is not None:
            os.environ["WORLDBASE_DB_PATH"] = self._orig_db
        else:
            os.environ.pop("WORLDBASE_DB_PATH", None)

    def test_harvest_unknown_portal(self):
        import ckan_harvester

        result = asyncio.run(ckan_harvester.harvest_portal("nonexistent"))
        self.assertIn("error", result)

    def test_harvest_with_mocked_search(self):
        import ckan_harvester

        ckan_harvester.init_harvest_log()

        mock_search_result = {
            "count": 1,
            "datasets": [
                {
                    "id": "ds-1",
                    "title": "Test",
                    "name": "test",
                    "notes": "Test notes",
                    "resources": [],
                    "tags": [],
                    "groups": [],
                }
            ],
        }

        with patch.object(
            ckan_harvester, "search_portal", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = mock_search_result
            with patch.object(ckan_harvester, "feed_registry", create=True) as mock_reg:
                mock_reg.write = MagicMock()
                result = asyncio.run(
                    ckan_harvester.harvest_portal("data_go_th", limit=1)
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["datasets_found"], 1)
        self.assertGreaterEqual(result["duration_ms"], 0)


class TestCKANConnectorRegistry(unittest.TestCase):
    """Test CKAN harvester is registered in connector catalog."""

    def test_ckan_in_catalog(self):
        import connector_registry

        self.assertIn("ckan_harvester", connector_registry.CONNECTOR_CATALOG)

    def test_ckan_manifest_fields(self):
        import connector_registry

        manifest = connector_registry.CONNECTOR_CATALOG["ckan_harvester"]
        self.assertEqual(manifest.id, "ckan_harvester")
        self.assertEqual(manifest.bridge, "ckan_harvester.py")
        self.assertIn("government", manifest.category)


if __name__ == "__main__":
    unittest.main()
