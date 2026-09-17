from __future__ import annotations

"""Milestone-3 bounded parametric repair trials.

This service extends the 3.1 engineering graph/closed-loop substrate without
letting an agent mutate arbitrary CAD. A repair trial may vary only numeric
parameters explicitly authorized on a canonical CAD object. It preserves the
failing requirement evidence, forks an experiment branch, evaluates a bounded
finite search, keeps the least-change passing candidate, re-verifies the same
requirement plus explicit guardrails, and returns a semantic branch diff.

Geometry changes invalidate solver evidence tied to the changed object before
requirements are re-evaluated. ForgeCAD therefore never treats a pre-change
simulation as proof that a repaired design is safe. No gradient, monotonicity or
causal relationship is invented. Search candidates are explicit and finite; if
none pass, the repair branch is restored to its starting parameter values and
remains unverified.
"""

from copy import deepcopy
import hashlib
import itertools
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from ..v310.engineering_graph import EngineeringGraphStore
from ..v310.integration_services import semantic_branch_diff, synchronize_graph, verify_requirements


class RepairVariable(BaseModel):
    object_id: str
    parameter: str
    lower: float
    upper: float
    samples: int = Field(default=7, ge=2, le=15)


class ParametricRepairTrialRequest(BaseModel):
    requirement_id: str
    guardrail_requirement_ids: list[str] = Field(default_factory=list, max_length=24)
    variables: list[RepairVariable] = Field(min_length=1, max_length=3)
    max_evaluations: int = Field(default=64, ge=2, le=256)
    branch_prefix: str = "analysis-repair"
    actor: Literal["jarvis", "forgecad", "human"] = "jarvis"


def _project_snapshot() -> dict[str, Any]:
    return {
        "name": str(core.PROJECT.get("name") or "ForgeCAD Project"),
        "revision": f"{core.ACTIVE_DESIGN}:{len(core.PROJECT.get('ledger', []))}:{core.PROJECT.get('updated_at', '')}",
        "active_branch": core.ACTIVE_DESIGN,
        "metrics": core.project_metrics(),
    }


def _sync(graph: EngineeringGraphStore, world: Any | None) -> dict[str, Any]:
    return synchronize_graph(graph, _project_snapshot(), world)


def _verification_map(graph: EngineeringGraphStore, requirement_ids: set[str]) -> dict[str, dict[str, Any]]:
    verification = verify_requirements(graph)
    rows = {
        str(item["requirement"].get("id")): item
        for item in verification["items"]
        if str(item["requirement"].get("id")) in requirement_ids
    }
    missing = sorted(requirement_ids - set(rows))
    if missing:
        raise KeyError(", ".join(missing))
    return rows


