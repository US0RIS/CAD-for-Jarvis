from __future__ import annotations

"""Milestone-3 bounded repair with candidate-by-candidate structural refresh.

A candidate geometry mutation is never allowed to inherit structural evidence from
its parent geometry. Every requested analysis has explicit loads/boundary conditions,
is rerun with ForgeCAD's existing 3D solid solver, and is persisted as an ordinary
canonical simulation before requirements are re-verified. Unsupported geometry fails
closed; no reduced-order result is substituted for the requested solid analysis.
"""

from copy import deepcopy
import itertools
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200 import structural_fea
from ..v310.engineering_graph import EngineeringGraphStore
from ..v310.integration_services import semantic_branch_diff, synchronize_graph, verify_requirements
from .repair_trials import RepairVariable


class StructuralRefreshSpec(BaseModel):
    object_id: str
    force_n: float
    support_axis: Literal["x"] = "x"
    load_direction: Literal["x", "y", "z"] = "z"
    mesh_counts: tuple[int, int, int] | None = None
    required_solver_grade: Literal["engineering_iteration"] = "engineering_iteration"


class AnalysisRefreshingRepairRequest(BaseModel):
    requirement_id: str
    guardrail_requirement_ids: list[str] = Field(default_factory=list, max_length=24)
    variables: list[RepairVariable] = Field(min_length=1, max_length=3)
    structural_refresh: list[StructuralRefreshSpec] = Field(min_length=1, max_length=3)
    max_evaluations: int = Field(default=64, ge=2, le=256)
    branch_prefix: str = "analysis-refresh-repair"
    actor: Literal["jarvis", "forgecad", "human"] = "jarvis"


def _snapshot() -> dict[str, Any]:
    return {
        "name": str(core.PROJECT.get("name") or "ForgeCAD Project"),
        "revision": f"{core.ACTIVE_DESIGN}:{len(core.PROJECT.get('ledger', []))}:{core.PROJECT.get('updated_at', '')}",
        "active_branch": core.ACTIVE_DESIGN,
        "metrics": core.project_metrics(),
    }


def _sync(graph: EngineeringGraphStore, world: Any | None) -> None:
    synchronize_graph(graph, _snapshot(), world)


def _rows(graph: EngineeringGraphStore, ids: set[str]) -> dict[str, dict[str, Any]]:
    result = verify_requirements(graph)
    rows = {str(row["requirement"].get("id")): row for row in result["items"] if str(row["requirement"].get("id")) in ids}
    missing = ids - set(rows)
    if missing:
        raise KeyError(", ".join(sorted(missing)))
    return rows


