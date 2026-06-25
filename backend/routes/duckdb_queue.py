"""HTTP surface for the DuckDB Write-Through Queue.

Endpoints:
- GET  /api/intel/queue/status  — queue backlog, DLQ count, config
- GET  /api/intel/queue/{task_id} — poll async task status
- GET  /api/admin/dlq            — list dead-letter tasks
- POST /api/admin/dlq/{task_id}/replay — re-enqueue a dead-letter task
- DELETE /api/admin/dlq          — clear all dead letters
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api", tags=["queue"])


@router.get("/intel/queue/status")
async def queue_status():
    import duckdb_queue

    return duckdb_queue.get_queue().status()


@router.get("/intel/queue/{task_id}")
async def task_status(task_id: str):
    import duckdb_queue

    result = duckdb_queue.get_queue().get_task_status(task_id)
    if result is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    return {"task_id": task_id, **result}


@router.get("/admin/dlq")
async def dlq_list(_auth: str | None = Depends(verify_lan_auth)):
    import duckdb_queue

    return {"dead_letters": duckdb_queue.get_queue().dlq_list()}


@router.post("/admin/dlq/{task_id}/replay")
async def dlq_replay(task_id: str, _auth: str | None = Depends(verify_lan_auth)):
    import duckdb_queue

    try:
        new_id = duckdb_queue.get_queue().dlq_replay(task_id)
        return {"replayed": True, "old_task_id": task_id, "new_task_id": new_id}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)[:200]}, status_code=503)


@router.delete("/admin/dlq")
async def dlq_clear(_auth: str | None = Depends(verify_lan_auth)):
    import duckdb_queue

    cleared = duckdb_queue.get_queue().dlq_clear()
    return {"cleared": cleared}
