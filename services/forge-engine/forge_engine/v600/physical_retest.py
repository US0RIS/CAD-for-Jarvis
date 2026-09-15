from __future__ import annotations

"""Milestone-5 revision-bound physical failure -> redesign -> retest lineage.

Simulation is prediction; physical evidence is observation. A failed observation may
motivate a redesign, but it belongs to the exact design fingerprint that was tested.
This service creates a controlled redesign branch using explicitly authorized numeric
CAD mutations, preserves the failed evidence on its source revision, and requires any
retest evidence to match the redesigned fingerprint exactly.

Passing a scoped retest never silently marks the entire design physically verified.
It only records that one requirement has current passing physical evidence.
"""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import (
    Measurement,
    RequirementEvidenceRequest,
    design_fingerprint,
    evidence_applies,
    verify_requirement,
)
from ..v310.integration_services import semantic_branch_diff


class PhysicalRepairMutation(BaseModel):
    object_id: str
    parameter: str
    value: float


class BeginPhysicalRetestCycleRequest(BaseModel):
    requirement_id: str
    failed_evidence_id: str
    mutations: list[PhysicalRepairMutation] = Field(min_length=1, max_length=8)
    branch_prefix: str = "physical-retest-redesign"
    actor: Literal["jarvis", "forgecad", "human"] = "jarvis"
    diagnosis: str = ""


class CompletePhysicalRetestRequest(BaseModel):
    status: Literal["passed", "failed", "inconclusive"]
    method: str
    note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)


def _requirement(requirement_id: str) -> dict[str, Any]:
    row = next((item for item in core.PROJECT.get("requirements") or [] if str(item.get("id")) == requirement_id), None)
    if row is None:
        raise KeyError(requirement_id)
    return row


def _evidence(requirement: dict[str, Any], evidence_id: str) -> dict[str, Any]:
    for row in requirement.get("verification_evidence") or []:
        if isinstance(row, dict) and str(row.get("id")) == evidence_id:
            return row
    for row in core.PROJECT.get("notebook") or []:
        if isinstance(row, dict) and str(row.get("id")) == evidence_id:
            return row
    raise KeyError(evidence_id)


def _authorized_mutation(mutation: PhysicalRepairMutation) -> tuple[dict[str, Any], float, dict[str, Any]]:
    obj = core.object_by_id(mutation.object_id)
    params = obj.get("params") or {}
    if mutation.parameter not in params or not isinstance(params[mutation.parameter], (int, float)):
        raise ValueError(f"Physical redesign mutation must reference an existing numeric CAD parameter: {mutation.object_id}:{mutation.parameter}")
    authority = (((obj.get("semantic") or {}).get("repair_authority") or {}).get("parameters") or {}).get(mutation.parameter)
    if not isinstance(authority, dict) or not bool(authority.get("enabled", False)):
        raise ValueError(f"Parameter {mutation.object_id}:{mutation.parameter} is not explicitly authorized for redesign")
    if authority.get("min") is None or authority.get("max") is None:
        raise ValueError(f"Repair authority for {mutation.object_id}:{mutation.parameter} must declare min and max")
    value = float(mutation.value)
    lo, hi = float(authority["min"]), float(authority["max"])
    if value < lo - 1e-12 or value > hi + 1e-12:
        raise ValueError(f"Requested redesign value {value} exceeds authorized range [{lo}, {hi}] for {mutation.object_id}:{mutation.parameter}")
    return obj, float(params[mutation.parameter]), deepcopy(authority)


def _cycle(cycle_id: str) -> dict[str, Any]:
    row = next((item for item in core.PROJECT.get("physical_retest_cycles") or [] if str(item.get("id")) == cycle_id), None)
    if row is None:
        raise KeyError(cycle_id)
    return row


