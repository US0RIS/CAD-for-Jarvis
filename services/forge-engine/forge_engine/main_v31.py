from __future__ import annotations

"""ForgeCAD 3.1 application entrypoint.

3.1 keeps the complete 3.0 world/capability surface and adds the canonical
engineering graph plus cross-domain integration services. The v2 and v3 routes
remain available for backward compatibility.
"""

from copy import deepcopy
from typing import Any

from fastapi import Depends, HTTPException, Request

from . import main_v3 as v3
from .v110 import core
from .v310 import INTEGRATION_VERSION
from .v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from .v310.integration_services import (
    DeploymentRequest,
    InspectionRequest,
    ProductProfileRequest,
    RequirementSpec,
    SolverJobRequest,
    SubstitutionRequest,
    apply_substitution,
    assembly_intelligence,
    fabrication_manifest,
    failure_diagnosis,
    hardware_drift,
    manufacturing_screening,
    product_profile,
    product_profile_findings,
    record_deployment,
    record_inspection,
    semantic_branch_diff,
    set_product_profile,
    solver_adapters,
    solver_job_contract,
    substitution_candidates,
    synchronize_graph,
    upsert_requirement,
    verify_requirements,
)


app = v3.app
GRAPH = EngineeringGraphStore()
_LAST_GRAPH_SYNC: dict[str, Any] = {"ok": False, "reason": "not_yet_synchronized"}


def _sync_graph(reason: str = "explicit") -> dict[str, Any]:
    global _LAST_GRAPH_SYNC
    try:
        result = synchronize_graph(GRAPH, v3.legacy.PROJECT.snapshot(), v3.WORLD)
        _LAST_GRAPH_SYNC = {**result, "reason": reason}
        return deepcopy(_LAST_GRAPH_SYNC)
    except Exception as exc:
        _LAST_GRAPH_SYNC = {"ok": False, "reason": reason, "error": str(exc)}
        raise


@app.on_event("startup")
async def initialize_engineering_graph() -> None:
    try:
        v3._sync_current_project(reason="v31_engine_startup")
        _sync_graph(reason="engine_startup")
    except Exception:
        # The legacy engineering surface stays reachable so a corrupt derived graph
        # can be inspected/rebuilt rather than making the application unrecoverable.
        pass


