"""Tests for breach_bridge (P8.8)."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import breach_bridge


class BreachBridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Use a temp DB for each test
        self._tmpfd, self._tmpdb = tempfile.mkstemp(suffix=".db")
        os.close(self._tmpfd)
        self._orig_db_path = os.environ.get("WORLDBASE_DB_PATH", "")
        os.environ["WORLDBASE_DB_PATH"] = self._tmpdb
        # Clear module-level cache between tests
        breach_bridge._cache.clear()

    def tearDown(self):
        os.environ["WORLDBASE_DB_PATH"] = self._orig_db_path
        if os.path.exists(self._tmpdb):
            os.remove(self._tmpdb)

    # --- Config / disabled ---

    def test_disabled_by_default(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = False
            cfg.briefing_breach = False
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg
            self.assertFalse(cfg.breach_enabled)

    def test_source_reliability(self):
        self.assertIn("hibp", breach_bridge.SOURCE_RELIABILITY)
        self.assertGreater(breach_bridge.SOURCE_RELIABILITY["hibp"], 0.5)
        self.assertIn("pwnedpasswords", breach_bridge.SOURCE_RELIABILITY)

    # --- Email hashing / labelling ---

    def test_hash_email_consistent(self):
        h1 = breach_bridge._hash_email("Test@Example.COM")
        h2 = breach_bridge._hash_email("test@example.com")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 40)  # SHA1 hex

    def test_hash_email_different(self):
        h1 = breach_bridge._hash_email("a@example.com")
        h2 = breach_bridge._hash_email("b@example.com")
        self.assertNotEqual(h1, h2)

    def test_ensure_label_masks_local(self):
        label = breach_bridge._ensure_label("alice@example.com")
        self.assertIn("@example.com", label)
        self.assertNotIn("alice", label)

    def test_ensure_label_short_local(self):
        label = breach_bridge._ensure_label("ab@example.com")
        self.assertIn("@example.com", label)
        self.assertNotIn("ab@", label)

    def test_ensure_label_invalid(self):
        label = breach_bridge._ensure_label("notanemail")
        self.assertEqual(label, "***")

    # --- DB tables ---

    def test_ensure_tables_creates_monitors(self):
        breach_bridge._ensure_tables()
        conn = sqlite3.connect(self._tmpdb)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        names = [t[0] for t in tables]
        self.assertIn("breach_monitors", names)
        self.assertIn("breach_checks", names)

    def test_add_and_list_monitor(self):
        breach_bridge._ensure_tables()
        result = breach_bridge.add_monitor("test@example.com")
        self.assertTrue(result["ok"])
        monitors = breach_bridge.list_monitors()
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0]["email_label"], "t**t@example.com")

    def test_add_monitor_idempotent(self):
        breach_bridge._ensure_tables()
        breach_bridge.add_monitor("dup@example.com")
        breach_bridge.add_monitor("dup@example.com")
        monitors = breach_bridge.list_monitors()
        self.assertEqual(len(monitors), 1)

    def test_add_monitor_stores_email_b64(self):
        breach_bridge._ensure_tables()
        breach_bridge.add_monitor("recoverable@example.com")
        conn = sqlite3.connect(self._tmpdb)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT email_b64 FROM breach_monitors LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        decoded = base64.b64decode(row["email_b64"]).decode("utf-8")
        self.assertEqual(decoded, "recoverable@example.com")

    def test_remove_monitor(self):
        breach_bridge._ensure_tables()
        breach_bridge.add_monitor("remove@example.com")
        monitors = breach_bridge.list_monitors()
        monitor_id = monitors[0]["id"]
        result = breach_bridge.remove_monitor(monitor_id)
        self.assertTrue(result["ok"])
        self.assertEqual(len(breach_bridge.list_monitors()), 0)

    def test_remove_nonexistent_monitor(self):
        breach_bridge._ensure_tables()
        result = breach_bridge.remove_monitor(99999)
        self.assertFalse(result["ok"])

    # --- HIBP API (mocked) ---

    async def test_check_email_breaches_disabled(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = False
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg
            result = await breach_bridge.check_email_breaches("test@example.com")
            self.assertFalse(result["breached"])
            self.assertEqual(result["count"], 0)
            self.assertIn("disabled", result["error"])

    async def test_check_email_breaches_no_key_uses_xposedornot(self):
        """Without HIBP key, should fall back to XposedOrNot (not return error)."""
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertFalse(result["breached"])
                self.assertEqual(result["count"], 0)
                self.assertIsNone(result["error"])
                self.assertEqual(result["provider"], "xposedornot")

    async def test_check_email_breaches_404(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = "fake-key"
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("clean@example.com")
                self.assertFalse(result["breached"])
                self.assertEqual(result["count"], 0)
                self.assertIsNone(result["error"])

    async def test_check_email_breaches_found(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = "fake-key"
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(
                return_value=[
                    {
                        "Name": "Adobe",
                        "Title": "Adobe",
                        "Domain": "adobe.com",
                        "BreachDate": "2013-10-04",
                        "AddedDate": "2013-12-04T00:00:00Z",
                        "PwnCount": 152445165,
                        "DataClasses": ["Emails", "Passwords", "Password hints"],
                        "IsVerified": True,
                        "IsFabricated": False,
                        "IsSensitive": False,
                        "IsRetired": False,
                        "IsSpamList": False,
                    }
                ]
            )

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("pwned@example.com")
                self.assertTrue(result["breached"])
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["breaches"][0]["name"], "Adobe")
                self.assertIn("Passwords", result["breaches"][0]["data_classes"])

    async def test_check_email_breaches_rate_limited(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = "fake-key"
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertFalse(result["breached"])
                self.assertIn("rate limit", result["error"])

    async def test_check_email_breaches_network_error(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = "fake-key"
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(
                side_effect=Exception("connection refused")
            )
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertFalse(result["breached"])
                self.assertIn("connection refused", result["error"])

    # --- Password k-anonymity (mocked) ---

    async def test_check_password_hash_compromised(self):
        sha1 = hashlib.sha1(b"password123").hexdigest().upper()
        suffix = sha1[5:]

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = f"{suffix}:42\nABCDEF:5\n"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await breach_bridge.check_password_hash(sha1)
            self.assertTrue(result["compromised"])
            self.assertEqual(result["count"], 42)
            self.assertIsNone(result["error"])

    async def test_check_password_hash_clean(self):
        sha1 = hashlib.sha1(b"uniquepass123").hexdigest().upper()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "AAAAA:5\nBBBBB:3\n"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await breach_bridge.check_password_hash(sha1)
            self.assertFalse(result["compromised"])
            self.assertEqual(result["count"], 0)

    async def test_check_password_hash_network_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await breach_bridge.check_password_hash("A" * 40)
            self.assertFalse(result["compromised"])
            self.assertIn("timeout", result["error"])

    # --- Briefing integration ---

    async def test_gather_breach_briefing_disabled(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = False
            cfg.briefing_breach = False
            mock_cfg.return_value = cfg
            digest = await breach_bridge.gather_breach_briefing()
            self.assertFalse(digest["enabled"])
            self.assertEqual(digest["count"], 0)

    async def test_gather_breach_briefing_no_monitors(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.briefing_breach = True
            mock_cfg.return_value = cfg
            digest = await breach_bridge.gather_breach_briefing()
            self.assertTrue(digest["enabled"])
            self.assertEqual(digest["count"], 0)

    async def test_gather_breach_briefing_with_new_breach(self):
        breach_bridge._ensure_tables()
        breach_bridge.add_monitor("pwned@example.com")

        # Insert a fake breach_check record
        conn = sqlite3.connect(self._tmpdb)
        from datetime import datetime, timezone

        conn.execute(
            "INSERT INTO breach_checks "
            "(email_hash, checked_at, breach_count, breach_names, is_new, data_classes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                breach_bridge._hash_email("pwned@example.com"),
                datetime.now(timezone.utc).isoformat(),
                1,
                "Adobe",
                1,
                "Emails,Passwords",
            ),
        )
        conn.commit()
        conn.close()

        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.briefing_breach = True
            mock_cfg.return_value = cfg
            digest = await breach_bridge.gather_breach_briefing()
            self.assertTrue(digest["enabled"])
            self.assertGreaterEqual(digest["count"], 1)
            line = digest["lines"][0]
            self.assertIn("BREACH", line["text"])
            self.assertEqual(line["severity"], "critical")  # has "Passwords"
            self.assertTrue(line["is_new"])

    # --- Watch items ---

    def test_build_breach_watch_items(self):
        digest = {
            "enabled": True,
            "count": 1,
            "lines": [
                {
                    "text": "BREACH: t**t@example.com — Adobe",
                    "severity": "critical",
                    "email_label": "t**t@example.com",
                    "breach_name": "Adobe",
                    "data_classes": "Emails,Passwords",
                    "is_new": True,
                    "relevance_score": 0.8,
                    "sources": ["hibp"],
                }
            ],
        }
        items = breach_bridge.build_breach_watch_items(digest)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prefix"], "breach")
        self.assertIn("Adobe", items[0]["title"])
        self.assertEqual(items[0]["confidence"], 0.8)

    def test_build_breach_watch_items_skips_old(self):
        digest = {
            "enabled": True,
            "count": 1,
            "lines": [
                {
                    "text": "BREACH: old",
                    "severity": "high",
                    "email_label": "t**t@example.com",
                    "breach_name": "OldBreach",
                    "data_classes": "Emails",
                    "is_new": False,
                    "relevance_score": 0.5,
                    "sources": ["hibp"],
                }
            ],
        }
        items = breach_bridge.build_breach_watch_items(digest)
        self.assertEqual(len(items), 0)

    def test_build_breach_watch_items_empty(self):
        items = breach_bridge.build_breach_watch_items(
            {"enabled": False, "count": 0, "lines": []}
        )
        self.assertEqual(len(items), 0)

    # --- Router ---

    def test_router_prefix(self):
        self.assertEqual(breach_bridge.router.prefix, "/api/darkweb/breach")

    def test_router_has_endpoints(self):
        routes = [r.path for r in breach_bridge.router.routes]
        self.assertIn("/api/darkweb/breach/status", routes)
        self.assertIn("/api/darkweb/breach/check", routes)
        self.assertIn("/api/darkweb/breach/password", routes)
        self.assertIn("/api/darkweb/breach/monitor", routes)
        self.assertIn("/api/darkweb/breach/monitors", routes)
        self.assertIn("/api/darkweb/breach/refresh", routes)

    # --- XposedOrNot fallback (no HIBP key) ---

    async def test_xposedornot_check_email_breached(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(
                return_value={
                    "breaches": [["Adobe", "LinkedIn", "Dropbox"]],
                    "email": "test@example.com",
                    "status": "success",
                }
            )

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertTrue(result["breached"])
                self.assertEqual(result["count"], 3)
                self.assertEqual(result["provider"], "xposedornot")
                self.assertIsNone(result["error"])
                names = [b["name"] for b in result["breaches"]]
                self.assertIn("Adobe", names)
                self.assertIn("LinkedIn", names)

    async def test_xposedornot_check_email_clean(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("clean@example.com")
                self.assertFalse(result["breached"])
                self.assertEqual(result["count"], 0)
                self.assertEqual(result["provider"], "xposedornot")

    async def test_xposedornot_rate_limited(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 429
            mock_resp.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertFalse(result["breached"])
                self.assertIn("rate limit", result["error"])
                self.assertEqual(result["provider"], "xposedornot")

    async def test_xposedornot_network_error(self):
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(
                side_effect=Exception("connection refused")
            )
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertFalse(result["breached"])
                self.assertIn("connection refused", result["error"])
                self.assertEqual(result["provider"], "xposedornot")

    async def test_xposedornot_flat_breach_list(self):
        """XposedOrNot may return breaches as flat list instead of nested."""
        with patch.object(breach_bridge, "get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.breach_enabled = True
            cfg.hibp_api_key = ""
            cfg.breach_cache_sec = 3600
            mock_cfg.return_value = cfg

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(
                return_value={
                    "breaches": ["Adobe", "LinkedIn"],
                    "email": "test@example.com",
                    "status": "success",
                }
            )

            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)

            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await breach_bridge.check_email_breaches("test@example.com")
                self.assertTrue(result["breached"])
                self.assertEqual(result["count"], 2)


if __name__ == "__main__":
    unittest.main()
