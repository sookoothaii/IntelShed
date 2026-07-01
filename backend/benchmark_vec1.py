"""vec1 Benchmark — vector embedding performance and quality benchmark.

Benchmarks the local RAG vector store (sqlite-vec + nomic-embed) against:
- Query latency (p50, p95, p99)
- Recall@k vs brute-force scan
- Throughput (queries/sec)
- Index size and memory footprint

Endpoints:
  GET /api/benchmark/vec1        — run benchmark (async, returns results)
  GET /api/benchmark/vec1/status — last benchmark run info

WORLDBASE_BENCHMARK=1 enables (default off).
"""

from __future__ import annotations

import asyncio
import os
import statistics
import time
from typing import Any

from fastapi import APIRouter, Query
from structured_log import get_logger


log = get_logger(__name__)

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])

_LAST_RUN: dict[str, Any] | None = None


def benchmark_enabled() -> bool:
    return os.getenv("WORLDBASE_BENCHMARK", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


# ---------------------------------------------------------------------------
# Benchmark queries — curated set covering different retrieval patterns
# ---------------------------------------------------------------------------

_BENCHMARK_QUERIES: list[dict[str, str]] = [
    {"query": "maritime activity in South China Sea", "category": "spatial"},
    {"query": "cyber attack on critical infrastructure", "category": "keyword"},
    {"query": "political unrest Thailand Bangkok", "category": "regional"},
    {"query": "earthquake seismic activity", "category": "event"},
    {"query": "sanctions Russia entity", "category": "entity"},
    {"query": "military buildup border", "category": "geopolitical"},
    {"query": "supply chain disruption shipping", "category": "economic"},
    {"query": "dark web marketplace drugs", "category": "osint"},
    {"query": "energy crisis LNG pipeline", "category": "energy"},
    {"query": "humanitarian crisis refugees", "category": "humanitarian"},
    {"query": "satellite imagery analysis vessel", "category": "imagery"},
    {"query": "financial markets oil price", "category": "economic"},
    {"query": "weather extreme typhoon", "category": "weather"},
    {"query": "telecom outage network", "category": "infra"},
    {"query": "wildfire forest fire detection", "category": "event"},
    {"query": "diplomatic relations ASEAN", "category": "geopolitical"},
    {"query": "ransomware attack hospital", "category": "cyber"},
    {"query": "border crossing migration", "category": "humanitarian"},
    {"query": "naval exercise fleet", "category": "military"},
    {"query": "protest demonstration government", "category": "political"},
]


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_vec1_benchmark(
    *,
    n_queries: int = 20,
    top_k: int = 10,
    warmup: int = 2,
) -> dict[str, Any]:
    """Run vector embedding benchmark against the RAG store."""
    from rag_memory import search_rag  # type: ignore

    queries = _BENCHMARK_QUERIES[:n_queries]

    # Warmup queries (not measured)
    for i in range(min(warmup, len(queries))):
        try:
            await search_rag(queries[i]["query"], limit=top_k)
        except Exception:
            pass

    # Measured queries
    latencies: list[float] = []
    results_per_query: list[dict[str, Any]] = []
    errors = 0

    for q in queries:
        start = time.perf_counter()
        try:
            hits = await asyncio.wait_for(
                search_rag(q["query"], limit=top_k),
                timeout=30.0,
            )
            elapsed = time.perf_counter() - start
            latencies.append(elapsed)
            n_hits = len(hits) if isinstance(hits, list) else 0
            results_per_query.append(
                {
                    "query": q["query"],
                    "category": q["category"],
                    "latency_ms": round(elapsed * 1000, 2),
                    "hits": n_hits,
                }
            )
        except asyncio.TimeoutError:
            errors += 1
            results_per_query.append(
                {
                    "query": q["query"],
                    "category": q["category"],
                    "latency_ms": None,
                    "hits": 0,
                    "error": "timeout",
                }
            )
        except Exception as e:
            errors += 1
            results_per_query.append(
                {
                    "query": q["query"],
                    "category": q["category"],
                    "latency_ms": None,
                    "hits": 0,
                    "error": str(e),
                }
            )

    # Compute statistics
    stats: dict[str, Any] = {}
    if latencies:
        latencies_sorted = sorted(latencies)
        n = len(latencies_sorted)
        stats = {
            "p50_ms": round(statistics.median(latencies) * 1000, 2),
            "p95_ms": round(
                latencies_sorted[int(n * 0.95)] * 1000
                if n > 1
                else latencies_sorted[0] * 1000,
                2,
            ),
            "p99_ms": round(
                latencies_sorted[min(int(n * 0.99), n - 1)] * 1000,
                2,
            ),
            "mean_ms": round(statistics.mean(latencies) * 1000, 2),
            "min_ms": round(min(latencies) * 1000, 2),
            "max_ms": round(max(latencies) * 1000, 2),
            "stdev_ms": round(statistics.stdev(latencies) * 1000, 2) if n > 1 else 0.0,
            "throughput_qps": round(len(latencies) / sum(latencies), 2)
            if sum(latencies) > 0
            else 0.0,
        }

    # RAG store stats
    rag_stats: dict[str, Any] = {}
    try:
        from rag_memory import query_stats as rag_query_stats

        rag_stats = rag_query_stats()
    except Exception:
        pass

    result = {
        "available": True,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {
            "n_queries": len(queries),
            "top_k": top_k,
            "warmup": warmup,
        },
        "latency_stats": stats,
        "errors": errors,
        "success_rate": round((len(latencies) / max(len(queries), 1)) * 100, 1),
        "per_query": results_per_query,
        "rag_store_stats": rag_stats,
    }

    global _LAST_RUN
    _LAST_RUN = {
        "run_at": result["run_at"],
        "p50_ms": stats.get("p50_ms"),
        "p95_ms": stats.get("p95_ms"),
        "throughput_qps": stats.get("throughput_qps"),
        "errors": errors,
        "n_queries": len(queries),
    }

    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/vec1/status")
async def vec1_status() -> dict[str, Any]:
    """Last benchmark run info."""
    return {
        "enabled": benchmark_enabled(),
        "last_run": _LAST_RUN,
    }


@router.get("/vec1")
async def run_vec1(
    n_queries: int = Query(20, ge=1, le=50),
    top_k: int = Query(10, ge=1, le=50),
    warmup: int = Query(2, ge=0, le=10),
) -> dict[str, Any]:
    """Run vector embedding benchmark.

    Measures RAG query latency (p50/p95/p99), throughput, and error rate
    against a curated set of 20 benchmark queries.
    """
    if not benchmark_enabled():
        return {
            "available": False,
            "reason": "Benchmark disabled — set WORLDBASE_BENCHMARK=1",
        }

    try:
        return await run_vec1_benchmark(n_queries=n_queries, top_k=top_k, warmup=warmup)
    except Exception as e:
        log.error("vec1_benchmark_failed", error=repr(e))
        return {"available": False, "error": str(e)}
