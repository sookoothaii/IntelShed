"""Tests for P7 — Maritime Pattern-of-Life (AIS Trajectory + Anomaly Detection)."""

from __future__ import annotations

import os
import time
import unittest


class TestP7Config(unittest.TestCase):
    """P7 config integration."""

    def test_trajectory_disabled_by_default(self):
        os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)
        from ais_trajectory import trajectory_enabled

        self.assertFalse(trajectory_enabled())

    def test_trajectory_enabled(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from ais_trajectory import trajectory_enabled

            self.assertTrue(trajectory_enabled())
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)

    def test_config_maritime_trajectory_default_off(self):
        os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.maritime_trajectory_enabled)


class TestP7Functions(unittest.TestCase):
    """P7 function existence and basic behavior."""

    def test_store_position_exists(self):
        from ais_trajectory import store_position

        self.assertTrue(callable(store_position))

    def test_compute_features_exists(self):
        from ais_trajectory import compute_features

        self.assertTrue(callable(compute_features))

    def test_detect_anomalies_exists(self):
        from ais_trajectory import detect_anomalies

        self.assertTrue(callable(detect_anomalies))

    def test_get_vessel_features_exists(self):
        from ais_trajectory import get_vessel_features

        self.assertTrue(callable(get_vessel_features))

    def test_prune_old_positions_exists(self):
        from ais_trajectory import prune_old_positions

        self.assertTrue(callable(prune_old_positions))

    def test_trajectory_stats_exists(self):
        from ais_trajectory import trajectory_stats

        self.assertTrue(callable(trajectory_stats))

    def test_flush_buffer_exists(self):
        from ais_trajectory import flush_buffer

        self.assertTrue(callable(flush_buffer))

    def test_haversine_km(self):
        from ais_trajectory import _haversine_km

        # Bangkok to Singapore ~1427 km
        dist = _haversine_km(13.7563, 100.5018, 1.3521, 103.8198)
        self.assertGreater(dist, 1300)
        self.assertLess(dist, 1500)

    def test_nearest_port(self):
        from ais_trajectory import _nearest_port

        # Near Singapore
        nm, pid = _nearest_port(1.3, 103.8)
        self.assertEqual(pid, "singapore")
        self.assertLess(nm, 50)

    def test_in_corridor(self):
        from ais_trajectory import _in_corridor

        # In Malacca Strait
        self.assertTrue(_in_corridor(5.0, 100.0))
        # In Singapore Strait
        self.assertTrue(_in_corridor(1.0, 104.0))
        # Outside corridors
        self.assertFalse(_in_corridor(50.0, 0.0))

    def test_proximity_to_risk_zones(self):
        from ais_trajectory import _proximity_to_risk_zones

        # Near Malacca piracy zone
        score, zone_id = _proximity_to_risk_zones(3.5, 100.5)
        self.assertGreater(score, 0.5)
        self.assertEqual(zone_id, "malacca_piracy")

        # Far from any risk zone
        score, zone_id = _proximity_to_risk_zones(50.0, 0.0)
        self.assertEqual(score, 0.0)

    def test_km_to_nm(self):
        from ais_trajectory import _km_to_nm

        self.assertAlmostEqual(_km_to_nm(1.852), 1.0, places=2)

    def test_is_night(self):
        from ais_trajectory import _is_night

        # Just test the function doesn't crash
        result = _is_night(time.time())
        self.assertIsInstance(result, bool)


class TestP7StorePosition(unittest.TestCase):
    """P7 ringbuffer non-blocking ingest."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_store_position_no_crash_when_disabled(self):
        os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)
        from ais_trajectory import store_position, _RINGBUFFER

        initial = len(_RINGBUFFER)
        store_position("123456789", 1.0, 103.0, speed=10.0, course=45.0)
        # Should not append when disabled
        self.assertEqual(len(_RINGBUFFER), initial)

    def test_store_position_appends_to_ringbuffer(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from ais_trajectory import store_position, _RINGBUFFER, flush_buffer

            _RINGBUFFER.clear()
            store_position("123456789", 1.0, 103.0, speed=10.0, course=45.0)
            self.assertEqual(len(_RINGBUFFER), 1)
            # Clean up
            flush_buffer()
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)


class TestP7APIRoutes(unittest.TestCase):
    """P7 API route presence."""

    def test_maritime_router_has_anomaly_routes(self):
        from ais_bridge import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/maritime/anomalies", paths)
        self.assertIn("/api/maritime/trajectory/{mmsi}", paths)
        self.assertIn("/api/maritime/trajectory/stats", paths)


class TestP7AISBridgeIntegration(unittest.TestCase):
    """P7 integration in ais_bridge.py."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_ais_bridge_has_trajectory_import(self):
        """Check that _ingest_stream_message calls ais_trajectory.store_position."""
        import ais_bridge

        source = open(ais_bridge.__file__).read()
        self.assertIn("ais_trajectory", source)
        self.assertIn("store_position", source)


if __name__ == "__main__":
    unittest.main()