def begin_physical_retest_cycle(request: BeginPhysicalRetestCycleRequest) -> dict[str, Any]:
    requirement = _requirement(request.requirement_id)
    failed = _evidence(requirement, request.failed_evidence_id)
    if failed.get("kind") != "requirement_verification" or not bool(failed.get("physical_evidence")):
        raise ValueError("Retest cycles require canonical physical requirement evidence")
    if str(failed.get("requirement_id")) != request.requirement_id:
        raise ValueError("Failed physical evidence belongs to a different requirement")
    if failed.get("status") != "failed":
        raise ValueError("Retest redesign must begin from failed physical evidence")
    if not evidence_applies(failed, core.PROJECT):
        raise ValueError("Failed physical evidence does not apply to the current design fingerprint")

    validated = [_authorized_mutation(row) for row in request.mutations]
    keys = [(row.object_id, row.parameter) for row in request.mutations]
    if len(keys) != len(set(keys)):
        raise ValueError("Physical redesign mutations must target unique object/parameter pairs")

    source_branch = core.ACTIVE_DESIGN
    source_fingerprint = design_fingerprint()
    with core.LOCK:
        core.DESIGNS.setdefault(source_branch, {})["physical_verified"] = False
        core.DESIGNS[source_branch]["physical_status"] = "failed_current_physical_evidence"
        core.DESIGNS[source_branch]["failed_physical_evidence_id"] = request.failed_evidence_id
        core.persist()

    core.create_branch(
        f"{request.branch_prefix}-{request.requirement_id}",
        reason=f"Redesign after failed physical evidence {request.failed_evidence_id}",
        prefix=f"{request.branch_prefix}-{request.requirement_id}",
    )
    redesign_branch = core.ACTIVE_DESIGN
    changes: list[dict[str, Any]] = []
    changed_ids: set[str] = set()
    with core.LOCK:
        for mutation, (_, before, authority) in zip(request.mutations, validated):
            obj = core.object_by_id(mutation.object_id)
            after = float(mutation.value)
            if abs(after - before) <= 1e-12:
                raise ValueError(f"Redesign mutation does not change {mutation.object_id}:{mutation.parameter}")
            obj["params"][mutation.parameter] = after
            changed_ids.add(mutation.object_id)
            changes.append({
                "object_id": mutation.object_id,
                "parameter": mutation.parameter,
                "before": before,
                "after": after,
                "authority": authority,
            })
        stale = sum(int(core.mark_simulations_stale(object_id)) for object_id in sorted(changed_ids))
        core.push_history("v6 physical feedback redesign", request.actor, f"Redesign after failed evidence {request.failed_evidence_id}")
        core.persist()

    redesign_fingerprint = design_fingerprint()
    if redesign_fingerprint == source_fingerprint:
        raise RuntimeError("Physical redesign did not change the design fingerprint")
    source_failure_now_stale = not evidence_applies(failed, core.PROJECT)
    if not source_failure_now_stale:
        raise RuntimeError("Source physical failure incorrectly remained current after redesign")

    diff = semantic_branch_diff(source_branch, redesign_branch)
    cycle = {
        "id": core.uid(),
        "schema": "forgecad-physical-retest-cycle/1",
        "milestone": 5,
        "requirement_id": request.requirement_id,
        "source_branch": source_branch,
        "source_design_fingerprint": source_fingerprint,
        "failed_evidence_id": request.failed_evidence_id,
        "failed_evidence_status": "failed",
        "redesign_branch": redesign_branch,
        "redesign_design_fingerprint": redesign_fingerprint,
        "mutations": changes,
        "stale_simulation_count": stale,
        "diagnosis": request.diagnosis,
        "semantic_diff_count": int(diff.get("count", 0)),
        "status": "pending_retest",
        "retest_evidence_id": None,
        "retest_design_fingerprint": None,
        "physical_validation_claimed": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("physical_retest_cycles", []).append(deepcopy(cycle))
        core.DESIGNS.setdefault(redesign_branch, {})["physical_verified"] = False
        core.DESIGNS[redesign_branch]["physical_status"] = "pending_retest"
        core.persist()

    return {
        "ok": True,
        "cycle": deepcopy(cycle),
        "source_failure_stale_on_redesign": True,
        "semantic_diff": diff,
        "physical_validation_claimed": False,
    }


def complete_physical_retest_cycle(cycle_id: str, request: CompletePhysicalRetestRequest) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    if cycle.get("status") != "pending_retest":
        raise ValueError(f"Retest cycle is not pending: {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch")):
        raise ValueError("Retest must be recorded on the redesign branch")
    current_fingerprint = design_fingerprint()
    expected_fingerprint = str(cycle.get("redesign_design_fingerprint") or "")
    if current_fingerprint != expected_fingerprint:
        raise ValueError("Redesign changed after the retest cycle began; start a new cycle for the new fingerprint")

    evidence = verify_requirement(
        str(cycle["requirement_id"]),
        RequirementEvidenceRequest(
            status=request.status,
            method=request.method,
            note=request.note,
            evidence_ids=list(request.evidence_ids),
            measurements=list(request.measurements),
        ),
    )
    if str(evidence.get("design_fingerprint")) != current_fingerprint:
        raise RuntimeError("Retest evidence did not bind to the current redesign fingerprint")

    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["status"] = {
            "passed": "retest_passed",
            "failed": "retest_failed",
            "inconclusive": "retest_inconclusive",
        }[request.status]
        cycle["retest_evidence_id"] = evidence["id"]
        cycle["retest_design_fingerprint"] = current_fingerprint
        cycle["physical_validation_claimed"] = request.status == "passed"
        meta = core.DESIGNS.setdefault(core.ACTIVE_DESIGN, {})
        meta["physical_verified"] = False
        meta["physical_status"] = cycle["status"]
        passed_ids = set(meta.get("physically_verified_requirement_ids") or [])
        if request.status == "passed":
            passed_ids.add(str(cycle["requirement_id"]))
        else:
            passed_ids.discard(str(cycle["requirement_id"]))
        meta["physically_verified_requirement_ids"] = sorted(passed_ids)
        core.push_history("v6 physical retest", "human", f"{cycle['requirement_id']}: {request.status}")
        core.persist()

    return {
        "ok": request.status == "passed",
        "cycle": deepcopy(_cycle(cycle_id)),
        "evidence": deepcopy(evidence),
        "requirement_physically_verified_on_current_fingerprint": request.status == "passed",
        "entire_design_physically_verified": False,
    }


def physical_retest_cycles() -> dict[str, Any]:
    return {
        "items": deepcopy(core.PROJECT.get("physical_retest_cycles") or []),
        "count": len(core.PROJECT.get("physical_retest_cycles") or []),
        "active_branch": core.ACTIVE_DESIGN,
        "design_fingerprint": design_fingerprint(),
    }
