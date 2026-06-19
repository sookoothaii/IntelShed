"""Connector registry API — manifest catalog + runtime cache overlay."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

import connector_registry

router = APIRouter(prefix="/api/connectors", tags=["connectors"])


@router.get("")
async def list_connectors(include_unlisted: bool = Query(True, description="Include feed_cache keys not in catalog")):
    """Connector manifest with optional live cache metadata."""
    return connector_registry.connectors_snapshot(include_unlisted=include_unlisted)


@router.get("/catalog")
async def connector_catalog():
    """Static connector definitions only (no SQLite reads)."""
    return connector_registry.export_manifest(include_runtime=False)


@router.get("/export")
async def export_connectors(
    format: str = Query("json", pattern="^(json|yaml)$"),
    runtime: bool = Query(False, description="Merge feed_cache runtime fields"),
):
    """Export manifest for scripts, CI, or community packaging."""
    if format == "yaml":
        body = connector_registry.export_manifest_yaml(include_runtime=runtime)
        return PlainTextResponse(body, media_type="text/yaml; charset=utf-8")
    return connector_registry.export_manifest(include_runtime=runtime)
