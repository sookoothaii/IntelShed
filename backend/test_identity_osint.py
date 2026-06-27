"""Unit tests for P9 — Identity OSINT Bridge (no network)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import identity_osint


class TestPlatformRegistry(unittest.TestCase):
    def test_email_sites_non_empty(self):
        self.assertGreaterEqual(len(identity_osint._EMAIL_SITES), 30)

    def test_username_sites_non_empty(self):
        self.assertGreaterEqual(len(identity_osint._USERNAME_SITES), 40)

    def test_total_platforms_50_plus(self):
        total = len(identity_osint._EMAIL_SITES) + len(identity_osint._USERNAME_SITES)
        self.assertGreaterEqual(total, 50)

    def test_username_sites_have_url_pattern(self):
        for site in identity_osint._USERNAME_SITES:
            self.assertIn(
                "{username}",
                site["url"],
                f"{site['name']} missing {{username}} placeholder",
            )

    def test_email_sites_have_name_and_category(self):
        for site in identity_osint._EMAIL_SITES:
            self.assertIn("name", site)
            self.assertIn("category", site)
            self.assertIn("method", site)


class TestValidation(unittest.TestCase):
    def test_valid_email(self):
        self.assertTrue(identity_osint._valid_email("test@example.com"))
        self.assertTrue(identity_osint._valid_email("user.name+tag@domain.co.uk"))

    def test_invalid_email(self):
        self.assertFalse(identity_osint._valid_email("not-an-email"))
        self.assertFalse(identity_osint._valid_email(""))
        self.assertFalse(identity_osint._valid_email("a@b"))
        self.assertFalse(identity_osint._valid_email("test@"))

    def test_sanitize_username_valid(self):
        self.assertEqual(identity_osint._sanitize_username("testuser"), "testuser")
        self.assertEqual(identity_osint._sanitize_username("test_user"), "test_user")
        self.assertEqual(identity_osint._sanitize_username("test-user"), "test-user")

    def test_sanitize_username_invalid(self):
        self.assertIsNone(identity_osint._sanitize_username(""))
        self.assertIsNone(identity_osint._sanitize_username("a"))
        self.assertIsNone(identity_osint._sanitize_username("user with spaces"))
        self.assertIsNone(identity_osint._sanitize_username("user@name!"))
        self.assertIsNone(identity_osint._sanitize_username("x" * 50))


class TestDisabledByDefault(unittest.TestCase):
    def test_lookup_email_disabled(self):
        result = asyncio.run(identity_osint.lookup_email("test@example.com"))
        self.assertIn("error", result)
        self.assertEqual(result["count"], 0)

    def test_lookup_username_disabled(self):
        result = asyncio.run(identity_osint.lookup_username("testuser"))
        self.assertIn("error", result)
        self.assertEqual(result["count"], 0)


class TestCache(unittest.TestCase):
    def setUp(self):
        identity_osint.clear_cache()

    def tearDown(self):
        identity_osint.clear_cache()

    def test_cache_set_and_get(self):
        async def _test():
            await identity_osint._set_cached("test_key", {"count": 5})
            result = await identity_osint._get_cached("test_key", 60)
            self.assertIsNotNone(result)
            self.assertEqual(result["count"], 5)

        asyncio.run(_test())

    def test_cache_miss(self):
        async def _test():
            result = await identity_osint._get_cached("nonexistent_key", 60)
            self.assertIsNone(result)

        asyncio.run(_test())

    def test_cache_expiry(self):
        async def _test():
            await identity_osint._set_cached("expiry_key", {"count": 1})
            # TTL of 0 means immediately expired
            result = await identity_osint._get_cached("expiry_key", 0)
            self.assertIsNone(result)

        asyncio.run(_test())

    def test_cache_key_deterministic(self):
        key1 = identity_osint._cache_key("test@example.com", "email")
        key2 = identity_osint._cache_key("test@example.com", "email")
        self.assertEqual(key1, key2)

    def test_cache_key_different_queries(self):
        key1 = identity_osint._cache_key("test@example.com", "email")
        key2 = identity_osint._cache_key("other@example.com", "email")
        self.assertNotEqual(key1, key2)


class TestPlatformCheckParsing(unittest.TestCase):
    def test_username_check_200_found(self):
        async def _test():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_resp)
            site = {"name": "GitHub", "url": "https://github.com/{username}"}
            result = await identity_osint._check_username_platform(
                site, "testuser", mock_client
            )
            self.assertTrue(result["found"])
            self.assertEqual(result["name"], "GitHub")
            self.assertIn("testuser", result["profile_url"])

        asyncio.run(_test())

    def test_username_check_404_not_found(self):
        async def _test():
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_resp)
            site = {"name": "GitHub", "url": "https://github.com/{username}"}
            result = await identity_osint._check_username_platform(
                site, "testuser", mock_client
            )
            self.assertFalse(result["found"])
            self.assertIsNone(result["profile_url"])

        asyncio.run(_test())

    def test_username_check_timeout_null(self):
        async def _test():
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(side_effect=Exception("timeout"))
            site = {"name": "GitHub", "url": "https://github.com/{username}"}
            result = await identity_osint._check_username_platform(
                site, "testuser", mock_client
            )
            self.assertIsNone(result["found"])

        asyncio.run(_test())

    def test_email_check_gravatar_found(self):
        async def _test():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            site = {"name": "Gravatar", "url": "https://gravatar.com/", "method": "api"}
            result = await identity_osint._check_email_platform(
                site, "test@example.com", mock_client
            )
            self.assertTrue(result["found"])

        asyncio.run(_test())

    def test_email_check_gravatar_not_found(self):
        async def _test():
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            site = {"name": "Gravatar", "url": "https://gravatar.com/", "method": "api"}
            result = await identity_osint._check_email_platform(
                site, "test@example.com", mock_client
            )
            self.assertFalse(result["found"])

        asyncio.run(_test())

    def test_email_check_password_reset_site_returns_null(self):
        async def _test():
            mock_client = AsyncMock()
            site = {
                "name": "Facebook",
                "url": "https://facebook.com/",
                "method": "password_reset",
            }
            result = await identity_osint._check_email_platform(
                site, "test@example.com", mock_client
            )
            self.assertIsNone(result["found"])

        asyncio.run(_test())


class TestRateLimiting(unittest.TestCase):
    def test_max_platforms_cap(self):
        async def _test():
            sites = [
                {"name": f"Site{i}", "url": "https://example.com/{username}"}
                for i in range(100)
            ]
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                results = await identity_osint._rate_limited_check(
                    sites,
                    "testuser",
                    identity_osint._check_username_platform,
                    rate_limit_sec=0,
                    max_platforms=5,
                )
            self.assertEqual(len(results), 5)

        asyncio.run(_test())

    def test_rate_limit_sleeps_between_checks(self):
        async def _test():
            sites = [
                {"name": "Site1", "url": "https://example.com/{username}"},
                {"name": "Site2", "url": "https://example.com/{username}"},
            ]
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_resp)

            sleep_calls = []
            original_sleep = asyncio.sleep

            async def mock_sleep(sec):
                sleep_calls.append(sec)
                await original_sleep(0)

            with patch("httpx.AsyncClient") as mock_client_cls, patch(
                "asyncio.sleep", side_effect=mock_sleep
            ):
                mock_client_cls.return_value.__aenter__ = AsyncMock(
                    return_value=mock_client
                )
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
                await identity_osint._rate_limited_check(
                    sites,
                    "testuser",
                    identity_osint._check_username_platform,
                    rate_limit_sec=2.0,
                    max_platforms=10,
                )
            # Should have slept at least once (between the 2 checks)
            self.assertGreaterEqual(len(sleep_calls), 1)
            self.assertAlmostEqual(sleep_calls[0], 2.0)

        asyncio.run(_test())


class TestNoPIIStorage(unittest.TestCase):
    def test_results_contain_no_passwords(self):
        async def _test():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=mock_resp)
            site = {"name": "GitHub", "url": "https://github.com/{username}"}
            result = await identity_osint._check_username_platform(
                site, "testuser", mock_client
            )
            # Only name, url, found, profile_url — no PII content
            self.assertEqual(
                set(result.keys()), {"name", "url", "found", "profile_url"}
            )
            self.assertNotIn("password", result)
            self.assertNotIn("token", result)
            self.assertNotIn("email_content", result)

        asyncio.run(_test())


class TestFtmEnrichment(unittest.TestCase):
    def test_enrich_ftm_fail_soft(self):
        """FtM enrichment should fail soft when FtM store is unavailable."""
        result = identity_osint._enrich_ftm(
            "fake-person-id",
            {
                "query": "testuser",
                "type": "username",
                "platforms": [
                    {
                        "name": "GitHub",
                        "url": "https://github.com/testuser",
                        "found": True,
                        "profile_url": "https://github.com/testuser",
                    }
                ],
            },
        )
        # Should not raise, should return a dict with count/ids/error
        self.assertIn("count", result)
        self.assertIn("ids", result)
        self.assertIn("error", result)

    def test_enrich_ftm_skips_not_found(self):
        """Enrichment should skip platforms where found is not True."""
        with patch("ftm_query.make_entity") as mock_make, patch(
            "ftm_query.upsert"
        ) as mock_upsert, patch("ftm_query.add_edge") as mock_edge:
            mock_entity = MagicMock()
            mock_entity.id = "test-acct-id"
            mock_make.return_value = mock_entity
            result = identity_osint._enrich_ftm(
                "person-id",
                {
                    "query": "testuser",
                    "type": "username",
                    "platforms": [
                        {
                            "name": "GitHub",
                            "url": "...",
                            "found": True,
                            "profile_url": "...",
                        },
                        {
                            "name": "Twitter",
                            "url": "...",
                            "found": False,
                            "profile_url": None,
                        },
                        {
                            "name": "Facebook",
                            "url": "...",
                            "found": None,
                            "profile_url": None,
                        },
                    ],
                },
            )
            self.assertEqual(result["count"], 1)
            mock_upsert.assert_called_once()
            mock_edge.assert_called_once()


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        os.environ["WORLDBASE_DB_PATH"] = self._tmp.name

    def tearDown(self):
        os.environ.pop("WORLDBASE_DB_PATH", None)
        import os as _os

        _os.unlink(self._tmp.name)

    def test_audit_log_insertion(self):
        identity_osint._ensure_audit_table()
        identity_osint._audit_log("test@example.com", "email", 5)
        entries = identity_osint.query_audit_log(limit=10)
        self.assertGreaterEqual(len(entries), 1)
        latest = entries[0]
        self.assertEqual(latest["query"], "test@example.com")
        self.assertEqual(latest["query_type"], "email")
        self.assertEqual(latest["result_count"], 5)

    def test_audit_log_cached_flag(self):
        identity_osint._ensure_audit_table()
        identity_osint._audit_log("testuser", "username", 3, cached=True)
        entries = identity_osint.query_audit_log(limit=10)
        latest = entries[0]
        self.assertEqual(latest["cached"], 1)


class TestGatherDigest(unittest.TestCase):
    def test_gather_digest_disabled(self):
        async def _test():
            with patch("identity_osint.get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.identity_osint_enabled = False
                cfg.briefing_identity = False
                mock_cfg.return_value = cfg
                result = await identity_osint.gather_identity_digest()
                self.assertFalse(result["enabled"])

        asyncio.run(_test())


class TestEnabledLookup(unittest.TestCase):
    def setUp(self):
        identity_osint.clear_cache()

    def tearDown(self):
        identity_osint.clear_cache()

    def test_lookup_email_invalid_when_enabled(self):
        async def _test():
            with patch("identity_osint.get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.identity_osint_enabled = True
                cfg.identity_osint_rate_limit_sec = 0
                cfg.identity_osint_max_platforms = 5
                cfg.identity_osint_cache_sec = 60
                mock_cfg.return_value = cfg
                result = await identity_osint.lookup_email("not-an-email")
                self.assertIn("error", result)
                self.assertEqual(result["count"], 0)

        asyncio.run(_test())

    def test_lookup_username_invalid_when_enabled(self):
        async def _test():
            with patch("identity_osint.get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.identity_osint_enabled = True
                cfg.identity_osint_rate_limit_sec = 0
                cfg.identity_osint_max_platforms = 5
                cfg.identity_osint_cache_sec = 60
                mock_cfg.return_value = cfg
                result = await identity_osint.lookup_username("x y z!")
                self.assertIn("error", result)
                self.assertEqual(result["count"], 0)

        asyncio.run(_test())

    def test_lookup_username_valid_when_enabled(self):
        async def _test():
            with patch("identity_osint.get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.identity_osint_enabled = True
                cfg.identity_osint_rate_limit_sec = 0
                cfg.identity_osint_max_platforms = 3
                cfg.identity_osint_cache_sec = 60
                mock_cfg.return_value = cfg

                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_client = AsyncMock()
                mock_client.head = AsyncMock(return_value=mock_resp)

                with patch("httpx.AsyncClient") as mock_client_cls:
                    mock_client_cls.return_value.__aenter__ = AsyncMock(
                        return_value=mock_client
                    )
                    mock_client_cls.return_value.__aexit__ = AsyncMock(
                        return_value=None
                    )
                    result = await identity_osint.lookup_username("testuser")
                self.assertEqual(result["query"], "testuser")
                self.assertEqual(result["type"], "username")
                self.assertEqual(result["total_checked"], 3)
                self.assertEqual(result["count"], 3)  # all 3 returned 200

        asyncio.run(_test())

    def test_lookup_email_cached(self):
        async def _test():
            with patch("identity_osint.get_config") as mock_cfg:
                cfg = MagicMock()
                cfg.identity_osint_enabled = True
                cfg.identity_osint_rate_limit_sec = 0
                cfg.identity_osint_max_platforms = 2
                cfg.identity_osint_cache_sec = 60
                mock_cfg.return_value = cfg

                # Pre-populate cache
                ckey = identity_osint._cache_key("test@example.com", "email")
                await identity_osint._set_cached(
                    ckey,
                    {
                        "query": "test@example.com",
                        "type": "email",
                        "platforms": [],
                        "count": 3,
                        "total_checked": 2,
                        "cached": False,
                        "error": None,
                    },
                )

                result = await identity_osint.lookup_email("test@example.com")
                self.assertTrue(result["cached"])
                self.assertEqual(result["count"], 3)

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
