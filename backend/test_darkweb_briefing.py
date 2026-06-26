"""Tests for darkweb_briefing ransomware digest bridge (P8.6)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from darkweb_briefing import DarkwebBriefingBridge, _operator_countries


class RansomwareBriefingTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled(self):
        cfg = MagicMock()
        cfg.ransomware_enabled = False
        bridge = DarkwebBriefingBridge(config=cfg)
        digest = await bridge.gather_ransomware_digest()
        self.assertFalse(digest["enabled"])
        self.assertEqual(digest["count"], 0)

    async def test_scores_and_prioritises(self):
        cfg = MagicMock()
        cfg.ransomware_enabled = True
        cfg.operator_region = "thailand"

        bridge = DarkwebBriefingBridge(config=cfg)
        bridge._find_ftm_match = lambda name: None
        victims = [
            {
                "victim": "GlobalCorp",
                "group": "akira",
                "discovered": "2026-06-25T10:00:00+00:00",
                "country": "US",
                "activity": "tech",
            },
            {
                "victim": "BangkokHospital",
                "group": "lockbit",
                "discovered": "2026-06-25T12:00:00+00:00",
                "country": "TH",
                "activity": "healthcare",
            },
            {
                "victim": "HanoiWorks",
                "group": "qilin",
                "discovered": "2026-06-25T11:00:00+00:00",
                "country": "VN",
                "activity": "manufacturing",
            },
        ]
        lines = []
        for v in victims:
            score, _ = bridge._score_victim(v)
            lines.append((score, v))
        # TH should outrank global, VN should outrank global.
        self.assertTrue(lines[1][0] > lines[0][0])
        self.assertTrue(lines[2][0] > lines[0][0])

    def test_operator_countries(self):
        self.assertIn("TH", _operator_countries("thailand"))
        self.assertIn("MM", _operator_countries("thailand"))
        self.assertEqual(_operator_countries("global"), [])

    def test_extract_data_size(self):
        bridge = DarkwebBriefingBridge()
        self.assertEqual(
            bridge._extract_data_size_gb({"description": "Data leak: 1.5 TB"}),
            1500.0,
        )
        self.assertEqual(
            bridge._extract_data_size_gb({"description": "50GB of files"}),
            50.0,
        )
        self.assertIsNone(
            bridge._extract_data_size_gb({"description": "No size mentioned"})
        )

    def test_build_watch_items(self):
        cfg = MagicMock()
        cfg.operator_region = "thailand"
        bridge = DarkwebBriefingBridge(config=cfg)
        lines = [
            {
                "group": "AKIRA",
                "victim": "Acme",
                "country": "TH",
                "industry": "logistics",
                "relevance_score": 0.85,
                "is_correlated_to_ftm": True,
                "sources": ["ransomware.live"],
            }
        ]
        items = bridge.build_watch_items(lines)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prefix"], "ransomware")
        self.assertEqual(items[0]["bucket"], "local")

    def test_format_prompt_block(self):
        bridge = DarkwebBriefingBridge()
        block = bridge.format_prompt_block([])
        self.assertEqual(block, "")
        block = bridge.format_prompt_block([{"text": "[AKIRA] Acme (TH, logistics)"}])
        self.assertIn("RANSOMWARE VICTIMS", block)
        self.assertIn("[AKIRA] Acme", block)


if __name__ == "__main__":
    unittest.main()
