#!/usr/bin/env python3
"""
Stack measurement script for WorldBase.
Records latency and payload size for critical endpoints + chat queries.
Run from repo root: backend\\venv\\Scripts\\python.exe scripts\\measure_stack.py
"""

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8002"
TIMEOUT = 60.0
REPEAT = 3

REPORT_PATH = Path("data/stack_measurement_report.json")


def load_api_key():
    """Read WORLDBASE_API_KEY from backend/.env if present."""
    env_path = Path("backend/.env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("WORLDBASE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return os.environ.get("WORLDBASE_API_KEY")


API_KEY = load_api_key()

CHAT_QUERIES = [
    ("simple", "What is the capital of France?"),
    ("analysis", "Analyze the situation around M4.4 earthquake near Moron, Venezuela."),
    ("operator_region", "What is the current situation in Thailand?"),
]

CHAT_TIMEOUT = 60.0  # Chat includes context assembly + LLM generation; allow 60s
CHAT_REPEAT = 1      # Do not repeat chat calls — each call is expensive and stateful


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def measure(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    start = time.perf_counter()
    if "timeout" not in kwargs:
        kwargs["timeout"] = TIMEOUT
    try:
        resp = client.request(method, url, **kwargs)
        elapsed = time.perf_counter() - start
        return {
            "status": resp.status_code,
            "latency_ms": round(elapsed * 1000, 2),
            "size_bytes": len(resp.content),
            "ok": resp.status_code == 200,
            "error": None,
        }
    except Exception as e:
        elapsed = time.perf_counter() - start
        return {
            "status": None,
            "latency_ms": round(elapsed * 1000, 2),
            "size_bytes": 0,
            "ok": False,
            "error": str(e),
        }


def measure_repeated(client: httpx.Client, method: str, url: str, timeout: float = TIMEOUT, repeat_count: int = REPEAT, **kwargs) -> dict:
    times = []
    last_result = None
    for _ in range(repeat_count):
        r = measure(client, method, url, timeout=timeout, **kwargs)
        if r["ok"]:
            times.append(r["latency_ms"])
        last_result = r
    if not times:
        return last_result
    return {
        "status": last_result["status"],
        "latency_ms": round(statistics.mean(times), 2),
        "latency_min_ms": round(min(times), 2),
        "latency_max_ms": round(max(times), 2),
        "size_bytes": last_result["size_bytes"],
        "ok": True,
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser(description="Measure WorldBase stack latency and payload sizes.")
    parser.add_argument("--chat", action="store_true", help="Include chat endpoint measurements (may hang if Ollama is under GPU pressure).")
    args = parser.parse_args()

    report = {
        "measured_at": now_iso(),
        "base_url": BASE_URL,
        "repeat": REPEAT,
        "run_chat": args.chat,
        "endpoints": {},
        "chat": {},
        "ollama": {},
        "system": {},
    }

    with httpx.Client() as client:
        # Health
        report["endpoints"]["health"] = measure_repeated(client, "GET", f"{BASE_URL}/api/health/ping")

        # Briefing
        report["endpoints"]["briefing"] = measure_repeated(client, "GET", f"{BASE_URL}/api/briefing")

        # Trust
        report["endpoints"]["trust"] = measure_repeated(client, "GET", f"{BASE_URL}/api/trust")

        # Intel stats
        report["endpoints"]["intel_stats"] = measure_repeated(client, "GET", f"{BASE_URL}/api/intel/stats")

        # Intel subgraph around operator bbox (small)
        report["endpoints"]["intel_subgraph"] = measure_repeated(client, "GET", f"{BASE_URL}/api/intel/subgraph?hops=1")

        # Connectors
        report["endpoints"]["connectors"] = measure_repeated(client, "GET", f"{BASE_URL}/api/connectors")

        # Chat queries (only if explicitly requested — Ollama may hang under GPU pressure)
        if args.chat:
            chat_headers = {"X-API-Key": API_KEY} if API_KEY else {}
            if not API_KEY:
                report["chat"]["_note"] = "No WORLDBASE_API_KEY found; chat requests will fail with 401."
            run_session = f"measurement-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            for label, query in CHAT_QUERIES:
                payload = {"query": query, "session_id": run_session}
                r = measure_repeated(client, "POST", f"{BASE_URL}/api/chat", json=payload, headers=chat_headers, timeout=CHAT_TIMEOUT, repeat_count=CHAT_REPEAT)
                report["chat"][label] = r
        else:
            report["chat"]["_note"] = "Skipped (use --chat to enable; Ollama may hang under GPU pressure)."

        # Ollama models
        try:
            ollama_resp = client.get("http://127.0.0.1:11434/api/tags", timeout=10.0)
            if ollama_resp.status_code == 200:
                models = ollama_resp.json().get("models", [])
                report["ollama"] = {
                    "ok": True,
                    "model_count": len(models),
                    "model_names": [m.get("name") for m in models],
                }
            else:
                report["ollama"] = {"ok": False, "error": f"status {ollama_resp.status_code}"}
        except Exception as e:
            report["ollama"] = {"ok": False, "error": str(e)}

        # System info (process count)
        try:
            import psutil
            report["system"]["python_memory_mb"] = round(psutil.Process().memory_info().rss / 1024 / 1024, 2)
            report["system"]["cpu_percent"] = psutil.cpu_percent(interval=1)
        except Exception as e:
            report["system"]["python_memory_mb"] = None
            report["system"]["cpu_percent"] = None
            report["system"]["error"] = str(e)

    # Save report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Print summary
    print("=" * 60)
    print("WorldBase Stack Measurement Summary")
    print("=" * 60)
    print(f"Measured at: {report['measured_at']}")
    print(f"Base URL:    {report['base_url']}")
    print(f"Repeat:      {report['repeat']}")
    print()
    print("Endpoints:")
    for name, data in report["endpoints"].items():
        status = "OK" if data["ok"] else "FAIL"
        print(f"  {name:20s} {status:5s} {data['latency_ms']:8.2f} ms  ({data['size_bytes']:,} bytes)")
    print()
    print("Chat queries:")
    for label, data in report["chat"].items():
        if isinstance(data, str):
            print(f"  {label:20s} NOTE  {data}")
            continue
        status = "OK" if data["ok"] else "FAIL"
        print(f"  {label:20s} {status:5s} {data['latency_ms']:8.2f} ms  ({data['size_bytes']:,} bytes)")
    print()
    print("Ollama:")
    print(f"  Models: {report['ollama'].get('model_count')} — {report['ollama'].get('model_names')}")
    print()
    print("System:")
    print(f"  Python memory: {report['system'].get('python_memory_mb')} MB")
    print(f"  CPU percent:   {report['system'].get('cpu_percent')}%")
    print()
    print(f"Full report saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
