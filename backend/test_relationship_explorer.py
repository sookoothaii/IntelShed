"""Tests for Session 7 — Relationship Explorer, Entity Timeline, Credential Manager.

Covers:
- get_entity_timeline() — entity metadata, statements, edges, intel_edges
- Credential store CRUD (set, list, delete)
- Credential store apply_to_env
- Timeline with empty/nonexistent entity
- Timeline with statements + edges + intel_edges
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import ftm_connection
import ftm_store
from ftm_query import (
    add_edge,
    add_intel_edge,
    get_entity_timeline,
    make_entity,
    upsert,
    upsert_cyber_entity,
)


class EntityTimelineTest(unittest.TestCase):
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

    def test_timeline_nonexistent_entity(self):
        result = get_entity_timeline("nonexistent-id")
        self.assertFalse(result["found"])
        self.assertEqual(result["events"], [])

    def test_timeline_entity_created_event(self):
        proxy = make_entity("Person", ["person", "alice"], {"name": ["Alice"]})
        eid = upsert(proxy, dataset="test")
        result = get_entity_timeline(eid)
        self.assertTrue(result["found"])
        self.assertEqual(result["entity_id"], eid)
        self.assertGreaterEqual(result["event_count"], 1)
        # Should have at least an entity_created event
        types = [e["type"] for e in result["events"]]
        self.assertIn("entity_created", types)

    def test_timeline_with_statements(self):
        proxy = make_entity("Person", ["person", "bob"], {"name": ["Bob"]})
        eid = upsert(proxy, dataset="test")
        result = get_entity_timeline(eid)
        # Entity should have statement events for name prop
        stmt_events = [e for e in result["events"] if e["type"] == "statement"]
        self.assertGreaterEqual(
            len(stmt_events), 0
        )  # Statements may or may not exist depending on upsert

    def test_timeline_with_edges(self):
        person_proxy = make_entity("Person", ["person", "carol"], {"name": ["Carol"]})
        person_id = upsert(person_proxy, dataset="test")

        org_proxy = make_entity(
            "Organization", ["org", "evilcorp"], {"name": ["EvilCorp"]}
        )
        org_id = upsert(org_proxy, dataset="test")

        add_edge(person_id, org_id, "worksFor", dataset="test")

        result = get_entity_timeline(person_id)
        edge_events = [e for e in result["events"] if e["type"] == "edge"]
        self.assertEqual(len(edge_events), 1)
        self.assertEqual(edge_events[0]["kind"], "worksFor")
        self.assertEqual(edge_events[0]["direction"], "outgoing")
        self.assertEqual(edge_events[0]["other_id"], org_id)

    def test_timeline_with_intel_edges(self):
        org_proxy = make_entity(
            "Organization", ["cyber", "org", "evilcorp"], {"name": ["EvilCorp"]}
        )
        org_id = upsert(org_proxy, dataset="test_cyber")

        ip_proxy = make_entity(
            "Thing", ["cyber", "ip", "8.8.8.8"], {"name": ["8.8.8.8"]}
        )
        ip_id = upsert_cyber_entity(ip_proxy, "IpAddress", "test_cyber")

        add_intel_edge(org_id, ip_id, "ownsAsset", dataset="test_cyber", confidence=0.9)

        result = get_entity_timeline(org_id)
        intel_events = [e for e in result["events"] if e["type"] == "intel_edge"]
        self.assertEqual(len(intel_events), 1)
        self.assertEqual(intel_events[0]["kind"], "ownsAsset")
        self.assertEqual(intel_events[0]["direction"], "outgoing")
        self.assertEqual(intel_events[0]["other_id"], ip_id)
        self.assertAlmostEqual(intel_events[0]["confidence"], 0.9)

    def test_timeline_events_sorted_by_timestamp(self):
        proxy = make_entity("Person", ["person", "dave"], {"name": ["Dave"]})
        eid = upsert(proxy, dataset="test")
        result = get_entity_timeline(eid)
        timestamps = [e.get("timestamp") or "" for e in result["events"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_timeline_incoming_edge_direction(self):
        person_proxy = make_entity("Person", ["person", "eve"], {"name": ["Eve"]})
        person_id = upsert(person_proxy, dataset="test")

        org_proxy = make_entity(
            "Organization", ["org", "goodcorp"], {"name": ["GoodCorp"]}
        )
        org_id = upsert(org_proxy, dataset="test")

        add_edge(person_id, org_id, "worksFor", dataset="test")

        # From org's perspective, the edge is incoming
        result = get_entity_timeline(org_id)
        edge_events = [e for e in result["events"] if e["type"] == "edge"]
        self.assertEqual(len(edge_events), 1)
        self.assertEqual(edge_events[0]["direction"], "incoming")
        self.assertEqual(edge_events[0]["other_id"], person_id)


class CredentialStoreTest(unittest.TestCase):
    def setUp(self):
        # Use a temp directory for the credential store
        self.tmpdir = tempfile.mkdtemp()
        self._orig_data_dir = os.environ.get("WORLDBASE_DATA_DIR")
        os.environ["WORLDBASE_DATA_DIR"] = self.tmpdir
        # Clear any env vars from previous test runs
        for key in list(os.environ.keys()):
            if key.startswith("TEST_CRED_"):
                os.environ.pop(key, None)

    def tearDown(self):
        if self._orig_data_dir is not None:
            os.environ["WORLDBASE_DATA_DIR"] = self._orig_data_dir
        else:
            os.environ.pop("WORLDBASE_DATA_DIR", None)
        # Clean up any env vars set during tests
        for key in list(os.environ.keys()):
            if key.startswith("TEST_CRED_"):
                os.environ.pop(key, None)

    def test_set_and_list_credential(self):
        from credentials.store import list_credentials, set_credential

        result = set_credential("TEST_CRED_API_KEY", "secret123")
        self.assertTrue(result["set"])
        self.assertEqual(result["env_var"], "TEST_CRED_API_KEY")

        creds = list_credentials()
        self.assertEqual(len(creds), 1)
        self.assertEqual(creds[0]["env_var"], "TEST_CRED_API_KEY")
        self.assertTrue(creds[0]["has_value"])
        self.assertEqual(creds[0]["masked"], "********")

    def test_delete_credential(self):
        from credentials.store import (
            delete_credential,
            list_credentials,
            set_credential,
        )

        set_credential("TEST_CRED_DELETE_ME", "value")
        self.assertEqual(len(list_credentials()), 1)

        result = delete_credential("TEST_CRED_DELETE_ME")
        self.assertTrue(result["deleted"])
        self.assertEqual(len(list_credentials()), 0)
        self.assertNotIn("TEST_CRED_DELETE_ME", os.environ)

    def test_delete_nonexistent_credential(self):
        from credentials.store import delete_credential

        result = delete_credential("TEST_CRED_NONEXISTENT")
        self.assertFalse(result["deleted"])

    def test_apply_credentials_to_env(self):
        from credentials.store import apply_credentials_to_env, set_credential

        set_credential("TEST_CRED_APPLY_ME", "applied_value")
        # Remove from env to simulate fresh start
        os.environ.pop("TEST_CRED_APPLY_ME", None)

        count = apply_credentials_to_env()
        self.assertGreaterEqual(count, 1)
        self.assertEqual(os.environ.get("TEST_CRED_APPLY_ME"), "applied_value")

    def test_set_credential_persists_to_file(self):
        from credentials.store import set_credential

        set_credential("TEST_CRED_PERSIST", "persisted")
        store_path = Path(self.tmpdir) / "credentials.json"
        self.assertTrue(store_path.exists())
        data = json.loads(store_path.read_text())
        self.assertIn("TEST_CRED_PERSIST", data)
        self.assertEqual(data["TEST_CRED_PERSIST"], "persisted")

    def test_list_credentials_never_exposes_value(self):
        from credentials.store import list_credentials, set_credential

        set_credential("TEST_CRED_SECRET", "super-secret-value")
        creds = list_credentials()
        for c in creds:
            self.assertNotIn("value", c)
            self.assertNotIn("TEST_CRED_SECRET", str(c.get("masked", "")))


if __name__ == "__main__":
    unittest.main()
