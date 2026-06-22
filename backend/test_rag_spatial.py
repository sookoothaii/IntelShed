"""Offline unit tests for spatial RAG helpers (Track R1.1)."""

from __future__ import annotations

import unittest

from rag_spatial import (
    apply_spatial_postfilter,
    encode_geohash,
    enrich_meta_spatial,
    extract_coords,
    meta_passes_bbox,
    point_in_bbox,
)


class RagSpatialTests(unittest.TestCase):
    def test_encode_geohash_bangkok(self):
        gh = encode_geohash(13.75, 100.5, precision=6)
        self.assertEqual(len(gh), 6)
        self.assertTrue(all(c in "0123456789bcdefghjkmnpqrstuvwxyz" for c in gh))

    def test_extract_coords_from_lat_lon(self):
        self.assertEqual(extract_coords({"lat": 13.75, "lon": 100.5}), (13.75, 100.5))

    def test_extract_coords_from_bbox_center(self):
        coords = extract_coords({"bbox": [100.0, 13.0, 101.0, 14.0]})
        self.assertIsNotNone(coords)
        self.assertAlmostEqual(coords[0], 13.5)
        self.assertAlmostEqual(coords[1], 100.5)

    def test_enrich_meta_adds_geohash(self):
        meta = enrich_meta_spatial({"lat": 13.75, "lon": 100.5})
        self.assertIn("geohash", meta)
        self.assertEqual(meta["lat"], 13.75)

    def test_meta_passes_bbox_allows_global_chunks(self):
        bbox = [95.0, 5.0, 106.0, 21.0]
        self.assertTrue(meta_passes_bbox({}, bbox))
        self.assertTrue(meta_passes_bbox({"lat": 13.75, "lon": 100.5}, bbox))
        self.assertFalse(meta_passes_bbox({"lat": 40.0, "lon": -74.0}, bbox))

    def test_postfilter_fail_open(self):
        bbox = [95.0, 5.0, 106.0, 21.0]
        hits = [
            {"id": 1, "meta": {"lat": 40.0, "lon": -74.0}, "text": "far"},
            {"id": 2, "meta": {}, "text": "global briefing"},
        ]
        out = apply_spatial_postfilter(hits, bbox, min_keep=2)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
