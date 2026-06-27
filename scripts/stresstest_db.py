"""P5 Stresstest - Direct DuckDB access (no API, no autopilot contention).

Run with venv AFTER shutting down the API:
    backend\\venv\\Scripts\\python.exe scripts\\stresstest_db.py

Tests:
  1. Single-entity upsert latency (50 iterations, target p50 <20ms)
  2. 2-hop subgraph traversal (10 calls, target p50 <200ms)
  3. Entity graph per-entity (10 random seeds, target p50 <50ms)
  4. Concurrent feed ingest (6 sources x 20 entities, target <5s total)
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import concurrent.futures
from datetime import datetime, timezone

# Ensure backend/ is on sys.path
_backend = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.abspath(_backend))

# Load .env
_env_path = os.path.join(_backend, ".env")
if os.path.exists(_env_path):
    for line in open(_env_path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def fmt_ms(ms_list: list[float]) -> str:
    if not ms_list:
        return "n/a"
    p50 = statistics.median(ms_list)
    s = sorted(ms_list)
    p95 = s[int(len(s) * 0.95)] if len(s) >= 20 else max(s)
    p99 = s[int(len(s) * 0.99)] if len(s) >= 100 else max(s)
    return f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms (n={len(ms_list)})"


def test_1_upsert_latency():
    """Test 1: Single-entity upsert - 50 iterations directly via ftm_query."""
    print("\n=== Test 1: Single-entity upsert latency (50 iterations, direct DuckDB) ===")
    import ftm_query
    seen_at = datetime.now(timezone.utc).isoformat()
    latencies: list[float] = []

    for i in range(50):
        props = {
            "name": [f"Stresstest Entity {i}"],
            "description": [f"Synthetic entity for stresstest iteration {i}"],
        }
        entity = ftm_query.make_entity("Thing", [f"stresstest-upsert-{i}"], props)
        t0 = time.perf_counter()
        ftm_query.upsert(entity, dataset="stresstest", seen_at=seen_at)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)

    print(f"  Upsert latency: {fmt_ms(latencies)}")
    s = sorted(latencies)
    p50 = statistics.median(latencies)
    p95 = s[int(len(s) * 0.95)] if len(s) >= 20 else max(s)
    passed = p50 < 20.0
    print(f"  Target: p50 < 20ms - {'PASS' if passed else 'FAIL'} (p50={p50:.1f}ms, p95={p95:.1f}ms)")
    return {"test": "upsert_latency", "passed": passed, "p50_ms": round(p50, 1), "p95_ms": round(p95, 1), "n": len(latencies)}


def test_2_subgraph_traversal():
    """Test 2: 2-hop subgraph via intel_subgraph.build_subgraph - 10 calls."""
    print("\n=== Test 2: 2-hop subgraph traversal (10 calls, direct DuckDB) ===")
    import intel_subgraph
    latencies: list[float] = []

    for i in range(10):
        t0 = time.perf_counter()
        result = intel_subgraph.build_subgraph(hops=2, seed_limit=5 + i * 3)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        nodes = result.get("node_count", 0)
        edges = result.get("edge_count", 0)
        print(f"  Call {i}: {nodes} nodes, {edges} edges in {dt:.1f}ms")

    print(f"  Traversal latency: {fmt_ms(latencies)}")
    p50 = statistics.median(latencies)
    s = sorted(latencies)
    p95 = s[int(len(s) * 0.95)] if len(s) >= 20 else max(s)
    passed = p50 < 200.0
    print(f"  Target: p50 < 200ms - {'PASS' if passed else 'FAIL'} (p50={p50:.1f}ms, p95={p95:.1f}ms)")
    return {"test": "subgraph_traversal", "passed": passed, "p50_ms": round(p50, 1), "p95_ms": round(p95, 1), "n": len(latencies)}


def test_3_entity_graph():
    """Test 3: Per-entity graph via ftm_query.graph_view - 10 random entities."""
    print("\n=== Test 3: Per-entity graph traversal (10 random entities, direct DuckDB) ===")
    import ftm_query
    import random

    # Get random entities that have edges
    import ftm_store
    rows = ftm_store.run_query(
        "SELECT DISTINCT source_id FROM edges USING SAMPLE 10 ROWS"
    )
    seed_ids = [r[0] for r in rows]

    if not seed_ids:
        print("  No entities with edges found - SKIP")
        return {"test": "entity_graph", "passed": None, "error": "no seed entities"}

    latencies: list[float] = []
    for eid in seed_ids:
        t0 = time.perf_counter()
        result = ftm_query.graph_view(eid, depth=2, limit=200)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        nodes = len(result.get("nodes", []))
        edges = len(result.get("edges", []))
        print(f"  {eid[:25]}... -> {nodes} nodes, {edges} edges in {dt:.1f}ms")

    print(f"  Per-entity latency: {fmt_ms(latencies)}")
    p50 = statistics.median(latencies)
    s = sorted(latencies)
    p95 = s[int(len(s) * 0.95)] if len(s) >= 20 else max(s)
    passed = p50 < 50.0
    print(f"  Target: p50 < 50ms - {'PASS' if passed else 'FAIL'} (p50={p50:.1f}ms, p95={p95:.1f}ms)")
    return {"test": "entity_graph", "passed": passed, "p50_ms": round(p50, 1), "p95_ms": round(p95, 1), "n": len(latencies)}


def test_4_concurrent_ingest():
    """Test 4: Concurrent feed ingest - 6 sources x 20 entities."""
    print("\n=== Test 4: Concurrent feed ingest (6 sources x 20 entities, direct DuckDB) ===")
    import ftm_query
    seen_at = datetime.now(timezone.utc).isoformat()
    sources = ["gdacs", "gdelt-pulse", "eonet", "ais", "anomalies", "intel-ingest"]
    per_source = 20
    total = len(sources) * per_source

    def ingest_batch(source: str, count: int) -> tuple[str, float, int]:
        t0 = time.perf_counter()
        ingested = 0
        for i in range(count):
            try:
                props = {
                    "name": [f"Concurrent {source} {i}"],
                    "description": [f"Stresstest concurrent ingest from {source}"],
                }
                entity = ftm_query.make_entity("Event", [f"concurrent-{source}-{i}"], props)
                ftm_query.upsert(entity, dataset=source, seen_at=seen_at)
                ingested += 1
            except Exception:
                pass
        dt = time.perf_counter() - t0
        return source, dt, ingested

    t0_total = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = [pool.submit(ingest_batch, src, per_source) for src in sources]
        results = []
        for fut in concurrent.futures.as_completed(futures):
            src, dt, n = fut.result()
            results.append((src, dt, n))
            print(f"  {src}: {n}/{per_source} entities in {dt:.2f}s")
    total_dt = time.perf_counter() - t0_total

    total_ingested = sum(n for _, _, n in results)
    print(f"  Total: {total_ingested}/{total} entities in {total_dt:.2f}s")
    if total_dt > 0:
        print(f"  Throughput: {total_ingested / total_dt:.0f} entities/s")

    passed = total_ingested == total and total_dt < 5.0
    print(f"  Target: all {total} ingested, <5s total - {'PASS' if passed else 'FAIL'}")
    return {"test": "concurrent_ingest", "passed": passed,
            "total_ingested": total_ingested, "total_target": total,
            "duration_s": round(total_dt, 2),
            "throughput_per_s": round(total_ingested / total_dt, 0) if total_dt > 0 else 0}


def cleanup():
    """Remove stresstest entities from DB."""
    try:
        import ftm_connection
        conn = ftm_connection._conn()
        if conn:
            conn.execute("DELETE FROM entities WHERE id LIKE 'stresstest-upsert-%'")
            conn.execute("DELETE FROM statements WHERE entity_id LIKE 'stresstest-upsert-%'")
            conn.execute("DELETE FROM edges WHERE source_id LIKE 'stresstest-upsert-%' OR target_id LIKE 'stresstest-upsert-%'")
            for src in ["gdacs", "gdelt-pulse", "eonet", "ais", "anomalies", "intel-ingest"]:
                conn.execute(f"DELETE FROM entities WHERE id LIKE 'concurrent-{src}-%'")
                conn.execute(f"DELETE FROM statements WHERE entity_id LIKE 'concurrent-{src}-%'")
            print("\n  Cleanup: stresstest entities removed")
    except Exception as e:
        print(f"\n  Cleanup warning: {e}")


def main():
    print("=" * 70)
    print("  WORLDBASE P5 STRESSTEST - Direct DuckDB (no API, no autopilot)")
    print("=" * 70)

    # Graph baseline
    try:
        import ftm_store
        stats = ftm_store.stats()
        print(f"  Graph: {stats.get('entities', '?')} entities, "
              f"{stats.get('statements', '?')} statements, "
              f"{stats.get('edges', '?')} edges")
    except Exception as e:
        print(f"  FATAL: Cannot open DuckDB: {e}")
        print(f"  Make sure the API is shut down (DuckDB is single-process).")
        sys.exit(1)

    results = []
    results.append(test_1_upsert_latency())
    results.append(test_2_subgraph_traversal())
    results.append(test_3_entity_graph())
    results.append(test_4_concurrent_ingest())

    # Summary
    print("\n" + "=" * 70)
    print("  STRESSTEST SUMMARY (Direct DuckDB, no autopilot contention)")
    print("=" * 70)
    passed = sum(1 for r in results if r.get("passed") is True)
    failed = sum(1 for r in results if r.get("passed") is False)
    skipped = sum(1 for r in results if r.get("passed") is None)
    for r in results:
        status = "PASS" if r.get("passed") is True else ("FAIL" if r.get("passed") is False else "SKIP")
        extra = ""
        if "p50_ms" in r:
            extra = f" (p50={r['p50_ms']}ms, p95={r['p95_ms']}ms)"
        elif "duration_s" in r:
            extra = f" ({r['duration_s']}s)"
        print(f"  {r['test']}: {status}{extra}")
    print(f"\n  Total: {passed} PASS / {failed} FAIL / {skipped} SKIP")

    # Write JSON results
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "stresstest_db_results.json")
    with open(out_path, "w") as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "direct_duckdb",
            "graph_baseline": stats if "stats" in dir() else {},
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Results written to {out_path}")

    cleanup()


if __name__ == "__main__":
    main()
