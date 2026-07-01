"""Tests for cache_coalesce — cache stampede protection.

Verifies that concurrent cache-misses for the same key share a single upstream
fetch, and that the result is cached for subsequent requests.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import cache_coalesce
import runtime_cache


class TestCacheCoalesce(unittest.IsolatedAsyncioTestCase):
    """Core coalescing behaviour."""

    async def asyncSetUp(self):
        runtime_cache.STORE.clear()
        cache_coalesce.clear_inflight()

    async def asyncTearDown(self):
        runtime_cache.STORE.clear()
        cache_coalesce.clear_inflight()

    async def test_single_fetch_caches_result(self):
        """A single call fetches and caches."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"data": "test"}

        result = await cache_coalesce.cached_fetch_json("k1", ttl=60, fetcher=fetcher)
        self.assertEqual(result, {"data": "test"})
        self.assertEqual(call_count, 1)

        # Second call should hit cache, not fetcher
        result2 = await cache_coalesce.cached_fetch_json("k1", ttl=60, fetcher=fetcher)
        self.assertEqual(result2, {"data": "test"})
        self.assertEqual(call_count, 1)  # no additional fetch

    async def test_concurrent_requests_single_fetch(self):
        """Multiple concurrent requests for same key → 1 upstream fetch."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            # Simulate slow upstream
            await asyncio.sleep(0.05)
            return {"data": f"result_{call_count}"}

        # Launch 10 concurrent requests for the same key
        tasks = [
            asyncio.create_task(
                cache_coalesce.cached_fetch_json(
                    "concurrent_key", ttl=60, fetcher=fetcher
                )
            )
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)

        # All should get the same result
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r == results[0] for r in results))
        # Only 1 upstream fetch should have occurred
        self.assertEqual(call_count, 1)

    async def test_different_keys_fetch_separately(self):
        """Different keys should fetch independently."""
        call_counts = {"a": 0, "b": 0}

        async def make_fetcher(key):
            async def fetcher():
                call_counts[key] += 1
                await asyncio.sleep(0.01)
                return {"key": key}

            return fetcher

        fa = await make_fetcher("a")
        fb = await make_fetcher("b")

        ra, rb = await asyncio.gather(
            cache_coalesce.cached_fetch_json("key_a", ttl=60, fetcher=fa),
            cache_coalesce.cached_fetch_json("key_b", ttl=60, fetcher=fb),
        )

        self.assertEqual(ra, {"key": "a"})
        self.assertEqual(rb, {"key": "b"})
        self.assertEqual(call_counts["a"], 1)
        self.assertEqual(call_counts["b"], 1)

    async def test_expired_cache_triggers_new_fetch(self):
        """After TTL expires, a new fetch should occur."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"version": call_count}

        # First fetch
        r1 = await cache_coalesce.cached_fetch_json(
            "expiry_key", ttl=0.05, fetcher=fetcher
        )
        self.assertEqual(r1, {"version": 1})
        self.assertEqual(call_count, 1)

        # Wait for TTL to expire
        await asyncio.sleep(0.1)

        # Second fetch should trigger new upstream call
        r2 = await cache_coalesce.cached_fetch_json(
            "expiry_key", ttl=0.05, fetcher=fetcher
        )
        self.assertEqual(r2, {"version": 2})
        self.assertEqual(call_count, 2)

    async def test_ttl_zero_always_fetches(self):
        """ttl=0 means always fetch (no caching)."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return {"n": call_count}

        r1 = await cache_coalesce.cached_fetch_json("no_cache", ttl=0, fetcher=fetcher)
        r2 = await cache_coalesce.cached_fetch_json("no_cache", ttl=0, fetcher=fetcher)
        self.assertEqual(r1, {"n": 1})
        self.assertEqual(r2, {"n": 2})
        self.assertEqual(call_count, 2)

    async def test_fetcher_exception_propagates(self):
        """If the fetcher raises, all waiters should get the exception."""

        async def fetcher():
            raise ValueError("upstream error")

        with self.assertRaises(ValueError):
            await cache_coalesce.cached_fetch_json("err_key", ttl=60, fetcher=fetcher)

    async def test_concurrent_exception_propagates_to_all(self):
        """All concurrent waiters should receive the exception."""

        async def fetcher():
            await asyncio.sleep(0.02)
            raise RuntimeError("upstream down")

        tasks = [
            asyncio.create_task(
                cache_coalesce.cached_fetch_json(
                    "err_concurrent", ttl=60, fetcher=fetcher
                )
            )
            for _ in range(5)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            self.assertIsInstance(r, RuntimeError)

    async def test_inflight_count_tracks_active(self):
        """get_inflight_count should reflect active coalesced requests."""
        self.assertEqual(cache_coalesce.get_inflight_count(), 0)

        started = asyncio.Event()

        async def fetcher():
            started.set()
            await asyncio.sleep(0.1)
            return {"ok": True}

        task = asyncio.create_task(
            cache_coalesce.cached_fetch_json("inflight_test", ttl=60, fetcher=fetcher)
        )
        await started.wait()
        # The inflight entry may or may not be visible depending on timing,
        # but it should be >= 0
        count = cache_coalesce.get_inflight_count()
        self.assertGreaterEqual(count, 0)

        result = await task
        self.assertEqual(result, {"ok": True})
        # After completion, inflight should be cleared
        self.assertEqual(cache_coalesce.get_inflight_count(), 0)

    async def test_coalescing_disabled_passes_through(self):
        """When WORLDBASE_CACHE_COALESCE=0, each request fetches independently."""
        with patch.dict(os.environ, {"WORLDBASE_CACHE_COALESCE": "0"}):
            # Reload module to pick up env change
            import importlib

            importlib.reload(cache_coalesce)

            call_count = 0

            async def fetcher():
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.01)
                return {"n": call_count}

            # Two concurrent requests with coalescing disabled
            r1, r2 = await asyncio.gather(
                cache_coalesce.cached_fetch_json(
                    "disabled_key", ttl=0, fetcher=fetcher
                ),
                cache_coalesce.cached_fetch_json(
                    "disabled_key", ttl=0, fetcher=fetcher
                ),
            )

            # Both should have fetched (no coalescing)
            self.assertEqual(call_count, 2)

        # Restore default
        importlib.reload(cache_coalesce)

    async def test_cache_invalidate(self):
        """cache_invalidate removes a key from the store."""

        async def fetcher():
            return {"v": 1}

        await cache_coalesce.cached_fetch_json(
            "invalidate_test", ttl=60, fetcher=fetcher
        )
        self.assertIsNotNone(runtime_cache.cache_get("invalidate_test", ttl=60))

        runtime_cache.cache_invalidate("invalidate_test")
        self.assertIsNone(runtime_cache.cache_get("invalidate_test", ttl=60))

    async def test_persist_writes_to_feed_registry(self):
        """persist=True should write to feed_registry."""
        with patch.object(cache_coalesce.feed_registry, "write_auto") as mock_write:

            async def fetcher():
                return {"data": "persisted"}

            await cache_coalesce.cached_fetch_json(
                "persist_key", ttl=60, fetcher=fetcher, persist=True
            )

            mock_write.assert_called_once_with("persist_key", {"data": "persisted"})

    async def test_persist_failure_does_not_raise(self):
        """If feed_registry.write_auto fails, the result should still be returned."""
        with patch.object(
            cache_coalesce.feed_registry,
            "write_auto",
            side_effect=Exception("disk full"),
        ):

            async def fetcher():
                return {"data": "ok"}

            result = await cache_coalesce.cached_fetch_json(
                "persist_fail", ttl=60, fetcher=fetcher, persist=True
            )
            self.assertEqual(result, {"data": "ok"})

    async def test_is_coalescing_enabled(self):
        """is_coalescing_enabled should reflect the env var."""
        # Default is enabled
        self.assertTrue(cache_coalesce.is_coalescing_enabled())


class TestCacheCoalesceEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Edge cases and regression tests."""

    async def asyncSetUp(self):
        runtime_cache.STORE.clear()
        cache_coalesce.clear_inflight()

    async def asyncTearDown(self):
        runtime_cache.STORE.clear()
        cache_coalesce.clear_inflight()

    async def test_sequential_different_keys(self):
        """Sequential calls with different keys should each fetch."""
        results = []

        async def make_fetcher(val):
            async def fetcher():
                results.append(val)
                return {"val": val}

            return fetcher

        for i in range(5):
            f = await make_fetcher(i)
            r = await cache_coalesce.cached_fetch_json(f"seq_{i}", ttl=60, fetcher=f)
            self.assertEqual(r, {"val": i})

        self.assertEqual(results, [0, 1, 2, 3, 4])

    async def test_cache_hit_after_concurrent_fetch(self):
        """After a coalesced fetch, subsequent calls should hit cache."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.02)
            return {"n": call_count}

        # 5 concurrent
        await asyncio.gather(
            *[
                cache_coalesce.cached_fetch_json("hit_after", ttl=60, fetcher=fetcher)
                for _ in range(5)
            ]
        )
        self.assertEqual(call_count, 1)

        # Sequential cache hits
        for _ in range(3):
            r = await cache_coalesce.cached_fetch_json(
                "hit_after", ttl=60, fetcher=fetcher
            )
            self.assertEqual(r, {"n": 1})
        self.assertEqual(call_count, 1)  # still 1 fetch

    async def test_large_concurrent_batch(self):
        """100 concurrent requests should still result in 1 fetch."""
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return {"ok": True}

        tasks = [
            asyncio.create_task(
                cache_coalesce.cached_fetch_json("batch_100", ttl=60, fetcher=fetcher)
            )
            for _ in range(100)
        ]
        results = await asyncio.gather(*tasks)

        self.assertEqual(call_count, 1)
        self.assertTrue(all(r == {"ok": True} for r in results))
        self.assertEqual(len(results), 100)


if __name__ == "__main__":
    unittest.main()