def _canonical_hash(project: dict[str, Any]) -> str:
    payload = deepcopy(project)
    payload.pop("updated_at", None)
    payload.pop("ledger", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _authority(obj: dict[str, Any], parameter: str) -> dict[str, Any]:
    semantic = obj.get("semantic") or {}
    authority = semantic.get("repair_authority") or {}
    parameters = authority.get("parameters") or {}
    row = parameters.get(parameter)
    if not isinstance(row, dict) or not bool(row.get("enabled", False)):
        raise ValueError(f"Object {obj.get('id')} parameter {parameter!r} is not explicitly authorized for bounded repair")
    if row.get("min") is None or row.get("max") is None:
        raise ValueError(f"Repair authority for {obj.get('id')}:{parameter} must declare min and max")
    return row


def _validate_variable(variable: RepairVariable) -> tuple[dict[str, Any], float, dict[str, Any]]:
    obj = core.object_by_id(variable.object_id)
    params = obj.get("params") or {}
    if variable.parameter not in params or not isinstance(params[variable.parameter], (int, float)):
        raise ValueError(f"Repair variable must reference an existing numeric CAD parameter: {variable.object_id}:{variable.parameter}")
    authority = _authority(obj, variable.parameter)
    allowed_min = float(authority["min"])
    allowed_max = float(authority["max"])
    if variable.lower < allowed_min - 1e-12 or variable.upper > allowed_max + 1e-12:
        raise ValueError(
            f"Requested bounds [{variable.lower}, {variable.upper}] exceed authorized range [{allowed_min}, {allowed_max}] "
            f"for {variable.object_id}:{variable.parameter}"
        )
    if variable.lower > variable.upper:
        raise ValueError("Repair variable lower bound exceeds upper bound")
    current = float(params[variable.parameter])
    if current < variable.lower - 1e-12 or current > variable.upper + 1e-12:
        raise ValueError(f"Current value {current} lies outside requested repair bounds for {variable.object_id}:{variable.parameter}")
    return obj, current, authority


def _values(variable: RepairVariable, current: float) -> list[float]:
    if variable.samples == 2:
        values = [float(variable.lower), float(variable.upper)]
    else:
        span = float(variable.upper) - float(variable.lower)
        values = [float(variable.lower) + span * index / float(variable.samples - 1) for index in range(variable.samples)]
    values.append(float(current))
    return sorted({round(value, 12) for value in values})


def _normalized_distance(combo: tuple[float, ...], baselines: list[float], variables: list[RepairVariable]) -> float:
    total = 0.0
    for value, baseline, variable in zip(combo, baselines, variables):
        span = max(1e-12, float(variable.upper) - float(variable.lower))
        total += abs(float(value) - baseline) / span
    return total


def _set_combo(variables: list[RepairVariable], combo: tuple[float, ...]) -> tuple[list[dict[str, Any]], list[str], int]:
    mutations: list[dict[str, Any]] = []
    changed_object_ids: set[str] = set()
    for variable, value in zip(variables, combo):
        obj = core.object_by_id(variable.object_id)
        before = float(obj["params"][variable.parameter])
        after = float(value)
        obj["params"][variable.parameter] = after
        changed = abs(before - after) > 1e-12
        if changed:
            changed_object_ids.add(variable.object_id)
        mutations.append(
            {
                "object_id": variable.object_id,
                "parameter": variable.parameter,
                "before": before,
                "after": after,
                "changed": changed,
            }
        )
    stale_count = 0
    for object_id in sorted(changed_object_ids):
        stale_count += int(core.mark_simulations_stale(object_id))
    return mutations, sorted(changed_object_ids), stale_count


def _guardrail_state(rows: dict[str, dict[str, Any]], guardrail_ids: list[str]) -> dict[str, Any]:
    items = [deepcopy(rows[requirement_id]) for requirement_id in guardrail_ids]
    failed = [row for row in items if row["status"] == "fail"]
    unknown = [row for row in items if row["status"] == "unknown"]
    return {
        "items": items,
        "ok": not failed and not unknown,
        "failed_requirement_ids": [str(row["requirement"].get("id")) for row in failed],
        "unknown_requirement_ids": [str(row["requirement"].get("id")) for row in unknown],
    }


def run_parametric_repair_trial(
    graph: EngineeringGraphStore,
    world: Any | None,
    request: ParametricRepairTrialRequest,
) -> dict[str, Any]:
    if request.requirement_id in request.guardrail_requirement_ids:
        raise ValueError("The target requirement must not also be listed as a guardrail")
    if len(set(request.guardrail_requirement_ids)) != len(request.guardrail_requirement_ids):
        raise ValueError("Guardrail requirement IDs must be unique")

    requirement = next((row for row in core.PROJECT.get("requirements", []) if str(row.get("id")) == request.requirement_id), None)
    if requirement is None:
        raise KeyError(request.requirement_id)

    validated = [_validate_variable(variable) for variable in request.variables]
    baselines = [row[1] for row in validated]
    authorities = [deepcopy(row[2]) for row in validated]
    baseline_branch = core.ACTIVE_DESIGN
    baseline_project = deepcopy(core.PROJECT)
    baseline_hash = _canonical_hash(baseline_project)

    selected_ids = {request.requirement_id, *request.guardrail_requirement_ids}
    _sync(graph, world)
    baseline_rows = _verification_map(graph, selected_ids)
    baseline_verification = baseline_rows[request.requirement_id]
    baseline_guardrails = _guardrail_state(baseline_rows, request.guardrail_requirement_ids)
    if baseline_verification["status"] == "unknown":
        raise ValueError("Bounded repair is blocked because the selected requirement has unknown evidence")
    if not baseline_guardrails["ok"]:
        raise ValueError(
            "Bounded repair is blocked because baseline guardrails are not all passing: "
            f"failed={baseline_guardrails['failed_requirement_ids']} unknown={baseline_guardrails['unknown_requirement_ids']}"
        )
    if baseline_verification["status"] == "pass":
        return {
            "ok": True,
            "status": "already_satisfied",
            "baseline_branch": baseline_branch,
            "repair_branch": None,
            "baseline_verification": baseline_verification,
            "baseline_guardrails": baseline_guardrails,
            "final_verification": baseline_verification,
            "final_guardrails": baseline_guardrails,
            "evaluations": [],
            "semantic_diff": {"source": baseline_branch, "target": baseline_branch, "changes": [], "count": 0},
        }

    baseline_evidence_id = str(baseline_verification["evidence_id"])
    baseline_guardrail_evidence_ids = {
        requirement_id: str(baseline_rows[requirement_id]["evidence_id"])
        for requirement_id in request.guardrail_requirement_ids
    }
    core.DESIGNS.setdefault(baseline_branch, {})["analysis_status"] = "requirements_failed"
    core.DESIGNS[baseline_branch]["last_failed_requirement_id"] = request.requirement_id
    core.persist()

    core.create_branch(
        f"{request.branch_prefix}-{request.requirement_id}",
        reason=f"Bounded parametric repair trial for requirement {request.requirement_id}",
        prefix=f"{request.branch_prefix}-{request.requirement_id}",
    )
    repair_branch = core.ACTIVE_DESIGN

    domains = [_values(variable, baseline) for variable, baseline in zip(request.variables, baselines)]
    combinations = list(itertools.product(*domains))
    combinations.sort(key=lambda combo: (_normalized_distance(combo, baselines, request.variables), tuple(float(v) for v in combo)))
    if len(combinations) > request.max_evaluations:
        combinations = combinations[: request.max_evaluations]

    evaluations: list[dict[str, Any]] = []
    passing: dict[str, Any] | None = None
    baseline_combo = tuple(baselines)
    blocked_by_unknown_guardrail = False
    for index, combo in enumerate(combinations, start=1):
        with core.LOCK:
            _set_combo(request.variables, baseline_combo)
            mutations, changed_object_ids, stale_simulation_count = _set_combo(request.variables, combo)
            core.push_history(
                "v6 bounded repair candidate",
                request.actor,
                f"repair trial {request.requirement_id} candidate {index}/{len(combinations)}",
            )
            core.persist()
        _sync(graph, world)
        rows = _verification_map(graph, selected_ids)
        verification = rows[request.requirement_id]
        guardrails = _guardrail_state(rows, request.guardrail_requirement_ids)
        record = {
            "index": index,
            "values": [float(value) for value in combo],
            "normalized_change": _normalized_distance(combo, baselines, request.variables),
            "mutations": mutations,
            "changed_object_ids": changed_object_ids,
            "stale_simulation_count": stale_simulation_count,
            "verification": deepcopy(verification),
            "guardrails": guardrails,
        }
        evaluations.append(record)
        if verification["status"] == "pass" and guardrails["ok"]:
            passing = record
            break
        if verification["status"] == "unknown":
            break
        if guardrails["unknown_requirement_ids"]:
            blocked_by_unknown_guardrail = True
            break

    if passing is None:
        with core.LOCK:
            _set_combo(request.variables, baseline_combo)
            core.DESIGNS.setdefault(repair_branch, {})["analysis_status"] = (
                "blocked_by_unknown_guardrail" if blocked_by_unknown_guardrail else "repair_search_failed"
            )
            core.push_history(
                "v6 bounded repair exhausted",
                request.actor,
                f"No verified passing candidate for {request.requirement_id}",
            )
            core.persist()
        _sync(graph, world)
        final_rows = _verification_map(graph, selected_ids)
        final_verification = final_rows[request.requirement_id]
        final_guardrails = _guardrail_state(final_rows, request.guardrail_requirement_ids)
        outcome = "blocked_by_unknown_guardrail" if blocked_by_unknown_guardrail else "no_passing_candidate"
        ok = False
    else:
        winner = tuple(float(value) for value in passing["values"])
        with core.LOCK:
            _set_combo(request.variables, winner)
            core.DESIGNS.setdefault(repair_branch, {})["analysis_status"] = "requirements_passed"
            core.DESIGNS[repair_branch]["verified_requirement_ids"] = sorted(
                set([
                    *(core.DESIGNS[repair_branch].get("verified_requirement_ids") or []),
                    request.requirement_id,
                    *request.guardrail_requirement_ids,
                ])
            )
            core.DESIGNS[repair_branch]["physical_verified"] = False
            core.push_history("v6 bounded repair selected", request.actor, f"Selected least-change passing candidate for {request.requirement_id}")
            core.persist()
        _sync(graph, world)
        final_rows = _verification_map(graph, selected_ids)
        final_verification = final_rows[request.requirement_id]
        final_guardrails = _guardrail_state(final_rows, request.guardrail_requirement_ids)
        ok = final_verification["status"] == "pass" and final_guardrails["ok"]
        outcome = "requirement_satisfied" if ok else "verification_regressed"

    final_evidence_id = str(final_verification["evidence_id"])
    evidence_rows = graph.evidence(requirement_id=request.requirement_id, include_stale=True)
    evidence_ids = [row.id for row in evidence_rows]
    if baseline_evidence_id not in evidence_ids:
        raise RuntimeError("Failing baseline evidence was not preserved across repair trial")
    if final_evidence_id not in evidence_ids:
        raise RuntimeError("Final repair verification evidence was not persisted")

    diff = semantic_branch_diff(baseline_branch, repair_branch)
    trial = {
        "schema": "forgecad-parametric-repair-trial/2",
        "requirement_id": request.requirement_id,
        "guardrail_requirement_ids": list(request.guardrail_requirement_ids),
        "baseline_branch": baseline_branch,
        "repair_branch": repair_branch,
        "baseline_project_fingerprint": baseline_hash,
        "baseline_evidence_id": baseline_evidence_id,
        "baseline_guardrail_evidence_ids": baseline_guardrail_evidence_ids,
        "final_evidence_id": final_evidence_id,
        "variables": [variable.model_dump(mode="json") for variable in request.variables],
        "authorities": authorities,
        "evaluations": deepcopy(evaluations),
        "outcome": outcome,
        "semantic_diff_count": int(diff["count"]),
        "physical_validation_claimed": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("engineering_trials", []).append(deepcopy(trial))
        core.push_history("v6 record repair trial", request.actor, outcome)
        core.persist()

    parent_snapshot = core.BRANCHES.get(baseline_branch)
    if parent_snapshot is None or _canonical_hash(parent_snapshot) != baseline_hash:
        raise RuntimeError("Repair trial mutated the preserved baseline branch")

    return {
        "ok": ok,
        "status": outcome,
        "baseline_branch": baseline_branch,
        "repair_branch": repair_branch,
        "baseline_verification": baseline_verification,
        "baseline_guardrails": baseline_guardrails,
        "final_verification": final_verification,
        "final_guardrails": final_guardrails,
        "baseline_evidence_preserved": True,
        "baseline_project_preserved": True,
        "evaluations": evaluations,
        "selected": deepcopy(passing),
        "semantic_diff": diff,
        "trial": trial,
        "policy": {
            "mutation_boundary": "explicit numeric params inside canonical semantic.repair_authority only",
            "search": "deterministic finite least-change search",
            "max_evaluations": request.max_evaluations,
            "guardrails": "all explicit guardrail requirements must remain pass; unknown blocks acceptance",
            "simulation_invalidation": "changed geometry marks object-linked simulations stale before re-verification",
            "physical_validation": "not claimed",
        },
    }
