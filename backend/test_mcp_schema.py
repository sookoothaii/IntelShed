"""Tests for V4-44 MCP outputSchema + JMESPath projection.

Tests:
- mcp_schema: output schema generation, describe_tool, list_tool_names
- mcp_jmespath: projection correctness, fail-soft, decorator behavior
- Integration: jmespath parameter on tools, output schema patching
"""

import asyncio
import os
import sys
from unittest.mock import patch


# Ensure backend is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# mcp_schema tests
# ---------------------------------------------------------------------------


class TestMcpSchema:
    def test_output_schema_enabled_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_MCP_OUTPUT_SCHEMA", None)
            import mcp_schema

            assert mcp_schema.output_schema_enabled() is True

    def test_output_schema_disabled(self):
        with patch.dict(os.environ, {"WORLDBASE_MCP_OUTPUT_SCHEMA": "0"}):
            import mcp_schema

            assert mcp_schema.output_schema_enabled() is False
            assert mcp_schema.get_output_schema("worldbase_health") is None

    def test_get_output_schema_health(self):
        import mcp_schema

        schema = mcp_schema.get_output_schema("worldbase_health")
        assert schema is not None
        assert schema["type"] == "object"
        assert "status" in schema["properties"]
        assert "time" in schema["properties"]
        assert "ftm_ready" in schema["properties"]

    def test_get_output_schema_briefing_latest(self):
        import mcp_schema

        schema = mcp_schema.get_output_schema("worldbase_briefing_latest")
        assert schema is not None
        assert "text_preview" in schema["properties"]
        assert "text_truncated" in schema["properties"]

    def test_get_output_schema_unknown_tool(self):
        import mcp_schema

        assert mcp_schema.get_output_schema("nonexistent_tool") is None

    def test_all_output_schemas(self):
        import mcp_schema

        schemas = mcp_schema.all_output_schemas()
        assert "worldbase_health" in schemas
        assert "worldbase_briefing_latest" in schemas
        assert "worldbase_chat" in schemas
        assert len(schemas) >= 15

    def test_list_tool_names(self):
        import mcp_schema

        names = mcp_schema.list_tool_names()
        assert "worldbase_health" in names
        assert len(names) >= 15
        # Should be sorted
        assert names == sorted(names)

    def test_describe_tool_known(self):
        import mcp_schema

        result = mcp_schema.describe_tool("worldbase_health")
        assert result["tool"] == "worldbase_health"
        assert result["short_name"] == "health"
        assert result["outputSchema"] is not None
        assert result["jmespath_supported"] is True

    def test_describe_tool_unknown(self):
        import mcp_schema

        result = mcp_schema.describe_tool("nonexistent")
        assert result["tool"] == "nonexistent"
        assert result["outputSchema"] is None


# ---------------------------------------------------------------------------
# mcp_jmespath tests
# ---------------------------------------------------------------------------


