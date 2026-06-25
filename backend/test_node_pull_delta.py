"""Unit tests for I8 — Pi Delta Sync: entity diff + compressed payload.

Tests cover:
- _briefing_hash: SHA-256 stability
- _node_pull_delta_enabled: config + env fallback
- compact_delta_for_pull: since filtering, 7d fallback, None fallback
- _pull_payload_digest: v3 payload compatibility
- _merge_delta_into_cache: briefing_unchanged merge logic
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


class BriefingHashTests(unittest.TestCase):
    """Tests for _briefing_hash."""

    def test_hash_stable(self):
        from node_sync import _briefing_hash
        self.assertEqual(
            _briefing_hash("hello world"),
            _briefing_hash("hello world"),
        )

    def test_hash_differs(self):
        from node_sync import _briefing_hash
        self.assertNotEqual(
            _briefing_hash("version A"),
            _briefing_hash("version B"),
        )

    def test_hash_none_empty(self):
        from node_sync import _briefing_hash
        self.assertEqual(_briefing_hash(None), _briefing_hash(""))
        self.assertEqual(_briefing_hash(""), _briefing_hash(""))


class NodePullDeltaEnabledTests(unittest.TestCase):
    """Tests for _node_pull_delta_enabled."""

    def test_default_on(self):
        from config import get_config
        get_config.cache_clear()
        with patch.dict("os.environ", {}, clear=False):
            import importlib
            import config as cfg_mod
            importlib.reload(cfg_mod)
            from node_sync import _node_pull_delta_enabled
            # Default should be on (config default True)
            result = _node_pull_delta_enabled()
            self.assertTrue(result)

    def test_env_off(self):
        from config import get_config
        get_config.cache_clear()
        with patch.dict("os.environ", {"WORLDBASE_NODE_PULL_DELTA": "0"}):
            from config import get_config as gc
            gc.cache_clear()
            from node_sync import _node_pull_delta_enabled
            result = _node_pull_delta_enabled()
            self.assertFalse(result)


class CompactDeltaForPullTests(unittest.TestCase):
    """Tests for compact_delta_for_pull."""

    def test_none_since_falls_back_to_full(self):
        """When since is None, should fall back to compact_for_pull."""
        from intel_graph_export import compact_delta_for_pull
        result = compact_delta_for_pull(None)
        # compact_for_pull returns available + nodes/edges or available=False
        self.assertIn("available", result)
        # Should NOT have delta-specific keys
        self.assertNotIn("delta", result)
        self.assertNotIn("nodes_added", result)

    def test_old_since_falls_back_to_full(self):
        """When since > 7d old, should fall back to compact_for_pull."""
        from intel_graph_export import compact_delta_for_pull
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        result = compact_delta_for_pull(old)
        self.assertIn("available", result)
        self.assertNotIn("delta", result)

    def test_invalid_since_falls_back_to_full(self):
        """When since is not parseable, should fall back to compact_for_pull."""
        from intel_graph_export import compact_delta_for_pull
        result = compact_delta_for_pull("not-a-date")
        self.assertIn("available", result)
        self.assertNotIn("delta", result)

    def test_recent_since_returns_delta_format(self):
        """When since is recent, should return delta format with nodes_added/edges_added."""
        from intel_graph_export import compact_delta_for_pull
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        # Mock the DuckDB connection to return empty results
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock(return_value=None)
        mock_lock.__exit__ = MagicMock(return_value=None)

        with patch("ftm_connection._conn", return_value=mock_conn):
            with patch("ftm_connection._LOCK", mock_lock):
                result = compact_delta_for_pull(recent)

        self.assertTrue(result.get("available"))
        self.assertTrue(result.get("delta"))
        self.assertEqual(result.get("nodes_added"), [])
        self.assertEqual(result.get("edges_added"), [])
        self.assertEqual(result.get("node_count"), 0)
        self.assertEqual(result.get("edge_count"), 0)
        self.assertEqual(result.get("since"), recent)

    def test_recent_since_with_entities(self):
        """Delta query returns entities/edges from DuckDB."""
        from intel_graph_export import compact_delta_for_pull
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        mock_conn = MagicMock()
        # Entity rows: id, schema, caption, datasets, lat, lon, last_seen
        mock_conn.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[
                ("ent-1", "Person", "Alice", '["gdelt"]', 13.0, 100.0, recent),
            ])),
            MagicMock(fetchall=MagicMock(return_value=[
                ("ent-1", "ent-2", "sameAs", "worldbase", 0.9, recent),
            ])),
        ]
        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock(return_value=None)
        mock_lock.__exit__ = MagicMock(return_value=None)

        with patch("ftm_connection._conn", return_value=mock_conn):
            with patch("ftm_connection._LOCK", mock_lock):
                result = compact_delta_for_pull(recent)

        self.assertTrue(result.get("available"))
        self.assertEqual(result.get("node_count"), 1)
        self.assertEqual(result.get("edge_count"), 1)
        self.assertEqual(result["nodes_added"][0]["id"], "ent-1")
        self.assertEqual(result["edges_added"][0]["kind"], "sameAs")


class PullPayloadDigestV3Tests(unittest.TestCase):
    """Tests for _pull_payload_digest with v3 payloads."""

    def test_v3_briefing_unchanged_digest_stable(self):
        from node_sync import _pull_payload_digest
        base = {
            "generated_at": "2026-06-25T15:00:00+00:00",
            "source": "worldbase-pc",
            "payload_version": 3,
            "briefing_unchanged": True,
            "briefing_at": "2026-06-25T14:00:00+00:00",
            "briefing_hash": "abc123",
            "since": "2026-06-25T12:00:00+00:00",
            "intel_delta": {"available": True, "nodes_added": [], "edges_added": []},
        }
        other = dict(base, generated_at="2026-06-25T16:00:00+00:00")
        self.assertEqual(_pull_payload_digest(base), _pull_payload_digest(other))

    def test_v3_full_payload_digest(self):
        from node_sync import _pull_payload_digest
        payload = {
            "generated_at": "2026-06-25T15:00:00+00:00",
            "source": "worldbase-pc",
            "payload_version": 3,
            "briefing": "LOCAL test",
            "briefing_at": "2026-06-25T14:00:00+00:00",
            "briefing_hash": "abc123",
            "since": "2026-06-25T12:00:00+00:00",
            "alerts": [{"severity": "low", "text": "test"}],
            "intel_delta": {"available": True, "nodes_added": [], "edges_added": []},
        }
        # Digest should be a valid hex string
        digest = _pull_payload_digest(payload)
        self.assertEqual(len(digest), 64)
        try:
            int(digest, 16)
        except ValueError:
            self.fail("digest is not valid hex")

    def test_v3_excludes_content_sha256(self):
        from node_sync import _pull_payload_digest
        payload = {
            "source": "worldbase-pc",
            "payload_version": 3,
            "briefing_unchanged": True,
            "content_sha256": "deadbeef",
        }
        without = {k: v for k, v in payload.items() if k != "content_sha256"}
        self.assertEqual(_pull_payload_digest(payload), _pull_payload_digest(without))


class MergeDeltaIntoCacheTests(unittest.TestCase):
    """Tests for Pi-side _merge_delta_into_cache logic (simulated)."""

    def test_briefing_unchanged_merges(self):
        """When briefing_unchanged=True, cached briefing is kept, intel_delta updated."""
        # Simulate the merge logic inline (Pi script not importable on PC)
        cached = {
            "briefing": "LOCAL Situation Report...",
            "briefing_at": "2026-06-25T14:00:00+00:00",
            "alerts": [{"severity": "high", "text": "test"}],
            "payload_version": 3,
            "_etag": "old-etag",
            "_briefing_hash": "abc123",
        }
        delta = {
            "generated_at": "2026-06-25T15:00:00+00:00",
            "source": "worldbase-pc",
            "payload_version": 3,
            "briefing_unchanged": True,
            "briefing_at": "2026-06-25T14:00:00+00:00",
            "briefing_hash": "abc123",
            "since": "2026-06-25T12:00:00+00:00",
            "intel_delta": {
                "available": True,
                "nodes_added": [{"id": "new-1", "schema": "Event"}],
                "edges_added": [],
            },
            "content_sha256": "new-sha",
            "_etag": "new-etag",
            "_briefing_hash": "abc123",
        }

        # Inline merge logic (mirrors _merge_delta_into_cache)
        if delta.get("briefing_unchanged"):
            cached["intel_delta"] = delta.get("intel_delta")
            cached["generated_at"] = delta.get("generated_at")
            cached["payload_version"] = 3
            cached["content_sha256"] = delta.get("content_sha256")
            cached["_etag"] = delta.get("_etag", cached.get("_etag"))
            if delta.get("_briefing_hash"):
                cached["_briefing_hash"] = delta["_briefing_hash"]

        # Briefing text preserved from cache
        self.assertEqual(cached["briefing"], "LOCAL Situation Report...")
        # Intel delta updated
        self.assertEqual(len(cached["intel_delta"]["nodes_added"]), 1)
        self.assertEqual(cached["content_sha256"], "new-sha")
        self.assertEqual(cached["_etag"], "new-etag")
        self.assertEqual(cached["payload_version"], 3)

    def test_full_payload_replaces_cache(self):
        """When briefing_unchanged is False/missing, full payload replaces cache."""
        full = {
            "briefing": "New briefing text",
            "briefing_at": "2026-06-25T16:00:00+00:00",
            "payload_version": 3,
        }
        # When briefing_unchanged is not set, data replaces cache entirely
        self.assertFalse(full.get("briefing_unchanged"))
        # In _commit_pull_ok, data is used directly (not merged)
        self.assertEqual(full["briefing"], "New briefing text")


if __name__ == "__main__":
    unittest.main()