def _guardrails(rows: dict[str, dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    items = [deepcopy(rows[req_id]) for req_id in ids]
    failed = [row for row in items if row["status"] == "fail"]
    unknown = [row for row in items if row["status"] == "unknown"]
    return {
        "ok": not failed and not unknown,
        "items": items,
        "failed_requirement_ids": [str(row["requirement"].get("id")) for row in failed],
        "unknown_requirement_ids": [str(row["requirement"].get("id")) for row in unknown],
    }


def _authority(variable: RepairVariable) -> tuple[dict[str, Any], float, dict[str, Any]]:
    obj = core.object_by_id(variable.object_id)
    params = obj.get("params") or {}
    if variable.parameter not in params or not isinstance(params[variable.parameter], (int, float)):
        raise ValueError(f"Repair variable must reference an existing numeric CAD parameter: {variable.object_id}:{variable.parameter}")
    semantic = obj.get("semantic") or {}
    row = ((semantic.get("repair_authority") or {}).get("parameters") or {}).get(variable.parameter)
    if not isinstance(row, dict) or not bool(row.get("enabled", False)):
        raise ValueError(f"Object {variable.object_id} parameter {variable.parameter!r} is not explicitly authorized for bounded repair")
    if row.get("min") is None or row.get("max") is None:
        raise ValueError(f"Repair authority for {variable.object_id}:{variable.parameter} must declare min and max")
    allowed_min, allowed_max = float(row["min"]), float(row["max"])
    if variable.lower < allowed_min - 1e-12 or variable.upper > allowed_max + 1e-12:
        raise ValueError(f"Requested bounds exceed authorized range [{allowed_min}, {allowed_max}] for {variable.object_id}:{variable.parameter}")
    current = float(params[variable.parameter])
    if not (variable.lower - 1e-12 <= current <= variable.upper + 1e-12):
        raise ValueError(f"Current value {current} lies outside requested repair bounds for {variable.object_id}:{variable.parameter}")
    return obj, current, deepcopy(row)


def _domain(variable: RepairVariable, current: float) -> list[float]:
    span = float(variable.upper) - float(variable.lower)
    values = [float(variable.lower) + span * i / float(variable.samples - 1) for i in range(variable.samples)]
    values.append(float(current))
    return sorted({round(value, 12) for value in values})


def _distance(combo: tuple[float, ...], baseline: list[float], variables: list[RepairVariable]) -> float:
    return sum(abs(float(value) - old) / max(float(variable.upper) - float(variable.lower), 1e-12) for value, old, variable in zip(combo, baseline, variables))


def _set_values(variables: list[RepairVariable], values: tuple[float, ...]) -> tuple[list[dict[str, Any]], list[str], int]:
    changes: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    for variable, value in zip(variables, values):
        obj = core.object_by_id(variable.object_id)
        before = float(obj["params"][variable.parameter])
        after = float(value)
        changed = abs(before - after) > 1e-12
        obj["params"][variable.parameter] = after
        if changed:
            changed_ids.add(variable.object_id)
        changes.append({"object_id": variable.object_id, "parameter": variable.parameter, "before": before, "after": after, "changed": changed})
    stale = sum(int(core.mark_simulations_stale(object_id)) for object_id in sorted(changed_ids))
    return changes, sorted(changed_ids), stale


def _refresh_structural(specs: list[StructuralRefreshSpec]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    all_ok = True
    for spec in specs:
        obj = core.object_by_id(spec.object_id)
        result = structural_fea.solve_box(
            obj,
            force_n=float(spec.force_n),
            support_axis=spec.support_axis,
            load_direction=spec.load_direction,
            mesh_counts=spec.mesh_counts,
        )
        if not result.get("supported"):
            all_ok = False
            rows.append({
                "ok": False,
                "object_id": spec.object_id,
                "solver_grade": result.get("solver_grade", "unsupported"),
                "reason": result.get("reason", "unsupported structural analysis"),
                "simulation_id": None,
            })
            continue
        if str(result.get("solver_grade")) != spec.required_solver_grade:
            all_ok = False
            rows.append({
                "ok": False,
                "object_id": spec.object_id,
                "solver_grade": result.get("solver_grade"),
                "reason": f"Required solver grade {spec.required_solver_grade!r} was not met",
                "simulation_id": None,
            })
            continue
        params = {
            "force_n": float(spec.force_n),
            "support_axis": spec.support_axis,
            "load_direction": spec.load_direction,
            "mesh_counts": list(spec.mesh_counts) if spec.mesh_counts is not None else None,
            "requested_by": "v600_analysis_refresh_repair",
        }
        simulation = core.record_simulation("v600_structural_repair_refresh", spec.object_id, params, result)
        rows.append({
            "ok": True,
            "object_id": spec.object_id,
            "solver_grade": result.get("solver_grade"),
            "simulation_id": simulation["id"],
            "yield_fos": result.get("yield_fos"),
            "max_von_mises_stress_mpa": result.get("max_von_mises_stress_mpa"),
            "input_sha256": result.get("input_sha256"),
        })
    return {"ok": all_ok, "items": rows}


def run_analysis_refreshing_repair(
    graph: EngineeringGraphStore,
    world: Any | None,
    request: AnalysisRefreshingRepairRequest,
) -> dict[str, Any]:
    if request.requirement_id in request.guardrail_requirement_ids:
        raise ValueError("Target requirement cannot also be a guardrail")
    if len(set(request.guardrail_requirement_ids)) != len(request.guardrail_requirement_ids):
        raise ValueError("Guardrail requirement IDs must be unique")

    requirement_ids = {request.requirement_id, *request.guardrail_requirement_ids}
    if not any(str(row.get("id")) == request.requirement_id for row in core.PROJECT.get("requirements", [])):
        raise KeyError(request.requirement_id)

    validated = [_authority(variable) for variable in request.variables]
    baseline_values = [row[1] for row in validated]
    authorities = [row[2] for row in validated]
    refresh_objects = {spec.object_id for spec in request.structural_refresh}
    changed_objects = {variable.object_id for variable in request.variables}
    if not changed_objects.issubset(refresh_objects):
        missing = sorted(changed_objects - refresh_objects)
        raise ValueError(f"Every repair-mutated object requires an explicit structural refresh spec; missing {missing}")

    _sync(graph, world)
    baseline_rows = _rows(graph, requirement_ids)
    target_before = deepcopy(baseline_rows[request.requirement_id])
    guards_before = _guardrails(baseline_rows, request.guardrail_requirement_ids)
    if target_before["status"] == "unknown":
        raise ValueError("Repair is blocked because target requirement evidence is unknown")
    if not guards_before["ok"]:
        raise ValueError(f"Repair is blocked because baseline guardrails are not all passing: {guards_before}")
    if target_before["status"] == "pass":
        return {"ok": True, "status": "already_satisfied", "baseline_branch": core.ACTIVE_DESIGN, "repair_branch": None, "evaluations": []}

    baseline_branch = core.ACTIVE_DESIGN
    baseline_snapshot = deepcopy(core.PROJECT)
    core.DESIGNS.setdefault(baseline_branch, {})["analysis_status"] = "requirements_failed"
    core.persist()
    core.create_branch(
        f"{request.branch_prefix}-{request.requirement_id}",
        reason=f"Analysis-refreshing bounded repair for {request.requirement_id}",
        prefix=f"{request.branch_prefix}-{request.requirement_id}",
    )
    repair_branch = core.ACTIVE_DESIGN

    domains = [_domain(variable, baseline) for variable, baseline in zip(request.variables, baseline_values)]
    combos = list(itertools.product(*domains))
    combos.sort(key=lambda combo: (_distance(combo, baseline_values, request.variables), tuple(float(v) for v in combo)))
    combos = combos[: request.max_evaluations]
    baseline_combo = tuple(baseline_values)
    evaluations: list[dict[str, Any]] = []
    winner: dict[str, Any] | None = None

    for index, combo in enumerate(combos, start=1):
        with core.LOCK:
            _set_values(request.variables, baseline_combo)
            mutations, changed, stale = _set_values(request.variables, combo)
            core.push_history("v6 analysis-refresh repair candidate", request.actor, f"candidate {index}/{len(combos)} for {request.requirement_id}")
            core.persist()
        refresh = _refresh_structural(request.structural_refresh)
        if not refresh["ok"]:
            evaluations.append({
                "index": index,
                "values": list(combo),
                "normalized_change": _distance(combo, baseline_values, request.variables),
                "mutations": mutations,
                "changed_object_ids": changed,
                "stale_simulation_count": stale,
                "analysis_refresh": refresh,
                "verification": None,
                "guardrails": None,
                "accepted": False,
                "rejection": "analysis_unsupported_or_insufficient_grade",
            })
            continue

        _sync(graph, world)
        current_rows = _rows(graph, requirement_ids)
        target = deepcopy(current_rows[request.requirement_id])
        guards = _guardrails(current_rows, request.guardrail_requirement_ids)
        accepted = target["status"] == "pass" and guards["ok"]
        record = {
            "index": index,
            "values": list(combo),
            "normalized_change": _distance(combo, baseline_values, request.variables),
            "mutations": mutations,
            "changed_object_ids": changed,
            "stale_simulation_count": stale,
            "analysis_refresh": refresh,
            "verification": target,
            "guardrails": guards,
            "accepted": accepted,
            "rejection": None if accepted else "requirements_or_guardrails_not_satisfied",
        }
        evaluations.append(record)
        if accepted:
            winner = record
            break

    if winner is None:
        with core.LOCK:
            _set_values(request.variables, baseline_combo)
            core.DESIGNS.setdefault(repair_branch, {})["analysis_status"] = "analysis_refresh_repair_failed"
            core.DESIGNS[repair_branch]["physical_verified"] = False
            core.push_history("v6 analysis-refresh repair exhausted", request.actor, f"No passing candidate for {request.requirement_id}")
            core.persist()
        outcome = "no_passing_candidate"
        ok = False
    else:
        winning_combo = tuple(float(v) for v in winner["values"])
        with core.LOCK:
            _set_values(request.variables, winning_combo)
            # Setting the winning combo from itself does not stale the freshly-created winning analysis.
            core.DESIGNS.setdefault(repair_branch, {})["analysis_status"] = "requirements_passed_after_fresh_analysis"
            core.DESIGNS[repair_branch]["physical_verified"] = False
            core.DESIGNS[repair_branch]["verified_requirement_ids"] = sorted(requirement_ids)
            core.push_history("v6 analysis-refresh repair selected", request.actor, f"Selected least-change freshly analyzed candidate for {request.requirement_id}")
            core.persist()
        outcome = "requirement_satisfied_with_fresh_analysis"
        ok = True

    _sync(graph, world)
    final_rows = _rows(graph, requirement_ids)
    final_target = deepcopy(final_rows[request.requirement_id])
    final_guards = _guardrails(final_rows, request.guardrail_requirement_ids)
    diff = semantic_branch_diff(baseline_branch, repair_branch)

    # Branch immutability check: create_branch captured the parent snapshot before
    # candidate mutations; the active branch may mutate, the parent may not.
    parent = core.BRANCHES.get(baseline_branch)
    if parent is None:
        raise RuntimeError("Repair parent branch snapshot disappeared")
    for variable, baseline in zip(request.variables, baseline_values):
        parent_obj = next(row for row in parent.get("objects", []) if str(row.get("id")) == variable.object_id)
        if abs(float(parent_obj["params"][variable.parameter]) - baseline) > 1e-12:
            raise RuntimeError("Analysis-refresh repair mutated its parent branch")

    trial = {
        "schema": "forgecad-analysis-refresh-repair-trial/1",
        "milestone": 3,
        "requirement_id": request.requirement_id,
        "guardrail_requirement_ids": list(request.guardrail_requirement_ids),
        "baseline_branch": baseline_branch,
        "repair_branch": repair_branch,
        "authorities": authorities,
        "structural_refresh": [spec.model_dump(mode="json") for spec in request.structural_refresh],
        "evaluations": deepcopy(evaluations),
        "outcome": outcome,
        "semantic_diff_count": int(diff["count"]),
        "physical_validation_claimed": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("engineering_trials", []).append(trial)
        core.persist()

    return {
        "ok": ok,
        "status": outcome,
        "baseline_branch": baseline_branch,
        "repair_branch": repair_branch,
        "baseline_verification": target_before,
        "baseline_guardrails": guards_before,
        "final_verification": final_target,
        "final_guardrails": final_guards,
        "winner": deepcopy(winner),
        "evaluations": evaluations,
        "semantic_diff": diff,
        "physical_validation_claimed": False,
        "baseline_project_preserved": baseline_snapshot is not core.PROJECT and core.ACTIVE_DESIGN == repair_branch,
    }
