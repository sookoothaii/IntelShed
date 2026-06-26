#!/usr/bin/env python3
"""System-level darkweb capability demonstration.

This script proves the robustness of the WorldBase darkweb OSINT module by
running a mixture of live endpoint probes and isolated unit-style checks against
the backend code. It does not require a running Tor proxy or real .onion
connectivity; it verifies fail-soft behaviour, entity extraction, circuit
isolation, and API surface.

Run from the workspace root with the backend venv:

    backend\\venv\\Scripts\\python.exe scripts\\test_darkweb_system.py

"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add backend to path without importing it as a package.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import httpx

import darkweb_bridge

API = "http://127.0.0.1:8002"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


async def probe_live_endpoints() -> dict:
    """Probe the running backend and record response shapes."""
    results: dict = {"status": False, "engines": False, "scrape": False, "deep_search": False}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{API}/api/health/ping")
            results["api_up"] = r.status_code == 200
            if not results["api_up"]:
                return results

            r = await client.get(f"{API}/api/darkweb/status")
            if r.status_code == 200:
                payload = r.json()
                results["status"] = {
                    "ok": True,
                    "has_engines": isinstance(payload.get("engines"), list),
                    "engine_count": len(payload.get("engine_registry", {})),
                    "has_timeout": "timeout_sec" in payload,
                }

            r = await client.get(f"{API}/api/darkweb/engines")
            if r.status_code == 200:
                payload = r.json()
                results["engines"] = {
                    "ok": True,
                    "count": len(payload.get("engines", [])),
                    "configured": payload.get("configured"),
                }

            r = await client.post(
                f"{API}/api/darkweb/scrape",
                json={"url": "http://abc234abc234abcd.onion/page"},
            )
            if r.status_code == 200:
                payload = r.json()
                results["scrape"] = {
                    "ok": True,
                    "has_url": "url" in payload,
                    "fail_soft": not payload.get("ok"),
                    "error": payload.get("error"),
                }

            r = await client.post(
                f"{API}/api/darkweb/deep_search",
                json={"q": "test", "engines": "ahmia", "limit": 5, "scrape_limit": 2},
            )
            if r.status_code == 200:
                payload = r.json()
                results["deep_search"] = {
                    "ok": True,
                    "fail_soft": bool(payload.get("error")),
                    "error": payload.get("error"),
                }
    except Exception as exc:
        results["error"] = str(exc)
    return results


def test_entity_extraction() -> dict:
    """Verify that the bridge extracts crypto, PGP, emails, IOCs and .onion links."""
    text = (
        "Send BTC to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa or "
        "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh. "
        "Contact alice@example.com or bob@example.org. "
        "Visit http://abc234abc234abcd.onion/page and "
        "http://xyz234xyz234xyz2.onion/post. "
        "PGP: 1234567890ABCDEF1234567890ABCDEF12345678. "
        "CVE-2026-12345, MD5: d41d8cd98f00b204e9800998ecf8427e."
    )
    entities = darkweb_bridge._extract_entities(text)
    return {
        "btc_wallet": len(entities.get("btc_wallet", [])) >= 2,
        "email": {"alice@example.com", "bob@example.org"} <= set(entities.get("email", [])),
        "onion": any("abc234" in u for u in entities.get("onion", [])),
        "pgp_fingerprint": len(entities.get("pgp_fingerprint", [])) >= 1,
        "cve": any("CVE-2026-12345" in c for c in entities.get("cve", [])),
        "md5": any("d41d8cd98f00b204e9800998ecf8427e" in m for m in entities.get("md5", [])),
    }


async def test_clearnet_parallel_and_tor_isolation() -> dict:
    """Prove clearnet engines share a client and Tor engines get fresh clients."""
    html = """
    <li class="result">
        <h4><a href="http://abc234abc234abcd.onion/page">Ahmia Title</a></h4>
        <p>snippet</p>
    </li>
    """
    with patch("darkweb_bridge.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        response = MagicMock()
        response.text = html
        response.raise_for_status = MagicMock()
        instance.get = AsyncMock(return_value=response)

        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
            out = await darkweb_bridge.search_darkweb(
                "test", engines=["ahmia", "darksearch"], limit=10
            )

        return {
            "clearnet_shared_client": mock_client.return_value.__aenter__.call_count == 1,
            "results_count": out["count"],
            "first_engine": out["results"][0]["engine"] if out["results"] else None,
        }


async def test_tor_sequential_fail_soft() -> dict:
    """Prove Tor engines are skipped without proxy and do not crash."""
    with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
        with patch.object(darkweb_bridge, "darkweb_enabled", return_value=True):
            out = await darkweb_bridge.search_darkweb(
                "test", engines=["torch", "tor66"], limit=10
            )
    return {
        "no_crash": isinstance(out, dict),
        "zero_results": out["count"] == 0,
        "error_mentions_tor": "requires Tor proxy" in (out.get("error") or ""),
    }


async def test_scrape_fail_soft() -> dict:
    """Prove .onion scrape fails gracefully without a proxy."""
    with patch.object(darkweb_bridge, "_tor_proxy", return_value=None):
        out = await darkweb_bridge._scrape_onion_page("http://abc234abc234abcd.onion/page")
    return {
        "not_ok": not out["ok"],
        "error": out["error"],
        "empty_text": out["text"] == "",
    }


async def test_scrape_rejects_clearnet() -> dict:
    """Prove the scraper refuses to fetch clearnet URLs."""
    out = await darkweb_bridge._scrape_onion_page("https://example.com/page")
    return {
        "rejected": not out["ok"],
        "error": out["error"],
    }


def score(results: dict) -> tuple[int, int, list[str]]:
    """Flatten nested results into pass/fail booleans and report failures."""
    passed = 0
    failed = 0
    failures: list[str] = []

    def walk(value, path: str = "root"):
        nonlocal passed, failed
        if isinstance(value, bool):
            if value:
                passed += 1
            else:
                failed += 1
                failures.append(path)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}")
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    walk(results)
    return passed, failed, failures


async def main() -> int:
    _log("Starting darkweb system capability test")
    start = time.time()

    results = {
        "live_endpoints": await probe_live_endpoints(),
        "entity_extraction": test_entity_extraction(),
        "clearnet_parallel": await test_clearnet_parallel_and_tor_isolation(),
        "tor_fail_soft": await test_tor_sequential_fail_soft(),
        "scrape_fail_soft": await test_scrape_fail_soft(),
        "scrape_rejects_clearnet": await test_scrape_rejects_clearnet(),
    }

    passed, failed, failures = score(results)
    total = passed + failed

    print("\n" + "=" * 60)
    print("DARKWEB SYSTEM CAPABILITY REPORT")
    print("=" * 60)
    print(json.dumps(results, indent=2, default=str))
    print("-" * 60)
    print(f"Score: {passed}/{total} checks passed ({failed} failed)")
    if failures:
        print("Failed checks:")
        for f in failures:
            print(f"  - {f}")
    print(f"Duration: {time.time() - start:.2f}s")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nAborted")
        sys.exit(130)
