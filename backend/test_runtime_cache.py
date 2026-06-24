"""Unit tests for runtime_cache thread-safety and TTL semantics."""

from __future__ import annotations

import threading
import time
import unittest

import runtime_cache as rc


class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        rc.STORE.clear()

    def tearDown(self):
        rc.STORE.clear()

    def test_cache_set_then_get(self):
        rc.cache_set("k1", {"v": 1})
        self.assertEqual(rc.cache_get("k1", ttl=60), {"v": 1})

    def test_cache_get_expired_returns_none(self):
        rc.cache_set("k2", "old")
        # simulate expiry by using ttl=0
        time.sleep(0.01)
        self.assertIsNone(rc.cache_get("k2", ttl=0))

    def test_cache_get_stale_returns_regardless_of_age(self):
        rc.cache_set("k3", "stale-val")
        time.sleep(0.01)
        self.assertEqual(rc.cache_get_stale("k3"), "stale-val")

    def test_cache_get_stale_missing_returns_none(self):
        self.assertIsNone(rc.cache_get_stale("nope"))

    def test_concurrent_set_get_no_crash(self):
        """Hammer cache_set / cache_get from multiple threads — must not raise."""

        errors: list[Exception] = []

        def writer():
            try:
                for i in range(200):
                    rc.cache_set(f"w:{i}", i)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(200):
                    rc.cache_get(f"w:{i}", ttl=60)
                    rc.cache_get_stale(f"w:{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_concurrent_set_preserves_integrity(self):
        """Last writer wins — value must be one of the written values."""
        rc.cache_set("shared", 0)
        vals = list(range(1, 50))

        def writer(v):
            rc.cache_set("shared", v)

        threads = [threading.Thread(target=writer, args=(v,)) for v in vals]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        result = rc.cache_get("shared", ttl=60)
        self.assertIn(result, vals)


if __name__ == "__main__":
    unittest.main()
