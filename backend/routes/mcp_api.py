"""MCP quota + conformance monitoring endpoints (E-06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/quota")
async def mcp_quota_status(_auth: str | None = Depends(verify_lan_auth)):
    """MCP per-tool quota dashboard: daily/hourly usage, limits, exceeded tools."""
    import mcp_quota

    return mcp_quota.get_quota_status()


@router.get("/quota/{tool}")
async def mcp_quota_tool(tool: str, _auth: str | None = Depends(verify_lan_auth)):
    """Usage for a specific MCP tool (daily + hourly)."""
    import mcp_quota

    return mcp_quota.get_tool_usage(tool)


@router.get("/quota/alerts")
async def mcp_quota_alerts(_auth: str | None = Depends(verify_lan_auth)):
    """Check for 80% threshold + exceeded MCP quota alerts."""
    import mcp_quota

    return {"alerts": mcp_quota.check_alerts()}


@router.get("/conformance")
async def mcp_conformance_status(_auth: str | None = Depends(verify_lan_auth)):
    """MCP protocol conformance: version, tool annotations, output budget."""
    import mcp_conformance

    return mcp_conformance.get_conformance_status()


@router.get("/conformance/annotations")
async def mcp_tool_annotations(_auth: str | None = Depends(verify_lan_auth)):
    """All MCP tool annotations (readOnlyHint, destructiveHint, idempotentHint)."""
    import mcp_conformance

    return {"annotations": mcp_conformance.all_tool_annotations()}


@router.get("/conformance/protocol")
async def mcp_protocol_version(_auth: str | None = Depends(verify_lan_auth)):
    """MCP protocol version info and supported versions."""
    import mcp_conformance

    return {
        "protocol_version": mcp_conformance.MCP_PROTOCOL_VERSION,
        "supported_versions": mcp_conformance._SUPPORTED_VERSIONS,
    }
