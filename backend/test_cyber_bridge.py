"""Tests for cyber_bridge — Shodan InternetDB integration (no network).

Tests the IP validation, caching, and ingest logic without making
actual HTTP requests to Shodan.
"""

import os
import tempfile
import unittest

import ftm_connection
import ftm_store
from cyber_bridge import (
    _validate_ip,
    _cache_get,
    _cache_set,
    _IP_CACHE,
    fetch_ip_intel,
    ingest_ip_intel,
)


class CyberBridgeValidationTest(unittest.TestCase):
    def test_valid_ipv4(self):
        self.assertTrue(_validate_ip("8.8.8.8"))
        self.assertTrue(_validate_ip("192.168.1.1"))
        self.assertTrue(_validate_ip("0.0.0.0"))
        self.assertTrue(_validate_ip("255.255.255.255"))

    def test_valid_ipv6(self):
        self.assertTrue(_validate_ip("2001:db8::1"))
        self.assertTrue(_validate_ip("::1"))

    def test_invalid_ip(self):
        self.assertFalse(_validate_ip("999.999.999.999"))
        self.assertFalse(_validate_ip("not-an-ip"))
        self.assertFalse(_validate_ip(""))
        self.assertFalse(_validate_ip("8.8.8"))
        self.assertFalse(_validate_ip("example.com"))


class CyberBridgeCacheTest(unittest.TestCase):
    def setUp(self):
        _IP_CACHE.clear()

    def tearDown(self):
        _IP_CACHE.clear()

    def test_cache_set_get(self):
        data = {"ip": "8.8.8.8", "found": True, "ports": [80]}
        _cache_set("8.8.8.8", data)
        cached = _cache_get("8.8.8.8")
        self.assertIsNotNone(cached)
        self.assertEqual(cached["ip"], "8.8.8.8")
        self.assertTrue(cached["found"])

    def test_cache_miss(self):
        self.assertIsNone(_cache_get("1.2.3.4"))


class CyberBridgeFetchTest(unittest.TestCase):
    def setUp(self):
        _IP_CACHE.clear()

    def tearDown(self):
        _IP_CACHE.clear()

    def test_fetch_invalid_ip(self):
        import asyncio

        result = asyncio.run(fetch_ip_intel("not-an-ip"))
        self.assertFalse(result["found"])
        self.assertIn("error", result)

    def test_fetch_cached(self):
        import asyncio

        cached_data = {"ip": "1.2.3.4", "found": True, "ports": [443]}
        _cache_set("1.2.3.4", cached_data)

        result = asyncio.run(fetch_ip_intel("1.2.3.4"))
        self.assertTrue(result["found"])
        self.assertEqual(result["ports"], [443])


class CyberBridgeIngestTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()
        _IP_CACHE.clear()

    def tearDown(self):
        try:
            if ftm_connection._CONN is not None:
                ftm_connection._CONN.close()
        finally:
            ftm_connection._CONN = None
        for ext in ("", ".wal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
        _IP_CACHE.clear()

    def test_ingest_ip_with_org_and_hostnames(self):
        data = {
            "ip": "8.8.8.8",
            "found": True,
            "source": "shodan_internetdb",
            "ports": [53, 443],
            "hostnames": ["dns.google"],
            "domains": ["google.com"],
            "tags": ["dns"],
            "vulns": [],
            "isp": "Google LLC",
            "org": "Google",
            "os": None,
            "cpes": [],
        }
        result = ingest_ip_intel("8.8.8.8", data, dataset="test_cyber")

        self.assertTrue(result["ingested"])
        self.assertGreaterEqual(len(result["entity_ids"]), 3)  # ip + 2 domains
        self.assertGreaterEqual(result["edge_count"], 2)  # at least linkedTo edges

        # Verify IpAddress entity
        ip_entities = ftm_store.list_entities_by_schema("IpAddress", limit=10)
        self.assertEqual(ip_entities["count"], 1)
        self.assertEqual(ip_entities["entities"][0]["caption"], "8.8.8.8")

        # Verify Domain entities
        dom_entities = ftm_store.list_entities_by_schema("Domain", limit=10)
        self.assertEqual(dom_entities["count"], 2)

        # Verify ownsAsset edges
        owns_edges = ftm_store.list_edges_by_type("ownsAsset", limit=10)
        self.assertGreaterEqual(owns_edges["count"], 1)

        # Verify linkedTo edges
        linked_edges = ftm_store.list_edges_by_type("linkedTo", limit=10)
        self.assertGreaterEqual(linked_edges["count"], 1)

    def test_ingest_ip_no_org(self):
        data = {
            "ip": "1.2.3.4",
            "found": True,
            "source": "shodan_internetdb",
            "ports": [22],
            "hostnames": [],
            "domains": [],
            "tags": [],
            "vulns": [],
            "isp": None,
            "org": None,
            "os": None,
            "cpes": [],
        }
        result = ingest_ip_intel("1.2.3.4", data, dataset="test_cyber")

        self.assertTrue(result["ingested"])
        self.assertEqual(len(result["entity_ids"]), 1)  # just the IP
        self.assertEqual(result["edge_count"], 0)  # no org, no domains

    def test_ingest_ip_with_vulns(self):
        data = {
            "ip": "10.0.0.1",
            "found": True,
            "source": "shodan_internetdb",
            "ports": [80],
            "hostnames": ["vuln.example.com"],
            "domains": [],
            "tags": ["vulnerable"],
            "vulns": ["CVE-2021-44228"],
            "isp": "Some ISP",
            "org": "VulnCorp",
            "os": "Linux",
            "cpes": [],
        }
        result = ingest_ip_intel("10.0.0.1", data, dataset="test_cyber")

        self.assertTrue(result["ingested"])
        # ip + org + hostname = 3 entities
        self.assertEqual(len(result["entity_ids"]), 3)


if __name__ == "__main__":
    unittest.main()
