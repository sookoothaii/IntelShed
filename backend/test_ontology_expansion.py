"""Tests for cyber/financial ontology expansion: schema, entities, edges, IOCs.

Single-writer discipline: each test uses a temp ``.duckdb`` and closes it in
``tearDown``. Never open ``entities.duckdb`` via CLI or a second Python process
while the WorldBase API holds the file.
"""

import os
import tempfile
import unittest

import ftm_connection
import ftm_store
from ftm_schema import CYBER_SCHEMA_MAP, INTEL_EDGE_TYPES


class OntologyExpansionTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

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

    # --- Schema constants ---

    def test_cyber_schema_map_contains_all_logical_types(self):
        expected = {
            "Organization",
            "Person",
            "Document",
            "Asset",
            "IpAddress",
            "Domain",
            "Url",
        }
        self.assertEqual(set(CYBER_SCHEMA_MAP.keys()), expected)

    def test_intel_edge_types_contains_all_kinds(self):
        expected = {
            "worksFor",
            "locatedAt",
            "ownsAsset",
            "mentionedIn",
            "linkedTo",
            "partOf",
        }
        self.assertEqual(set(INTEL_EDGE_TYPES), expected)

    # --- intel_edges table exists ---

    def test_intel_edges_table_exists(self):
        from ftm_connection import _LOCK, _conn

        with _LOCK:
            con = _conn()
            rows = con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'intel_edges'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "intel_edges")

    # --- upsert_cyber_entity ---

    def test_upsert_cyber_entity_ipaddress(self):
        proxy = ftm_store.make_entity(
            "Thing", ["cyber", "ip", "8.8.8.8"], {"name": ["8.8.8.8"]}
        )
        eid = ftm_store.upsert_cyber_entity(proxy, "IpAddress", "test_cyber")
        self.assertIsNotNone(eid)

        result = ftm_store.list_entities_by_schema("IpAddress", limit=10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["caption"], "8.8.8.8")
        self.assertEqual(result["entities"][0]["schema"], "IpAddress")

    def test_upsert_cyber_entity_domain(self):
        proxy = ftm_store.make_entity(
            "Thing", ["cyber", "domain", "evil.com"], {"name": ["evil.com"]}
        )
        eid = ftm_store.upsert_cyber_entity(proxy, "Domain", "test_cyber")
        self.assertIsNotNone(eid)

        result = ftm_store.list_entities_by_schema("Domain", limit=10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["entities"][0]["caption"], "evil.com")

    def test_upsert_cyber_entity_url(self):
        proxy = ftm_store.make_entity(
            "HyperText",
            ["cyber", "url", "http://evil.com/payload"],
            {"name": ["http://evil.com/payload"]},
        )
        eid = ftm_store.upsert_cyber_entity(proxy, "Url", "test_cyber")
        self.assertIsNotNone(eid)

        result = ftm_store.list_entities_by_schema("Url", limit=10)
        self.assertEqual(result["count"], 1)

    # --- list_entities_by_schema ---

    def test_list_entities_by_schema_empty(self):
        result = ftm_store.list_entities_by_schema("IpAddress", limit=10)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["entities"], [])

    def test_list_entities_by_schema_multiple(self):
        for ip in ["1.2.3.4", "5.6.7.8", "9.10.11.12"]:
            proxy = ftm_store.make_entity("Thing", ["cyber", "ip", ip], {"name": [ip]})
            ftm_store.upsert_cyber_entity(proxy, "IpAddress", "test_cyber")

        result = ftm_store.list_entities_by_schema("IpAddress", limit=10)
        self.assertEqual(result["count"], 3)

    # --- add_intel_edge ---

    def test_add_intel_edge_owns_asset(self):
        org_proxy = ftm_store.make_entity(
            "Organization", ["cyber", "org", "EvilCorp"], {"name": ["EvilCorp"]}
        )
        org_id = ftm_store.upsert(org_proxy, dataset="test_cyber")

        ip_proxy = ftm_store.make_entity(
            "Thing", ["cyber", "ip", "8.8.8.8"], {"name": ["8.8.8.8"]}
        )
        ip_id = ftm_store.upsert_cyber_entity(ip_proxy, "IpAddress", "test_cyber")

        ftm_store.add_intel_edge(
            org_id, ip_id, "ownsAsset", dataset="test_cyber", confidence=0.9
        )

        result = ftm_store.list_edges_by_type("ownsAsset", limit=10)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["edges"][0]["source_id"], org_id)
        self.assertEqual(result["edges"][0]["target_id"], ip_id)
        self.assertEqual(result["edges"][0]["kind"], "ownsAsset")
        self.assertAlmostEqual(result["edges"][0]["confidence"], 0.9)

    def test_add_intel_edge_linked_to(self):
        ip_proxy = ftm_store.make_entity(
            "Thing", ["cyber", "ip", "1.2.3.4"], {"name": ["1.2.3.4"]}
        )
        ip_id = ftm_store.upsert_cyber_entity(ip_proxy, "IpAddress", "test_cyber")

        dom_proxy = ftm_store.make_entity(
            "Thing", ["cyber", "domain", "evil.com"], {"name": ["evil.com"]}
        )
        dom_id = ftm_store.upsert_cyber_entity(dom_proxy, "Domain", "test_cyber")

        ftm_store.add_intel_edge(ip_id, dom_id, "linkedTo", dataset="test_cyber")

        result = ftm_store.list_edges_by_type("linkedTo", limit=10)
        self.assertEqual(result["count"], 1)

    def test_add_intel_edge_invalid_kind_rejected(self):
        ip_proxy = ftm_store.make_entity(
            "Thing", ["cyber", "ip", "1.1.1.1"], {"name": ["1.1.1.1"]}
        )
        ip_id = ftm_store.upsert_cyber_entity(ip_proxy, "IpAddress", "test_cyber")

        # "hacksFor" is not in INTEL_EDGE_TYPES — should be silently rejected
        ftm_store.add_intel_edge(ip_id, ip_id, "hacksFor", dataset="test_cyber")

        result = ftm_store.list_edges_by_type("hacksFor", limit=10)
        self.assertEqual(result["count"], 0)

    def test_add_intel_edge_empty_ids_rejected(self):
        ftm_store.add_intel_edge("", "some-id", "ownsAsset", dataset="test")
        ftm_store.add_intel_edge("some-id", "", "ownsAsset", dataset="test")
        result = ftm_store.list_edges_by_type("ownsAsset", limit=10)
        self.assertEqual(result["count"], 0)

    # --- list_edges_by_type fallback ---

    def test_list_edges_by_type_falls_back_to_regular_edges(self):
        # Add a regular edge with kind "mentionedIn" (also in INTEL_EDGE_TYPES)
        doc_proxy = ftm_store.make_entity(
            "Document", ["doc", "test"], {"title": ["Test Doc"]}
        )
        doc_id = ftm_store.upsert(doc_proxy, dataset="test_cyber")

        person_proxy = ftm_store.make_entity(
            "Person", ["person", "alice"], {"name": ["Alice"]}
        )
        person_id = ftm_store.upsert(person_proxy, dataset="test_cyber")

        ftm_store.add_edge(person_id, doc_id, "mentionedIn", dataset="test_cyber")

        # Should find it via fallback to regular edges table
        result = ftm_store.list_edges_by_type("mentionedIn", limit=10)
        self.assertEqual(result["count"], 1)

    # --- IOC extraction ---

    def test_extract_iocs_ipv4(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("Contact server at 192.168.1.1 for details.")
        self.assertIn("ipv4", iocs)
        self.assertIn("192.168.1.1", iocs["ipv4"])

    def test_extract_iocs_domain(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("Visit https://evil.com for malware samples.")
        self.assertIn("domain", iocs)
        self.assertIn("evil.com", iocs["domain"])

    def test_extract_iocs_url(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("Download from http://evil.com/payload.exe now")
        self.assertIn("url", iocs)
        self.assertTrue(any("http://evil.com/payload.exe" in u for u in iocs["url"]))

    def test_extract_iocs_sha256(self):
        from intel_ingest import extract_iocs

        h = "a" * 64
        iocs = extract_iocs(f"File hash: {h}")
        self.assertIn("sha256", iocs)
        self.assertIn(h, iocs["sha256"])

    def test_extract_iocs_md5(self):
        from intel_ingest import extract_iocs

        h = "d41d8cd98f00b204e9800998ecf8427e"
        iocs = extract_iocs(f"File hash: {h}")
        self.assertIn("md5", iocs)
        self.assertIn(h, iocs["md5"])

    def test_extract_iocs_email(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("Contact attacker@evil.com for decryption key.")
        self.assertIn("email", iocs)
        self.assertIn("attacker@evil.com", iocs["email"])

    def test_extract_iocs_dedup(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("8.8.8.8 and 8.8.8.8 and 8.8.8.8")
        self.assertEqual(len(iocs.get("ipv4", [])), 1)

    def test_extract_iocs_exclude_example(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("Visit example.com for docs.")
        # example.com is in the exclude list
        self.assertNotIn("domain", iocs)

    def test_extract_iocs_empty(self):
        from intel_ingest import extract_iocs

        iocs = extract_iocs("No indicators here, just plain text.")
        self.assertEqual(iocs, {})

    def test_extract_iocs_multiple_types(self):
        from intel_ingest import extract_iocs

        text = (
            "Server at 10.0.0.1 hosts https://malware.xyz/payload. Contact admin@malware.xyz. SHA256: "
            + "b" * 64
        )
        iocs = extract_iocs(text)
        self.assertIn("ipv4", iocs)
        self.assertIn("url", iocs)
        self.assertIn("email", iocs)
        self.assertIn("sha256", iocs)


if __name__ == "__main__":
    unittest.main()
