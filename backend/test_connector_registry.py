"""Unit tests for connector_registry (no network)."""

from __future__ import annotations

import json
import unittest

import connector_registry


class ConnectorRegistryTests(unittest.TestCase):
    def test_catalog_non_empty(self):
        self.assertGreaterEqual(len(connector_registry.CONNECTOR_CATALOG), 29)

    def test_catalog_ids_unique(self):
        ids = connector_registry.catalog_ids()
        self.assertEqual(len(ids), len(set(ids)))

    def test_feed_ttl_known_keys(self):
        self.assertEqual(connector_registry.feed_ttl_sec("wildfires"), 600)
        self.assertEqual(connector_registry.feed_ttl_sec("weather:13.75:100.5"), 1800)
        self.assertEqual(connector_registry.feed_ttl_sec("traffic_cams:regional"), 120)
        self.assertEqual(connector_registry.feed_ttl_sec("unknown_feed"), 600)

    def test_manifest_serializable(self):
        spec = connector_registry.CONNECTOR_CATALOG["wildfires"]
        d = spec.to_dict()
        self.assertEqual(d["id"], "wildfires")
        self.assertIn("/api/wildfires", d["endpoints"])
        self.assertIn("firms", d["credential_ids"])

    def test_export_static_json(self):
        doc = connector_registry.export_manifest(include_runtime=False)
        self.assertEqual(doc["version"], 1)
        self.assertGreaterEqual(len(doc["connectors"]), 29)
        json.dumps(doc)

    def test_export_yaml_roundtrip_shape(self):
        yaml_text = connector_registry.export_manifest_yaml(include_runtime=False)
        self.assertIn("id: wildfires", yaml_text)
        self.assertIn("endpoints:", yaml_text)

    def test_snapshot_shape(self):
        snap = connector_registry.connectors_snapshot(include_unlisted=False)
        self.assertIn("connectors", snap)
        self.assertIn("ingest_mappings", snap)
        self.assertEqual(snap["count"], len(snap["connectors"]))
        first = snap["connectors"][0]
        self.assertIn("credentials_mode", first)
        self.assertIn("endpoints", first)

    def test_credential_mode_fallback_for_optional_aircraft(self):
        spec = connector_registry.CONNECTOR_CATALOG["aircraft"]
        creds = [{"id": "opensky", "configured": False, "tier": "optional"}]
        self.assertEqual(connector_registry._credential_mode(spec, creds), "fallback")

    def test_credential_mode_ok_when_configured(self):
        spec = connector_registry.CONNECTOR_CATALOG["wildfires"]
        creds = [{"id": "firms", "configured": True, "tier": "optional"}]
        self.assertEqual(connector_registry._credential_mode(spec, creds), "ok")

    def test_traffic_cams_merged_in_catalog(self):
        self.assertIn("traffic_cams_merged", connector_registry.CONNECTOR_CATALOG)
        spec = connector_registry.CONNECTOR_CATALOG["traffic_cams_merged"]
        self.assertEqual(spec.cache_key, "traffic_cams:all")

    def test_gdacs_has_ingest_mapping(self):
        spec = connector_registry.CONNECTOR_CATALOG["gdacs"]
        self.assertEqual(spec.ingest_mapping, "gdacs_alerts")

    def test_traffic_connectors_share_globe_layer(self):
        reg = connector_registry.CONNECTOR_CATALOG["traffic_cams_regional"]
        glob = connector_registry.CONNECTOR_CATALOG["traffic_cams_global"]
        self.assertEqual(reg.globe_layer, "trafficCams")
        self.assertEqual(glob.globe_layer, "trafficCams")


if __name__ == "__main__":
    unittest.main()
