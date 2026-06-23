"""Unit tests for AIS maritime bridge (no network)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import ais_bridge as ais


class AisBridgeTests(unittest.TestCase):
    def test_active_regions_thailand_default(self):
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            regions = ais._active_regions()
            self.assertIn("malacca", regions)
            self.assertIn("bangkok_port", regions)
            self.assertNotIn("hamburg", regions)

    def test_active_regions_env_override(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_MARITIME_REGIONS": "malacca,singapore"},
            clear=False,
        ):
            regions = ais._active_regions()
            self.assertEqual(set(regions.keys()), {"malacca", "singapore"})

    def test_maritime_operator_bbox(self):
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            bbox = ais.maritime_operator_bbox()
            self.assertIsNotNone(bbox)
            self.assertEqual(len(bbox), 4)
            self.assertLess(bbox[0], bbox[2])
            self.assertLess(bbox[1], bbox[3])

    def test_snapshot_from_stream_filters_regions(self):
        ais._STREAM["vessels"] = {
            "1": {
                "mmsi": "1",
                "name": "A",
                "lat": 1.25,
                "lon": 103.85,
                "region": "singapore",
                "_seen_at": 9999999999.0,
            },
            "2": {
                "mmsi": "2",
                "name": "B",
                "lat": 53.5,
                "lon": 9.9,
                "region": "hamburg",
                "_seen_at": 9999999999.0,
            },
        }
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            snap = ais._snapshot_from_stream(ais._active_regions())
        mmsis = {v["mmsi"] for v in snap}
        self.assertIn("1", mmsis)
        self.assertNotIn("2", mmsis)
        ais._STREAM["vessels"] = {}

    def test_aisstream_background_on_requires_key(self):
        with patch.dict(os.environ, {"AISSTREAM_API_KEY": "", "WORLDBASE_MARITIME_AISSTREAM": "1"}, clear=False):
            self.assertFalse(ais._aisstream_background_on())
        with patch.dict(os.environ, {"AISSTREAM_API_KEY": "abc", "WORLDBASE_MARITIME_AISSTREAM": "0"}, clear=False):
            self.assertFalse(ais._aisstream_background_on())

    def test_touch_maritime_cache_writes_stream_snapshot(self):
        ais._STREAM["vessels"] = {
            "9": {
                "mmsi": "9",
                "name": "Touch",
                "lat": 13.7,
                "lon": 100.5,
                "region": "bangkok_port",
                "_seen_at": 9999999999.0,
            },
        }
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            with patch.object(ais.feed_registry, "write_auto") as write_auto:
                out = ais.touch_maritime_cache()
        self.assertIsNotNone(out)
        self.assertEqual(out.get("count"), 1)
        write_auto.assert_called_once()
        ais._STREAM["vessels"] = {}


if __name__ == "__main__":
    unittest.main()
