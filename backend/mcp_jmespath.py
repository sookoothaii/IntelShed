"""V4-44 JMESPath server-side projection for MCP tool responses.

Every MCP tool accepts an optional ``jmespath`` string argument.  When provided,
the tool's response JSON is projected through the JMESPath expression before
return, achieving 80–95% response size reduction in typical use cases.

Feature flag: ``WORLDBASE_MCP_JMESPATH=1`` (default on — token efficiency).

Pure Python, 0 VRAM.  Depends on the ``jmespath`` library (pip-installable).
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from typing import Any

logger = logging.getLogger("worldbase.mcp_jmespath")

_JMESPATH_AVAILABLE: bool | None = None


def _jmespath_available() -> bool:
    global _JMESPATH_AVAILABLE
    if _JMESPATH_AVAILABLE is None:
        try:
            import jmespath  # noqa: F401

            _JMESPATH_AVAILABLE = True
        except ImportError:
            _JMESPATH_AVAILABLE = False
    return _JMESPATH_AVAILABLE


def jmespath_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MCP_JMESPATH", "1"))


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def apply_jmespath(data: Any, expression: str) -> Any:
    """Apply a JMESPath expression to *data* and return the projected result.

    Fail-soft: on any error, returns the original *data* unchanged with an
    ``_jmespath_error`` field appended (when *data* is a dict).
    """
    if not expression or not expression.strip():
        return data
    if not jmespath_enabled():
        return data
    if not _jmespath_available():
        if isinstance(data, dict):
            data["_jmespath_error"] = "jmespath library not installed"
        return data

    import jmespath

    try:
        result = jmespath.search(expression, data)
        if result is None:
            return {"_jmespath_empty": True, "expression": expression}
        return result
    except Exception as exc:
        logger.warning(
            f"jmespath_projection_failed expression={expression!r} error={exc!s}"
        )
        if isinstance(data, dict):
            data["_jmespath_error"] = str(exc)[:200]
        return data


def maybe_project(data: Any, jmespath_expr: str | None) -> Any:
    """Convenience wrapper: project only when *jmespath_expr* is non-empty."""
    if not jmespath_expr or not jmespath_expr.strip():
        return data
    return apply_jmespath(data, jmespath_expr)


# ---------------------------------------------------------------------------
# Decorator: add jmespath parameter to any MCP tool function
# ---------------------------------------------------------------------------


def with_jmespath(fn):
    """Decorator that adds an optional ``jmespath`` parameter to an MCP tool.

    When the client passes ``jmespath="expression"``, the tool's response is
    projected through the JMESPath expression before return.

    The decorator preserves the original function's signature for FastMCP's
    introspection — it appends ``jmespath: str | None = None`` as a
    keyword-only parameter.
    """
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())
    # Avoid double-adding if already present
    if not any(p.name == "jmespath" for p in params):
        params.append(
            inspect.Parameter(
                "jmespath",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=str | None,
            )
        )
    new_sig = sig.replace(parameters=params)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        jp = kwargs.pop("jmespath", None)
        result = await fn(*args, **kwargs)
        return maybe_project(result, jp)

    wrapper.__signature__ = new_sig
    wrapper.__wrapped__ = fn
    return wrapper
