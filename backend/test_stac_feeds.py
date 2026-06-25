"""Unit tests for STAC feed snapshot items (no network)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

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
        self.assertIn("bbox", sample)
        self.assertIsNotNone(sample.get("geometry"))

    def test_feed_stac_item_missing_cache(self):
        from connector_registry import CONNECTOR_CATALOG

        spec = CONNECTOR_CATALOG["cve"]
        item = stac._feed_stac_item(
            spec, None, cache_payload=None, now=datetime.now(timezone.utc)
        )
        self.assertEqual(item["properties"]["worldbase:status"], "missing")
        self.assertEqual(item["id"], "worldbase-cve")
        self.assertIn("bbox", item)
        self.assertEqual(item["geometry"]["type"], "Polygon")

    def test_connector_bbox_thailand_local(self):
        from connector_registry import CONNECTOR_CATALOG

        spec = CONNECTOR_CATALOG["cams_haze"]
        bbox = stac._connector_bbox(spec)
        self.assertIsNotNone(bbox)
        expected = stac._union_bbox(
            [
                stac.REGION_PRESETS["bangkok"]["bbox"],
                stac.REGION_PRESETS["asean"]["bbox"],
            ]
        )
        self.assertEqual(bbox, expected)

    def test_extract_payload_centroid_maritime(self):
        payload = {
            "vessels": [
                {"lat": 13.0, "lon": 100.5, "name": "A"},
                {"lat": 13.2, "lon": 100.7, "name": "B"},
            ],
        }
        c = stac._extract_payload_centroid(payload)
        self.assertIsNotNone(c)
        lon, lat = c
        self.assertAlmostEqual(lat, 13.1)
        self.assertAlmostEqual(lon, 100.6)

    def test_connector_registry_links(self):
        from connector_registry import CONNECTOR_CATALOG

        spec = CONNECTOR_CATALOG["maritime"]
        links = stac._connector_registry_links(spec)
        rels = {lnk["rel"] for lnk in links}
        self.assertIn("describedby", rels)

    def test_connector_bbox_maritime_uses_port_regions(self):
        from connector_registry import CONNECTOR_CATALOG
        from ais_bridge import maritime_operator_bbox

        spec = CONNECTOR_CATALOG["maritime"]
        with patch.dict(
            os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
        ):
            self.assertEqual(stac._connector_bbox(spec), maritime_operator_bbox())

    def test_connector_bbox_skips_global_when_mixed(self):
        from connector_registry import CONNECTOR_CATALOG

        spec = CONNECTOR_CATALOG["maritime"]
        bbox = stac._connector_bbox(spec)
        self.assertIsNotNone(bbox)
        self.assertNotEqual(bbox, stac._GLOBAL_BBOX)

    def test_feed_item_status_fresh(self):
        now = datetime.now(timezone.utc)
        meta = {"cached_at": now.isoformat(), "count": 5}
        status = stac._feed_item_status(meta, ttl_sec=900, now=now)
        self.assertEqual(status, "fresh")


if __name__ == "__main__":
    unittest.main()
