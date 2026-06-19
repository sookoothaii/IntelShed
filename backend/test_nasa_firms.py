import unittest

from nasa_firms import (
    _combine_globe_fires,
    _in_bbox,
    _parse_firms_confidence,
    _partition_fires,
    filter_fires,
    haversine_km,
)


class TestNasaFirms(unittest.TestCase):
    def test_confidence_letters_and_digits(self):
        self.assertEqual(_parse_firms_confidence("h"), 90)
        self.assertEqual(_parse_firms_confidence("n"), 65)
        self.assertEqual(_parse_firms_confidence("l"), 35)
        self.assertEqual(_parse_firms_confidence("80"), 80)

    def test_partition_asean_bbox(self):
        fires = [
            {"lat": 13.75, "lon": 100.5, "confidence": 90},
            {"lat": -31.24, "lon": 30.02, "confidence": 95},
        ]
        bbox = [92.0, -11.0, 141.0, 28.0]
        regional, global_f = _partition_fires(fires, bbox)
        self.assertEqual(len(regional), 1)
        self.assertEqual(regional[0]["zone"], "regional")
        self.assertEqual(len(global_f), 1)
        self.assertEqual(global_f[0]["zone"], "global")

    def test_in_bbox(self):
        bbox = [92.0, -11.0, 141.0, 28.0]
        self.assertTrue(_in_bbox(13.75, 100.5, bbox))
        self.assertFalse(_in_bbox(66.59, 166.26, bbox))

    def test_combine_globe_fires_regional_first(self):
        regional = [{"lat": 1, "lon": 100, "confidence": 70, "zone": "regional"}]
        global_f = [{"lat": 66, "lon": 160, "confidence": 90, "zone": "global"}]
        combined = _combine_globe_fires(regional, global_f)
        self.assertEqual(combined[0]["zone"], "regional")
        self.assertEqual(combined[1]["zone"], "global")

    def test_filter_distance_from_reference(self):
        fires = [
            {"lat": 13.75, "lon": 100.5, "confidence": 65, "zone": "regional", "frp": 1},
            {"lat": -8.1, "lon": 140.8, "confidence": 65, "zone": "regional", "frp": 2},
        ]
        page, matched = filter_fires(
            fires,
            zone="regional",
            sort="distance",
            near_lat=9.55,
            near_lon=100.05,
            max_km=1500,
            limit=10,
        )
        self.assertEqual(matched, 1)
        self.assertAlmostEqual(page[0]["lat"], 13.75, places=2)
        self.assertLess(page[0]["distance_km"], 600)

    def test_haversine_short_hop(self):
        d = haversine_km(9.55, 100.05, 13.75, 100.5)
        self.assertGreater(d, 400)
        self.assertLess(d, 550)


if __name__ == "__main__":
    unittest.main()
