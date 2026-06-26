"""Tests for darkweb_bridge (P8)."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

import darkweb_bridge


class DarkwebBridgeTests(unittest.IsolatedAsyncioTestCase):
    def test_disabled_by_default(self):
        with patch.object(darkweb_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.darkweb_enabled = False
            mock_cfg.return_value = cfg
            self.assertFalse(darkweb_bridge.darkweb_enabled())

    def test_engines_default(self):
        self.assertIn("ahmia", darkweb_bridge._engines())

    def test_max_results(self):
        self.assertEqual(darkweb_bridge._max_results(), 50)

    def test_engine_registry_has_ahmia_and_darksearch(self):
        self.assertIn("ahmia", darkweb_bridge._ENGINE_REGISTRY)
        self.assertIn("darksearch", darkweb_bridge._ENGINE_REGISTRY)
        self.assertFalse(darkweb_bridge._ENGINE_REGISTRY["ahmia"]["tor_required"])
        self.assertTrue(darkweb_bridge._ENGINE_REGISTRY["darksearch"].get("deprecated"))

    def test_extract_entities(self):
        text = (
            "Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa or "
            "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh. "
            "Contact alice@example.com or visit http://abc234abc234abcd.onion/page. "
            "PGP: 1234567890ABCDEF1234567890ABCDEF12345678."
        )
        entities = darkweb_bridge._extract_entities(text)
        self.assertIn("btc_wallet", entities)
        self.assertIn("email", entities)
        self.assertIn("onion", entities)
        self.assertIn("pgp_fingerprint", entities)
        self.assertIn("alice@example.com", entities["email"])
        self.assertTrue(any(".onion" in u for u in entities["onion"]))

    def test_hash_url(self):
        h1 = darkweb_bridge._hash_url("http://example.onion/test")
        h2 = darkweb_bridge._hash_url("http://example.onion/test")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_to_mention(self):
        result = {
            "title": "Test",
            "url": "http://test.onion/page",
            "snippet": "snippet",
            "engine": "ahmia",
        }
        m = darkweb_bridge._to_mention(result)
        self.assertEqual(m["schema"], "Mention")
        self.assertIn("http://test.onion/page", m["properties"]["url"])
        self.assertEqual(m["properties"]["source"], ["ahmia"])

    def test_match_entities_to_darkweb(self):
        results = [
            {"title": "Hello Alice", "snippet": "Bob too", "url": "http://x.onion/1"},
            {"title": "Other", "snippet": "nothing", "url": "http://x.onion/2"},
        ]
        entities = [
            {"id": "ent1", "name": "Alice"},
            {"id": "ent2", "name": "Bob", "aliases": ["Bobby"]},
        ]
        matches = darkweb_bridge.match_entities_to_darkweb(results, entities)
        self.assertEqual(len(matches), 1)
        self.assertEqual(sorted(matches[0]["matched_names"]), ["Alice", "Bob"])
        self.assertEqual(sorted(matches[0]["entity_ids"]), ["ent1", "ent2"])

    async def test_search_disabled(self):
        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=False):
            out = await darkweb_bridge.search_darkweb("test", limit=10)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["error"], "darkweb disabled")

    async def test_search_ahmia(self):
        html = """
        <li class="result">
            <h4><a href="http://abc234abc234abcd.onion/page">Test Title</a></h4>
            <p>Test snippet content</p>
        </li>
        """
        with patch("darkweb_bridge.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            instance.get = AsyncMock(return_value=response)

            with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
                out = await darkweb_bridge.search_darkweb(
                    "test", engines=["ahmia"], limit=10
                )
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["results"][0]["engine"], "ahmia")
            self.assertEqual(
                out["results"][0]["url"], "http://abc234abc234abcd.onion/page"
            )

    async def test_search_darksearch(self):
        payload = {
            "data": [
                {
                    "title": "Dark Result",
                    "link": "http://xyz234xyz234xyz2.onion/post",
                    "snippet": "Dark snippet",
                }
            ]
        }
        with patch("darkweb_bridge.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            response = MagicMock()
            response.json = MagicMock(return_value=payload)
            response.raise_for_status = MagicMock()
            instance.get = AsyncMock(return_value=response)

            with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
                out = await darkweb_bridge.search_darkweb(
                    "test", engines=["darksearch"], limit=10
                )
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["results"][0]["engine"], "darksearch")
            self.assertEqual(
                out["results"][0]["url"], "http://xyz234xyz234xyz2.onion/post"
            )

    def test_ingest_results_empty(self):
        self.assertEqual(
            darkweb_bridge.ingest_results([]), {"count": 0, "ids": [], "error": None}
        )

    def test_tor_client_requires_proxy(self):
        with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
            with self.assertRaises(RuntimeError):
                darkweb_bridge._tor_client()

    def test_tor_client_uses_configured_proxy(self):
        with patch.object(
            darkweb_bridge, "_tor_proxy", return_value="socks5://127.0.0.1:9050"
        ):
            client = darkweb_bridge._tor_client()
            self.assertIsInstance(client, httpx.AsyncClient)

    async def test_tor_engine_skipped_without_proxy(self):
        with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
            with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
                out = await darkweb_bridge.search_darkweb(
                    "test", engines=["torch"], limit=10
                )
        self.assertEqual(out["count"], 0)
        self.assertIn("requires Tor proxy", out.get("error", ""))

    async def test_parallel_clearnet_engines(self):
        html = """
        <li class="result">
            <h4><a href="http://abc234abc234abcd.onion/page">Ahmia Title</a></h4>
            <p>Ahmia snippet</p>
        </li>
        """
        with patch("darkweb_bridge.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            response = MagicMock()
            response.text = html
            response.raise_for_status = MagicMock()
            instance.get = AsyncMock(return_value=response)

            with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
                out = await darkweb_bridge.search_darkweb(
                    "test", engines=["ahmia", "darksearch"], limit=10
                )
            # Both clearnet engines share a single client instance.
            self.assertEqual(mock_client.return_value.__aenter__.call_count, 1)
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["results"][0]["engine"], "ahmia")

    def test_scrape_onion_rejects_non_onion(self):
        async def run():
            out = await darkweb_bridge._scrape_onion_page("http://example.com/page")
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "not an onion URL")
            return out

        import asyncio

        asyncio.run(run())

    def test_scrape_onion_rejects_missing_proxy(self):
        async def run():
            with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
                out = await darkweb_bridge._scrape_onion_page(
                    "http://abc234abc234abcd.onion/page"
                )
            self.assertFalse(out["ok"])
            self.assertEqual(out["error"], "no Tor proxy")
            return out

        import asyncio

        asyncio.run(run())

    async def test_deep_search_disabled(self):
        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=False):
            out = await darkweb_bridge._deep_search("test")
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["error"], "darkweb disabled")

    async def test_search_mode_tor_requires_proxy(self):
        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
            with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
                out = await darkweb_bridge.search_darkweb(
                    "test", engines=["ahmia"], limit=10, mode="tor"
                )
        self.assertEqual(out["count"], 0)
        self.assertIn("requires Tor proxy", out.get("error", ""))

    async def test_search_mode_clear_skips_tor_engines(self):
        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
            out = await darkweb_bridge.search_darkweb(
                "test", engines=["ahmia", "torch"], limit=10, mode="clear"
            )
        # Ahmia has no mocked client here, but the routing should skip torch.
        self.assertIn("torch: skipped in clear mode", out.get("error", ""))


class RansomwareTrackerTests(unittest.IsolatedAsyncioTestCase):
    """Tests for ransomware_tracker (P8.6)."""

    def test_disabled_by_default(self):
        import ransomware_tracker

        with patch.object(ransomware_tracker, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.ransomware_enabled = False
            mock_cfg.return_value = cfg
            data = asyncio.run(ransomware_tracker.get_recent_victims())
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["error"], "ransomware disabled")

    def test_groups_disabled_by_default(self):
        import ransomware_tracker

        with patch.object(ransomware_tracker, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.ransomware_enabled = False
            mock_cfg.return_value = cfg
            data = asyncio.run(ransomware_tracker.get_tracked_groups())
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["error"], "ransomware disabled")

    def test_normalise_victim_rl(self):
        import ransomware_tracker

        row = {
            "post_title": "Acme Corp",
            "group_name": "lockbit",
            "discovered": "2026-01-15",
            "country": "US",
            "description": "Data exfiltrated",
            "post_url": "http://example.onion/post",
        }
        v = ransomware_tracker._normalise_victim_rl(row)
        self.assertEqual(v["victim"], "Acme Corp")
        self.assertEqual(v["group"], "lockbit")
        self.assertEqual(v["source"], "ransomware.live")

    def test_normalise_victim_rlook(self):
        import ransomware_tracker

        row = {
            "post_title": "Globex Inc",
            "group_name": "akira",
            "discovered": "2026-01-20",
        }
        v = ransomware_tracker._normalise_victim_rlook(row)
        self.assertEqual(v["victim"], "Globex Inc")
        self.assertEqual(v["group"], "akira")
        self.assertEqual(v["source"], "ransomlook")

    def test_normalise_group_rl(self):
        import ransomware_tracker

        row = {"name": "qilin", "url": "http://abc.onion"}
        g = ransomware_tracker._normalise_group_rl(row)
        self.assertEqual(g["name"], "qilin")
        self.assertEqual(g["source"], "ransomware.live")

    def test_ingest_victims_empty(self):
        import ransomware_tracker

        result = ransomware_tracker.ingest_victims_as_events([])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["error"])

    async def test_gather_digest_disabled(self):
        import ransomware_tracker

        with patch.object(ransomware_tracker, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.ransomware_enabled = False
            cfg.briefing_ransomware = False
            mock_cfg.return_value = cfg
            digest = await ransomware_tracker.gather_ransomware_digest()
        self.assertFalse(digest["enabled"])
        self.assertEqual(digest["count"], 0)

    async def test_victims_with_mocked_api(self):
        import ransomware_tracker

        rl_payload = [
            {
                "post_title": "TestCorp",
                "group_name": "akira",
                "discovered": "2026-01-01",
                "country": "DE",
                "description": "Leaked",
                "post_url": "http://abc.onion/1",
            }
        ]
        rlook_payload = [
            {
                "post_title": "OtherCorp",
                "group_name": "qilin",
                "discovered": "2026-01-02",
            }
        ]

        with patch("ransomware_tracker.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            rl_resp = MagicMock()
            rl_resp.json = MagicMock(return_value=rl_payload)
            rl_resp.raise_for_status = MagicMock()
            rlook_resp = MagicMock()
            rlook_resp.json = MagicMock(return_value=rlook_payload)
            rlook_resp.raise_for_status = MagicMock()
            instance.get = AsyncMock(side_effect=[rl_resp, rlook_resp])

            with patch.object(ransomware_tracker, "get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.ransomware_enabled = True
                cfg.ransomware_cache_sec = 3600
                cfg.briefing_ransomware = False
                mock_cfg.return_value = cfg

                data = await ransomware_tracker.get_recent_victims(
                    limit=10, refresh=True
                )

        self.assertEqual(data["count"], 2)
        self.assertEqual(data["victims"][0]["victim"], "TestCorp")
        self.assertEqual(data["victims"][1]["victim"], "OtherCorp")
        self.assertIn("ransomware.live", data["sources"])
        self.assertIn("ransomlook", data["sources"])

    async def test_victims_group_filter(self):
        import ransomware_tracker

        rl_payload = [
            {
                "post_title": "TestCorp",
                "group_name": "akira",
                "discovered": "2026-01-01",
            },
            {
                "post_title": "OtherCorp",
                "group_name": "qilin",
                "discovered": "2026-01-02",
            },
        ]
        rlook_payload: list = []

        with patch("ransomware_tracker.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            rl_resp = MagicMock()
            rl_resp.json = MagicMock(return_value=rl_payload)
            rl_resp.raise_for_status = MagicMock()
            rlook_resp = MagicMock()
            rlook_resp.json = MagicMock(return_value=rlook_payload)
            rlook_resp.raise_for_status = MagicMock()
            instance.get = AsyncMock(side_effect=[rl_resp, rlook_resp])

            with patch.object(ransomware_tracker, "get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.ransomware_enabled = True
                cfg.ransomware_cache_sec = 3600
                cfg.briefing_ransomware = False
                mock_cfg.return_value = cfg

                data = await ransomware_tracker.get_recent_victims(
                    limit=10, group="akira", refresh=True
                )

        self.assertEqual(data["count"], 1)
        self.assertEqual(data["victims"][0]["victim"], "TestCorp")

    async def test_dedup_across_sources(self):
        import ransomware_tracker

        rl_payload = [
            {
                "post_title": "SameCorp",
                "group_name": "akira",
                "discovered": "2026-01-01",
            }
        ]
        rlook_payload = [
            {
                "post_title": "SameCorp",
                "group_name": "akira",
                "discovered": "2026-01-01",
            }
        ]

        with patch("ransomware_tracker.httpx.AsyncClient") as mock_client:
            instance = mock_client.return_value.__aenter__.return_value
            rl_resp = MagicMock()
            rl_resp.json = MagicMock(return_value=rl_payload)
            rl_resp.raise_for_status = MagicMock()
            rlook_resp = MagicMock()
            rlook_resp.json = MagicMock(return_value=rlook_payload)
            rlook_resp.raise_for_status = MagicMock()
            instance.get = AsyncMock(side_effect=[rl_resp, rlook_resp])

            with patch.object(ransomware_tracker, "get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.ransomware_enabled = True
                cfg.ransomware_cache_sec = 3600
                cfg.briefing_ransomware = False
                mock_cfg.return_value = cfg

                data = await ransomware_tracker.get_recent_victims(
                    limit=10, refresh=True
                )

        self.assertEqual(data["count"], 1)


if __name__ == "__main__":
    unittest.main()
