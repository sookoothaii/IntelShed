"""Unit tests for STAC feed snapshot items (no network)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import stac_bridge as stac


class StacFeedItemsTests(unittest.TestCase):
    def test_build_feed_stac_items_shape(self):
        payload = stac.build_feed_stac_items()
        self.assertEqual(payload["type"], "FeatureCollection")
        self.assertEqual(payload["collection"], stac._FEEDS_COLLECTION_ID)
        feats = payload.get("features") or []
        self.assertGreater(len(feats), 0)
        sample = feats[0]
        self.assertEqual(sample["type"], "Feature")
        self.assertIn("worldbase:connector_id", sample["properties"])
        self.assertIn("assets", sample)
        self.assertTrue(sample["links"])

    def test_feed_stac_item_missing_cache(self):
        from connector_registry import CONNECTOR_CATALOG

        spec = CONNECTOR_CATALOG["cve"]
        item = stac._feed_stac_item(spec, None, now=datetime.now(timezone.utc))
        self.assertEqual(item["properties"]["worldbase:status"], "missing")
        self.assertEqual(item["id"], "worldbase-cve")

    def test_feed_item_status_fresh(self):
        now = datetime.now(timezone.utc)
        meta = {"cached_at": now.isoformat(), "count": 5}
        status = stac._feed_item_status(meta, ttl_sec=900, now=now)
        self.assertEqual(status, "fresh")


if __name__ == "__main__":
    unittest.main()
