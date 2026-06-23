"""Rate limiter backend configuration (memory + optional Redis)."""

import unittest
from unittest.mock import patch

from middleware import rate_limit as rl


class RateLimitBackendTests(unittest.TestCase):
    def test_memory_backend_uses_key_prefix_and_fallback(self):
        with patch.object(rl, "RATE_LIMIT_STORAGE", "memory"), patch.object(rl, "REDIS_URL", None):
            limiter = rl.create_limiter()
        self.assertEqual(limiter._key_prefix, "worldbase:ratelimit:")
        self.assertTrue(limiter._in_memory_fallback_enabled)
        self.assertGreater(len(limiter._default_limits), 0)

    def test_redis_backend_short_timeouts_and_pool(self):
        with patch.object(rl, "RATE_LIMIT_STORAGE", "redis"), patch.object(
            rl, "REDIS_URL", "redis://127.0.0.1:6379/0"
        ):
            opts = rl._redis_storage_options()
            limiter = rl.create_limiter()
        self.assertEqual(opts["socket_connect_timeout"], 2.0)
        self.assertEqual(opts["socket_timeout"], 2.0)
        self.assertEqual(opts["max_connections"], 10)
        self.assertEqual(limiter._storage_uri, "redis://127.0.0.1:6379/0")

    def test_redis_status_probe_when_local_redis_up(self):
        with patch.object(rl, "RATE_LIMIT_STORAGE", "redis"), patch.object(
            rl, "REDIS_URL", "redis://127.0.0.1:6379/0"
        ):
            status = rl.get_rate_limit_backend_status()
        if status["backend"] != "redis":
            self.skipTest("Redis backend not selected")
        if status.get("redis_reachable") is not True:
            self.skipTest(f"Local Redis unreachable: {status.get('redis_error')}")
        self.assertEqual(status["key_prefix"], "worldbase:ratelimit:")


if __name__ == "__main__":
    unittest.main()
