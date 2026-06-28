"""Tests for Phase 3.1 — Pi sync conflict detection (no live DB)."""

from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException, Request

import node_briefing
from node_briefing import _detect_pull_conflict, _pull_conflict_payload, _briefing_hash
from node_ingest import (
    _server_briefing_version,
    _node_conflict_check_enabled,
    node_push,
)


class ConflictDetectionTests(unittest.TestCase):
    def test_no_conflict_when_no_client_version(self):
        self.assertIsNone(
            _detect_pull_conflict(
                client_version=None, client_hash="x", server_version=5, server_hash="y"
            )
        )

    def test_conflict_when_client_ahead(self):
        reason = _detect_pull_conflict(
            client_version=7, client_hash="x", server_version=5, server_hash="y"
        )
        self.assertEqual(reason, "client_ahead")

    def test_no_conflict_when_client_behind(self):
        self.assertIsNone(
            _detect_pull_conflict(
                client_version=3, client_hash="x", server_version=5, server_hash="y"
            )
        )

    def test_diverged_when_same_version_different_hash(self):
        reason = _detect_pull_conflict(
            client_version=5, client_hash="x", server_version=5, server_hash="y"
        )
        self.assertEqual(reason, "diverged")

    def test_no_conflict_when_same_version_same_hash(self):
        self.assertIsNone(
            _detect_pull_conflict(
                client_version=5, client_hash="x", server_version=5, server_hash="x"
            )
        )

    def test_conflict_payload_client_ahead(self):
        payload = _pull_conflict_payload(
            reason="client_ahead",
            client_version=7,
            client_hash="h",
            server_version=5,
            server_hash="s",
            brief={"text": "server text", "created_at": "2026-06-28T08:00:00Z"},
        )
        self.assertTrue(payload["conflict"])
        self.assertEqual(payload["reason"], "client_ahead")
        self.assertEqual(payload["server_version"], 5)
        self.assertEqual(payload["client_version"], 7)
        self.assertEqual(payload["server_briefing_preview"], "server text")
        self.assertIn("POST /api/node/push", payload["resolve"])

    def test_conflict_payload_diverged(self):
        payload = _pull_conflict_payload(
            reason="diverged",
            client_version=5,
            client_hash="h",
            server_version=5,
            server_hash="s",
            brief={"text": "server text", "created_at": "2026-06-28T08:00:00Z"},
        )
        self.assertEqual(payload["reason"], "diverged")
        self.assertIn("concurrent edit", payload["detail"])

    def test_briefing_hash_stable(self):
        self.assertEqual(_briefing_hash("abc"), _briefing_hash("abc"))
        self.assertNotEqual(_briefing_hash("abc"), _briefing_hash("abd"))


class ServerVersionTests(unittest.TestCase):
    def _in_memory_db(self, rows=()):
        @contextmanager
        def ctx():
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.execute("CREATE TABLE briefings (id INTEGER PRIMARY KEY)")
            if rows:
                conn.executemany("INSERT INTO briefings (id) VALUES (?)", rows)
            conn.commit()
            try:
                yield conn
            finally:
                conn.close()

        return ctx

    def test_server_version_zero_when_empty(self):
        with patch("node_ingest._db", self._in_memory_db()):
            self.assertEqual(_server_briefing_version(), 0)

    def test_server_version_from_max_id(self):
        with patch("node_ingest._db", self._in_memory_db(rows=[(1,), (42,)])):
            self.assertEqual(_server_briefing_version(), 42)


