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


def compact_delta_for_pull(
    since: str | None = None,
    *,
    max_nodes: int = 20,
    max_edges: int = 30,
) -> dict[str, Any]:
    """Return only entities/edges created or modified after *since* timestamp.

    Delta format (payload_version 3):
        {
            "available": true,
            "delta": true,
            "since": "...",
            "as_of": "...",
            "nodes_added": [...],
            "edges_added": [...],
            "node_count": N,
            "edge_count": M,
        }

    When *since* is None or older than 7 days, falls back to full
    :func:`compact_for_pull`.
    """
    if not since:
        return compact_for_pull(max_nodes=max_nodes, max_edges=max_edges)

    # Force full refresh when since > 7d old
    try:
        from datetime import datetime, timezone, timedelta

        since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - since_dt
        if age > timedelta(days=7):
            return compact_for_pull(max_nodes=max_nodes, max_edges=max_edges)
    except Exception:
        return compact_for_pull(max_nodes=max_nodes, max_edges=max_edges)

    try:
        from ftm_connection import _LOCK, _conn
    except ImportError:
        return {"available": False, "reason": "ftm_connection not importable"}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        with _LOCK:
            con = _conn()
            # Entities with last_seen after since
            entity_rows = con.execute(
                """
                SELECT id, schema, caption, datasets, lat, lon, last_seen
                FROM entities
                WHERE last_seen IS NOT NULL AND last_seen > ?
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                [since, max_nodes],
            ).fetchall()
            for row in entity_rows:
                nodes.append(
                    {
                        "id": row[0],
                        "caption": str(row[2] or "")[:80],
                        "schema": row[1],
                        "datasets": json.loads(row[3] or "[]")[:3],
                        "lat": row[4],
                        "lon": row[5],
                        "last_seen": row[6],
                    }
                )

            # Edges with seen_at after since
            edge_rows = con.execute(
                """
                SELECT source_id, target_id, kind, dataset, confidence, seen_at
                FROM edges
                WHERE seen_at IS NOT NULL AND seen_at > ?
                ORDER BY seen_at DESC
                LIMIT ?
                """,
                [since, max_edges],
            ).fetchall()
            for row in edge_rows:
                edges.append(
                    {
                        "kind": row[2],
                        "dataset": row[3],
                        "source_id": row[0],
                        "target_id": row[1],
                        "confidence": row[4],
                        "seen_at": row[5],
                    }
                )
    except Exception as exc:
        logger.warning("compact_delta_for_pull query failed: %s", exc)
        return {"available": False, "reason": "delta query error"}

    return {
        "available": True,
        "delta": True,
        "since": since,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "nodes_added": nodes,
        "edges_added": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
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
