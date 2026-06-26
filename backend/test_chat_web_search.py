"""Tests for auto-web-search trigger in chat_proxy.

Verifies that _wants_web_search detects explicit web search requests
and _auto_web_search fetches and formats DuckDuckGo results.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import chat_proxy


class WantsWebSearchTests(unittest.TestCase):
    """Test _wants_web_search trigger detection."""

    def test_explicit_duckduckgo(self):
        self.assertTrue(chat_proxy._wants_web_search("nutze duckduckgo zur recherche"))

    def test_explicit_web_search(self):
        self.assertTrue(
            chat_proxy._wants_web_search("please web search for space weather")
        )

    def test_live_data(self):
        self.assertTrue(
            chat_proxy._wants_web_search("I need live data on solar flares")
        )

    def test_recherche_german(self):
        self.assertTrue(chat_proxy._wants_web_search("recherche weltraumwetter"))

    def test_aktuelle_daten_german(self):
        self.assertTrue(chat_proxy._wants_web_search("aktuelle daten zum kp index"))

    def test_no_trigger_normal_query(self):
        self.assertFalse(chat_proxy._wants_web_search("What is space weather?"))

    def test_no_trigger_short_text(self):
        self.assertFalse(chat_proxy._wants_web_search("hi"))

    def test_no_trigger_empty(self):
        self.assertFalse(chat_proxy._wants_web_search(""))

    def test_realtime_data(self):
        self.assertTrue(
            chat_proxy._wants_web_search("give me real-time data on geomagnetic storms")
        )

    def test_internet_search(self):
        self.assertTrue(
            chat_proxy._wants_web_search("do an internet search for NOAA SWPC")
        )

    def test_suche_mir_internet_regex(self):
        self.assertTrue(
            chat_proxy._wants_web_search("suche mir gezielte infos dazu im internet")
        )

    def test_suche_infos_internet_regex(self):
        self.assertTrue(chat_proxy._wants_web_search("suche informationen im internet"))

    def test_search_for_online_regex(self):
        self.assertTrue(
            chat_proxy._wants_web_search("search for info about this online")
        )

    def test_find_web_regex(self):
        self.assertTrue(chat_proxy._wants_web_search("find details on the web"))

    def test_recherche_internet_regex(self):
        self.assertTrue(chat_proxy._wants_web_search("recherche dazu im internet"))

    def test_suche_im_internet_direct(self):
        self.assertTrue(
            chat_proxy._wants_web_search("suche im internet nach weltraumwetter")
        )

    def test_suche_mir_direct(self):
        self.assertTrue(
            chat_proxy._wants_web_search("suche mir details zu diesem ereignis")
        )

    def test_no_trigger_generic_suche(self):
        """'suche' alone without internet/web/online context should not trigger."""
        self.assertFalse(
            chat_proxy._wants_web_search("suche ist ein wichtiges werkzeug")
        )

    def test_check_noch_einmal(self):
        self.assertTrue(chat_proxy._wants_web_search("check noch einmal nach infos"))

    def test_suche_nach_regex(self):
        self.assertTrue(
            chat_proxy._wants_web_search("suche nach details zu diesem ereignis")
        )

    def test_pruefe_nach_regex(self):
        self.assertTrue(
            chat_proxy._wants_web_search("prüfe nach aktuellen informationen")
        )

    def test_schau_nach_regex(self):
        self.assertTrue(chat_proxy._wants_web_search("schau mal nach im internet"))

    def test_check_again(self):
        self.assertTrue(chat_proxy._wants_web_search("check again for updates"))

    def test_find_info_regex(self):
        self.assertTrue(chat_proxy._wants_web_search("find more info about this event"))


class AutoWebSearchTests(unittest.IsolatedAsyncioTestCase):
    """Test _auto_web_search fetches and formats results."""

    async def test_returns_formatted_results(self):
        mock_results = {
            "query": "space weather",
            "count": 2,
            "results": [
                {
                    "title": "NOAA SWPC",
                    "url": "https://swpc.noaa.gov",
                    "snippet": "Kp index 3",
                },
                {
                    "title": "DLR Space Weather",
                    "url": "https://dlr.de/sw",
                    "snippet": "Solar wind 400 km/s",
                },
            ],
        }
        with patch(
            "chat_context.search_web", new_callable=AsyncMock, return_value=mock_results
        ):
            result = await chat_proxy._auto_web_search("space weather")
        self.assertIn("[1] NOAA SWPC", result)
        self.assertIn("Kp index 3", result)
        self.assertIn("[2] DLR Space Weather", result)
        self.assertIn("https://swpc.noaa.gov", result)

    async def test_returns_empty_on_no_results(self):
        with patch(
            "chat_context.search_web",
            new_callable=AsyncMock,
            return_value={"results": []},
        ):
            result = await chat_proxy._auto_web_search("nonexistent topic xyz")
        self.assertEqual(result, "")

    async def test_returns_empty_on_error(self):
        with patch(
            "chat_context.search_web",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await chat_proxy._auto_web_search("test query")
        self.assertEqual(result, "")


class ClaimAuditorTests(unittest.TestCase):
    """Test _claim_auditor detects hallucinated claims."""

    def test_no_violations_when_grounded(self):
        ctx = ["Entity: Wildfire Test\nDATE: 6/10/2026\nhttps://example.com/fire"]
        resp = "This wildfire was reported on 6/10/2026. See https://example.com/fire for details."
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIsNone(meta)
        self.assertEqual(text, resp)

    def test_detects_fabricated_source(self):
        ctx = ["Entity: Wildfire Test\nDATE: 6/10/2026"]
        resp = "According to GDELT reports, this fire burned 32,000 acres."
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIsNotNone(meta)
        self.assertIn("GDELT", meta["claim_auditor"]["violations"][0])

    def test_detects_fabricated_url(self):
        ctx = ["Entity: Wildfire Test\nDATE: 6/10/2026"]
        resp = "More info at https://fakesite.com/details"
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIsNotNone(meta)
        self.assertTrue(
            any("fakesite.com" in v for v in meta["claim_auditor"]["violations"])
        )

    def test_detects_fabricated_timestamp(self):
        ctx = ["Entity: Wildfire Test\nDATE: 6/10/2026"]
        resp = "The fire was first reported at 8:03 AM and contained by 12:33 PM."
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIsNotNone(meta)
        violations = meta["claim_auditor"]["violations"]
        self.assertTrue(any("8:03" in v for v in violations))
        self.assertTrue(any("12:33" in v for v in violations))

    def test_allows_source_in_context(self):
        ctx = [
            "=== INTERNAL TELEMETRY ===\nGDELT: 3 events near location\nUSGS: M2.1 quake"
        ]
        resp = "GDELT shows 3 events and USGS recorded a M2.1 quake."
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIsNone(meta)

    def test_empty_context_blocks(self):
        resp = "Some response with GDELT reference."
        text, meta = chat_proxy._claim_auditor(resp, [])
        self.assertEqual(text, resp)
        self.assertIsNone(meta)

    def test_empty_response(self):
        ctx = ["Some context"]
        text, meta = chat_proxy._claim_auditor("", ctx)
        self.assertEqual(text, "")
        self.assertIsNone(meta)

    def test_warning_appended_to_response(self):
        ctx = ["Entity: Test Fire\nDATE: 6/10/2026"]
        resp = "GDELT reports this fire at 8:03 AM."
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertIn("CLAIM AUDITOR WARNING", text)
        self.assertIn("GDELT", text)
        self.assertIn("8:03", text)

    def test_multiple_violations_capped(self):
        ctx = ["Entity: Test"]
        sources = " ".join(chat_proxy._KNOWN_SOURCES[:15])
        resp = f"Sources: {sources}"
        text, meta = chat_proxy._claim_auditor(resp, ctx)
        self.assertGreater(meta["claim_auditor"]["violation_count"], 10)
        self.assertLessEqual(len(meta["claim_auditor"]["violations"]), 10)


if __name__ == "__main__":
    unittest.main()
