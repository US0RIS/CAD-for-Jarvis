from __future__ import annotations

"""Bounded closed-loop engineering orchestration for ForgeCAD 3.1.

This layer deliberately does not let an LLM mutate arbitrary state. It evaluates
canonical requirements, diagnoses explicit graph dependencies, proposes bounded
repairs, and may auto-apply only deterministic low-risk substitutions when the
caller explicitly enables that policy. Each applied repair occurs on an experiment
branch and is re-verified.
"""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from .engineering_graph import EngineeringGraphStore
from .integration_services import (
    SubstitutionRequest,
    apply_substitution,
    failure_diagnosis,
    substitution_candidates,
    synchronize_graph,
    verify_requirements,
)
from .recovery import create_checkpoint


class EngineeringLoopRequest(BaseModel):
    requirement_ids: list[str] = Field(default_factory=list)
    max_iterations: int = Field(default=3, ge=1, le=12)
    mode: Literal["analyze", "propose", "auto_low_risk"] = "propose"
    max_component_candidates: int = Field(default=6, ge=1, le=30)
    component_constraints: dict[str, dict[str, Any]] = Field(default_factory=dict)
    create_checkpoint: bool = True
    stop_on_unknown: bool = True


def _requirements(request: EngineeringLoopRequest) -> list[dict[str, Any]]:
    rows = deepcopy(core.PROJECT.get("requirements", []))
    if request.requirement_ids:
        wanted = set(request.requirement_ids)
        rows = [row for row in rows if str(row.get("id")) in wanted]
    return rows


def _candidate_for_cause(cause: dict[str, Any], graph: EngineeringGraphStore, request: EngineeringLoopRequest) -> dict[str, Any] | None:
    if cause.get("kind") != "catalog_component":
        return None
    component_node_id = str(cause.get("node_id") or "")
    component_ref = component_node_id.removeprefix("component:")
    linked = [edge for edge in graph.edges(node_id=component_node_id, kind="instance_of")]
    cad_node_id = next((edge.from_id if edge.to_id == component_node_id else edge.to_id for edge in linked if (edge.from_id.startswith("cad:") or edge.to_id.startswith("cad:"))), None)
    if not cad_node_id:
        return None
    object_id = cad_node_id.removeprefix("cad:")
    constraints = deepcopy(request.component_constraints.get(object_id) or request.component_constraints.get(component_ref) or {})
    try:
        candidates = substitution_candidates(
            SubstitutionRequest(
                object_id=object_id,
                constraints=constraints,
                max_candidates=request.max_component_candidates,
                allow_envelope_growth_pct=0.0,
            ),
            graph,
        )
    except Exception:
        return None
    best = next((row for row in candidates.get("items", []) if row.get("feasible")), None)
    if not best:
        return None
    return {
        "action": "component_substitution",
        "object_id": object_id,
        "old_component_id": component_ref,
        "component_id": best["component_id"],
        "candidate": best,
        "impact": candidates.get("impact"),
        "deterministic": True,
        "risk": "low",
    }


