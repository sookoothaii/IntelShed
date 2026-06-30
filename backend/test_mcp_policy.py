"""Tests for MCP per-tool RBAC policy (Phase 4.4).

Covers:
- Default policy dict lookups
- Env overrides (WORLDBASE_MCP_POLICY_<tool>)
- _gate_mcp_tool enforcement: readonly can read, blocked from write
- _gate_mcp_tool with policy disabled: no enforcement
- _role_from_scope extraction (API key, node token, JWT)
- Fail-soft behavior
- Backward compat: _gate_mcp_write alias
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_mcp_role():
    """Reset the MCP role context var to None."""
    import mcp_server

    mcp_server._mcp_role.set(None)


def _set_mcp_role(role: str | None):
    """Set the MCP role context var."""
    import mcp_server

    mcp_server._mcp_role.set(role)


# ---------------------------------------------------------------------------
# Policy lookup tests
# ---------------------------------------------------------------------------


class TestPolicyLookup(unittest.TestCase):
    def test_default_read_tools_require_readonly(self):
        from mcp_server import _get_mcp_tool_required_role

        self.assertEqual(_get_mcp_tool_required_role("worldbase_health"), "readonly")
        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_briefing_latest"), "readonly"
        )
        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_feed_sample"), "readonly"
        )
        self.assertEqual(_get_mcp_tool_required_role("worldbase_nodes"), "readonly")
        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_situations"), "readonly"
        )

    def test_default_write_tools_require_operator(self):
        from mcp_server import _get_mcp_tool_required_role

        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_briefing_generate"), "operator"
        )
        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_globe_fly_to"), "operator"
        )
        self.assertEqual(
            _get_mcp_tool_required_role("worldbase_globe_toggle_layer"), "operator"
        )

    def test_unknown_tool_defaults_to_none(self):
        from mcp_server import _get_mcp_tool_required_role

        self.assertEqual(_get_mcp_tool_required_role("worldbase_nonexistent"), "none")

    def test_env_override_takes_precedence(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_MCP_POLICY_briefing_generate": "readonly"},
            clear=True,
        ):
            from mcp_server import _get_mcp_tool_required_role

            self.assertEqual(
                _get_mcp_tool_required_role("worldbase_briefing_generate"), "readonly"
            )

    def test_env_override_invalid_value_falls_back_to_default(self):
        with patch.dict(
            os.environ,
            {"WORLDBASE_MCP_POLICY_briefing_generate": "superuser"},
            clear=True,
        ):
            from mcp_server import _get_mcp_tool_required_role

            self.assertEqual(
                _get_mcp_tool_required_role("worldbase_briefing_generate"), "operator"
            )

    def test_env_override_none_disables_check(self):
        with patch.dict(
            os.environ, {"WORLDBASE_MCP_POLICY_health": "none"}, clear=True
        ):
            from mcp_server import _get_mcp_tool_required_role

            self.assertEqual(_get_mcp_tool_required_role("worldbase_health"), "none")

    def test_tool_short_name_strips_prefix(self):
        from mcp_server import _tool_short_name

        self.assertEqual(_tool_short_name("worldbase_health"), "health")
        self.assertEqual(_tool_short_name("health"), "health")
        self.assertEqual(
            _tool_short_name("worldbase_briefing_generate"), "briefing_generate"
        )


# ---------------------------------------------------------------------------
# _gate_mcp_tool enforcement tests
# ---------------------------------------------------------------------------


class TestGateMcpTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _reset_mcp_role()

    def tearDown(self):
        _reset_mcp_role()

    async def test_readonly_can_call_read_tool(self):
        """A readonly token can call worldbase_feed_sample (read tool)."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            from mcp_server import _gate_mcp_tool

            await _gate_mcp_tool(
                "worldbase_feed_sample", {"feed_id": "gdacs"}, write=False
            )

    async def test_readonly_blocked_from_write_tool(self):
        """A readonly token is blocked from worldbase_briefing_generate."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                with self.assertRaises(PermissionError) as ctx:
                    await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)
                self.assertIn("requires role 'operator'", str(ctx.exception))

    async def test_operator_can_call_write_tool(self):
        """An operator token can call worldbase_briefing_generate."""
        _set_mcp_role("operator")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)

    async def test_admin_can_call_any_tool(self):
        """Admin role can call any tool."""
        _set_mcp_role("admin")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)
                await _gate_mcp_tool("worldbase_health", {}, write=False)

    async def test_node_role_blocked_from_operator_tool(self):
        """Node role (level 1) cannot call operator-level tools."""
        _set_mcp_role("node")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                with self.assertRaises(PermissionError) as ctx:
                    await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)
                self.assertIn("requires role 'operator'", str(ctx.exception))

    async def test_node_can_call_readonly_tool(self):
        """Node role (level 1) can call readonly-level tools."""
        _set_mcp_role("node")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            from mcp_server import _gate_mcp_tool

            await _gate_mcp_tool("worldbase_health", {}, write=False)

    async def test_policy_disabled_no_enforcement(self):
        """When policy is disabled, readonly can call write tools (no RBAC check)."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=False):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)

    async def test_none_role_no_enforcement(self):
        """When role is None (unauthenticated), policy allows access (auth middleware handles auth)."""
        _set_mcp_role(None)
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)

    async def test_env_override_lowers_requirement(self):
        """Env override can lower a write tool's requirement to readonly."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch.dict(
                os.environ,
                {"WORLDBASE_MCP_POLICY_briefing_generate": "readonly"},
                clear=True,
            ):
                with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                    from mcp_server import _gate_mcp_tool

                    await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)

    async def test_env_override_raises_requirement(self):
        """Env override can raise a read tool's requirement to operator."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch.dict(
                os.environ, {"WORLDBASE_MCP_POLICY_health": "operator"}, clear=True
            ):
                from mcp_server import _gate_mcp_tool

                with self.assertRaises(PermissionError) as ctx:
                    await _gate_mcp_tool("worldbase_health", {}, write=False)
                self.assertIn("requires role 'operator'", str(ctx.exception))

    async def test_none_required_allows_any_role(self):
        """When required role is 'none', any role is allowed."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", return_value=True):
            with patch.dict(os.environ, {"WORLDBASE_MCP_POLICY_HEALTH": "none"}):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_health", {}, write=False)

    async def test_backward_compat_alias_exists(self):
        """_gate_mcp_write should still exist as an alias."""
        import mcp_server

        self.assertTrue(hasattr(mcp_server, "_gate_mcp_write"))
        self.assertIs(mcp_server._gate_mcp_write, mcp_server._gate_mcp_tool)

    async def test_fail_soft_on_exception(self):
        """If policy check throws unexpectedly, tool call should not be blocked."""
        _set_mcp_role("readonly")
        with patch("mcp_server.mcp_policy_enabled", side_effect=Exception("boom")):
            with patch("firewall_bridge.ensure_mcp_tool_allowed", new=AsyncMock()):
                from mcp_server import _gate_mcp_tool

                await _gate_mcp_tool("worldbase_briefing_generate", {}, write=True)


# ---------------------------------------------------------------------------
# _role_from_scope tests
# ---------------------------------------------------------------------------


class TestRoleFromScope(unittest.TestCase):
    def test_api_key_returns_operator(self):
        with patch("mcp_server.API_KEY", "test-key-123"):
            from mcp_server import _role_from_scope

            scope = {
                "type": "http",
                "headers": [
                    (b"x-api-key", b"test-key-123"),
                ],
            }
            self.assertEqual(_role_from_scope(scope), "operator")

    def test_node_token_returns_node(self):
        with patch("mcp_server.INGEST_TOKEN", "node-token-456"):
            from mcp_server import _role_from_scope

            scope = {
                "type": "http",
                "headers": [
                    (b"x-node-token", b"node-token-456"),
                ],
            }
            self.assertEqual(_role_from_scope(scope), "node")

    def test_no_credentials_returns_none(self):
        from mcp_server import _role_from_scope

        scope = {
            "type": "http",
            "headers": [],
        }
        self.assertIsNone(_role_from_scope(scope))

    def test_wrong_api_key_returns_none(self):
        with patch("mcp_server.API_KEY", "correct-key"):
            from mcp_server import _role_from_scope

            scope = {
                "type": "http",
                "headers": [
                    (b"x-api-key", b"wrong-key"),
                ],
            }
            self.assertIsNone(_role_from_scope(scope))

    def test_jwt_bearer_returns_role(self):
        from mcp_server import _role_from_scope

        fake_payload = {"type": "access", "role": "viewer"}
        with patch("auth.jwt.decode_token", return_value=fake_payload):
            scope = {
                "type": "http",
                "headers": [
                    (b"authorization", b"Bearer fake.jwt.token"),
                ],
            }
            self.assertEqual(_role_from_scope(scope), "viewer")

    def test_jwt_bearer_admin_role(self):
        from mcp_server import _role_from_scope

        fake_payload = {"type": "access", "role": "admin"}
        with patch("auth.jwt.decode_token", return_value=fake_payload):
            scope = {
                "type": "http",
                "headers": [
                    (b"authorization", b"Bearer fake.jwt.token"),
                ],
            }
            self.assertEqual(_role_from_scope(scope), "admin")

    def test_jwt_invalid_token_returns_none(self):
        from mcp_server import _role_from_scope

        with patch("auth.jwt.decode_token", return_value=None):
            scope = {
                "type": "http",
                "headers": [
                    (b"authorization", b"Bearer invalid.token"),
                ],
            }
            self.assertIsNone(_role_from_scope(scope))


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestMcpPolicyConfig(unittest.TestCase):
    def test_config_default_off(self):
        old = os.environ.pop("WORLDBASE_MCP_POLICY", None)
        try:
            from config import get_config

            get_config.cache_clear()
            cfg = get_config()
            self.assertFalse(cfg.mcp_policy_enabled)
        finally:
            if old is not None:
                os.environ["WORLDBASE_MCP_POLICY"] = old
            from config import get_config

            get_config.cache_clear()

    def test_config_enabled_via_env(self):
        with patch.dict(os.environ, {"WORLDBASE_MCP_POLICY": "1"}):
            from config import get_config

            get_config.cache_clear()
            cfg = get_config()
            self.assertTrue(cfg.mcp_policy_enabled)
            get_config.cache_clear()

    def test_mcp_policy_enabled_function(self):
        with patch.dict(os.environ, {"WORLDBASE_MCP_POLICY": "1"}):
            from config import get_config

            get_config.cache_clear()
            import mcp_server

            self.assertTrue(mcp_server.mcp_policy_enabled())
            get_config.cache_clear()

    def test_mcp_policy_disabled_function(self):
        with patch.dict(os.environ, {"WORLDBASE_MCP_POLICY": "0"}):
            from config import get_config

            get_config.cache_clear()
            import mcp_server

            self.assertFalse(mcp_server.mcp_policy_enabled())
            get_config.cache_clear()


if __name__ == "__main__":
    unittest.main()
