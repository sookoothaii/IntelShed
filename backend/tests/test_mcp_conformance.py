"""Tests for MCP protocol conformance (E-06).

Covers:
- Tool annotations (readOnlyHint, destructiveHint, idempotentHint)
- Protocol version checking
- Output budget enforcement
- Conformance disabled by default
- get_conformance_status
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import mcp_conformance
from mcp_conformance import (
    MCP_PROTOCOL_VERSION,
    OutputBudgetExceeded,
    check_protocol_version,
    conformance_enabled,
    enforce_output_budget,
    get_conformance_status,
    get_tool_annotations,
    all_tool_annotations,
)


# ---------------------------------------------------------------------------
# Tool annotations
# ---------------------------------------------------------------------------


class TestToolAnnotations:
    def test_read_only_tools_have_read_only_hint(self):
        for tool in [
            "worldbase_health",
            "worldbase_briefing_latest",
            "worldbase_nodes",
            "worldbase_situations",
            "worldbase_entity_search",
        ]:
            ann = get_tool_annotations(tool)
            assert ann["readOnlyHint"] is True, f"{tool} should be read-only"
            assert ann["destructiveHint"] is False, f"{tool} should not be destructive"

    def test_write_tools_have_write_hint(self):
        ann = get_tool_annotations("worldbase_briefing_generate")
        assert ann["readOnlyHint"] is False
        assert ann["destructiveHint"] is False

    def test_globe_tools_are_not_read_only(self):
        for tool in ["worldbase_globe_fly_to", "worldbase_globe_toggle_layer"]:
            ann = get_tool_annotations(tool)
            assert ann["readOnlyHint"] is False

    def test_unknown_tool_defaults_to_read_only(self):
        ann = get_tool_annotations("worldbase_nonexistent_tool")
        assert ann["readOnlyHint"] is True
        assert ann["destructiveHint"] is False

    def test_all_annotations_have_three_keys(self):
        annotations = all_tool_annotations()
        for tool, ann in annotations.items():
            assert "readOnlyHint" in ann, f"{tool} missing readOnlyHint"
            assert "destructiveHint" in ann, f"{tool} missing destructiveHint"
            assert "idempotentHint" in ann, f"{tool} missing idempotentHint"

    def test_annotation_count_matches_tools(self):
        annotations = all_tool_annotations()
        # Should have annotations for all 28+ tools
        assert len(annotations) >= 25


# ---------------------------------------------------------------------------
# Protocol version
# ---------------------------------------------------------------------------


class TestProtocolVersion:
    def test_supported_version(self):
        result = check_protocol_version(MCP_PROTOCOL_VERSION)
        assert result["supported"] is True
        assert result["negotiated"] == MCP_PROTOCOL_VERSION

    def test_unsupported_version(self):
        result = check_protocol_version("2099-01-01")
        assert result["supported"] is False
        assert result["negotiated"] == MCP_PROTOCOL_VERSION

    def test_none_version_uses_server_default(self):
        result = check_protocol_version(None)
        assert result["supported"] is True
        assert result["negotiated"] == MCP_PROTOCOL_VERSION
        assert result["client_version"] is None

    def test_supported_versions_list(self):
        assert MCP_PROTOCOL_VERSION in mcp_conformance._SUPPORTED_VERSIONS
        assert len(mcp_conformance._SUPPORTED_VERSIONS) >= 3


# ---------------------------------------------------------------------------
# Output budget
# ---------------------------------------------------------------------------


class TestOutputBudget:
    def test_disabled_does_not_check(self, monkeypatch):
        monkeypatch.delenv("WORLDBASE_MCP_CONFORMANCE", raising=False)
        large = {"data": "x" * 10_000_000}
        # Should not raise — conformance disabled
        result = enforce_output_budget("worldbase_chat", large)
        assert result is large

    def test_enforces_budget_when_enabled(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_MCP_CONFORMANCE", "1")
        monkeypatch.setenv("WORLDBASE_MCP_OUTPUT_BUDGET_BYTES", "100")
        small = {"ok": True}
        result = enforce_output_budget("worldbase_health", small)
        assert result is small

    def test_raises_on_oversized(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_MCP_CONFORMANCE", "1")
        large = {"data": "x" * 1000}
        with patch.object(mcp_conformance, "_DEFAULT_OUTPUT_BUDGET", 50):
            with pytest.raises(OutputBudgetExceeded) as exc:
                enforce_output_budget("worldbase_chat", large)
        assert exc.value.tool == "worldbase_chat"
        assert exc.value.size > 50
        assert exc.value.budget == 50

    def test_custom_budget(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_MCP_CONFORMANCE", "1")
        data = {"x": "y"}
        result = enforce_output_budget("worldbase_health", data, budget=10_000)
        assert result is data


# ---------------------------------------------------------------------------
# Conformance status
# ---------------------------------------------------------------------------


class TestConformanceStatus:
    def test_status_structure(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_MCP_CONFORMANCE", "1")
        status = get_conformance_status()
        assert status["enabled"] is True
        assert status["protocol_version"] == MCP_PROTOCOL_VERSION
        assert "supported_versions" in status
        assert "output_budget_bytes" in status
        assert status["tool_count"] >= 25
        assert isinstance(status["tools_with_annotations"], list)

    def test_status_disabled(self, monkeypatch):
        monkeypatch.delenv("WORLDBASE_MCP_CONFORMANCE", raising=False)
        status = get_conformance_status()
        assert status["enabled"] is False


# ---------------------------------------------------------------------------
# Enabled / disabled
# ---------------------------------------------------------------------------


class TestConformanceEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("WORLDBASE_MCP_CONFORMANCE", raising=False)
        assert not conformance_enabled()

    def test_enabled_when_set(self, monkeypatch):
        monkeypatch.setenv("WORLDBASE_MCP_CONFORMANCE", "1")
        assert conformance_enabled()
