"""Unit tests for adaptive RAG chunking profiles (Track R1.3, no Ollama)."""

from __future__ import annotations

import unittest

from ingest.mapping_runner import iter_rag_chunk_entries, load_rag_profile
from rag_chunking import (
    chunk_record,
    chunk_text,
    format_record_body,
    get_source_profile,
    profile_from_yaml,
    split_text,
)


class RagChunkingTests(unittest.TestCase):
    def test_headline_profile_keeps_short_text_single_chunk(self):
        profile = get_source_profile("gdelt_pulse_local", "gdelt_events")
        parts = chunk_record(
            {"title": "Flood near Bangkok", "snippet": "Heavy rain continues", "id": "x1"},
            profile,
        )
        self.assertEqual(len(parts), 1)
        self.assertIn("Bangkok", parts[0])

    def test_paragraph_profile_splits_long_gdacs_text(self):
        profile = load_rag_profile("gdacs_alerts")
        self.assertIsNotNone(profile)
        assert profile is not None
        long_desc = "Impact detail. " * 120
        parts = chunk_record(
            {
                "eventid": "gdacs-abc",
                "title": "EQ Alert",
                "description": long_desc,
                "eventtype": "EQ",
                "alertlevel": "Orange",
            },
            profile,
        )
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= profile.max_chars + 20 for p in parts))

    def test_ais_template_record(self):
        profile = load_rag_profile("ais_vessels")
        self.assertIsNotNone(profile)
        assert profile is not None
        body = format_record_body(
            {
                "name": "Test Ship",
                "mmsi": "123456789",
                "imo": "9876543",
                "flag": "TH",
                "type": "Cargo",
                "callsign": "HSXX",
            },
            profile,
        )
        self.assertIn("Test Ship", body)
        self.assertIn("123456789", body)

    def test_briefing_default_splits_into_multiple_chunks(self):
        profile = get_source_profile("briefing")
        text = ("Section line.\n\n") * 80
        parts = chunk_text(text, profile)
        self.assertGreater(len(parts), 1)

    def test_iter_rag_chunk_entries_multi_chunk_ids(self):
        long_desc = "Sentence one. " * 90
        entries = iter_rag_chunk_entries(
            [
                {
                    "eventid": "gdacs-1",
                    "title": "Flood",
                    "description": long_desc,
                    "eventtype": "FL",
                    "alertlevel": "Green",
                }
            ],
            "gdacs_alerts",
            rag_source="gdacs",
        )
        self.assertGreater(len(entries), 1)
        self.assertTrue(entries[0][1].endswith(":c0"))
        self.assertEqual(entries[0][0], "gdacs")

    def test_profile_from_yaml_defaults(self):
        profile = profile_from_yaml({"strategy": "headline", "max_chars": 400})
        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.strategy, "headline")
        self.assertEqual(profile.max_chars, 400)

    def test_split_text_respects_overlap(self):
        text = "Alpha block.\n\n" * 40
        parts = split_text(text, max_chars=120, overlap=30)
        self.assertGreater(len(parts), 2)


if __name__ == "__main__":
    unittest.main()
