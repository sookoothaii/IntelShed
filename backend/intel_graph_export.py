"""Export operator FtM subgraph snapshot to disk (Track 3+ Sprint 2)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "intel_subgraph_latest.json"


def export_path() -> Path:
    raw = os.getenv("WORLDBASE_INTEL_SUBGRAPH_EXPORT_PATH", "").strip()
    return Path(raw) if raw else _DEFAULT_PATH


def enabled() -> bool:
    return os.getenv("WORLDBASE_INTEL_SUBGRAPH_EXPORT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def export_operator_subgraph(
    *,
    hops: int | None = None,
    window_hours: int = 24,
    write_disk: bool = True,
) -> dict[str, Any]:
    """Build operator subgraph and optionally persist JSON for Pi/offline use."""
    import intel_subgraph

    sg = intel_subgraph.build_subgraph(hops=hops, window_hours=window_hours)
    payload: dict[str, Any] = {
        **sg,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "export_version": 1,
    }
    if write_disk and enabled():
        path = export_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        payload["export_path"] = str(path)
    return payload


def read_latest_export() -> dict[str, Any] | None:
    path = export_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compact_for_pull(
    subgraph: dict[str, Any] | None = None,
    *,
    max_nodes: int = 8,
    max_edges: int = 10,
    window_hours: int = 24,
) -> dict[str, Any]:
    """Trim operator subgraph for Pi pull payload (offline graph hint)."""
    payload = subgraph
    if payload is None:
        payload = read_latest_export()
    if not payload:
        try:
            import intel_subgraph

            payload = intel_subgraph.build_subgraph(window_hours=window_hours)
        except Exception:
            return {"available": False, "reason": "subgraph build error"}

    if not payload.get("available"):
        return {
            "available": False,
            "reason": payload.get("reason") or payload.get("error"),
        }

    nodes = []
    for node in (payload.get("nodes") or [])[:max_nodes]:
        nodes.append(
            {
                "id": node.get("id"),
                "caption": str(node.get("caption") or "")[:80],
                "schema": node.get("schema"),
                "datasets": (node.get("datasets") or [])[:3],
            }
        )
    edges = []
    for edge in (payload.get("edges") or [])[:max_edges]:
        edges.append(
            {
                "kind": edge.get("kind"),
                "dataset": edge.get("dataset"),
                "source_id": edge.get("source_id"),
                "target_id": edge.get("target_id"),
            }
        )
    return {
        "available": True,
        "node_count": int(payload.get("node_count") or len(payload.get("nodes") or [])),
        "edge_count": int(payload.get("edge_count") or len(payload.get("edges") or [])),
        "hops": payload.get("hops"),
        "exported_at": payload.get("exported_at"),
        "nodes": nodes,
        "edges": edges,
    }


from fastapi import APIRouter, Depends, HTTPException, Query  # noqa: E402

from auth.security import verify_lan_auth  # noqa: E402

router = APIRouter(prefix="/api/intel/subgraph", tags=["intel"])


@router.post("/export")
async def subgraph_export(
    hops: int | None = Query(None, ge=1, le=3),
    window_hours: int = Query(24, ge=1, le=168),
    _auth: str | None = Depends(verify_lan_auth),
):
    if not enabled():
        raise HTTPException(status_code=503, detail="subgraph export disabled")
    try:
        return export_operator_subgraph(
            hops=hops, window_hours=window_hours, write_disk=True
        )
    except Exception as exc:
        logger.exception("subgraph export failed")
        raise HTTPException(status_code=503, detail="subgraph export failed") from exc


@router.get("/export/latest")
async def subgraph_export_latest():
    payload = read_latest_export()
    if not payload:
        raise HTTPException(status_code=404, detail="no subgraph export on disk")
    return payload
