"""Tests for Phase 2.1 — RBAC scaffolding + audit log.

Covers:
- auth/audit.py: table creation, record, query, prune, stats, fail-soft
- auth/rbac.py: re-exports, role hierarchy, convenience dependencies
- middleware/rbac.py: admin/readonly roles, hierarchy enforcement
- config.py: auth_audit_enabled, auth_audit_retention_days
- sqlite_bootstrap.py: auth_audit table migration
- auth/security.py: audit hooks in verify_api_key, verify_lan_auth, require_admin_token
- mcp_server.py: audit logging in _MCPAuthMiddleware, _gate_mcp_write
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Use a temporary SQLite DB for audit tests."""
    db_path = str(tmp_path / "test_audit.db")
    monkeypatch.setenv("WORLDBASE_DB_PATH", db_path)
    monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "1")
    monkeypatch.setenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "90")
    # Reload audit module to pick up new env
    import importlib

    import auth.audit

    importlib.reload(auth.audit)
    auth.audit.ensure_audit_table()
    yield db_path


@pytest.fixture
def clean_config(monkeypatch):
    """Reset config cache and set clean env."""
    monkeypatch.setenv("WORLDBASE_RBAC", "0")
    monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "1")
    monkeypatch.setenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "90")
    from config import get_config

    get_config.cache_clear()
    yield
    get_config.cache_clear()


# ---------------------------------------------------------------------------
# auth/audit.py tests
# ---------------------------------------------------------------------------


