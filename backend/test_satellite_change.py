"""Unit tests for K4 satellite imagery change detection."""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure the feature is enabled when satellite_change is first imported.
os.environ.setdefault("WORLDBASE_SATELLITE_CHANGE", "1")

import satellite_change


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(satellite_change.router)
    return TestClient(app)


class SatelliteChangeUnitTests(unittest.TestCase):
    def test_resolve_bbox_region(self):
        bbox = satellite_change._resolve_bbox(None, "bangkok")
        self.assertEqual(bbox, [100.30, 13.50, 100.95, 14.05])

    def test_resolve_bbox_string(self):
        bbox = satellite_change._resolve_bbox("100.0,13.0,101.0,14.0", None)
        self.assertEqual(bbox, [100.0, 13.0, 101.0, 14.0])

    def test_utm_epsg_northern(self):
        self.assertEqual(satellite_change._utm_epsg(100.5, 13.7), "EPSG:32647")

    def test_utm_epsg_southern(self):
        self.assertEqual(satellite_change._utm_epsg(100.5, -13.7), "EPSG:32747")

    def test_compute_index(self):
        red = np.array([[0, 100], [200, 300]], dtype=np.float32)
        nir = np.array([[100, 200], [300, 400]], dtype=np.float32)
        ndvi = satellite_change._compute_index(red, nir)
        expected = np.array([1.0, 0.3333, 0.2, 0.1429], dtype=np.float32)
        np.testing.assert_allclose(ndvi.flatten(), expected, atol=0.001)

    def test_confidence_range(self):
        self.assertGreaterEqual(satellite_change._confidence(0.5, 1000), 0.0)
        self.assertLessEqual(satellite_change._confidence(0.5, 1000), 1.0)


class SatelliteChangeEndpointTests(unittest.TestCase):
    def test_health(self):
        client = _client()
        resp = client.get("/api/satellite/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["enabled"])
        self.assertTrue(data["rasterio_available"])

    def test_change_missing_region(self):
        client = _client()
        resp = client.get("/api/satellite/change?bbox=foo")
        self.assertEqual(resp.status_code, 400)

    def test_change_unknown_index(self):
        client = _client()
        resp = client.get("/api/satellite/change?region=bangkok&index=foo")
        self.assertEqual(resp.status_code, 400)

    def test_change_no_scenes(self):
        with patch.object(
            satellite_change,
            "_search_best_scenes",
            new=AsyncMock(
                side_effect=satellite_change.HTTPException(503, "no suitable scenes")
            ),
        ):
            client = _client()
            resp = client.get("/api/satellite/change?region=bangkok")
            self.assertEqual(resp.status_code, 503)
            self.assertIn("no suitable scenes", resp.json()["detail"])

    def test_change_success(self):
        fake_result = {
            "type": "FeatureCollection",
            "properties": {
                "before_id": "S2-A",
                "after_id": "S2-B",
                "index": "ndvi",
                "threshold": 0.2,
                "feature_count": 2,
                "total_pixels": 50,
                "before_scene": {"id": "S2-A"},
                "after_scene": {"id": "S2-B"},
            },
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": []},
                    "properties": {
                        "class": "decrease",
                        "mean_delta": -0.35,
                        "pixel_count": 30,
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": []},
                    "properties": {
                        "class": "increase",
                        "mean_delta": 0.4,
                        "pixel_count": 20,
                    },
                },
            ],
        }

        async def _fake_search(*args, **kwargs):
            return {"id": "S2-A"}, {"id": "S2-B"}

        with patch.object(satellite_change, "_search_best_scenes", new=_fake_search):
            with patch.object(
                satellite_change,
                "_run_change_detection_sync",
                return_value=fake_result,
            ):
                client = _client()
                resp = client.get("/api/satellite/change?region=bangkok")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["properties"]["feature_count"], 2)
                self.assertEqual(data["properties"]["index"], "ndvi")
                self.assertFalse(data["cached"])

    def test_change_disabled(self):
        with patch.object(satellite_change, "_ENABLED", False):
            client = _client()
            resp = client.get("/api/satellite/change?region=bangkok")
            self.assertEqual(resp.status_code, 503)
            self.assertIn("disabled", resp.json()["detail"])


class SatelliteChangeRasterTests(unittest.TestCase):
    def test_detect_changes_vectorizes(self):
        before = np.full((20, 20), 0.3, dtype=np.float32)
        after = np.full((20, 20), 0.3, dtype=np.float32)
        # Create a 5x5 increase zone.
        after[5:10, 5:10] = 0.7
        # Create a 4x4 decrease zone.
        after[12:16, 12:16] = 0.0

        transform = satellite_change.Affine.translation(
            0, 0
        ) * satellite_change.Affine.scale(1, -1)
        result = satellite_change._detect_changes(
            before,
            after,
            transform,
            "EPSG:4326",
            threshold=0.2,
            min_area_px=5,
            before_id="S2-A",
            after_id="S2-B",
            index_name="ndvi",
        )
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(result["properties"]["index"], "ndvi")
        self.assertGreaterEqual(result["properties"]["feature_count"], 2)
        classes = {f["properties"]["class"] for f in result["features"]}
        self.assertIn("increase", classes)
        self.assertIn("decrease", classes)


if __name__ == "__main__":
    unittest.main()
