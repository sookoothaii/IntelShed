"""RBAC re-export from middleware/rbac.py.

This module provides a stable import path under ``auth/`` for role constants
and the ``require_role`` dependency factory.  The implementation lives in
``middleware/rbac.py`` to avoid circular imports (middleware depends on
``auth.security`` and ``auth.jwt``).

Roles:
    - admin:     full access including admin endpoints
    - operator:  full access (all endpoints except admin)
    - viewer:    read-only (GET only)
    - readonly:  alias for viewer
    - node:      Pi ingest + pull only (scoped to /api/node/*)

When WORLDBASE_RBAC=0 (default), all RBAC checks are bypassed.
"""

from __future__ import annotations

from middleware.rbac import (
    Role,
    _ROLE_HIERARCHY,
    require_admin,
    require_node,
    require_operator,
    require_readonly,
    require_viewer,
    rbac_enabled,
    verify_role,
)

__all__ = [
    "Role",
    "rbac_enabled",
    "verify_role",
    "require_operator",
    "require_viewer",
    "require_node",
    "require_admin",
    "require_readonly",
    "_ROLE_HIERARCHY",
]
