"""Unit tests for AIS maritime bridge (no network)."""

from __future__ import annotations

import asyncio
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

    def test_empty_sources_return_no_vessels(self):
        async def run() -> dict:
            with patch.dict(
                os.environ,
                {"AISSTREAM_API_KEY": "abc", "WORLDBASE_MARITIME_AISSTREAM": "1"},
                clear=False,
            ):
                ais._STREAM["vessels"] = {}
                ais._STREAM["connected"] = True
                ais._STREAM["errors"] = []
                with patch.object(ais, "_supplement_myshiptracking", return_value=[]):
                    with patch.object(ais, "_fetch_aishub", return_value=[]):
                        return await ais._build_maritime_result()

        result = asyncio.run(run())
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["vessels"], [])
        self.assertNotIn("demo_mode", result)
        self.assertTrue(result.get("errors"))

    def test_vessel_from_aisstream_doc_example(self):
        sample = {
            "Message": {
                "PositionReport": {
                    "Cog": 308,
                    "Latitude": 66.02695,
                    "Longitude": 12.253821666666665,
                    "Sog": 0,
                    "UserID": 259000420,
                }
            },
            "MessageType": "PositionReport",
            "MetaData": {
                "MMSI": 259000420,
                "ShipName": "AUGUSTSON",
                "latitude": 66.02695,
                "longitude": 12.253821666666665,
            },
        }
        with patch.dict(os.environ, {"WORLDBASE_MARITIME_REGIONS": "all"}, clear=False):
            vessel = ais._vessel_from_aisstream(sample, ais._active_regions())
        self.assertIsNotNone(vessel)
        assert vessel is not None
        self.assertEqual(vessel["mmsi"], "259000420")
        self.assertEqual(vessel["name"], "AUGUSTSON")
        self.assertEqual(vessel["source"], "aisstream")

    def test_aisstream_service_error_detected(self):
        err = ais._aisstream_service_error({"error": "Api Key Is Not Valid"})
        self.assertEqual(err, "Api Key Is Not Valid")

    def test_ingest_stream_message_marks_connected_on_any_frame(self):
        ais._STREAM["vessels"] = {}
        ais._STREAM["last_msg_at"] = 0.0
        sample = {
            "Message": {"PositionReport": {"UserID": 1, "Latitude": 53.5, "Longitude": 9.9}},
            "MessageType": "PositionReport",
            "MetaData": {"MMSI": 1, "latitude": 53.5, "longitude": 9.9},
        }
        with patch.dict(os.environ, {"WORLDBASE_MARITIME_REGIONS": "all"}, clear=False):
            ok = ais._ingest_stream_message(sample, ais._active_regions())
        self.assertTrue(ok)
        self.assertGreater(ais._STREAM["last_msg_at"], 0.0)
        ais._STREAM["vessels"] = {}
        ais._STREAM["last_msg_at"] = 0.0


if __name__ == "__main__":
    unittest.main()
