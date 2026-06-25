"""Unit tests for operator subgraph export (Track 3+ Sprint 2, no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import intel_graph_export as igx


class IntelGraphExportTests(unittest.TestCase):
    def test_export_writes_json(self):
        fake = {
            "available": True,
            "node_count": 2,
            "edge_count": 1,
            "nodes": [{"id": "a"}],
            "edges": [{"source_id": "a", "target_id": "b"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subgraph.json"
            with patch.object(igx, "export_path", return_value=path):
                with patch("intel_subgraph.build_subgraph", return_value=fake):
                    out = igx.export_operator_subgraph(hops=2, window_hours=24)
            self.assertEqual(out["node_count"], 2)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["export_version"], 1)

    def test_compact_for_pull_trims_nodes_edges(self):
        fake = {
            "available": True,
            "node_count": 12,
            "edge_count": 9,
            "hops": 2,
            "nodes": [
                {
                    "id": f"n{i}",
                    "caption": f"Node {i}",
                    "schema": "Event",
                    "datasets": ["gdacs"],
                }
                for i in range(12)
            ],
            "edges": [
                {
                    "kind": "nearby",
                    "dataset": "spatial-proximity",
                    "source_id": "a",
                    "target_id": "b",
                }
                for _ in range(9)
            ],
        }
        out = igx.compact_for_pull(fake, max_nodes=3, max_edges=2)
        self.assertTrue(out["available"])
        self.assertEqual(out["node_count"], 12)
        self.assertEqual(len(out["nodes"]), 3)
        self.assertEqual(len(out["edges"]), 2)


if __name__ == "__main__":
    unittest.main()
