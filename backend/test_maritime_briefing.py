"""Tests for P7 maritime anomaly briefing bridge."""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch


class TestMaritimeBriefingBridge(unittest.TestCase):
    """Test maritime_briefing.py bridge functions."""

    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_gather_digest_disabled_when_trajectory_off(self):
        os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)
        from maritime_briefing import gather_maritime_anomaly_digest

        result = asyncio.run(gather_maritime_anomaly_digest())
        self.assertFalse(result["enabled"])
        self.assertEqual(result["count"], 0)

    def test_gather_digest_enabled_no_anomalies(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from maritime_briefing import gather_maritime_anomaly_digest

            with patch("ais_trajectory.trajectory_enabled", return_value=True):
                with patch("ais_trajectory.detect_anomalies", return_value=[]):
                    result = asyncio.run(gather_maritime_anomaly_digest())
            self.assertTrue(result["enabled"])
            self.assertEqual(result["count"], 0)
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)

    def test_gather_digest_with_anomalies(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from maritime_briefing import gather_maritime_anomaly_digest

            fake_anomaly = {
                "mmsi": "123456789",
                "anomaly_score": 0.85,
                "nearest_port_id": "laem_chabang",
                "nearest_port_nm": 1.5,
                "ais_gap_max_sec": 10800.0,
                "night_port_visits": 3,
                "course_changes": 8,
                "speed_variance": 18.0,
                "risk_zone_id": "malacca_piracy",
                "mean_speed": 0.5,
                "in_corridor": True,
            }
            with patch("ais_trajectory.trajectory_enabled", return_value=True):
                with patch(
                    "ais_trajectory.detect_anomalies", return_value=[fake_anomaly]
                ):
                    result = asyncio.run(gather_maritime_anomaly_digest())
            self.assertTrue(result["enabled"])
            self.assertEqual(result["count"], 1)
            line = result["lines"][0]
            self.assertIn("123456789", line["text"])
            self.assertEqual(line["bucket"], "local")
            self.assertEqual(line["severity"], "critical")
            self.assertIn("AIS gap", line["text"])
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)

    def test_gather_digest_max_lines(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from maritime_briefing import gather_maritime_anomaly_digest

            fake_anomalies = [
                {
                    "mmsi": f"mmsi_{i}",
                    "anomaly_score": 0.5 + i * 0.05,
                    "nearest_port_id": "singapore",
                    "nearest_port_nm": 10.0,
                    "ais_gap_max_sec": 3600.0,
                    "night_port_visits": 0,
                    "course_changes": 3,
                    "speed_variance": 5.0,
                    "risk_zone_id": "",
                    "mean_speed": 12.0,
                    "in_corridor": True,
                }
                for i in range(10)
            ]
            with patch("ais_trajectory.trajectory_enabled", return_value=True):
                with patch(
                    "ais_trajectory.detect_anomalies", return_value=fake_anomalies
                ):
                    result = asyncio.run(gather_maritime_anomaly_digest(max_lines=3))
            self.assertEqual(result["count"], 3)
            # Should be sorted by score descending
            scores = [line["anomaly_score"] for line in result["lines"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)

    def test_classify_bucket_local(self):
        from maritime_briefing import _classify_bucket

        self.assertEqual(
            _classify_bucket({"nearest_port_id": "laem_chabang", "in_corridor": True}),
            "local",
        )
        self.assertEqual(
            _classify_bucket({"nearest_port_id": "bangkok_port", "in_corridor": False}),
            "local",
        )

    def test_classify_bucket_regional(self):
        from maritime_briefing import _classify_bucket

        self.assertEqual(
            _classify_bucket({"nearest_port_id": "singapore", "in_corridor": True}),
            "regional",
        )
        self.assertEqual(
            _classify_bucket({"nearest_port_id": "", "in_corridor": True}),
            "regional",
        )

    def test_classify_bucket_global(self):
        from maritime_briefing import _classify_bucket

        self.assertEqual(
            _classify_bucket({"nearest_port_id": "", "in_corridor": False}),
            "global",
        )

    def test_format_anomaly_line(self):
        from maritime_briefing import _format_anomaly_line

        anomaly = {
            "mmsi": "987654321",
            "anomaly_score": 0.75,
            "nearest_port_id": "phuket",
            "nearest_port_nm": 1.0,
            "ais_gap_max_sec": 9000.0,
            "night_port_visits": 2,
            "course_changes": 7,
            "speed_variance": 20.0,
            "risk_zone_id": "scs_disputed",
            "mean_speed": 0.3,
            "in_corridor": True,
        }
        line = _format_anomaly_line(anomaly)
        self.assertIn("987654321", line["text"])
        self.assertIn("phuket", line["text"])
        self.assertEqual(line["bucket"], "local")
        self.assertEqual(line["severity"], "high")
        self.assertIn("AIS gap", line["text"])
        self.assertIn("night-port", line["text"])
        self.assertIn("course changes", line["text"])
        self.assertIn("speed var", line["text"])
        self.assertIn("scs_disputed", line["text"])

    def test_format_anomaly_line_anchored(self):
        from maritime_briefing import _format_anomaly_line

        anomaly = {
            "mmsi": "111222333",
            "anomaly_score": 0.4,
            "nearest_port_id": "singapore",
            "nearest_port_nm": 3.0,
            "ais_gap_max_sec": 1800.0,
            "night_port_visits": 0,
            "course_changes": 1,
            "speed_variance": 2.0,
            "risk_zone_id": "",
            "mean_speed": 0.5,
            "in_corridor": False,
        }
        line = _format_anomaly_line(anomaly)
        self.assertIn("anchored near port", line["text"])

    def test_build_watch_items_high_score(self):
        from maritime_briefing import build_maritime_watch_items

        digest = {
            "enabled": True,
            "lines": [
                {
                    "mmsi": "123456789",
                    "anomaly_score": 0.85,
                    "nearest_port": "laem_chabang",
                    "bucket": "local",
                    "sources": ["maritime_trajectory"],
                },
            ],
        }
        items = build_maritime_watch_items(digest)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prefix"], "maritime")
        self.assertEqual(items[0]["bucket"], "local")
        self.assertIn("123456789", items[0]["id"])

    def test_build_watch_items_skip_low_score(self):
        from maritime_briefing import build_maritime_watch_items

        digest = {
            "enabled": True,
            "lines": [
                {
                    "mmsi": "999999999",
                    "anomaly_score": 0.5,
                    "nearest_port": "unknown",
                    "bucket": "global",
                    "sources": ["maritime_trajectory"],
                },
            ],
        }
        items = build_maritime_watch_items(digest)
        self.assertEqual(len(items), 0)

    def test_build_watch_items_ftm_correlated(self):
        from maritime_briefing import build_maritime_watch_items

        digest = {
            "enabled": True,
            "lines": [
                {
                    "mmsi": "555666777",
                    "anomaly_score": 0.55,
                    "nearest_port": "singapore",
                    "bucket": "regional",
                    "ftm_entity_id": "vessel-abc",
                    "sources": ["maritime_trajectory"],
                },
            ],
        }
        items = build_maritime_watch_items(digest)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["entity_id"], "vessel-abc")

    def test_build_watch_items_empty_digest(self):
        from maritime_briefing import build_maritime_watch_items

        items = build_maritime_watch_items({"enabled": False})
        self.assertEqual(items, [])

    def test_find_ftm_vessel_no_query(self):
        from maritime_briefing import _find_ftm_vessel

        self.assertIsNone(_find_ftm_vessel("123", None))

    def test_find_ftm_vessel_match(self):
        from maritime_briefing import _find_ftm_vessel

        class FakeQuery:
            def list_entities(self, limit=1000):
                return [
                    {
                        "id": "vessel-1",
                        "schema": "Vessel",
                        "caption": "MV TEST",
                        "properties": {"mmsi": ["123456789"]},
                    },
                    {
                        "id": "org-1",
                        "schema": "Organization",
                        "caption": "ACME",
                        "properties": {},
                    },
                ]

        result = _find_ftm_vessel("123456789", FakeQuery())
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "vessel-1")

    def test_find_ftm_vessel_no_match(self):
        from maritime_briefing import _find_ftm_vessel

        class FakeQuery:
            def list_entities(self, limit=1000):
                return [
                    {
                        "id": "vessel-1",
                        "schema": "Vessel",
                        "caption": "MV TEST",
                        "properties": {"mmsi": ["999999999"]},
                    },
                ]

        result = _find_ftm_vessel("123456789", FakeQuery())
        self.assertIsNone(result)

    def test_gather_digest_fail_soft_on_exception(self):
        os.environ["WORLDBASE_MARITIME_TRAJECTORY"] = "1"
        try:
            from maritime_briefing import gather_maritime_anomaly_digest

            with patch(
                "ais_trajectory.trajectory_enabled",
                side_effect=Exception("DB error"),
            ):
                result = asyncio.run(gather_maritime_anomaly_digest())
            self.assertFalse(result["enabled"])
        finally:
            os.environ.pop("WORLDBASE_MARITIME_TRAJECTORY", None)


if __name__ == "__main__":
    unittest.main()
