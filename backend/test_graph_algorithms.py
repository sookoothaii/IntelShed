"""Tests for V4-24 Graph Algorithms — NetworkX on FtM graph."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure backend dir on path
_backend = Path(__file__).resolve().parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


@pytest.fixture
def _isolation_env(monkeypatch, tmp_path):
    """Isolate graph_algorithms with a temp DuckDB and env vars."""
    db_path = tmp_path / "test_graph.duckdb"
    monkeypatch.setenv("WORLDBASE_DB_PATH", str(tmp_path / "test_worldbase.db"))
    monkeypatch.setenv("WORLDBASE_GRAPH_ALGORITHMS", "1")
    monkeypatch.setenv("WORLDBASE_GRAPH_MAX_NODES", "5000")
    monkeypatch.setenv("WORLDBASE_GRAPH_MAX_EDGES", "10000")

    # Patch ftm_connection._ro_conn to return a test DuckDB
    import duckdb

    test_con = duckdb.connect(str(db_path), read_only=False)
    test_con.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id VARCHAR PRIMARY KEY,
            schema VARCHAR,
            caption VARCHAR,
            lat DOUBLE,
            lon DOUBLE,
            first_seen VARCHAR,
            last_seen VARCHAR,
            datasets VARCHAR[]
        )
        """
    )
    test_con.execute(
        """
        CREATE TABLE IF NOT EXISTS edges (
            source_id VARCHAR NOT NULL,
            target_id VARCHAR NOT NULL,
            kind VARCHAR NOT NULL,
            properties VARCHAR,
            confidence DOUBLE,
            dataset VARCHAR NOT NULL,
            seen_at VARCHAR,
            UNIQUE (source_id, target_id, kind, dataset)
        )
        """
    )

    # Insert test entities
    test_con.execute(
        "INSERT INTO entities VALUES ('ent_a', 'Person', 'Alice', 13.0, 100.0, '2026-01-01', '2026-01-02', ['test'])"
    )
    test_con.execute(
        "INSERT INTO entities VALUES ('ent_b', 'Person', 'Bob', 13.1, 100.1, '2026-01-01', '2026-01-02', ['test'])"
    )
    test_con.execute(
        "INSERT INTO entities VALUES ('ent_c', 'Organization', 'Acme', 13.2, 100.2, '2026-01-01', '2026-01-02', ['test'])"
    )
    test_con.execute(
        "INSERT INTO entities VALUES ('ent_d', 'Person', 'Dave', 13.3, 100.3, '2026-01-01', '2026-01-02', ['test'])"
    )
    test_con.execute(
        "INSERT INTO entities VALUES ('ent_e', 'Person', 'Eve', 13.4, 100.4, '2026-01-01', '2026-01-02', ['test'])"
    )

    # Insert test edges: a-b, a-c, b-c, c-d, d-e (c is a hub)
    for src, tgt, kind, conf in [
        ("ent_a", "ent_b", "sameAs", 0.9),
        ("ent_a", "ent_c", "owns", 0.8),
        ("ent_b", "ent_c", "knows", 0.7),
        ("ent_c", "ent_d", "sameAs", 0.85),
        ("ent_d", "ent_e", "knows", 0.6),
    ]:
        test_con.execute(
            "INSERT INTO edges VALUES (?, ?, ?, NULL, ?, 'test', '2026-01-01')",
            [src, tgt, kind, conf],
        )

    import ftm_connection

    monkeypatch.setattr(ftm_connection, "_ro_conn", lambda: test_con)

    import graph_algorithms

    # Clear cache
    graph_algorithms._CACHE.clear()
    yield graph_algorithms
    graph_algorithms._CACHE.clear()
    test_con.close()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_enabled_default_on(self, monkeypatch):
        monkeypatch.delenv("WORLDBASE_GRAPH_ALGORITHMS", raising=False)
        import graph_algorithms

        assert graph_algorithms._enabled() is True

    def test_enabled_explicit_off(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_GRAPH_ALGORITHMS", "0")
        import graph_algorithms

        assert graph_algorithms._enabled() is False

    def test_enabled_explicit_on(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_GRAPH_ALGORITHMS", "1")
        import graph_algorithms

        assert graph_algorithms._enabled() is True


# ---------------------------------------------------------------------------
# Graph building tests
# ---------------------------------------------------------------------------


class TestBuildGraph:
    def test_build_graph_basic(self, _isolation_env):
        mod = _isolation_env
        G, edge_count, node_count = mod.build_graph()
        assert node_count == 5
        assert edge_count == 5
        assert G.has_edge("ent_a", "ent_b")
        assert G.has_edge("ent_c", "ent_d")

    def test_build_graph_cache(self, _isolation_env):
        mod = _isolation_env
        G1, _, _ = mod.build_graph()
        G2, _, _ = mod.build_graph()
        assert G1 is G2  # Same object from cache

    def test_build_graph_weights(self, _isolation_env):
        mod = _isolation_env
        G, _, _ = mod.build_graph()
        assert G["ent_a"]["ent_b"]["weight"] == 0.9
        assert G["ent_c"]["ent_d"]["weight"] == 0.85

    def test_build_graph_kinds(self, _isolation_env):
        mod = _isolation_env
        G, _, _ = mod.build_graph()
        assert "sameAs" in G["ent_a"]["ent_b"]["kinds"]
        assert "owns" in G["ent_a"]["ent_c"]["kinds"]


# ---------------------------------------------------------------------------
# PageRank tests
# ---------------------------------------------------------------------------


class TestPageRank:
    def test_pagerank_returns_scores(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_pagerank(top_n=5)
        assert result["enabled"] is True
        assert result["algorithm"] == "pagerank"
        assert result["node_count"] == 5
        assert len(result["nodes"]) == 5
        # ent_c is a hub (connected to a, b, d) — should rank high
        top_id = result["nodes"][0]["id"]
        assert top_id == "ent_c"

    def test_pagerank_top_n_limit(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_pagerank(top_n=3)
        assert len(result["nodes"]) == 3

    def test_pagerank_scores_between_0_and_1(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_pagerank(top_n=5)
        for node in result["nodes"]:
            assert 0 <= node["score"] <= 1

    def test_pagerank_entity_metadata(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_pagerank(top_n=5)
        for node in result["nodes"]:
            assert node["schema"] is not None
            assert node["caption"] is not None

    def test_pagerank_empty_graph(self, monkeypatch, tmp_path):
        """PageRank on empty graph returns empty nodes."""
        db_path = tmp_path / "empty.duckdb"
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute(
            "CREATE TABLE entities (id VARCHAR, schema VARCHAR, caption VARCHAR, lat DOUBLE, lon DOUBLE, first_seen VARCHAR, last_seen VARCHAR, datasets VARCHAR[])"
        )
        con.execute(
            "CREATE TABLE edges (source_id VARCHAR, target_id VARCHAR, kind VARCHAR, properties VARCHAR, confidence DOUBLE, dataset VARCHAR, seen_at VARCHAR, UNIQUE (source_id, target_id, kind, dataset))"
        )

        import ftm_connection

        monkeypatch.setattr(ftm_connection, "_ro_conn", lambda: con)
        monkeypatch.setenv("WORLDBASE_GRAPH_ALGORITHMS", "1")

        import graph_algorithms

        graph_algorithms._CACHE.clear()
        result = graph_algorithms.compute_pagerank(top_n=10)
        assert result["node_count"] == 0
        assert result["nodes"] == []
        graph_algorithms._CACHE.clear()
        con.close()


# ---------------------------------------------------------------------------
# Centrality tests
# ---------------------------------------------------------------------------


class TestCentrality:
    def test_degree_centrality(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_centrality(measure="degree", top_n=5)
        assert result["algorithm"] == "centrality_degree"
        assert len(result["nodes"]) == 5
        # ent_c has degree 3 (a, b, d) — highest
        assert result["nodes"][0]["id"] == "ent_c"

    def test_betweenness_centrality(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_centrality(measure="betweenness", top_n=5)
        assert result["algorithm"] == "centrality_betweenness"
        assert len(result["nodes"]) == 5
        # ent_c is on the path between {a,b} and {d,e}
        assert result["nodes"][0]["id"] == "ent_c"

    def test_closeness_centrality(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_centrality(measure="closeness", top_n=5)
        assert result["algorithm"] == "centrality_closeness"
        assert len(result["nodes"]) == 5

    def test_eigenvector_centrality(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_centrality(measure="eigenvector", top_n=5)
        assert result["algorithm"] == "centrality_eigenvector"
        assert len(result["nodes"]) == 5

    def test_invalid_measure_defaults_to_degree(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_centrality(measure="invalid", top_n=5)
        # Should fall back to degree centrality
        assert result["measure"] == "invalid"
        assert len(result["nodes"]) == 5


# ---------------------------------------------------------------------------
# Community detection tests
# ---------------------------------------------------------------------------


class TestCommunities:
    def test_communities_detected(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_communities(top_n=10, min_size=2)
        assert result["enabled"] is True
        assert result["total_communities"] >= 1
        assert len(result["communities"]) >= 1
        # Each community has size and members
        for comm in result["communities"]:
            assert comm["size"] >= 2
            assert len(comm["member_ids"]) > 0

    def test_communities_method(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_communities(top_n=10, min_size=2)
        assert result["method"] in ("greedy_modularity", "label_propagation")

    def test_communities_min_size_filter(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_communities(top_n=10, min_size=10)
        # No community has 10 members in our 5-node test graph
        assert len(result["communities"]) == 0

    def test_communities_member_metadata(self, _isolation_env):
        mod = _isolation_env
        result = mod.compute_communities(top_n=10, min_size=2)
        for comm in result["communities"]:
            for member in comm["members_sample"]:
                assert "id" in member
                assert "schema" in member


# ---------------------------------------------------------------------------
# Overview tests
# ---------------------------------------------------------------------------


class TestOverview:
    def test_overview_basic(self, _isolation_env):
        mod = _isolation_env
        result = mod.graph_overview()
        assert result["enabled"] is True
        assert result["node_count"] == 5
        assert result["edge_count"] == 5
        assert result["density"] > 0
        assert "pagerank" in result["algorithms"]
        assert "centrality" in result["algorithms"]
        assert "communities" in result["algorithms"]

    def test_overview_components(self, _isolation_env):
        mod = _isolation_env
        result = mod.graph_overview()
        # All 5 nodes are connected in one component
        assert result["is_connected"] is True
        assert result["components"] == 1