@app.middleware("http")
async def synchronize_graph_after_mutation(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if (
        response.status_code < 400
        and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        and (path.startswith("/v2/") or path.startswith("/v3/") or path.startswith("/v3.1/"))
        and path not in {"/v3.1/graph/sync"}
    ):
        try:
            _sync_graph(reason=f"{request.method.upper()} {path}")
        except Exception:
            # Canonical mutations are never reported as failed solely because a
            # reconstructable projection needs repair. Health exposes the condition.
            pass
    return response


@app.get("/v3.1/health")
async def v31_health() -> dict[str, Any]:
    return {
        "ok": bool(_LAST_GRAPH_SYNC.get("ok")) and bool(v3._LAST_SYNC.get("ok")),
        "api_version": "3.1",
        "engine_version": INTEGRATION_VERSION,
        "engineering_graph": GRAPH.summary(),
        "graph_sync": deepcopy(_LAST_GRAPH_SYNC),
        "world_sync": deepcopy(v3._LAST_SYNC),
        "capability_runtime": v3._action_runtime_summary(),
        "profile": product_profile(),
    }


@app.post("/v3.1/graph/sync", dependencies=[Depends(v3.legacy.require_session)])
async def sync_engineering_graph() -> dict[str, Any]:
    try:
        v3._sync_current_project(reason="v31_explicit_graph_sync")
        return _sync_graph(reason="explicit_api_sync")
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v3.1/graph", dependencies=[Depends(v3.legacy.require_session)])
async def engineering_graph(include_evidence: bool = True) -> dict[str, Any]:
    try:
        payload = GRAPH.snapshot().model_dump(mode="json")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not include_evidence:
        payload["evidence"] = []
    return payload


@app.get("/v3.1/graph/nodes", dependencies=[Depends(v3.legacy.require_session)])
async def graph_nodes(kind: str | None = None, domain: str | None = None, dirty: bool | None = None, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    rows = GRAPH.nodes(kind=kind, domain=domain, dirty=dirty)
    offset = max(0, int(offset))
    limit = max(1, min(5000, int(limit)))
    page = rows[offset : offset + limit]
    return {"items": [row.model_dump(mode="json") for row in page], "count": len(page), "total": len(rows), "offset": offset, "limit": limit}


@app.get("/v3.1/graph/nodes/{node_id:path}", dependencies=[Depends(v3.legacy.require_session)])
async def graph_node(node_id: str) -> dict[str, Any]:
    try:
        node = GRAPH.node(node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown engineering node: {node_id}") from exc
    return {
        "node": node.model_dump(mode="json"),
        "edges": [row.model_dump(mode="json") for row in GRAPH.edges(node_id=node_id)],
        "evidence": [row.model_dump(mode="json") for row in GRAPH.evidence(subject_node_id=node_id)],
    }


@app.get("/v3.1/graph/impact/{node_id:path}", dependencies=[Depends(v3.legacy.require_session)])
async def graph_impact(node_id: str, max_depth: int = 6) -> dict[str, Any]:
    try:
        return GRAPH.impact(node_id, max_depth=max(1, min(12, int(max_depth))))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown engineering node: {node_id}") from exc


@app.get("/v3.1/evidence", dependencies=[Depends(v3.legacy.require_session)])
async def graph_evidence(requirement_id: str | None = None, subject_node_id: str | None = None, include_stale: bool = True) -> dict[str, Any]:
    rows = GRAPH.evidence(requirement_id=requirement_id, subject_node_id=subject_node_id, include_stale=include_stale)
    return {"items": [row.model_dump(mode="json") for row in rows], "count": len(rows)}


@app.post("/v3.1/evidence", dependencies=[Depends(v3.legacy.require_session)])
async def add_engineering_evidence(evidence: EngineeringEvidence) -> dict[str, Any]:
    try:
        return GRAPH.add_evidence(evidence).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown evidence subject node: {exc.args[0]}") from exc


@app.post("/v3.1/requirements", dependencies=[Depends(v3.legacy.require_session)])
async def put_requirement(spec: RequirementSpec) -> dict[str, Any]:
    try:
        return upsert_requirement(spec)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v3.1/requirements/verify", dependencies=[Depends(v3.legacy.require_session)])
async def requirement_verification() -> dict[str, Any]:
    try:
        _sync_graph(reason="pre_requirement_verification")
        result = verify_requirements(GRAPH)
        return result
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v3.1/assembly/validate", dependencies=[Depends(v3.legacy.require_session)])
async def assembly_validation() -> dict[str, Any]:
    return assembly_intelligence()


@app.post("/v3.1/components/substitution/candidates", dependencies=[Depends(v3.legacy.require_session)])
async def component_substitution_candidates(request: SubstitutionRequest) -> dict[str, Any]:
    try:
        return substitution_candidates(request, GRAPH)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v3.1/components/{object_id}/substitute/{component_id:path}", dependencies=[Depends(v3.legacy.require_session)])
async def substitute_component(object_id: str, component_id: str) -> dict[str, Any]:
    try:
        result = apply_substitution(object_id, component_id, GRAPH)
        v3._sync_current_project(reason="v31_component_substitution")
        result["graph_sync"] = _sync_graph(reason="component_substitution")
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v3.1/manufacturing/screen/{object_id}", dependencies=[Depends(v3.legacy.require_session)])
async def manufacturing_screen(object_id: str, process: str = "cnc") -> dict[str, Any]:
    try:
        return manufacturing_screening(object_id, process)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v3.1/fabrication/packages", dependencies=[Depends(v3.legacy.require_session)])
async def generate_fabrication_package(name: str = "Fabrication Package") -> dict[str, Any]:
    try:
        _sync_graph(reason="pre_fabrication_package")
        manifest = fabrication_manifest(GRAPH, name=name)
        _sync_graph(reason="fabrication_package")
        return manifest
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v3.1/physical/inspections", dependencies=[Depends(v3.legacy.require_session)])
async def physical_inspection(request: InspectionRequest) -> dict[str, Any]:
    try:
        result = record_inspection(request, GRAPH)
        _sync_graph(reason="physical_inspection")
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/v3.1/hardware/deployments", dependencies=[Depends(v3.legacy.require_session)])
async def deployment_record(request: DeploymentRequest) -> dict[str, Any]:
    try:
        result = record_deployment(request)
        _sync_graph(reason="deployment_record")
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/v3.1/hardware/drift", dependencies=[Depends(v3.legacy.require_session)])
async def deployment_drift(object_id: str | None = None) -> dict[str, Any]:
    return hardware_drift(object_id)


@app.get("/v3.1/solvers", dependencies=[Depends(v3.legacy.require_session)])
async def available_solver_adapters() -> dict[str, Any]:
    return solver_adapters()


@app.post("/v3.1/solvers/jobs/contract", dependencies=[Depends(v3.legacy.require_session)])
async def create_solver_job_contract(request: SolverJobRequest) -> dict[str, Any]:
    try:
        return solver_job_contract(request, GRAPH)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v3.1/diagnostics/requirements/{requirement_id}", dependencies=[Depends(v3.legacy.require_session)])
async def diagnose_requirement(requirement_id: str) -> dict[str, Any]:
    try:
        return failure_diagnosis(GRAPH, requirement_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown requirement: {requirement_id}") from exc


@app.get("/v3.1/history/semantic-diff", dependencies=[Depends(v3.legacy.require_session)])
async def engineering_semantic_diff(source: str, target: str) -> dict[str, Any]:
    try:
        return semantic_branch_diff(source, target)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown design branch: {exc.args[0]}") from exc


@app.get("/v3.1/product-profile", dependencies=[Depends(v3.legacy.require_session)])
async def get_product_profile() -> dict[str, Any]:
    return {"profile": product_profile(), "screening": product_profile_findings()}


@app.put("/v3.1/product-profile", dependencies=[Depends(v3.legacy.require_session)])
async def update_product_profile(request: ProductProfileRequest) -> dict[str, Any]:
    profile = set_product_profile(request)
    _sync_graph(reason="product_profile")
    return {"profile": profile, "screening": product_profile_findings()}


@app.get("/v3.1/jarvis/context", dependencies=[Depends(v3.legacy.require_session)])
async def jarvis_engineering_context(max_nodes: int = 300) -> dict[str, Any]:
    max_nodes = max(1, min(2000, int(max_nodes)))
    snapshot = GRAPH.snapshot()
    nodes = snapshot.nodes[:max_nodes]
    node_ids = {row.id for row in nodes}
    return {
        "engine_version": INTEGRATION_VERSION,
        "project_revision": snapshot.project_revision,
        "engineering_graph_revision": snapshot.graph_revision,
        "profile": deepcopy(snapshot.profile),
        "nodes": [
            {
                "id": row.id,
                "kind": row.kind,
                "domain": row.domain,
                "name": row.name,
                "fingerprint": row.fingerprint,
                "dirty": row.dirty,
                "source": row.source,
                "source_id": row.source_id,
                "tags": row.tags,
            }
            for row in nodes
        ],
        "edges": [
            {"id": row.id, "kind": row.kind, "from_id": row.from_id, "to_id": row.to_id}
            for row in snapshot.edges
            if row.from_id in node_ids or row.to_id in node_ids
        ],
        "failed_or_unknown_requirements": [
            row
            for row in core.requirement_checks()
            if row.get("passed") is not True
        ],
        "hardware_drift": hardware_drift(),
        "assembly": assembly_intelligence(),
        "profile_screening": product_profile_findings(),
        "world": v3.WORLD.summary(),
    }
