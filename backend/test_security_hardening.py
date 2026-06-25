"""Security regression tests for Phase 6 hardening (2026-06-24).

Covers:
- 6.1: Auth-by-default enforcement (bootstrap_env warnings)
- 6.2: Admin/ingest token separation (no fallback)
- 6.3: Error messages don't leak internals
- 6.4: DuckDB queries use parameterized bindings (no f-string SQL)
- 6.5: Content-type validation on file uploads
- 6.6: Private IP blocking in OSINT tools
"""

from __future__ import annotations

import unittest
from unittest.mock import patch
from unittest.mock import MagicMock



class TestBootstrapEnvWarnings(unittest.TestCase):
    """6.1 — Auth-by-default enforcement."""

    def test_warns_when_no_tokens_set(self):
        import bootstrap_env

        with patch.dict("os.environ", {}, clear=True):
            with patch("builtins.print") as mock_print:
                bootstrap_env.log_security_startup()
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("WARNING", printed)
        self.assertIn("unauthenticated", printed)

    def test_no_warning_when_api_key_set(self):
        import bootstrap_env

        with patch.dict("os.environ", {"WORLDBASE_API_KEY": "test-key"}, clear=True):
            with patch("builtins.print") as mock_print:
                bootstrap_env.log_security_startup()
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertNotIn("WARNING", printed)
        self.assertIn("API key auth enabled", printed)

    def test_dev_mode_suppresses_warning(self):
        import bootstrap_env

        with patch.dict("os.environ", {"WORLDBASE_INSECURE_DEV": "1"}, clear=True):
            with patch("builtins.print") as mock_print:
                bootstrap_env.log_security_startup()
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("INSECURE DEV MODE", printed)
        self.assertNotIn("WARNING", printed)

    def test_require_node_token_raises_without_token(self):
        import bootstrap_env

        with patch.dict(
            "os.environ",
            {"WORLDBASE_REQUIRE_NODE_TOKEN": "1"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                bootstrap_env.log_security_startup()
        self.assertIn("Refusing to start", str(ctx.exception))


class TestAdminTokenSeparation(unittest.TestCase):
    """6.2 — Admin token no longer falls back to ingest token."""

    def test_admin_token_empty_when_not_set(self):
        with patch.dict("os.environ", {"NODE_INGEST_TOKEN": "ingest-secret"}, clear=True):
            # Need to reimport to pick up env changes
            import importlib
            import auth.security as sec
            importlib.reload(sec)
            self.assertEqual(sec.ADMIN_TOKEN, "")
            self.assertEqual(sec.INGEST_TOKEN, "ingest-secret")

    def test_admin_token_set_independently(self):
        with patch.dict(
            "os.environ",
            {"NODE_ADMIN_TOKEN": "admin-secret", "NODE_INGEST_TOKEN": "ingest-secret"},
            clear=True,
        ):
            import importlib
            import auth.security as sec
            importlib.reload(sec)
            self.assertEqual(sec.ADMIN_TOKEN, "admin-secret")
            self.assertEqual(sec.INGEST_TOKEN, "ingest-secret")

    def test_require_admin_raises_without_token(self):
        import importlib
        import auth.security as sec
        importlib.reload(sec)

        with patch.dict("os.environ", {}, clear=True):
            importlib.reload(sec)
            request = MagicMock()
            with self.assertRaises(Exception) as ctx:
                sec.require_admin_token(request)
        # Should be HTTPException with 503
        self.assertEqual(ctx.exception.status_code, 503)

    def test_require_admin_allows_in_dev_mode(self):
        import importlib
        import auth.security as sec

        with patch.dict("os.environ", {"WORLDBASE_INSECURE_DEV": "1"}, clear=True):
            importlib.reload(sec)
            request = MagicMock()
            # Should not raise
            sec.require_admin_token(request)


class TestErrorSanitization(unittest.TestCase):
    """6.3 — Error messages don't leak exception details."""

    def test_duckdb_fusion_errors_are_generic(self):
        import duckdb_fusion as df

        # Check that error strings in the module don't contain str(exc)
        import inspect
        source = inspect.getsource(df)
        self.assertNotIn("str(exc)", source)
        self.assertNotIn("{exc}", source)

    def test_entity_resolution_errors_are_generic(self):
        import entity_resolution as er
        import inspect

        source = inspect.getsource(er)
        self.assertNotIn("{exc}", source)

    def test_intel_ingest_errors_are_generic(self):
        import intel_ingest as ii
        import inspect

        source = inspect.getsource(ii)
        self.assertNotIn("{exc}", source)

    def test_feed_ingest_errors_are_generic(self):
        import feed_ingest as fi
        import inspect

        source = inspect.getsource(fi)
        self.assertNotIn("{exc}", source)


class TestDuckDBParameterization(unittest.TestCase):
    """6.4 — DuckDB queries use parameterized bindings."""

    def test_duckdb_fusion_no_fstring_sql(self):
        import duckdb_fusion as df
        import inspect

        source = inspect.getsource(df)
        # Should not have f-string SQL with sqlite_scan or read_parquet
        self.assertNotIn("f\"SELECT", source)
        self.assertNotIn("f\"\"\"", source)

    def test_fusion_spatial_stage_no_fstring_sql(self):
        import fusion_spatial_stage as fss
        import inspect

        source = inspect.getsource(fss)
        # Should not have f-string with read_parquet
        self.assertNotIn("read_parquet('{", source)
        self.assertNotIn("read_parquet(f\"", source)


class TestPrivateIPBlocking(unittest.TestCase):
    """6.6 — Private IP ranges blocked in OSINT tools."""

    def test_private_ip_detected(self):
        import osint_tools as ot

        self.assertTrue(ot._is_private_or_reserved("10.0.0.1"))
        self.assertTrue(ot._is_private_or_reserved("172.16.0.1"))
        self.assertTrue(ot._is_private_or_reserved("192.168.1.1"))
        self.assertTrue(ot._is_private_or_reserved("127.0.0.1"))
        self.assertTrue(ot._is_private_or_reserved("169.254.1.1"))

    def test_public_ip_not_blocked(self):
        import osint_tools as ot

        self.assertFalse(ot._is_private_or_reserved("8.8.8.8"))
        self.assertFalse(ot._is_private_or_reserved("1.1.1.1"))
        self.assertFalse(ot._is_private_or_reserved("93.184.216.34"))

    def test_invalid_ip_treated_as_private(self):
        import osint_tools as ot

        self.assertTrue(ot._is_private_or_reserved("not-an-ip"))
        self.assertTrue(ot._is_private_or_reserved(""))

    def test_ipv6_loopback_blocked(self):
        import osint_tools as ot

        self.assertTrue(ot._is_private_or_reserved("::1"))
        self.assertTrue(ot._is_private_or_reserved("fe80::1"))


class TestContentTypeValidation(unittest.TestCase):
    """6.5 — File upload content-type validation."""

    def test_allowed_types_defined(self):
        import intel_ingest as ii
        import inspect

        source = inspect.getsource(ii)
        self.assertIn("application/pdf", source)
        self.assertIn("message/rfc822", source)
        self.assertIn("text/plain", source)
        self.assertIn("content_type", source)


if __name__ == "__main__":
    unittest.main()
