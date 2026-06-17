"""Unit tests for the FollowTheMoney canonical entity store (no network)."""

import json
import os
import tempfile
import unittest

import ftm_store


class FtmStoreTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(self.path)  # let DuckDB create it fresh
        ftm_store._CONN = None
        ftm_store.set_db_path(self.path)
        ftm_store.init_store()

    def tearDown(self):
        try:
            if ftm_store._CONN is not None:
                ftm_store._CONN.close()
        finally:
            ftm_store._CONN = None
        for ext in ("", ".wal"):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass

    def test_ndjson_roundtrip_preserves_id_and_props(self):
        line = json.dumps({
            "id": "ext-vessel-1",
            "schema": "Vessel",
            "properties": {"name": ["MV Test"], "imoNumber": ["1234567"], "flag": ["ru"]},
        })
        res = ftm_store.import_ndjson(line, dataset="manual")
        self.assertEqual(res["imported"], 1)
        self.assertEqual(res["errors"], [])
        ent = ftm_store.get_entity("ext-vessel-1")
        self.assertIsNotNone(ent)
        self.assertEqual(ent["schema"], "Vessel")
        self.assertEqual(ent["properties"]["name"], ["MV Test"])
        self.assertEqual(ent["properties"]["imoNumber"], ["1234567"])

    def test_provenance_statements_carry_dataset_and_seen_at(self):
        proxy = ftm_store.make_entity("Person", ["t", "alice"], {"name": "Alice"})
        eid = ftm_store.upsert(proxy, dataset="osint")
        full = ftm_store.get_entity_full(eid)
        self.assertTrue(full["statements"])
        for st in full["statements"]:
            self.assertEqual(st["dataset"], "osint")
            self.assertTrue(st["seen_at"])

    def test_merge_unions_datasets_and_values(self):
        p1 = ftm_store.make_entity("Person", ["k"], {"name": "Bob"})
        p2 = ftm_store.make_entity("Person", ["k"], {"name": "Bob", "country": "th"})
        eid = ftm_store.upsert(p1, dataset="feedA")
        ftm_store.upsert(p2, dataset="feedB")
        ent = ftm_store.get_entity(eid)
        self.assertCountEqual(ent["datasets"], ["feedA", "feedB"])
        self.assertEqual(ent["properties"]["country"], ["th"])

    def test_legacy_mirror_maps_schema_and_keeps_id(self):
        ftm_store.upsert_legacy("aircraft:abc", "aircraft", label="FL1",
                                source_feed="opensky", external_id="abc")
        ent = ftm_store.get_entity("aircraft:abc")
        self.assertIsNotNone(ent)
        self.assertEqual(ent["schema"], "Airplane")
        self.assertEqual(ent["caption"], "FL1")
        self.assertIn("opensky", ent["datasets"])

    def test_edges_and_graph(self):
        ftm_store.upsert_legacy("inv:1", "investigation", label="Op", source_feed="osint")
        ftm_store.upsert_legacy("aircraft:xyz", "aircraft", label="FL2", source_feed="opensky")
        ftm_store.add_edge("inv:1", "aircraft:xyz", "contains", dataset="osint", confidence=0.9)
        g = ftm_store.graph_view("inv:1", depth=2)
        node_ids = {n["id"] for n in g["nodes"]}
        self.assertIn("aircraft:xyz", node_ids)
        self.assertEqual(len(g["edges"]), 1)
        self.assertEqual(g["edges"][0]["confidence"], 0.9)

    def test_graph_overview_returns_recent_entities(self):
        p = ftm_store.make_entity("Event", ["ov1"], {"name": "Overview Event"})
        ftm_store.upsert(p, dataset="gdacs")
        ov = ftm_store.graph_overview(limit=10, datasets=["gdacs"])
        self.assertTrue(ov["found"])
        self.assertGreaterEqual(len(ov["nodes"]), 1)

    def test_compat_entity_list_and_graph_stats(self):
        p = ftm_store.make_entity("Person", ["c1"], {"name": "Compat Test"})
        ftm_store.upsert(p, dataset="livetest")
        listed = ftm_store.list_entities_recent(limit=5, dataset="livetest")
        self.assertGreaterEqual(listed["count"], 1)
        gs = ftm_store.graph_stats()
        self.assertIn("graph_endpoints", gs)
        self.assertIn("resolution_edges", gs)

    def test_sanctions_adapter_maps_fields(self):
        row = {
            "id": "ofac-1", "schema": "Person", "name": "Bad Actor",
            "aliases": "B. Actor; Actor, Bad", "countries": "ru;ir",
            "birth_date": "1970", "identifiers": "PASS1", "sanctions": "OFAC SDN",
        }
        proxy = ftm_store.ftm_from_sanctions_row(row)
        self.assertEqual(proxy.id, "ofac-1")
        self.assertEqual(proxy.schema.name, "Person")
        props = proxy.to_dict()["properties"]
        self.assertEqual(props["name"], ["Bad Actor"])
        self.assertCountEqual(props["alias"], ["B. Actor", "Actor, Bad"])
        self.assertCountEqual(props["country"], ["ru", "ir"])


if __name__ == "__main__":
    unittest.main()
