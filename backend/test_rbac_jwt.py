"""Tests for I9 — RBAC + JWT + API Key Scopes + Rotation."""

from __future__ import annotations

import os
import time
import unittest


class TestJWT(unittest.TestCase):
    """JWT encode/decode/refresh."""

    def test_encode_decode_access_token(self):
        from auth.jwt import encode_access_token, decode_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        token = encode_access_token("user1", "operator")
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "user1")
        self.assertEqual(payload["role"], "operator")
        self.assertEqual(payload["type"], "access")

    def test_encode_decode_refresh_token(self):
        from auth.jwt import encode_refresh_token, decode_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        token = encode_refresh_token("user1", "viewer")
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["type"], "refresh")
        self.assertEqual(payload["role"], "viewer")

    def test_decode_invalid_token(self):
        from auth.jwt import decode_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        self.assertIsNone(decode_token("invalid.token.here"))
        self.assertIsNone(decode_token(""))

    def test_decode_wrong_secret(self):
        from auth.jwt import encode_access_token, decode_token

        os.environ["WORLDBASE_JWT_SECRET"] = "secret-a"
        token = encode_access_token("user", "operator")
        os.environ["WORLDBASE_JWT_SECRET"] = "secret-b"
        self.assertIsNone(decode_token(token))

    def test_token_pair(self):
        from auth.jwt import token_pair, decode_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        pair = token_pair("user1", "operator")
        self.assertIn("access_token", pair)
        self.assertIn("refresh_token", pair)
        self.assertEqual(pair["token_type"], "bearer")
        self.assertEqual(pair["expires_in"], 900)
        access = decode_token(pair["access_token"])
        self.assertEqual(access["type"], "access")
        refresh = decode_token(pair["refresh_token"])
        self.assertEqual(refresh["type"], "refresh")

    def test_refresh_access_token(self):
        from auth.jwt import encode_refresh_token, refresh_access_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        refresh = encode_refresh_token("user1", "operator")
        result = refresh_access_token(refresh)
        self.assertIsNotNone(result)
        self.assertIn("access_token", result)
        self.assertIn("refresh_token", result)

    def test_refresh_with_access_token_fails(self):
        from auth.jwt import encode_access_token, refresh_access_token

        os.environ["WORLDBASE_JWT_SECRET"] = "test-secret-key"
        access = encode_access_token("user1", "operator")
        self.assertIsNone(refresh_access_token(access))

    def test_auto_generate_secret(self):
        from auth.jwt import get_jwt_secret

        os.environ.pop("WORLDBASE_JWT_SECRET", None)
        secret = get_jwt_secret()
        self.assertTrue(len(secret) > 20)


class TestRBAC(unittest.TestCase):
    """RBAC middleware."""

    def test_rbac_disabled_by_default(self):
        from middleware.rbac import rbac_enabled

        os.environ.pop("WORLDBASE_RBAC", None)
        self.assertFalse(rbac_enabled())

    def test_rbac_enabled_when_configured(self):
        from middleware.rbac import rbac_enabled

        os.environ["WORLDBASE_RBAC"] = "1"
        self.assertTrue(rbac_enabled())
        os.environ.pop("WORLDBASE_RBAC", None)

    def test_role_hierarchy(self):
        from middleware.rbac import _ROLE_HIERARCHY

        self.assertGreater(_ROLE_HIERARCHY["operator"], _ROLE_HIERARCHY["viewer"])
        self.assertGreater(_ROLE_HIERARCHY["operator"], _ROLE_HIERARCHY["node"])


class TestAuthRoutes(unittest.TestCase):
    """Auth endpoint smoke tests."""

    def test_auth_router_has_routes(self):
        from routes import auth

        paths = [r.path for r in auth.router.routes]
        self.assertIn("/api/auth/token", paths)
        self.assertIn("/api/auth/refresh", paths)
        self.assertIn("/api/auth/rotate", paths)
        self.assertIn("/api/auth/scopes", paths)

    def test_token_request_model(self):
        from routes.auth import TokenRequest

        req = TokenRequest(api_key="test")
        self.assertEqual(req.api_key, "test")

    def test_refresh_request_model(self):
        from routes.auth import RefreshRequest

        req = RefreshRequest(refresh_token="abc")
        self.assertEqual(req.refresh_token, "abc")


class TestConfigRBAC(unittest.TestCase):
    """Config integration."""

    def test_config_rbac_default_off(self):
        os.environ.pop("WORLDBASE_RBAC", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.rbac_enabled)

    def test_config_rbac_enabled(self):
        os.environ["WORLDBASE_RBAC"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.rbac_enabled)
        finally:
            os.environ.pop("WORLDBASE_RBAC", None)


if __name__ == "__main__":
    unittest.main()