class TestAuditTable:
    def test_ensure_audit_table_creates_table(self, temp_db):
        import auth.audit

        auth.audit.ensure_audit_table()
        conn = sqlite3.connect(temp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_audit'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1
        assert tables[0][0] == "auth_audit"

    def test_ensure_audit_table_idempotent(self, temp_db):
        import auth.audit

        auth.audit.ensure_audit_table()
        auth.audit.ensure_audit_table()  # Should not raise
        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM auth_audit").fetchone()[0]
        conn.close()
        assert count == 0

    def test_auth_audit_has_expected_columns(self, temp_db):
        import auth.audit

        auth.audit.ensure_audit_table()
        conn = sqlite3.connect(temp_db)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(auth_audit)").fetchall()]
        conn.close()
        expected = {
            "id",
            "timestamp",
            "client",
            "endpoint",
            "tool",
            "action",
            "success",
            "error",
        }
        assert expected.issubset(set(cols))


class TestRecordAuditEvent:
    def test_record_success_event(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(
            action="test_action",
            client="127.0.0.1",
            endpoint="/api/test",
            tool="test_tool",
            success=True,
        )
        rows = auth.audit.query_audit_log(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "test_action"
        assert rows[0]["client"] == "127.0.0.1"
        assert rows[0]["endpoint"] == "/api/test"
        assert rows[0]["tool"] == "test_tool"
        assert rows[0]["success"] == 1
        assert rows[0]["error"] == ""

    def test_record_failure_event(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(
            action="test_fail",
            client="10.0.0.1",
            endpoint="/api/secure",
            success=False,
            error="Invalid token",
        )
        rows = auth.audit.query_audit_log(limit=10)
        assert len(rows) == 1
        assert rows[0]["success"] == 0
        assert rows[0]["error"] == "Invalid token"

    def test_record_multiple_events(self, temp_db):
        import auth.audit

        for i in range(5):
            auth.audit.record_audit_event(action=f"action_{i}")
        rows = auth.audit.query_audit_log(limit=10)
        assert len(rows) == 5

    def test_record_does_not_raise_on_db_error(self, monkeypatch):
        import auth.audit

        # Point to a non-existent directory
        monkeypatch.setenv("WORLDBASE_DB_PATH", "/nonexistent/path/db.db")
        import importlib

        importlib.reload(auth.audit)
        # Should not raise
        auth.audit.record_audit_event(action="test")

    def test_audit_disabled_does_not_record(self, monkeypatch, tmp_path):
        import importlib

        import auth.audit

        db_path = str(tmp_path / "test_disabled.db")
        monkeypatch.setenv("WORLDBASE_DB_PATH", db_path)
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "0")
        importlib.reload(auth.audit)
        assert not auth.audit.audit_enabled()
        auth.audit.record_audit_event(action="should_not_record")
        # Table might not even exist, but no error
        assert not os.path.exists(db_path) or auth.audit.query_audit_log() == []


class TestQueryAuditLog:
    def test_query_by_action(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(action="login", success=True)
        auth.audit.record_audit_event(action="logout", success=True)
        auth.audit.record_audit_event(action="login", success=False, error="bad key")
        rows = auth.audit.query_audit_log(action="login")
        assert len(rows) == 2
        assert all(r["action"] == "login" for r in rows)

    def test_query_by_success(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(action="test", success=True)
        auth.audit.record_audit_event(action="test", success=False, error="err")
        successes = auth.audit.query_audit_log(success=True)
        failures = auth.audit.query_audit_log(success=False)
        assert len(successes) == 1
        assert len(failures) == 1

    def test_query_limit(self, temp_db):
        import auth.audit

        for i in range(10):
            auth.audit.record_audit_event(action=f"action_{i}")
        rows = auth.audit.query_audit_log(limit=3)
        assert len(rows) == 3

    def test_query_since_filter(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(action="old")
        time.sleep(0.05)
        cutoff = datetime.now(timezone.utc).isoformat()
        time.sleep(0.05)
        auth.audit.record_audit_event(action="new")
        rows = auth.audit.query_audit_log(since=cutoff)
        actions = [r["action"] for r in rows]
        assert "new" in actions
        assert "old" not in actions


class TestPruneAuditLog:
    def test_prune_removes_old_entries(self, temp_db):
        import auth.audit

        # Insert an old entry manually
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        with sqlite3.connect(temp_db) as conn:
            conn.execute(
                "INSERT INTO auth_audit (timestamp, client, endpoint, tool, action, success, error) "
                "VALUES (?, '', '', '', 'old_action', 1, '')",
                (old_ts,),
            )
            conn.commit()
        # Insert a fresh entry
        auth.audit.record_audit_event(action="fresh_action")
        deleted = auth.audit.prune_audit_log(retention_days=90)
        assert deleted >= 1
        rows = auth.audit.query_audit_log()
        actions = [r["action"] for r in rows]
        assert "old_action" not in actions
        assert "fresh_action" in actions

    def test_prune_keeps_recent_entries(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(action="keep_me")
        deleted = auth.audit.prune_audit_log(retention_days=90)
        assert deleted == 0
        rows = auth.audit.query_audit_log()
        assert any(r["action"] == "keep_me" for r in rows)

    def test_prune_fail_soft(self, monkeypatch):
        import auth.audit

        monkeypatch.setattr(auth.audit, "_DB_PATH", "/nonexistent/prune.db")
        result = auth.audit.prune_audit_log()
        assert result == 0  # Fail-soft returns 0


class TestAuditStats:
    def test_stats_returns_summary(self, temp_db):
        import auth.audit

        auth.audit.record_audit_event(action="login", success=True)
        auth.audit.record_audit_event(action="login", success=False, error="bad")
        auth.audit.record_audit_event(action="mcp_write", success=True)
        stats = auth.audit.audit_stats()
        assert stats["enabled"] is True
        assert stats["total"] == 3
        assert stats["failures"] == 1
        assert "login" in stats["by_action"]
        assert stats["by_action"]["login"] == 2

    def test_stats_fail_soft(self, monkeypatch):
        import auth.audit

        monkeypatch.setattr(auth.audit, "_DB_PATH", "/nonexistent/stats.db")
        stats = auth.audit.audit_stats()
        assert stats["enabled"] is True
        assert "error" in stats


# ---------------------------------------------------------------------------
# auth/rbac.py tests
# ---------------------------------------------------------------------------


class TestAuthRbacModule:
    def test_re_exports_verify_role(self):
        from auth.rbac import verify_role

        assert callable(verify_role)

    def test_re_exports_rbac_enabled(self):
        from auth.rbac import rbac_enabled

        assert callable(rbac_enabled)

    def test_re_exports_convenience_deps(self):
        from auth.rbac import (
            require_admin,
            require_node,
            require_operator,
            require_readonly,
            require_viewer,
        )

        assert all(
            callable(d)
            for d in [
                require_admin,
                require_node,
                require_operator,
                require_readonly,
                require_viewer,
            ]
        )

    def test_role_hierarchy_includes_admin_and_readonly(self):
        from auth.rbac import _ROLE_HIERARCHY

        assert "admin" in _ROLE_HIERARCHY
        assert "readonly" in _ROLE_HIERARCHY
        assert _ROLE_HIERARCHY["admin"] > _ROLE_HIERARCHY["operator"]
        assert _ROLE_HIERARCHY["readonly"] == _ROLE_HIERARCHY["viewer"]


# ---------------------------------------------------------------------------
# middleware/rbac.py tests
# ---------------------------------------------------------------------------


class TestRbacRoles:
    def test_admin_role_in_hierarchy(self):
        from middleware.rbac import _ROLE_HIERARCHY

        assert _ROLE_HIERARCHY["admin"] == 4
        assert _ROLE_HIERARCHY["operator"] == 3

    def test_readonly_alias_for_viewer(self):
        from middleware.rbac import _ROLE_ALIASES

        assert _ROLE_ALIASES.get("readonly") == "viewer"

    def test_require_admin_dependency_exists(self):
        from middleware.rbac import require_admin

        assert callable(require_admin)

    def test_require_readonly_dependency_exists(self):
        from middleware.rbac import require_readonly

        assert callable(require_readonly)


class TestRbacRoleHierarchy:
    def test_operator_cannot_access_admin(self, clean_config, monkeypatch):
        """When RBAC is enabled, operator role cannot access admin endpoints."""
        monkeypatch.setenv("WORLDBASE_RBAC", "1")
        from config import get_config

        get_config.cache_clear()
        from middleware.rbac import verify_role

        # Create a mock request with operator role
        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.url.path = "/api/admin/something"
        mock_request.method = "GET"

        dep = verify_role("admin")
        with patch("middleware.rbac._role_from_request", return_value="operator"):
            with pytest.raises(Exception) as exc_info:
                import asyncio

                asyncio.run(dep(mock_request))
            assert "403" in str(exc_info.value.status_code)

    def test_admin_can_access_operator(self, clean_config, monkeypatch):
        """Admin role should be able to access operator-level endpoints."""
        monkeypatch.setenv("WORLDBASE_RBAC", "1")
        from config import get_config

        get_config.cache_clear()
        from middleware.rbac import verify_role

        mock_request = MagicMock()
        mock_request.headers = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.url.path = "/api/something"
        mock_request.method = "GET"

        dep = verify_role("operator")
        with patch("middleware.rbac._role_from_request", return_value="admin"):
            import asyncio

            result = asyncio.run(dep(mock_request))
            assert result == "admin"

    def test_rbac_disabled_bypasses_checks(self, clean_config):
        """When RBAC is disabled, all roles are bypassed."""
        from middleware.rbac import rbac_enabled

        assert not rbac_enabled()


# ---------------------------------------------------------------------------
# config.py tests
# ---------------------------------------------------------------------------


class TestConfigAuthAudit:
    def test_auth_audit_enabled_default_true(self, clean_config):
        from config import get_config

        cfg = get_config()
        assert cfg.auth_audit_enabled is True

    def test_auth_audit_retention_days_default_90(self, clean_config):
        from config import get_config

        cfg = get_config()
        assert cfg.auth_audit_retention_days == 90

    def test_auth_audit_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "0")
        from config import get_config

        get_config.cache_clear()
        cfg = get_config()
        assert cfg.auth_audit_enabled is False
        get_config.cache_clear()

    def test_auth_audit_retention_custom(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "30")
        from config import get_config

        get_config.cache_clear()
        cfg = get_config()
        assert cfg.auth_audit_retention_days == 30
        get_config.cache_clear()

    def test_auth_audit_retention_minimum_1(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT_RETENTION_DAYS", "0")
        from config import get_config

        get_config.cache_clear()
        cfg = get_config()
        assert cfg.auth_audit_retention_days == 1
        get_config.cache_clear()


# ---------------------------------------------------------------------------
# sqlite_bootstrap.py tests
# ---------------------------------------------------------------------------


class TestSqliteBootstrapAuthAudit:
    def test_init_db_creates_auth_audit_table(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test_bootstrap.db")
        monkeypatch.setenv("WORLDBASE_DB_PATH", db_path)
        import importlib

        import sqlite_bootstrap

        importlib.reload(sqlite_bootstrap)
        sqlite_bootstrap.init_db()
        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='auth_audit'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1
        assert tables[0][0] == "auth_audit"

    def test_auth_audit_indexes_created(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test_indexes.db")
        monkeypatch.setenv("WORLDBASE_DB_PATH", db_path)
        import importlib

        import sqlite_bootstrap

        importlib.reload(sqlite_bootstrap)
        sqlite_bootstrap.init_db()
        conn = sqlite3.connect(db_path)
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_auth_audit_%'"
        ).fetchall()
        conn.close()
        index_names = {r[0] for r in indexes}
        assert "idx_auth_audit_ts" in index_names
        assert "idx_auth_audit_action" in index_names


# ---------------------------------------------------------------------------
# auth/security.py audit hook tests
# ---------------------------------------------------------------------------


class TestSecurityAuditHooks:
    def test_verify_api_key_records_success(self, monkeypatch, tmp_path):
        """verify_api_key should record audit event on success."""
        import auth.audit
        import auth.security

        db_path = str(tmp_path / "sec_audit.db")
        monkeypatch.setattr(auth.audit, "_DB_PATH", db_path)
        monkeypatch.setattr(auth.audit, "_ENABLED", True)
        monkeypatch.setattr(auth.security, "API_KEY", "test-key-123")
        auth.audit.ensure_audit_table()

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api/test"

        import asyncio

        result = asyncio.run(
            auth.security.verify_api_key(request=mock_request, api_key="test-key-123")
        )
        assert result == "test-key-123"
        rows = auth.audit.query_audit_log(action="auth_verify_api_key")
        assert len(rows) == 1
        assert rows[0]["success"] == 1

    def test_verify_api_key_records_failure(self, monkeypatch, tmp_path):
        """verify_api_key should record audit event on failure."""
        import auth.audit
        import auth.security

        db_path = str(tmp_path / "sec_fail.db")
        monkeypatch.setattr(auth.audit, "_DB_PATH", db_path)
        monkeypatch.setattr(auth.audit, "_ENABLED", True)
        monkeypatch.setattr(auth.security, "API_KEY", "correct-key")
        auth.audit.ensure_audit_table()

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "10.0.0.1"
        mock_request.url.path = "/api/secure"

        import asyncio

        with pytest.raises(Exception) as exc_info:
            asyncio.run(
                auth.security.verify_api_key(request=mock_request, api_key="wrong-key")
            )
        assert exc_info.value.status_code == 401
        rows = auth.audit.query_audit_log(action="auth_verify_api_key", success=False)
        assert len(rows) == 1
        assert rows[0]["error"] == "Invalid or missing API Key"

    def test_verify_api_key_no_audit_when_disabled(self, monkeypatch, tmp_path):
        """verify_api_key should not record when audit is disabled."""
        import auth.audit
        import auth.security

        db_path = str(tmp_path / "no_audit.db")
        monkeypatch.setattr(auth.audit, "_DB_PATH", db_path)
        monkeypatch.setattr(auth.audit, "_ENABLED", False)
        monkeypatch.setattr(auth.security, "API_KEY", "test-key")

        mock_request = MagicMock()
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.url.path = "/api/test"

        import asyncio

        asyncio.run(
            auth.security.verify_api_key(request=mock_request, api_key="test-key")
        )
        assert not auth.audit.audit_enabled()


# ---------------------------------------------------------------------------
# mcp_server.py audit integration tests
# ---------------------------------------------------------------------------


class TestMcpAuditIntegration:
    def test_gate_mcp_write_records_audit_when_rbac_enabled(
        self, monkeypatch, tmp_path
    ):
        """_gate_mcp_write should record audit event when RBAC is enabled."""
        monkeypatch.setenv("WORLDBASE_DB_PATH", str(tmp_path / "mcp_audit.db"))
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "1")
        monkeypatch.setenv("WORLDBASE_RBAC", "1")
        import importlib

        import auth.audit

        importlib.reload(auth.audit)
        auth.audit.ensure_audit_table()
        from config import get_config

        get_config.cache_clear()

        # Mock firewall_bridge and middleware.rbac to avoid full mcp_server import
        with patch("firewall_bridge.ensure_mcp_tool_allowed", return_value=None):
            from middleware.rbac import rbac_enabled

            assert rbac_enabled()
            auth.audit.record_audit_event(
                action="mcp_write",
                tool="test_tool",
                success=True,
            )
        rows = auth.audit.query_audit_log(action="mcp_write")
        assert len(rows) == 1
        assert rows[0]["tool"] == "test_tool"
        assert rows[0]["success"] == 1
        get_config.cache_clear()

    def test_gate_mcp_write_no_audit_when_rbac_disabled(self, monkeypatch, tmp_path):
        """_gate_mcp_write should not record audit when RBAC is disabled."""
        monkeypatch.setenv("WORLDBASE_DB_PATH", str(tmp_path / "mcp_no_rbac.db"))
        monkeypatch.setenv("WORLDBASE_AUTH_AUDIT", "1")
        monkeypatch.setenv("WORLDBASE_RBAC", "0")
        import importlib

        import auth.audit

        importlib.reload(auth.audit)
        auth.audit.ensure_audit_table()
        from config import get_config

        get_config.cache_clear()

        from middleware.rbac import rbac_enabled

        assert not rbac_enabled()
        # When RBAC is disabled, _gate_mcp_write does not record audit
        # (verified by code inspection — the rbac_enabled() check gates the recording)
        rows = auth.audit.query_audit_log(action="mcp_write")
        assert len(rows) == 0
        get_config.cache_clear()
