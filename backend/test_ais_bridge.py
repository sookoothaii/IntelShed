"""Unit tests for AIS maritime bridge (no network)."""

from __future__ import annotations

import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

import ais_bridge as ais


class AisBridgeTests(unittest.TestCase):
    def test_active_regions_thailand_default(self):
        with patch.dict(
            os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
        ):
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
        with patch.dict(
            os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
        ):
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
        with patch.dict(
            os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
        ):
            snap = ais._snapshot_from_stream(ais._active_regions())
        mmsis = {v["mmsi"] for v in snap}
        self.assertIn("1", mmsis)
        self.assertNotIn("2", mmsis)
        ais._STREAM["vessels"] = {}

    def test_aisstream_background_on_requires_key(self):
        with patch.dict(
            os.environ,
            {"AISSTREAM_API_KEY": "", "WORLDBASE_MARITIME_AISSTREAM": "1"},
            clear=False,
        ):
            self.assertFalse(ais._aisstream_background_on())
        with patch.dict(
            os.environ,
            {"AISSTREAM_API_KEY": "abc", "WORLDBASE_MARITIME_AISSTREAM": "0"},
            clear=False,
        ):
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

    def test_touch_maritime_cache_writes_feed_registry(self):
        async def run() -> bool:
            ais._STREAM["vessels"] = {
                "1": {
                    "mmsi": "1",
                    "name": "A",
                    "lat": 1.25,
                    "lon": 103.85,
                    "region": "singapore",
                    "_seen_at": 9999999999.0,
                },
            }
            with patch.dict(
                os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
            ):
                with patch.object(ais.feed_registry, "write_auto") as write_auto:
                    ok = await ais.touch_maritime_cache()
            ais._STREAM["vessels"] = {}
            return ok, write_auto.call_count

        ok, writes = asyncio.run(run())
        self.assertTrue(ok)
        self.assertEqual(writes, 1)


