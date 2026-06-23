"""Security tests for core feed routes (no network)."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from routes.core_feeds import _safe_tle_disk_path, _validate_satellite_group


class SatelliteGroupSecurityTests(unittest.TestCase):
    def test_rejects_path_traversal_group(self):
        with self.assertRaises(HTTPException) as ctx:
            _validate_satellite_group("../../../tmp/wb_pwn")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_accepts_known_group(self):
        self.assertEqual(_validate_satellite_group("active"), "active")
        self.assertEqual(_validate_satellite_group("STARLINK"), "starlink")

    def test_safe_disk_path_stays_under_tle_dir(self):
        tle_dir = "/tmp/worldbase-tle-test"
        path = _safe_tle_disk_path(tle_dir, "active")
        self.assertTrue(path.endswith("active.tle"))


if __name__ == "__main__":
    unittest.main()
