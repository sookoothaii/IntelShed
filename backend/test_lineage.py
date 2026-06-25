"""Tests for J4 — Data Lineage & Impact Graph."""

from __future__ import annotations

import os
import unittest
import uuid


class TestLineage(unittest.TestCase):
    """Lineage store operations."""

    def test_lineage_disabled_by_default(self):
        from lineage import lineage_enabled

        os.environ.pop("WORLDBASE_LINEAGE", None)
        self.assertFalse(lineage_enabled())

    def test_lineage_enabled_when_configured(self):
        from lineage import lineage_enabled

        os.environ["WORLDBASE_LINEAGE"] = "1"
        self.assertTrue(lineage_enabled())
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_record_edge_noop_when_disabled(self):
        from lineage import record_edge, get_downstream

        os.environ.pop("WORLDBASE_LINEAGE", None)
        sid = f"noop_{uuid.uuid4().hex[:8]}"
        record_edge(sid, "feed_item", "ent1", "entity", "feed_item→entity")
        result = get_downstream(sid)
        edges = [e for e in result if e["source_id"] == sid]
        self.assertEqual(len(edges), 0)

    def test_record_and_get_downstream(self):
        from lineage import (
            record_edge, get_downstream, init_lineage_db, lineage_enabled,
        )

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        sid = f"test_src_{uuid.uuid4().hex[:8]}"
        record_edge(sid, "feed_item", "ent1", "entity", "feed_item→entity")
        record_edge(sid, "feed_item", "ent2", "entity", "feed_item→entity")
        downstream = get_downstream(sid)
        self.assertEqual(len(downstream), 2)
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_get_upstream(self):
        from lineage import record_edge, get_upstream, init_lineage_db

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        tid = f"test_tgt_{uuid.uuid4().hex[:8]}"
        record_edge("src1", "feed_item", tid, "entity", "feed_item→entity")
        record_edge("src2", "feed_item", tid, "entity", "feed_item→entity")
        upstream = get_upstream(tid)
        self.assertEqual(len(upstream), 2)
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_get_full_impact(self):
        from lineage import (
            record_edge, get_full_impact, init_lineage_db,
        )

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        eid = f"test_impact_{uuid.uuid4().hex[:8]}"
        record_edge(eid, "entity", "brief-1", "briefing", "entity→briefing")
        record_edge(eid, "entity", "insight-1", "insight", "entity→insight")
        record_edge(eid, "entity", "watch-1", "watch_item", "entity→watch_item")
        impact = get_full_impact(eid)
        self.assertEqual(len(impact["briefings"]), 1)
        self.assertEqual(len(impact["insights"]), 1)
        self.assertEqual(len(impact["watch_items"]), 1)
        self.assertEqual(impact["total_downstream"], 3)
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_lineage_stats(self):
        from lineage import lineage_stats, init_lineage_db

        init_lineage_db()
        stats = lineage_stats()
        self.assertIn("enabled", stats)
        self.assertIn("total_edges", stats)
        self.assertIn("by_edge_type", stats)

    def test_delete_edges(self):
        from lineage import record_edge, delete_edges, get_downstream, init_lineage_db

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        sid = f"test_del_{uuid.uuid4().hex[:8]}"
        record_edge(sid, "feed_item", "e1", "entity", "feed_item→entity")
        record_edge(sid, "feed_item", "e2", "entity", "feed_item→entity")
        count = delete_edges(sid)
        self.assertEqual(count, 2)
        remaining = get_downstream(sid)
        self.assertEqual(len(remaining), 0)
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_convenience_functions(self):
        from lineage import (
            record_feed_to_entity, record_entity_to_briefing,
            record_entity_to_insight, record_entity_to_watch_item,
            record_feed_to_fusion, get_downstream, init_lineage_db,
        )

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        fid = f"feed_{uuid.uuid4().hex[:8]}"
        eid = f"ent_{uuid.uuid4().hex[:8]}"
        record_feed_to_entity(fid, eid)
        record_entity_to_briefing(eid, "brief-1")
        record_entity_to_insight(eid, "insight-1")
        record_entity_to_watch_item(eid, "watch-1")
        record_feed_to_fusion(fid, "fusion-1")
        # Check feed downstream
        fd = get_downstream(fid)
        self.assertEqual(len(fd), 2)  # entity + fusion_cell
        # Check entity downstream
        ed = get_downstream(eid)
        self.assertEqual(len(ed), 3)  # briefing + insight + watch_item
        os.environ.pop("WORLDBASE_LINEAGE", None)


class TestImpactGraph(unittest.TestCase):
    """Impact graph cascade."""

    def test_cascade_refresh_disabled(self):
        from impact_graph import cascade_refresh

        os.environ.pop("WORLDBASE_LINEAGE", None)
        result = cascade_refresh("test-entity")
        self.assertFalse(result["enabled"])

    def test_cascade_refresh_enabled(self):
        from impact_graph import cascade_refresh
        from lineage import record_edge, init_lineage_db

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        eid = f"test_cascade_{uuid.uuid4().hex[:8]}"
        record_edge(eid, "entity", "brief-1", "briefing", "entity→briefing")
        record_edge(eid, "entity", "watch-1", "watch_item", "entity→watch_item")
        result = cascade_refresh(eid)
        self.assertTrue(result["enabled"])
        self.assertEqual(result["briefings_affected"], 1)
        self.assertEqual(result["watch_items_invalidated"], 0)  # no ledger table
        self.assertTrue(result["requires_rebriefing"])
        os.environ.pop("WORLDBASE_LINEAGE", None)

    def test_get_impact(self):
        from impact_graph import get_impact
        from lineage import record_edge, init_lineage_db

        os.environ["WORLDBASE_LINEAGE"] = "1"
        init_lineage_db()
        eid = f"test_get_impact_{uuid.uuid4().hex[:8]}"
        record_edge(eid, "entity", "b1", "briefing", "entity→briefing")
        impact = get_impact(eid)
        self.assertEqual(impact["entity_id"], eid)
        self.assertIn("b1", impact["briefings"])
        os.environ.pop("WORLDBASE_LINEAGE", None)


class TestAdminRoutesJ4(unittest.TestCase):
    """Admin API route presence for J4."""

    def test_admin_has_lineage_routes(self):
        from routes.admin import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/admin/refresh/{source_id}", paths)
        self.assertIn("/api/admin/lineage/stats", paths)
        self.assertIn("/api/admin/lineage/downstream/{source_id}", paths)
        self.assertIn("/api/admin/lineage/upstream/{target_id}", paths)

    def test_ftm_api_has_impact_route(self):
        from routes.ftm_api import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/intel/impact", paths)


class TestConfigLineage(unittest.TestCase):
    """Config integration."""

    def test_config_lineage_default_off(self):
        os.environ.pop("WORLDBASE_LINEAGE", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.lineage_enabled)

    def test_config_lineage_enabled(self):
        os.environ["WORLDBASE_LINEAGE"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.lineage_enabled)
        finally:
            os.environ.pop("WORLDBASE_LINEAGE", None)


if __name__ == "__main__":
    unittest.main()