class NodeConflictCheckEnabledTests(unittest.TestCase):
    def test_default_on(self):
        with patch("config.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.node_conflict_check = True
            mock_cfg.return_value = cfg
            self.assertTrue(_node_conflict_check_enabled())

    def test_env_off(self):
        with patch("config.get_config", side_effect=ImportError):
            with patch.dict(
                "os.environ", {"WORLDBASE_NODE_CONFLICT_CHECK": "0"}, clear=False
            ):
                self.assertFalse(_node_conflict_check_enabled())


class NodePushEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _in_memory_db(self):
        @contextmanager
        def ctx():
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE node_push_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT,
                    client_version INTEGER,
                    client_data_hash TEXT,
                    server_version_at_push INTEGER,
                    reason TEXT,
                    briefing TEXT,
                    payload TEXT,
                    status TEXT,
                    created_at TEXT,
                    resolved_at TEXT,
                    resolution TEXT
                );
            """)
            conn.commit()
            try:
                yield conn
            finally:
                conn.close()

        return ctx

    def _push_request(self, body: dict):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/node/push",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
        }
        req = Request(scope)
        req.json = AsyncMock(return_value=body)
        return req

    async def test_push_requires_node_secret(self):
        with patch(
            "node_ingest._verify_node_secret", side_effect=HTTPException(403, "nope")
        ):
            req = self._push_request({"node_id": "pi"})
            with self.assertRaises(HTTPException):
                await node_push(req, x_node_token="bad")

    async def test_push_records_pending_merge(self):
        with patch("node_ingest._verify_node_secret", return_value=None):
            with patch("node_ingest._server_briefing_version", return_value=5):
                with patch("node_ingest._db", self._in_memory_db()):
                    req = self._push_request(
                        {
                            "node_id": "offgrid-pi",
                            "briefing": "local text",
                            "client_version": 7,
                            "client_data_hash": "hash",
                            "reason": "offline",
                        }
                    )
                    out = await node_push(req, x_node_token="good")
        self.assertTrue(out["ok"])
        self.assertEqual(out["merge_id"], 1)
        self.assertEqual(out["status"], "pending_merge")
        self.assertEqual(out["node_id"], "offgrid-pi")
        self.assertEqual(out["server_version"], 5)


class NodePullConflictEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _pull_request(self, force=False, client_version=7, client_hash="different"):
        query_string = b"force=1" if force else b""
        headers = [
            (b"x-client-version", str(client_version).encode()),
            (b"x-client-data-hash", client_hash.encode()),
        ]
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/node/pull",
            "headers": headers,
            "query_string": query_string,
            "client": ("127.0.0.1", 12345),
        }
        return Request(scope)

    async def test_pull_returns_409_when_conflict(self):
        with patch("node_briefing._verify_node_secret", return_value=None):
            with patch(
                "node_briefing.latest_briefing",
                return_value={
                    "text": "server",
                    "created_at": "2026-06-28T08:00:00Z",
                    "alerts": [],
                },
            ):
                with patch(
                    "node_briefing._node_conflict_check_enabled", return_value=True
                ):
                    with patch(
                        "node_briefing._server_briefing_version", return_value=5
                    ):
                        with patch(
                            "node_briefing._node_pull_delta_enabled", return_value=False
                        ):
                            resp = await node_briefing.node_pull(
                                self._pull_request(force=False),
                                since=None,
                                x_node_token="x",
                            )
        self.assertEqual(resp.status_code, 409)
        data = json.loads(resp.body)
        self.assertEqual(data["reason"], "client_ahead")
        self.assertEqual(data["client_version"], 7)
        self.assertEqual(data["server_version"], 5)

    async def test_pull_force_bypasses_conflict(self):
        with patch("node_briefing._verify_node_secret", return_value=None):
            with patch(
                "node_briefing.latest_briefing",
                return_value={
                    "text": "server",
                    "created_at": "2026-06-28T08:00:00Z",
                    "alerts": [],
                },
            ):
                with patch(
                    "node_briefing._node_conflict_check_enabled", return_value=True
                ):
                    with patch(
                        "node_briefing._server_briefing_version", return_value=5
                    ):
                        with patch(
                            "node_briefing._node_pull_delta_enabled", return_value=False
                        ):
                            resp = await node_briefing.node_pull(
                                self._pull_request(force=True),
                                since=None,
                                x_node_token="x",
                            )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.body)
        self.assertEqual(data["source"], "worldbase-pc")
        self.assertEqual(data["briefing"], "server")


if __name__ == "__main__":
    unittest.main()
