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

    def test_vessel_from_aisstream_metadata_lowercase(self):
        msg = {
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 259000420,
                "ShipName": "AUGUSTSON",
                "latitude": 66.02695,
                "longitude": 12.25382,
            },
            "Message": {"PositionReport": {"Cog": 308, "Sog": 0}},
        }
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            vessel = ais._vessel_from_aisstream(msg, ais._active_regions())
        self.assertIsNotNone(vessel)
        assert vessel is not None
        self.assertEqual(vessel["mmsi"], "259000420")
        self.assertEqual(vessel["name"], "AUGUSTSON")

    def test_vessel_from_aisstream_position_report_only(self):
        msg = {
            "MessageType": "PositionReport",
            "Message": {
                "PositionReport": {
                    "UserID": 367719770,
                    "Latitude": 7.9,
                    "Longitude": 98.4,
                    "Cog": 180,
                    "Sog": 12.5,
                }
            },
        }
        with patch.dict(os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False):
            vessel = ais._vessel_from_aisstream(msg, ais._active_regions())
        self.assertIsNotNone(vessel)
        assert vessel is not None
        self.assertEqual(vessel["mmsi"], "367719770")
        self.assertEqual(vessel["region"], "phuket")

    def test_handle_stream_payload_records_upstream_error(self):
        ais._STREAM["errors"] = []
        ais._handle_stream_payload({"error": "Api Key Is Not Valid"}, ais.PORT_REGIONS)
        self.assertEqual(ais._STREAM["errors"], ["Api Key Is Not Valid"])

    def test_build_result_no_demo_fleet_on_empty(self):
        result = ais._build_result([], demo_mode=False, errors=["all live AIS sources returned no vessels"])
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["demo_mode"])
        self.assertEqual(result["vessels"], [])
        self.assertIn("all live AIS sources", result["error"])


if __name__ == "__main__":
    unittest.main()