class EdgeAisReceiverTests(unittest.TestCase):
    """Tests for Pi edge AIS receiver buffer and endpoints."""

    def setUp(self):
        ais._EDGE_VESSELS.clear()
        ais._EDGE_STATUS.update(
            {
                "active": False,
                "receiver_type": "unknown",
                "messages_received": 0,
                "vessels_seen": 0,
                "last_message_at": "",
                "lat": None,
                "lon": None,
                "range_km": 25,
                "updated_at": "",
            }
        )

    def tearDown(self):
        ais._EDGE_VESSELS.clear()
        ais._EDGE_STATUS.update(
            {
                "active": False,
                "receiver_type": "unknown",
                "messages_received": 0,
                "vessels_seen": 0,
                "last_message_at": "",
                "lat": None,
                "lon": None,
                "range_km": 25,
                "updated_at": "",
            }
        )

    def test_prune_edge_vessels_removes_expired(self):
        ais._EDGE_VESSELS["123"] = {
            "mmsi": "123",
            "lat": 1.25,
            "lon": 103.85,
            "_seen_at": time.time() - 999,
        }
        ais._prune_edge_vessels()
        self.assertNotIn("123", ais._EDGE_VESSELS)

    def test_prune_edge_vessels_keeps_fresh(self):
        ais._EDGE_VESSELS["456"] = {
            "mmsi": "456",
            "lat": 1.25,
            "lon": 103.85,
            "_seen_at": time.time(),
        }
        ais._prune_edge_vessels()
        self.assertIn("456", ais._EDGE_VESSELS)

    def test_snapshot_edge_vessels_filters_by_region(self):
        ais._EDGE_VESSELS["1"] = {
            "mmsi": "1",
            "name": "A",
            "lat": 1.25,
            "lon": 103.85,
            "_seen_at": time.time(),
        }
        ais._EDGE_VESSELS["2"] = {
            "mmsi": "2",
            "name": "B",
            "lat": 53.5,
            "lon": 9.9,
            "_seen_at": time.time(),
        }
        with patch.dict(
            os.environ, {"WORLDBASE_OPERATOR_REGION": "thailand"}, clear=False
        ):
            snap = ais._snapshot_edge_vessels(ais._active_regions())
        mmsis = {v["mmsi"] for v in snap}
        self.assertIn("1", mmsis)
        self.assertNotIn("2", mmsis)

    def test_snapshot_edge_vessels_strips_internal_keys(self):
        ais._EDGE_VESSELS["789"] = {
            "mmsi": "789",
            "lat": 1.25,
            "lon": 103.85,
            "_seen_at": time.time(),
            "_internal": "secret",
        }
        with patch.dict(os.environ, {"WORLDBASE_MARITIME_REGIONS": "all"}, clear=False):
            snap = ais._snapshot_edge_vessels(ais._active_regions())
        self.assertEqual(len(snap), 1)
        self.assertNotIn("_seen_at", snap[0])
        self.assertNotIn("_internal", snap[0])
        self.assertEqual(snap[0]["mmsi"], "789")

    def test_edge_vessels_merged_into_maritime_result(self):
        async def run() -> dict:
            ais._STREAM["vessels"] = {}
            ais._STREAM["connected"] = True
            ais._STREAM["errors"] = []
            ais._EDGE_VESSELS["999"] = {
                "mmsi": "999",
                "name": "EdgeVessel",
                "lat": 1.25,
                "lon": 103.85,
                "_seen_at": time.time(),
            }
            with patch.dict(
                os.environ,
                {"AISSTREAM_API_KEY": "abc", "WORLDBASE_MARITIME_AISSTREAM": "1"},
                clear=False,
            ):
                with patch.object(
                    ais, "_supplement_myshiptracking", side_effect=lambda v, *a, **kw: v
                ):
                    with patch.object(ais, "_fetch_aishub", return_value=[]):
                        return await ais._build_maritime_result()

        with patch.dict(os.environ, {"WORLDBASE_MARITIME_REGIONS": "all"}, clear=False):
            result = asyncio.run(run())
        mmsis = {v["mmsi"] for v in result["vessels"]}
        self.assertIn("999", mmsis)
        ais._EDGE_VESSELS.clear()

    def test_receive_edge_vessels_endpoint(self):
        """Test POST /edge endpoint via direct function call."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ais.router)
        client = TestClient(app)

        with patch.dict(os.environ, {"NODE_INGEST_TOKEN": ""}, clear=False):
            ais._NODE_TOKEN = ""
            body = {
                "vessels": [
                    {"mmsi": "111", "name": "TestA", "lat": 1.3, "lon": 103.9},
                    {"mmsi": "222", "name": "TestB", "lat": 1.4, "lon": 104.0},
                ],
                "receiver_lat": 1.35,
                "receiver_lon": 103.95,
            }
            r = client.post(
                "/api/maritime/edge",
                data=json.dumps(body),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["ingested"], 2)
        self.assertEqual(data["edge_vessels_total"], 2)
        self.assertIn("111", ais._EDGE_VESSELS)
        self.assertIn("222", ais._EDGE_VESSELS)
        self.assertTrue(ais._EDGE_STATUS["active"])
        self.assertEqual(ais._EDGE_STATUS["lat"], 1.35)
        self.assertEqual(ais._EDGE_STATUS["lon"], 103.95)
        ais._EDGE_VESSELS.clear()

    def test_receive_edge_vessels_rejects_invalid_json(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ais.router)
        client = TestClient(app)

        with patch.dict(os.environ, {"NODE_INGEST_TOKEN": ""}, clear=False):
            ais._NODE_TOKEN = ""
            r = client.post(
                "/api/maritime/edge",
                data="not json",
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(r.status_code, 400)

    def test_receive_edge_vessels_skips_missing_coords(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ais.router)
        client = TestClient(app)

        with patch.dict(os.environ, {"NODE_INGEST_TOKEN": ""}, clear=False):
            ais._NODE_TOKEN = ""
            body = {
                "vessels": [
                    {"mmsi": "333", "name": "NoCoords"},
                    {"mmsi": "444", "lat": 1.3, "lon": 103.9},
                ],
            }
            r = client.post(
                "/api/maritime/edge",
                data=json.dumps(body),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["ingested"], 1)
        self.assertNotIn("333", ais._EDGE_VESSELS)
        self.assertIn("444", ais._EDGE_VESSELS)
        ais._EDGE_VESSELS.clear()

    def test_get_edge_status_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(ais.router)
        client = TestClient(app)

        ais._EDGE_VESSELS["555"] = {
            "mmsi": "555",
            "lat": 1.25,
            "lon": 103.85,
            "_seen_at": time.time(),
        }
        ais._EDGE_STATUS["active"] = True

        r = client.get("/api/maritime/edge")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["status"]["active"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["vessels"]), 1)
        ais._EDGE_VESSELS.clear()


if __name__ == "__main__":
    unittest.main()
