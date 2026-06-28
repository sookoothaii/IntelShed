"""Tests for onion_directory feed module."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import onion_directory


class TestParseRealWorldOnionSites(unittest.TestCase):
    """Parse master.csv from alecmuffett/real-world-onion-sites."""

    def test_parse_csv(self):
        """Parse a well-formed CSV with onion URLs."""
        csv_text = """category,flaky,site_name,onion_url,onion_name,proof_url,comment
News,,ProPublica,https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion/,propublica,https://propublica.org,Investigative
News,,BBC News,https://www.bbcnewsd73hkzno2ini43t4gblxvycyac5aw4gnv7t2rccijh7745uqd.onion/,bbc,https://www.bbc.co.uk,News
"""
        sites = onion_directory._parse_rwos_csv(csv_text)
        self.assertEqual(len(sites), 2)
        self.assertEqual(sites[0]["name"], "ProPublica")
        self.assertEqual(
            sites[0]["onion"],
            "p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
        )
        self.assertEqual(sites[0]["category"], "News")
        self.assertEqual(sites[1]["name"], "BBC News")
        self.assertTrue(sites[1]["onion"].endswith(".onion"))

    def test_parse_skips_non_onion_links(self):
        """Rows without .onion addresses are skipped."""
        csv_text = """category,flaky,site_name,onion_url,onion_name,proof_url,comment
Web,,Tor Project,https://torproject.org,torproject,https://torproject.org,Clearnet
Tech,,Qubes OS,http://www.qubesosfasa4zl44o4tws22di6kepyzfeqv3tg4e3ztknltfxqrymdad.onion/,qubesos,https://qubes-os.org,Security OS
"""
        sites = onion_directory._parse_rwos_csv(csv_text)
        self.assertEqual(len(sites), 1)
        self.assertEqual(sites[0]["name"], "Qubes OS")
        self.assertEqual(
            sites[0]["onion"],
            "www.qubesosfasa4zl44o4tws22di6kepyzfeqv3tg4e3ztknltfxqrymdad.onion",
        )

    def test_parse_empty_csv(self):
        sites = onion_directory._parse_rwos_csv("")
        self.assertEqual(sites, [])

    def test_parse_csv_with_subdomain(self):
        """Extracts onion host from full URLs with subdomains."""
        csv_text = """category,flaky,site_name,onion_url,onion_name,proof_url,comment
News,,DW,https://www.dwnewsgngmhlplxy6o2twtfgjnrnjxbegbwqx6wnotdhkzt562tszfid.onion/de/,dw,https://dw.com,News
"""
        sites = onion_directory._parse_rwos_csv(csv_text)
        self.assertEqual(len(sites), 1)
        self.assertEqual(
            sites[0]["onion"],
            "www.dwnewsgngmhlplxy6o2twtfgjnrnjxbegbwqx6wnotdhkzt562tszfid.onion",
        )


class TestParseSecureDrop(unittest.TestCase):
    """Parse securedrop-api.csv from real-world-onion-sites."""

    def test_parse_securedrop_csv(self):
        """Parse SecureDrop CSV format."""
        csv_text = """flaky,category,site_name,onion_name,onion_url,proof_url,comment
,SecureDrop,New York Times,nytimes.securedrop.tor.onion,http://ej3kv4ebuugcmuwxctx5ic7zxh73rnxt42soi3tdneu2c2em55thufqd.onion/,https://www.nytimes.com/tips,via: securedrop.org
,SecureDrop,The Guardian,theguardian.securedrop.tor.onion,http://xp44cagis447k3lpb4wwhcqukix6cgqokbuys24vmxmbzmaq2gjvc2yd.onion/,https://www.theguardian.com/securedrop,
"""
        sites = onion_directory._parse_securedrop_csv(csv_text)
        self.assertEqual(len(sites), 2)
        self.assertEqual(sites[0]["name"], "New York Times")
        self.assertEqual(
            sites[0]["onion"],
            "ej3kv4ebuugcmuwxctx5ic7zxh73rnxt42soi3tdneu2c2em55thufqd.onion",
        )
        self.assertEqual(sites[0]["category"], "SecureDrop")
        self.assertEqual(sites[0]["source"], "securedrop")

    def test_parse_empty_securedrop(self):
        sites = onion_directory._parse_securedrop_csv("")
        self.assertEqual(sites, [])

    def test_parse_securedrop_missing_name(self):
        """Uses onion address as fallback name."""
        csv_text = """flaky,category,site_name,onion_name,onion_url,proof_url,comment
