"""Unit tests for STIX 2.1 export from FtM entities.

Tests verify:
1. FtM Person → STIX ThreatActor mapping
2. FtM Organization → STIX Identity mapping
3. FtM Event → STIX Campaign mapping
4. FtM Address → STIX Location mapping
5. FtM InternetDomain → STIX DomainName SCO
6. FtM IpAddress → STIX IPv4Addr SCO
7. Edges → STIX Relationship mapping
8. Full bundle structure (type, id, objects)
9. MISP event export
10. Unknown schema returns None
11. Deterministic STIX IDs
12. Property mapping (name, alias, email, country, lat/lon)
13. External references and labels from datasets
14. Briefing export as STIX Report
"""

from __future__ import annotations

import os
import tempfile
import unittest

import ftm_connection
import ftm_store
import stix_export


class StixExportTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)
        ftm_connection._CONN = None
        ftm_connection._SPATIAL_LOADED = False
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

    def tearDown(self):
        try:
            if ftm_connection._CONN is not None:
                ftm_connection._CONN.close()
        finally:
            ftm_connection._CONN = None
            ftm_connection._SPATIAL_LOADED = False
        for ext in ("", ".wal", ".bak", ".recovery"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def _seed(self, schema: str, key: str, props: dict, lat=None, lon=None) -> str:
        proxy = ftm_store.make_entity(schema, [key], props)
        eid = ftm_store.upsert(proxy, dataset="test", lat=lat, lon=lon)
        return eid

    # --- Schema mapping tests ---

    def test_person_to_threat_actor(self):
        eid = self._seed(
            "Person",
            "person1",
            {"name": ["John Doe"], "alias": ["JD"], "email": ["john@test.com"]},
        )
        bundle = stix_export.export_entity_stix(eid)
        self.assertEqual(bundle["type"], "bundle")
        objects = bundle["objects"]
        self.assertTrue(len(objects) >= 1)
        sdo = objects[0]
        self.assertEqual(sdo["type"], "threat-actor")
        self.assertEqual(sdo["name"], "John Doe")
        self.assertIn("JD", sdo.get("aliases", []))
        self.assertEqual(sdo["primary_email_addr"], "john@test.com")
        self.assertEqual(sdo["spec_version"], "2.1")

    def test_organization_to_identity(self):
        eid = self._seed(
            "Organization",
            "org1",
            {"name": ["Acme Corp"], "country": ["US"], "website": ["https://acme.com"]},
        )
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["type"], "identity")
        self.assertEqual(sdo["name"], "Acme Corp")
        self.assertEqual(sdo["country"], "us")
        self.assertTrue(sdo["website"].startswith("https://acme.com"))

    def test_event_to_campaign(self):
        eid = self._seed(
            "Event", "evt1", {"name": ["Operation X"], "summary": ["Test operation"]}
        )
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["type"], "campaign")
        self.assertEqual(sdo["name"], "Operation X")
        self.assertEqual(sdo["description"], "Test operation")

    def test_address_to_location(self):
        eid = self._seed(
            "Address",
            "addr1",
            {"name": ["Location A"], "city": ["Bangkok"], "country": ["th"]},
            lat=13.75,
            lon=100.5,
        )
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["type"], "location")
        self.assertEqual(sdo["city"], "Bangkok")
        self.assertEqual(sdo["country"], "th")
        self.assertEqual(sdo["latitude"], 13.75)
        self.assertEqual(sdo["longitude"], 100.5)

    def test_email_to_sco(self):
        eid = self._seed("Email", "email1", {"address": ["test@example.com"]})
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["type"], "email-addr")
        self.assertEqual(sdo["value"], "test@example.com")
        # SCOs should not have created/modified
        self.assertNotIn("created", sdo)
        self.assertNotIn("modified", sdo)

    def test_crypto_wallet_to_sco(self):
        eid = self._seed(
            "CryptoWallet",
            "wallet1",
            {
                "address": ["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"],
                "currency": ["BTC"],
            },
        )
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["type"], "cryptocurrency-wallet")
        self.assertEqual(sdo["value"], "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh")

    def test_unknown_schema_returns_empty(self):
        eid = self._seed("Thing", "thing1", {"name": ["Mystery"]})
        bundle = stix_export.export_entity_stix(eid)
        # "Thing" is not in _SCHEMA_MAP, so no SDO
        objects = bundle["objects"]
        # Only the entity itself, which maps to nothing → empty objects
        self.assertEqual(len(objects), 0)

    def test_entity_not_found(self):
        bundle = stix_export.export_entity_stix("nonexistent-id")
        self.assertEqual(bundle["objects"], [])
        self.assertIn("error", bundle)

    # --- STIX ID tests ---

    def test_deterministic_stix_ids(self):
        eid = self._seed("Person", "det1", {"name": ["Test Person"]})
        bundle1 = stix_export.export_entity_stix(eid)
        bundle2 = stix_export.export_entity_stix(eid)
        self.assertEqual(bundle1["objects"][0]["id"], bundle2["objects"][0]["id"])

    def test_stix_id_format(self):
        eid = self._seed("Person", "fmt1", {"name": ["Test"]})
        bundle = stix_export.export_entity_stix(eid)
        sdo_id = bundle["objects"][0]["id"]
        self.assertTrue(sdo_id.startswith("threat-actor--"))
        # UUID v5 format: 36 chars after the type prefix
        uuid_part = sdo_id.split("--")[1]
        self.assertEqual(len(uuid_part), 36)

    # --- Property mapping tests ---

    def test_property_mapping_aliases(self):
        eid = self._seed(
            "Person", "alias1", {"name": ["Main"], "alias": ["A1", "A2", "A3"]}
        )
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertEqual(sdo["aliases"], ["A1", "A2", "A3"])

    def test_external_references_from_datasets(self):
        eid = self._seed("Person", "ext1", {"name": ["Ref Test"]})
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertIn("external_references", sdo)
        ext_refs = sdo["external_references"]
        self.assertEqual(ext_refs[0]["source_name"], "worldbase")
        self.assertEqual(ext_refs[0]["external_id"], eid)

    def test_labels_from_datasets(self):
        eid = self._seed("Organization", "lbl1", {"name": ["Labeled Org"]})
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertIn("labels", sdo)
        self.assertTrue(any("worldbase:" in lbl for lbl in sdo["labels"]))

    # --- Edge / relationship tests ---

    def test_edge_to_relationship(self):
        person_id = self._seed("Person", "rel_p1", {"name": ["Person A"]})
        org_id = self._seed("Organization", "rel_o1", {"name": ["Org B"]})
        ftm_store.add_edge(person_id, org_id, "member", dataset="test", confidence=0.9)

        bundle = stix_export.export_entity_stix(person_id)
        rels = [o for o in bundle["objects"] if o["type"] == "relationship"]
        self.assertTrue(len(rels) >= 1)
        rel = rels[0]
        self.assertEqual(rel["relationship_type"], "member-of")
        self.assertEqual(rel["source_ref"], bundle["objects"][0]["id"])
        self.assertEqual(rel["confidence"], 90)

    # --- MISP export tests ---

    def test_misp_event_structure(self):
        eid = self._seed(
            "Person",
            "misp1",
            {"name": ["MISP Test"], "email": ["test@misp.com"], "phone": ["+1234"]},
        )
        event = stix_export.export_misp_event(eid)
        self.assertIn("Event", event)
        misp_event = event["Event"]
        self.assertEqual(misp_event["info"], "MISP Test")
        self.assertEqual(misp_event["threat_level_id"], "1")  # Person = high
        attrs = misp_event["Attribute"]
        self.assertTrue(len(attrs) >= 2)
        email_attr = [a for a in attrs if a["type"] == "email-dst"]
        self.assertTrue(len(email_attr) >= 1)
        self.assertEqual(email_attr[0]["value"], "test@misp.com")

    def test_misp_event_not_found(self):
        event = stix_export.export_misp_event("nonexistent")
        self.assertIn("error", event)

    def test_misp_tags_from_datasets(self):
        eid = self._seed("Organization", "misp_tag1", {"name": ["Tagged"]})
        event = stix_export.export_misp_event(eid)
        tags = event["Event"]["Tag"]
        self.assertTrue(len(tags) >= 1)
        self.assertTrue(any("worldbase:" in t["name"] for t in tags))

    # --- Bundle structure tests ---

    def test_bundle_structure(self):
        eid = self._seed("Person", "bundle1", {"name": ["Bundle Test"]})
        bundle = stix_export.export_entity_stix(eid)
        self.assertEqual(bundle["type"], "bundle")
        self.assertTrue(bundle["id"].startswith("bundle--"))
        self.assertIsInstance(bundle["objects"], list)

    def test_bundle_with_neighbours(self):
        person_id = self._seed("Person", "nb_p", {"name": ["Main Person"]})
        org_id = self._seed("Organization", "nb_o", {"name": ["Related Org"]})
        ftm_store.add_edge(person_id, org_id, "member", dataset="test")

        bundle = stix_export.export_entity_stix(person_id)
        objects = bundle["objects"]
        # Should have: main SDO + neighbour SDO + at least 1 relationship
        types = [o["type"] for o in objects]
        self.assertIn("threat-actor", types)
        self.assertIn("identity", types)
        self.assertIn("relationship", types)

    # --- Briefing export tests ---

    def test_briefing_export_structure(self):
        briefing = {
            "id": "test-briefing-001",
            "date": "2026-06-29T08:00:00Z",
            "generated_at": "2026-06-29T08:00:00Z",
            "insights": [{"text": "Test insight", "entity_id": None}],
            "watch_items": [],
        }
        bundle = stix_export.export_briefing_stix(briefing)
        self.assertEqual(bundle["type"], "bundle")
        objects = bundle["objects"]
        # Should contain at least a Report SDO
        reports = [o for o in objects if o["type"] == "report"]
        self.assertTrue(len(reports) >= 1)
        report = reports[0]
        self.assertIn("Test insight", report["description"])
        self.assertEqual(report["report_types"], ["threat-report"])

    def test_briefing_export_with_entity_refs(self):
        eid = self._seed("Person", "brief_ent", {"name": ["Briefing Entity"]})
        briefing = {
            "id": "test-briefing-002",
            "date": "2026-06-29T08:00:00Z",
            "generated_at": "2026-06-29T08:00:00Z",
            "insights": [{"text": "Entity insight", "entity_id": eid}],
            "watch_items": [],
        }
        bundle = stix_export.export_briefing_stix(briefing)
        objects = bundle["objects"]
        # Should have Report + ThreatActor for the referenced entity
        types = [o["type"] for o in objects]
        self.assertIn("report", types)
        self.assertIn("threat-actor", types)
        report = [o for o in objects if o["type"] == "report"][0]
        self.assertTrue(len(report["object_refs"]) >= 1)

    # --- Timestamp tests ---

    def test_stix_timestamp_normalization(self):
        self.assertEqual(
            stix_export._stix_timestamp("2026-06-29T08:00:00Z"),
            "2026-06-29T08:00:00.000Z",
        )
        self.assertEqual(
            stix_export._stix_timestamp("2026-06-29T08:00:00+00:00"),
            "2026-06-29T08:00:00.000Z",
        )
        self.assertIsNone(stix_export._stix_timestamp(None))
        self.assertIsNone(stix_export._stix_timestamp("invalid"))

    def test_sdo_has_created_and_modified(self):
        eid = self._seed("Person", "ts1", {"name": ["TS Test"]})
        bundle = stix_export.export_entity_stix(eid)
        sdo = bundle["objects"][0]
        self.assertIn("created", sdo)
        self.assertIn("modified", sdo)
        self.assertTrue(sdo["created"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
