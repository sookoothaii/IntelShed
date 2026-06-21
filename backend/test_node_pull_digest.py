"""Unit tests for node pull payload digest (ETag / SHA-256 stability)."""

from __future__ import annotations

import unittest

from node_sync import _pull_payload_digest


class NodePullDigestTests(unittest.TestCase):
    def test_digest_excludes_generated_at(self):
        base = {
            "generated_at": "2026-06-21T15:00:00+00:00",
            "source": "worldbase-pc",
            "payload_version": 2,
            "briefing": "LOCAL test",
            "briefing_at": "2026-06-21T14:00:00+00:00",
            "alerts": [{"severity": "low", "text": "test"}],
            "fusion_hotspots": [],
            "quality": {"score": 0.9},
            "digest": {"local_count": 2},
        }
        other = dict(base, generated_at="2026-06-21T16:00:00+00:00")
        self.assertEqual(_pull_payload_digest(base), _pull_payload_digest(other))

    def test_digest_changes_when_briefing_changes(self):
        a = {
            "generated_at": "2026-06-21T15:00:00+00:00",
            "source": "worldbase-pc",
            "payload_version": 2,
            "briefing": "version A",
            "briefing_at": "2026-06-21T14:00:00+00:00",
            "alerts": [],
        }
        b = dict(a, briefing="version B")
        self.assertNotEqual(_pull_payload_digest(a), _pull_payload_digest(b))

    def test_content_sha256_not_in_digest_input(self):
        payload = {
            "source": "worldbase-pc",
            "briefing_at": "2026-06-21T14:00:00+00:00",
            "briefing": "x",
            "content_sha256": "deadbeef",
        }
        without = {k: v for k, v in payload.items() if k != "content_sha256"}
        self.assertEqual(_pull_payload_digest(payload), _pull_payload_digest(without))


if __name__ == "__main__":
    unittest.main()