def run_engineering_loop(
    graph: EngineeringGraphStore,
    project_snapshot: dict[str, Any],
    world: Any | None,
    request: EngineeringLoopRequest,
) -> dict[str, Any]:
    selected_requirements = _requirements(request)
    if not selected_requirements:
        raise ValueError("Closed-loop engineering requires at least one canonical requirement")
    checkpoint = create_checkpoint("pre-engineering-loop", reason="Before bounded autonomous engineering loop", actor="forgecad") if request.create_checkpoint else None
    iterations: list[dict[str, Any]] = []
    applied_repairs: list[dict[str, Any]] = []
    branch_before = core.ACTIVE_DESIGN

    for iteration in range(1, request.max_iterations + 1):
        synchronize_graph(graph, project_snapshot if iteration == 1 else _snapshot_for_graph(), world)
        verification = verify_requirements(graph)
        relevant = [row for row in verification["items"] if not request.requirement_ids or str(row["requirement"].get("id")) in set(request.requirement_ids)]
        failing = [row for row in relevant if row["status"] == "fail"]
        unknown = [row for row in relevant if row["status"] == "unknown"]
        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "branch": core.ACTIVE_DESIGN,
            "verification": relevant,
            "diagnostics": [],
            "proposals": [],
            "applied": [],
        }
        if not failing and not unknown:
            iteration_record["outcome"] = "requirements_satisfied"
            iterations.append(iteration_record)
            break
        if unknown and request.stop_on_unknown:
            iteration_record["outcome"] = "blocked_by_unknown_evidence"
            iteration_record["unknown_requirement_ids"] = [str(row["requirement"].get("id")) for row in unknown]
            iterations.append(iteration_record)
            break

        proposals: list[dict[str, Any]] = []
        for failed in failing:
            req_id = str(failed["requirement"].get("id") or "")
            diagnosis = failure_diagnosis(graph, req_id)
            iteration_record["diagnostics"].append(diagnosis)
            # Prefer explicit deterministic substitution when a purchased component
            # lies on the causal path. Other repair types remain proposals for Jarvis
            # or a human to implement through typed CAD/electrical/software APIs.
            for cause in diagnosis.get("causes", [])[:8]:
                candidate = _candidate_for_cause(cause, graph, request)
                if candidate and all(existing.get("object_id") != candidate.get("object_id") for existing in proposals):
                    candidate["requirement_id"] = req_id
                    proposals.append(candidate)
            for repair in diagnosis.get("repairs", []):
                if repair.get("action") == "component_substitution":
                    continue
                proposals.append({**repair, "requirement_id": req_id, "deterministic": False, "risk": "review"})
        iteration_record["proposals"] = deepcopy(proposals)

        if request.mode != "auto_low_risk":
            iteration_record["outcome"] = "repair_proposed" if proposals else "no_bounded_repair_found"
            iterations.append(iteration_record)
            break

        auto = next((proposal for proposal in proposals if proposal.get("deterministic") and proposal.get("risk") == "low" and proposal.get("action") == "component_substitution"), None)
        if auto is None:
            iteration_record["outcome"] = "no_auto_safe_repair"
            iterations.append(iteration_record)
            break
        if core.ACTIVE_DESIGN == branch_before or (core.DESIGNS.get(core.ACTIVE_DESIGN) or {}).get("status") in {"working", "working_in_real_life"}:
            core.create_branch(
                f"auto-repair-{iteration}",
                reason=f"Bounded 3.1 engineering loop repair for requirement {auto.get('requirement_id')}",
                prefix=f"auto-repair-{iteration}",
            )
        result = apply_substitution(
            str(auto["object_id"]),
            str(auto["component_id"]),
            graph,
            actor="jarvis",
            reason=f"Auto low-risk repair for requirement {auto.get('requirement_id')}",
        )
        repair_record = {**auto, "result": result, "branch": core.ACTIVE_DESIGN}
        iteration_record["applied"].append(repair_record)
        applied_repairs.append(repair_record)
        iteration_record["outcome"] = "repair_applied_reverify"
        iterations.append(iteration_record)
    else:
        pass

    synchronize_graph(graph, _snapshot_for_graph(), world)
    final_verification = verify_requirements(graph)
    relevant_final = [row for row in final_verification["items"] if not request.requirement_ids or str(row["requirement"].get("id")) in set(request.requirement_ids)]
    final_pass = bool(relevant_final) and all(row["status"] == "pass" for row in relevant_final)
    return {
        "ok": final_pass,
        "mode": request.mode,
        "branch_before": branch_before,
        "branch_after": core.ACTIVE_DESIGN,
        "checkpoint": checkpoint,
        "iterations": iterations,
        "applied_repairs": applied_repairs,
        "final_verification": relevant_final,
        "status": "satisfied" if final_pass else "needs_review",
        "policy": {
            "max_iterations": request.max_iterations,
            "auto_apply_boundary": "compatible purchased-component substitutions only",
            "arbitrary_geometry_or_physical_actions": "never auto-applied by this loop",
        },
    }


def _snapshot_for_graph() -> dict[str, Any]:
    return {
        "name": str(core.PROJECT.get("name") or "ForgeCAD Project"),
        "revision": f"{core.ACTIVE_DESIGN}:{len(core.PROJECT.get('ledger', []))}:{core.PROJECT.get('updated_at', '')}",
        "active_branch": core.ACTIVE_DESIGN,
        "metrics": core.project_metrics(),
    }
