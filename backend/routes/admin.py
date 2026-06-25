"""HTTP surface for dynamic feature flags (J2).

Endpoints:
- GET  /api/admin/flags          — list all flags with state + source
- POST /api/admin/flags/{key}    — toggle a flag (body: {"enabled": true})
- GET  /api/admin/flags/log      — audit log of flag changes
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth.security import verify_lan_auth

router = APIRouter(prefix="/api/admin", tags=["admin"])


class FlagUpdate(BaseModel):
    enabled: bool
    updated_by: str = "operator"


@router.get("/flags")
async def list_flags(_auth: str | None = Depends(verify_lan_auth)):
    import features

    return {"flags": features.get_all_flags()}


@router.post("/flags/{key}")
async def set_flag(
    key: str,
    body: FlagUpdate,
    _auth: str | None = Depends(verify_lan_auth),
):
    import features

    result = features.set_flag(key, body.enabled, body.updated_by)
    return result


@router.get("/flags/log")
async def flag_log(
    limit: int = 100,
    _auth: str | None = Depends(verify_lan_auth),
):
    import features

    return {"entries": features.get_flag_log(limit=limit)}


# ---------------------------------------------------------------------------
# J1 — Prompt Versioning & A/B Testing
# ---------------------------------------------------------------------------


class PromptSave(BaseModel):
    name: str
    template: str
    set_default: bool = False


class ExperimentCreate(BaseModel):
    experiment_name: str
    variant_a_id: int
    variant_b_id: int
    traffic_split: float = 0.5


@router.get("/prompts")
async def list_prompts_route(
    name: str | None = None,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    return {"prompts": prompt_registry.list_prompts(name=name)}


@router.post("/prompts")
async def save_prompt_route(
    body: PromptSave,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    prompt_id = prompt_registry.save_prompt(body.name, body.template, body.set_default)
    return {"id": prompt_id, "name": body.name}


@router.post("/prompts/{prompt_id}/activate")
async def activate_prompt_route(
    prompt_id: int,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    ok = prompt_registry.activate_prompt(prompt_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "Prompt not found"})
    return {"ok": True, "activated": prompt_id}


@router.get("/prompts/experiments")
async def list_experiments_route(
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    return {"experiments": prompt_registry.list_experiments()}


@router.post("/prompts/experiments")
async def create_experiment_route(
    body: ExperimentCreate,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    exp_id = prompt_registry.create_experiment(
        body.experiment_name, body.variant_a_id, body.variant_b_id, body.traffic_split
    )
    return {"id": exp_id, "experiment": body.experiment_name}


@router.post("/prompts/experiments/{name}/evaluate")
async def evaluate_experiment_route(
    name: str,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_eval

    return prompt_eval.evaluate_experiment(name)


@router.get("/prompts/experiments/{name}/results")
async def experiment_results_route(
    name: str,
    _auth: str | None = Depends(verify_lan_auth),
):
    import prompt_registry

    return {
        "experiment": name,
        "results": prompt_registry.get_results(name),
    }


# ---------------------------------------------------------------------------
# J4 — Data Lineage & Impact Graph
# ---------------------------------------------------------------------------


@router.post("/refresh/{source_id}")
async def cascade_refresh_route(
    source_id: str,
    source_type: str = "entity",
    _auth: str | None = Depends(verify_lan_auth),
):
    import impact_graph

    return impact_graph.cascade_refresh(source_id, source_type)


@router.get("/lineage/stats")
async def lineage_stats_route(
    _auth: str | None = Depends(verify_lan_auth),
):
    import lineage

    return lineage.lineage_stats()


@router.get("/lineage/downstream/{source_id}")
async def lineage_downstream_route(
    source_id: str,
    source_type: str | None = None,
    _auth: str | None = Depends(verify_lan_auth),
):
    import lineage

    return {"edges": lineage.get_downstream(source_id, source_type)}


@router.get("/lineage/upstream/{target_id}")
async def lineage_upstream_route(
    target_id: str,
    target_type: str | None = None,
    _auth: str | None = Depends(verify_lan_auth),
):
    import lineage

    return {"edges": lineage.get_upstream(target_id, target_type)}
