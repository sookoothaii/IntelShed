"""Security regression — core feed path handling."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from routes.core_feeds import _sanitize_tle_group


class CoreFeedsSecurityTests(unittest.TestCase):
    def test_sanitize_tle_group_accepts_known(self):
        self.assertEqual(_sanitize_tle_group("starlink"), "starlink")
        self.assertEqual(_sanitize_tle_group("gps-ops"), "gps-ops")

    def test_sanitize_tle_group_rejects_traversal(self):
        with self.assertRaises(HTTPException) as ctx:
            _sanitize_tle_group("../../tmp/wb_pwn")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