,SecureDrop,,,http://ej3kv4ebuugcmuwxctx5ic7zxh73rnxt42soi3tdneu2c2em55thufqd.onion/,,test
"""
        sites = onion_directory._parse_securedrop_csv(csv_text)
        self.assertEqual(len(sites), 1)
        self.assertEqual(
            sites[0]["name"],
            "ej3kv4ebuugcmuwxctx5ic7zxh73rnxt42soi3tdneu2c2em55thufqd.onion",
        )
        self.assertEqual(
            sites[0]["onion"],
            "ej3kv4ebuugcmuwxctx5ic7zxh73rnxt42soi3tdneu2c2em55thufqd.onion",
        )


class TestNormaliseSite(unittest.TestCase):
    """Normalise parsed sites into FtM-ready dicts."""

    def test_normalise_basic(self):
        site = {
            "name": "ProPublica",
            "onion": "p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
            "category": "journalism",
            "notes": "Investigative journalism",
        }
        result = onion_directory._normalise_site(site)
        self.assertEqual(result["name"], "ProPublica")
        self.assertEqual(
            result["onion"],
            "p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
        )
        self.assertEqual(result["schema"], "Domain")
        self.assertEqual(result["category"], "journalism")
        self.assertIn("first_seen", result)


class TestFtMIngest(unittest.TestCase):
    """FtM entity ingestion from onion sites."""

    def test_ingest_empty(self):
        result = onion_directory._ingest_ftm([])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["error"])

    def test_ingest_sites(self):
        sites = [
            {
                "name": "ProPublica",
                "onion": "p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion",
                "category": "journalism",
                "first_seen": datetime.now(timezone.utc).isoformat(),
            },
            {
                "name": "BBC News",
                "onion": "bbcweb3hytmzhn5d532owbu6oqadra5z3ab6qbqn6dilyraboafh6ad.onion",
                "category": "journalism",
                "first_seen": datetime.now(timezone.utc).isoformat(),
            },
        ]
        import sys

        mock_ftm = MagicMock()
        mock_entity = MagicMock()
        mock_entity.id = "test-id"
        mock_ftm.make_entity.return_value = mock_entity
        sys.modules["ftm_query"] = mock_ftm
        try:
            result = onion_directory._ingest_ftm(sites)
        finally:
            del sys.modules["ftm_query"]
        self.assertEqual(result["count"], 2)
        self.assertIsNone(result["error"])

    def test_ingest_fail_soft(self):
        import sys

        mock_ftm = MagicMock()
        mock_ftm.make_entity.side_effect = Exception("DB error")
        sys.modules["ftm_query"] = mock_ftm
        try:
            result = onion_directory._ingest_ftm(
                [{"name": "test", "onion": "abc.onion"}]
            )
        finally:
            del sys.modules["ftm_query"]
        self.assertEqual(result["count"], 0)
        self.assertIn("DB error", result["error"])


class TestOnionDirectoryDisabled(unittest.IsolatedAsyncioTestCase):
    """When feature is disabled, endpoints return empty payloads."""

    async def test_directory_disabled(self):
        with patch.object(onion_directory, "_enabled", return_value=False):
            result = await onion_directory.get_directory()
        self.assertEqual(result["count"], 0)
        self.assertIn("disabled", result.get("error", ""))


class TestGatherDirectory(unittest.IsolatedAsyncioTestCase):
    """End-to-end gather with mocked HTTP."""

    async def test_gather_with_mocked_responses(self):
        master_csv = """category,flaky,site_name,onion_url,onion_name,proof_url,comment
News,,ProPublica,https://p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion/,propublica,https://propublica.org,Pulitzer
"""
        securedrop_csv = """flaky,category,site_name,onion_name,onion_url,proof_url,comment
,SecureDrop,NYT,nytimes.securedrop.tor.onion,http://nytimes3xbfgragh.onion/,https://www.nytimes.com/tips,
"""

        mock_resp_master = MagicMock()
        mock_resp_master.text = master_csv
        mock_resp_master.raise_for_status = MagicMock()

        mock_resp_sd = MagicMock()
        mock_resp_sd.text = securedrop_csv
        mock_resp_sd.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_resp_master, mock_resp_sd])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(onion_directory, "_enabled", return_value=True), patch.object(
            onion_directory.httpx, "AsyncClient", return_value=mock_client
        ):
            result = await onion_directory._gather_directory()

        self.assertGreaterEqual(result["count"], 2)
        onions = [s["onion"] for s in result["sites"]]
        self.assertIn(
            "p53lf57qovyuvwsc6xnrppyply3vtqm7l6pcobkmyqsiofyeznfu5uqd.onion", onions
        )
        self.assertIn("nytimes3xbfgragh.onion", onions)

    async def test_gather_fail_soft_on_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch.object(onion_directory, "_enabled", return_value=True), patch.object(
            onion_directory.httpx, "AsyncClient", return_value=mock_client
        ):
            result = await onion_directory._gather_directory()

        self.assertEqual(result["count"], 0)
        self.assertIsNotNone(result.get("error"))


if __name__ == "__main__":
    unittest.main()
