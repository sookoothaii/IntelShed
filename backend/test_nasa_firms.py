import unittest

from nasa_firms import (
    _combine_fires,
    _in_bbox,
    _parse_firms_confidence,
    _partition_fires,
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

    def test_combine_fires_regional_first(self):
        regional = [{"lat": 1, "lon": 100, "confidence": 70, "zone": "regional"}]
        global_f = [{"lat": 66, "lon": 160, "confidence": 90, "zone": "global"}]
        combined = _combine_fires(regional, global_f)
        self.assertEqual(combined[0]["zone"], "regional")
        self.assertEqual(combined[1]["zone"], "global")


if __name__ == "__main__":
    unittest.main()
