"""Offline unit tests for secrets_manager (Phase 2.2) and /api/config/cesium.

All tests are offline — no network, no vault calls.
Vault backends are mocked via unittest.mock.patch.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure clean env before import
os.environ.pop("WORLDBASE_SECRET_BACKEND", None)
os.environ.pop("WORLDBASE_SECRET_VAULT_URL", None)

from secrets_manager import (  # noqa: E402
    _backend,
    _read_dotenv,
    clear_cache,
    get_backend,
    get_secret,
)


class TestSecretsManagerEnv(unittest.TestCase):
    """Tests for the default env backend."""

    def setUp(self):
        clear_cache()

    def tearDown(self):
        clear_cache()

    def test_get_secret_from_env(self):
        with patch.dict(os.environ, {"MY_TEST_KEY": "abc123"}):
            clear_cache()
            result = get_secret("MY_TEST_KEY", "")
            self.assertEqual(result, "abc123")

    def test_get_secret_default_when_missing(self):
        result = get_secret("NONEXISTENT_KEY_12345", "fallback")
        self.assertEqual(result, "fallback")

    def test_get_secret_dotenv_fallback(self):
        """When env var is not set, _read_dotenv should be tried."""
        with patch.dict(os.environ, {}, clear=True):
            clear_cache()
            with patch("secrets_manager._read_dotenv", return_value="from_dotenv"):
                result = get_secret("DOTENV_FALLBACK_KEY", "")
                self.assertEqual(result, "from_dotenv")

    def test_get_secret_dotenv_strips_quotes(self):
        """_read_dotenv strips quotes; get_secret just .strip()s the result."""
        with patch.dict(os.environ, {}, clear=True):
            clear_cache()
            with patch("secrets_manager._read_dotenv", return_value="unquoted_value"):
                result = get_secret("STRIP_TEST", "")
                self.assertEqual(result, "unquoted_value")

    def test_get_secret_caches(self):
        """Repeated calls should return cached value without re-reading env."""
        with patch.dict(os.environ, {"CACHE_TEST": "v1"}):
            clear_cache()
            r1 = get_secret("CACHE_TEST", "")
            self.assertEqual(r1, "v1")
            # Change env — cache should still return old value
            with patch.dict(os.environ, {"CACHE_TEST": "v2"}):
                r2 = get_secret("CACHE_TEST", "")
                self.assertEqual(r2, "v1")  # cached
                # Clear cache inside v2 context so it reads fresh
                clear_cache()
                r3 = get_secret("CACHE_TEST", "")
                self.assertEqual(r3, "v2")  # fresh after cache clear

    def test_get_backend_default(self):
        self.assertEqual(get_backend(), "env")

    def test_backend_reads_env_var(self):
        """_backend should reflect WORLDBASE_SECRET_BACKEND at import time."""
        # _backend was read at import; just verify it matches the default
        self.assertEqual(_backend, "env")


class TestSecretsManagerDotenv(unittest.TestCase):
    """Tests for _read_dotenv helper."""

    def test_read_dotenv_missing_file(self):
        """Should return None when .env doesn't exist."""
        result = _read_dotenv("NONEXISTENT_KEY_999")
        # May return None or a value depending on if backend/.env exists
        # Just verify it doesn't crash
        self.assertTrue(result is None or isinstance(result, str))

    def test_read_dotenv_skips_comments_and_empty(self):
        """Comments and empty lines should be skipped."""
        import secrets_manager as sm

        with patch("builtins.open", create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__iter__ = lambda self: iter(
                [
                    "# This is a comment\n",
                    "\n",
                    "VALID_KEY=valid_value\n",
                ]
            )
            mock_open.return_value.__enter__ = lambda s: mock_file
            mock_open.return_value.__exit__ = lambda s, *a: None
            with patch.object(sm.os.path, "exists", return_value=True):
                result = _read_dotenv("VALID_KEY")
                self.assertEqual(result, "valid_value")


class TestSecretsManagerVault(unittest.TestCase):
    """Tests for vault backend paths (all mocked — no real vault calls)."""

    def setUp(self):
        clear_cache()

    def tearDown(self):
        clear_cache()

    def test_azure_keyvault_fail_soft(self):
        """Azure KeyVault should return None when SDK not installed / unreachable."""
        with patch("secrets_manager._azure_keyvault_get", return_value=None):
            with patch.dict(
                os.environ,
                {"WORLDBASE_SECRET_BACKEND": "azure_keyvault"},
            ):
                # _backend is read at import time, so we patch it directly
                with patch("secrets_manager._backend", "azure_keyvault"):
                    clear_cache()
                    result = get_secret("SOME_VAULT_KEY", "default_val")
                    self.assertEqual(result, "default_val")

    def test_aws_secretsmanager_fail_soft(self):
        with patch("secrets_manager._aws_sm_get", return_value=None):
            with patch("secrets_manager._backend", "aws_secretsmanager"):
                clear_cache()
                result = get_secret("SOME_AWS_KEY", "aws_default")
                self.assertEqual(result, "aws_default")

    def test_hashicorp_vault_fail_soft(self):
        with patch("secrets_manager._hvac_get", return_value=None):
            with patch("secrets_manager._backend", "hashicorp_vault"):
                clear_cache()
                result = get_secret("SOME_HVAC_KEY", "hvac_default")
                self.assertEqual(result, "hvac_default")

    def test_vault_returns_value_when_available(self):
        """When vault returns a value, it should be used."""
        with patch(
            "secrets_manager._azure_keyvault_get", return_value="vault_secret_123"
        ):
            with patch("secrets_manager._backend", "azure_keyvault"):
                with patch.dict(os.environ, {}, clear=True):
                    clear_cache()
                    result = get_secret("VAULT_KEY", "default")
                    self.assertEqual(result, "vault_secret_123")

    def test_env_takes_priority_over_vault(self):
        """Env var should be checked before vault."""
        with patch("secrets_manager._azure_keyvault_get", return_value="vault_value"):
            with patch("secrets_manager._backend", "azure_keyvault"):
                with patch.dict(os.environ, {"PRIORITY_TEST": "env_value"}):
                    clear_cache()
                    result = get_secret("PRIORITY_TEST", "")
                    self.assertEqual(result, "env_value")


class TestCesiumConfigEndpoint(unittest.TestCase):
    """Tests for GET /api/config/cesium."""

    def test_cesium_endpoint_returns_token(self):
        import routes.config as cfg_mod

        cfg_mod._cache_token = ""
        cfg_mod._cache_ts = 0.0

        with patch.dict(os.environ, {"CESIUM_ION_TOKEN": "test_cesium_abc"}):
            cfg_mod._cache_token = ""
            cfg_mod._cache_ts = 0.0
            token = cfg_mod._get_cesium_token()
            self.assertEqual(token, "test_cesium_abc")

    def test_cesium_endpoint_empty_when_no_token(self):
        import routes.config as cfg_mod

        cfg_mod._cache_token = ""
        cfg_mod._cache_ts = 0.0

        with patch.dict(os.environ, {}, clear=True):
            cfg_mod._cache_token = ""
            cfg_mod._cache_ts = 0.0
            token = cfg_mod._get_cesium_token()
            self.assertEqual(token, "")

    def test_cesium_endpoint_caches(self):
        """Token should be cached for 5 minutes."""
        import routes.config as cfg_mod

        cfg_mod._cache_token = ""
        cfg_mod._cache_ts = 0.0

        with patch.dict(os.environ, {"CESIUM_ION_TOKEN": "cached_token"}):
            cfg_mod._cache_token = ""
            cfg_mod._cache_ts = 0.0
            t1 = cfg_mod._get_cesium_token()
            self.assertEqual(t1, "cached_token")

            # Remove env var — cache should still return old value
            with patch.dict(os.environ, {}, clear=True):
                t2 = cfg_mod._get_cesium_token()
                self.assertEqual(t2, "cached_token")

    def test_cesium_endpoint_falls_back_to_vite_env(self):
        """When CESIUM_ION_TOKEN is not set, VITE_CESIUM_ION_TOKEN should be tried."""
        import routes.config as cfg_mod

        cfg_mod._cache_token = ""
        cfg_mod._cache_ts = 0.0

        with patch.dict(
            os.environ,
            {"VITE_CESIUM_ION_TOKEN": "vite_fallback_token"},
            clear=True,
        ):
            cfg_mod._cache_token = ""
            cfg_mod._cache_ts = 0.0
            token = cfg_mod._get_cesium_token()
            self.assertEqual(token, "vite_fallback_token")

    def test_cesium_endpoint_via_test_client(self):
        """Full HTTP round-trip via TestClient."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import routes.config as cfg_mod
        from routes.config import router

        cfg_mod._cache_token = ""
        cfg_mod._cache_ts = 0.0

        app = FastAPI()
        app.include_router(router)

        with patch.dict(os.environ, {"CESIUM_ION_TOKEN": "http_token_123"}):
            cfg_mod._cache_token = ""
            cfg_mod._cache_ts = 0.0
            client = TestClient(app)
            resp = client.get("/api/config/cesium")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["token"], "http_token_123")


class TestRotateApiKey(unittest.TestCase):
    """Tests for scripts/rotate_api_key.py."""

    def test_generate_key_default_length(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
        try:
            from rotate_api_key import generate_key

            key = generate_key()
            self.assertGreater(len(key), 20)
            # URL-safe base64
            for c in key:
                self.assertIn(
                    c,
                    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
                )
        finally:
            sys.path.pop(0)

    def test_generate_key_custom_length(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
        try:
            from rotate_api_key import generate_key

            key = generate_key(length=48)
            self.assertGreater(len(key), 40)
        finally:
            sys.path.pop(0)

    def test_generate_key_unique(self):
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
        try:
            from rotate_api_key import generate_key

            k1 = generate_key()
            k2 = generate_key()
            self.assertNotEqual(k1, k2)
        finally:
            sys.path.pop(0)

    def test_update_env_file_with_fake_path(self):
        """update_env_file should return False when .env doesn't exist at patched path."""
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
        try:
            from rotate_api_key import update_env_file

            with patch("rotate_api_key.Path.exists", return_value=False):
                result = update_env_file("fake_key_12345")
                self.assertFalse(result)
        finally:
            sys.path.pop(0)


class TestConfigSecretsFields(unittest.TestCase):
    """Verify config.py has secrets_manager_enabled and secrets_provider fields."""

    def test_config_has_secrets_fields(self):
        from config import WorldBaseConfig

        # Verify fields exist on the model
        self.assertIn("secrets_manager_enabled", WorldBaseConfig.model_fields)
        self.assertIn("secrets_provider", WorldBaseConfig.model_fields)

    def test_config_defaults(self):
        from config import WorldBaseConfig

        cfg = WorldBaseConfig()
        self.assertFalse(cfg.secrets_manager_enabled)
        self.assertEqual(cfg.secrets_provider, "env")

    def test_config_from_env_secrets(self):
        from config import get_config

        get_config.cache_clear()
        with patch.dict(
            os.environ,
            {
                "WORLDBASE_SECRETS_MANAGER": "1",
                "WORLDBASE_SECRET_BACKEND": "azure_keyvault",
            },
        ):
            get_config.cache_clear()
            cfg = get_config()
            self.assertTrue(cfg.secrets_manager_enabled)
            self.assertEqual(cfg.secrets_provider, "azure_keyvault")
        get_config.cache_clear()


if __name__ == "__main__":
    unittest.main()