class TestMcpJmespath:
    def test_jmespath_enabled_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_MCP_JMESPATH", None)
            import mcp_jmespath

            assert mcp_jmespath.jmespath_enabled() is True

    def test_jmespath_disabled(self):
        with patch.dict(os.environ, {"WORLDBASE_MCP_JMESPATH": "0"}):
            import mcp_jmespath

            assert mcp_jmespath.jmespath_enabled() is False
            # When disabled, projection is a no-op
            data = {"a": 1, "b": 2}
            assert mcp_jmespath.apply_jmespath(data, "a") == data

    def test_apply_jmespath_simple(self):
        import mcp_jmespath

        data = {"a": 1, "b": 2, "c": 3}
        result = mcp_jmespath.apply_jmespath(data, "a")
        assert result == 1

    def test_apply_jmespath_nested(self):
        import mcp_jmespath

        data = {"briefing": {"insights": [{"title": "A"}, {"title": "B"}]}}
        result = mcp_jmespath.apply_jmespath(data, "briefing.insights[*].title")
        assert result == ["A", "B"]

    def test_apply_jmespath_array(self):
        import mcp_jmespath

        data = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
        result = mcp_jmespath.apply_jmespath(data, "items[*].id")
        assert result == [1, 2, 3]

    def test_apply_jmespath_empty_expression(self):
        import mcp_jmespath

        data = {"a": 1}
        assert mcp_jmespath.apply_jmespath(data, "") == data
        assert mcp_jmespath.apply_jmespath(data, "   ") == data

    def test_apply_jmespath_none_result(self):
        import mcp_jmespath

        data = {"a": 1}
        result = mcp_jmespath.apply_jmespath(data, "nonexistent")
        assert isinstance(result, dict)
        assert result["_jmespath_empty"] is True

    def test_apply_jmespath_invalid_expression(self):
        import mcp_jmespath

        data = {"a": 1}
        result = mcp_jmespath.apply_jmespath(data, "invalid!!syntax")
        # Fail-soft: returns original data with error
        assert isinstance(result, dict)
        assert "a" in result  # original data preserved

    def test_maybe_project_no_expression(self):
        import mcp_jmespath

        data = {"a": 1}
        assert mcp_jmespath.maybe_project(data, None) == data
        assert mcp_jmespath.maybe_project(data, "") == data

    def test_maybe_project_with_expression(self):
        import mcp_jmespath

        data = {"a": 42, "b": "hello"}
        assert mcp_jmespath.maybe_project(data, "a") == 42

    def test_with_jmespath_decorator_adds_param(self):
        import mcp_jmespath

        @mcp_jmespath.with_jmespath
        async def my_tool(x: int) -> dict:
            return {"value": x, "extra": "noise"}

        import inspect

        sig = inspect.signature(my_tool)
        assert "jmespath" in sig.parameters
        assert sig.parameters["jmespath"].default is None

    def test_with_jmespath_decorator_applies_projection(self):
        import mcp_jmespath

        @mcp_jmespath.with_jmespath
        async def my_tool(x: int) -> dict:
            return {"value": x, "extra": "noise", "list": [1, 2, 3]}

        # Without jmespath
        result = asyncio.run(my_tool(42))
        assert result == {"value": 42, "extra": "noise", "list": [1, 2, 3]}

        # With jmespath projection
        result = asyncio.run(my_tool(42, jmespath="value"))
        assert result == 42

        # With jmespath projection (list)
        result = asyncio.run(my_tool(42, jmespath="list[-1]"))
        assert result == 3

    def test_with_jmespath_decorator_preserves_name(self):
        import mcp_jmespath

        @mcp_jmespath.with_jmespath
        async def my_special_tool() -> dict:
            return {"ok": True}

        assert my_special_tool.__name__ == "my_special_tool"
        assert hasattr(my_special_tool, "__wrapped__")


# ---------------------------------------------------------------------------
# Integration: mcp_server tools have jmespath parameter
# ---------------------------------------------------------------------------


class TestMcpServerIntegration:
    def test_all_tools_have_jmespath_in_schema(self):
        """Verify that the with_jmespath decorator was applied to all tools."""
        import inspect

        # Import mcp_server to trigger tool registration
        import mcp_server

        # Check that key tool functions have __wrapped__ (set by with_jmespath)
        tool_funcs = [
            mcp_server.worldbase_health,
            mcp_server.worldbase_briefing_latest,
            mcp_server.worldbase_nodes,
            mcp_server.worldbase_situations,
            mcp_server.worldbase_fusion_hotspots,
            mcp_server.worldbase_feed_sample,
            mcp_server.worldbase_feed_allowlist,
            mcp_server.worldbase_feed_status,
            mcp_server.worldbase_entity_search,
            mcp_server.worldbase_describe_tool,
            mcp_server.worldbase_list_tools,
        ]

        for fn in tool_funcs:
            # The with_jmespath decorator sets __wrapped__
            assert hasattr(fn, "__wrapped__"), f"{fn.__name__} missing __wrapped__"

            # Verify jmespath is in the signature
            sig = inspect.signature(fn)
            assert "jmespath" in sig.parameters, f"{fn.__name__} missing jmespath param"

    def test_describe_tool_meta_tool(self):
        """Test the describe_tool meta-tool returns schema info."""
        import mcp_server

        result = asyncio.run(
            mcp_server.worldbase_describe_tool.__wrapped__("worldbase_health")
        )
        assert result["tool"] == "worldbase_health"
        assert result["outputSchema"] is not None
        assert result["jmespath_supported"] is True

    def test_list_tools_meta_tool(self):
        """Test the list_tools meta-tool returns all tools."""
        import mcp_server

        result = asyncio.run(mcp_server.worldbase_list_tools.__wrapped__())
        assert "count" in result
        assert result["count"] >= 15
        assert "tools" in result
        # Each tool entry should have name, output_schema_available, jmespath_supported
        for t in result["tools"]:
            assert "name" in t
            assert "output_schema_available" in t
            assert "jmespath_supported" in t

    def test_jmespath_projection_on_health_tool(self):
        """Test that jmespath projection works end-to-end on a real tool."""
        import mcp_server

        # Call health tool with jmespath projection
        result = asyncio.run(mcp_server.worldbase_health(jmespath="status"))
        assert result == "ok"

    def test_output_schema_patch_function_exists(self):
        """Verify _patch_output_schemas function exists and is callable."""
        import mcp_server

        assert callable(mcp_server._patch_output_schemas)
