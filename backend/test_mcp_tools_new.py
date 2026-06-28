"""Unit tests for the 5 new WorldBase MCP tools (entity_search, chat, feed_status, darkweb_search, domain_intel)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import mcp_server


class EntitySearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_entity_not_found(self):
        with patch("ftm_query.get_entity", return_value=None):
            out = await mcp_server.worldbase_entity_search(entity_id="nonexistent")
        self.assertFalse(out["found"])
        self.assertEqual(out["entity_id"], "nonexistent")

    async def test_entity_found_basic(self):
        fake = {
            "id": "ent1",
            "schema": "Person",
            "caption": "Alice",
            "properties": {},
            "datasets": [],
        }
        with patch("ftm_query.get_entity", return_value=fake):
            out = await mcp_server.worldbase_entity_search(entity_id="ent1")
        self.assertTrue(out["found"])
        self.assertEqual(out["entity"]["caption"], "Alice")

    async def test_entity_found_full(self):
        fake = {
            "id": "ent1",
            "schema": "Person",
            "caption": "Alice",
            "properties": {},
            "datasets": [],
            "statements": [],
            "edges": [],
            "neighbours": [],
        }
        with patch("ftm_query.get_entity_full", return_value=fake):
            out = await mcp_server.worldbase_entity_search(entity_id="ent1", full=True)
        self.assertTrue(out["found"])
        self.assertIn("statements", out["entity"])

    async def test_schema_filter(self):
        fake_entities = [{"id": "e1", "schema": "Person", "caption": "A"}]
        with patch(
            "ftm_query.list_entities_for_resolution", return_value=fake_entities
        ) as mock_fn:
            out = await mcp_server.worldbase_entity_search(schema="Person", limit=10)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["schema"], "Person")
        mock_fn.assert_called_once_with(schemas=["Person"], limit=10, dataset=None)

    async def test_recent_entities_default(self):
        fake_result = {"count": 2, "entities": [{"id": "e1"}, {"id": "e2"}]}
        with patch(
            "ftm_query.list_entities_recent", return_value=fake_result
        ) as mock_fn:
            out = await mcp_server.worldbase_entity_search()
        self.assertEqual(out["count"], 2)
        mock_fn.assert_called_once_with(limit=50, dataset=None)

    async def test_limit_clamped(self):
        with patch(
            "ftm_query.list_entities_recent", return_value={"count": 0, "entities": []}
        ) as mock_fn:
            await mcp_server.worldbase_entity_search(limit=99999)
        args = mock_fn.call_args
        self.assertLessEqual(args.kwargs["limit"], 500)


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_ollama_with_tools(self):
        fake_messages = [{"role": "assistant", "content": "Hello!"}]
        fake_actions = []
        with patch(
            "chat_proxy._prepare_chat_messages",
            new=AsyncMock(
                return_value=([{"role": "user", "content": "hi"}], None, None, "hi", [])
            ),
        ):
            with patch(
                "chat_tools.run_ollama_with_tools",
                new=AsyncMock(return_value=(fake_messages, fake_actions)),
            ):
                with patch.dict(
                    "os.environ", {"OLLAMA_HOSTS": "127.0.0.1:11434"}, clear=False
                ):
                    out = await mcp_server.worldbase_chat(
                        message="Hello", use_tools=True, provider="ollama"
                    )
        self.assertTrue(out["done"])
        self.assertEqual(out["message"]["content"], "Hello!")
        self.assertEqual(out["provider"], "ollama")

    async def test_chat_blocked_by_firewall(self):
        block_msg = {"error": "blocked", "detail": "session guard"}
        with patch(
            "chat_proxy._prepare_chat_messages",
            new=AsyncMock(return_value=([], None, block_msg, "hi", [])),
        ):
            out = await mcp_server.worldbase_chat(message="bad text")
        self.assertIn("error", out)

    async def test_chat_no_api_key_for_external_provider(self):
        with patch(
            "chat_proxy._prepare_chat_messages",
            new=AsyncMock(
                return_value=([{"role": "user", "content": "hi"}], None, None, "hi", [])
            ),
        ):
            with patch.dict("os.environ", {}, clear=True):
                out = await mcp_server.worldbase_chat(
                    message="hi", provider="openai", use_tools=False
                )
        self.assertIn("error", out)
        self.assertIn("OPENAI_API_KEY", out["error"])


class FeedStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_feed_status_basic_shape(self):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor

        with patch("sqlite3.connect", return_value=mock_conn):
            out = await mcp_server.worldbase_feed_status()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["feed_count"], 0)
        self.assertEqual(out["feeds_fresh"], 0)

    async def test_feed_status_single_feed(self):
        from datetime import datetime, timezone

        now_iso = datetime.now(timezone.utc).isoformat()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("earthquakes", '{"count": 5}', now_iso),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.execute.return_value = mock_cursor

        with patch("sqlite3.connect", return_value=mock_conn):
            with patch("connector_registry.feed_ttl_sec", return_value=300.0):
                out = await mcp_server.worldbase_feed_status(feed_id="earthquakes")
        self.assertEqual(out["feed_id"], "earthquakes")
        self.assertIn("earthquakes", out["feeds"])


class DarkwebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_darkweb_search_basic(self):
        fake_result = {
            "query": "test",
            "engines": ["ahmia"],
            "results": [{"title": "Hit 1", "url": "http://abc.onion"}],
            "count": 1,
            "sources": ["ahmia"],
            "mode": "auto",
            "tor_proxy": False,
            "error": None,
        }
        with patch(
            "darkweb_bridge.search_darkweb", new=AsyncMock(return_value=fake_result)
        ):
            out = await mcp_server.worldbase_darkweb_search(query="test")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["title"], "Hit 1")

    async def test_darkweb_search_ingest_requires_write(self):
        fake_result = {
            "query": "test",
            "engines": [],
            "results": [{"title": "Hit"}],
            "count": 1,
            "sources": [],
            "mode": "auto",
            "tor_proxy": False,
            "error": None,
        }
        with patch(
            "darkweb_bridge.search_darkweb", new=AsyncMock(return_value=fake_result)
        ):
            with patch("mcp_server.mcp_write_enabled", return_value=False):
                with self.assertRaises(PermissionError):
                    await mcp_server.worldbase_darkweb_search(query="test", ingest=True)

    async def test_darkweb_search_ingest_success(self):
        fake_result = {
            "query": "test",
            "engines": ["ahmia"],
            "results": [{"title": "Hit 1", "url": "http://abc.onion"}],
            "count": 1,
            "sources": ["ahmia"],
            "mode": "auto",
            "tor_proxy": False,
            "error": None,
        }
        fake_ingest = {"count": 1, "ids": ["m1"], "error": None}
        with patch(
            "darkweb_bridge.search_darkweb", new=AsyncMock(return_value=fake_result)
        ):
            with patch("darkweb_bridge.ingest_results", return_value=fake_ingest):
                with patch("mcp_server.mcp_write_enabled", return_value=True):
                    with patch("mcp_server._gate_mcp_write", new=AsyncMock()):
                        out = await mcp_server.worldbase_darkweb_search(
                            query="test", ingest=True
                        )
        self.assertIn("ingest", out)
        self.assertEqual(out["ingest"]["count"], 1)

    async def test_darkweb_limit_clamped(self):
        fake_result = {
            "query": "test",
            "engines": [],
            "results": [],
            "count": 0,
            "sources": [],
            "mode": "auto",
            "tor_proxy": False,
            "error": None,
        }
        with patch(
            "darkweb_bridge.search_darkweb", new=AsyncMock(return_value=fake_result)
        ) as mock_fn:
            await mcp_server.worldbase_darkweb_search(query="test", limit=999)
        args = mock_fn.call_args
        self.assertLessEqual(args.kwargs["limit"], 50)


class DomainIntelTests(unittest.IsolatedAsyncioTestCase):
    async def test_domain_intel_invalid_domain(self):
        out = await mcp_server.worldbase_domain_intel(domain="notadomain")
        self.assertIn("error", out)

    async def test_domain_intel_cached(self):
        fake_result = {
            "domain": "example.com",
            "certs": {},
            "wayback": {},
            "rdap": {},
            "summary": {},
        }
        with patch("domain_intel._domain_cache_get", return_value=fake_result):
            out = await mcp_server.worldbase_domain_intel(domain="example.com")
        self.assertEqual(out["domain"], "example.com")

    async def test_domain_intel_refresh(self):
        fake_result = {
            "domain": "example.com",
            "certs": {},
            "wayback": {},
            "rdap": {},
            "summary": {},
        }
        with patch("domain_intel._domain_cache_get", return_value=None):
            with patch(
                "domain_intel._gather_domain_intel",
                new=AsyncMock(return_value=fake_result),
            ):
                with patch("domain_intel._domain_cache_set") as mock_set:
                    out = await mcp_server.worldbase_domain_intel(
                        domain="example.com", refresh=True
                    )
        self.assertEqual(out["domain"], "example.com")
        mock_set.assert_called_once()

    async def test_domain_intel_ingest_requires_write(self):
        fake_result = {
            "domain": "example.com",
            "certs": {},
            "wayback": {},
            "rdap": {},
            "summary": {},
        }
        with patch("domain_intel._domain_cache_get", return_value=fake_result):
            with patch("mcp_server.mcp_write_enabled", return_value=False):
                with self.assertRaises(PermissionError):
                    await mcp_server.worldbase_domain_intel(
                        domain="example.com", organization_id="org1"
                    )

    async def test_domain_intel_ingest_success(self):
        fake_result = {
            "domain": "example.com",
            "certs": {},
            "wayback": {},
            "rdap": {},
            "summary": {},
        }
        fake_enrich = {"count": 1, "ids": ["d1"], "error": None}
        with patch("domain_intel._domain_cache_get", return_value=fake_result):
            with patch("domain_intel._enrich_ftm", return_value=fake_enrich):
                with patch("mcp_server.mcp_write_enabled", return_value=True):
                    with patch("mcp_server._gate_mcp_write", new=AsyncMock()):
                        out = await mcp_server.worldbase_domain_intel(
                            domain="example.com", organization_id="org1"
                        )
        self.assertIn("ftm_ingest", out)
        self.assertEqual(out["ftm_ingest"]["count"], 1)

    async def test_domain_intel_strips_wildcard(self):
        fake_result = {
            "domain": "example.com",
            "certs": {},
            "wayback": {},
            "rdap": {},
            "summary": {},
        }
        with patch(
            "domain_intel._domain_cache_get", return_value=fake_result
        ) as mock_get:
            out = await mcp_server.worldbase_domain_intel(domain="*.example.com")
        self.assertEqual(out["domain"], "example.com")
        mock_get.assert_called_once_with("example.com")


if __name__ == "__main__":
    unittest.main()
