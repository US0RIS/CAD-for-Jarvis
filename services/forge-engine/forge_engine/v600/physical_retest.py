from __future__ import annotations

"""Milestone-5 revision-bound physical failure -> redesign -> retest lineage.

Simulation is prediction; physical evidence is observation. A failed observation may
motivate a redesign, but it belongs to the exact design fingerprint that was tested.
This service creates a controlled redesign branch using explicitly authorized numeric
CAD mutations, preserves the failed evidence on its source revision, and requires any
retest evidence to match the redesigned fingerprint exactly.

A causal explanation supplied during redesign is recorded only as an unproven
hypothesis. When a retest cycle declares quantitative acceptance criteria, ForgeCAD
derives pass/fail from the recorded measurements and rejects a contradictory status.
Passing a scoped retest never silently marks the entire design physically verified.
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


class PhysicalTestCriterion(BaseModel):
    measurement: str = Field(min_length=1, max_length=128)
    unit: str = Field(default="", max_length=64)
    op: Literal["<=", ">=", "between"]
    target: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    required: bool = True


class BeginPhysicalRetestCycleRequest(BaseModel):
    requirement_id: str
    failed_evidence_id: str
    mutations: list[PhysicalRepairMutation] = Field(min_length=1, max_length=8)
    criteria: list[PhysicalTestCriterion] = Field(default_factory=list, max_length=16)
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


def _validate_criteria(criteria: list[PhysicalTestCriterion]) -> list[dict[str, Any]]:
    names = [row.measurement.strip() for row in criteria]
    if any(not name for name in names):
        raise ValueError("Physical test criteria require a non-empty measurement name")
    normalized = [name.casefold() for name in names]
    if len(normalized) != len(set(normalized)):
        raise ValueError("Physical test criteria must reference unique measurement names")
    rows: list[dict[str, Any]] = []
    for criterion in criteria:
        if criterion.op in {"<=", ">="}:
            if criterion.target is None:
                raise ValueError(f"Criterion {criterion.measurement} with operator {criterion.op} requires target")
            if criterion.minimum is not None or criterion.maximum is not None:
                raise ValueError(f"Criterion {criterion.measurement} cannot mix target with range bounds")
        elif criterion.op == "between":
            if criterion.minimum is None or criterion.maximum is None:
                raise ValueError(f"Criterion {criterion.measurement} requires minimum and maximum")
            if float(criterion.minimum) > float(criterion.maximum):
                raise ValueError(f"Criterion {criterion.measurement} minimum exceeds maximum")
            if criterion.target is not None:
                raise ValueError(f"Criterion {criterion.measurement} cannot mix target with range bounds")
        row = criterion.model_dump()
        row["measurement"] = criterion.measurement.strip()
        row["unit"] = criterion.unit.strip()
        rows.append(row)
    return rows


def _evaluate_criteria(criteria: list[dict[str, Any]], measurements: list[Measurement]) -> tuple[list[dict[str, Any]], str | None]:
    if not criteria:
        return [], None
    by_name: dict[str, Measurement] = {}
    for measurement in measurements:
        key = measurement.name.strip().casefold()
        if key in by_name:
            raise ValueError(f"Physical retest contains duplicate measurement {measurement.name}")
        by_name[key] = measurement

    results: list[dict[str, Any]] = []
    missing: list[str] = []
    for criterion in criteria:
        name = str(criterion.get("measurement") or "").strip()
        measurement = by_name.get(name.casefold())
        if measurement is None:
            if bool(criterion.get("required", True)):
                missing.append(name)
            results.append({
                "measurement": name,
                "required": bool(criterion.get("required", True)),
                "status": "missing",
                "passed": None,
            })
            continue
        expected_unit = str(criterion.get("unit") or "").strip()
        observed_unit = measurement.unit.strip()
        if observed_unit.casefold() != expected_unit.casefold():
            raise ValueError(
                f"Physical retest measurement {name} uses unit {observed_unit!r}; criterion requires {expected_unit!r}"
            )
        value = float(measurement.value)
        op = str(criterion.get("op") or "")
        if op == "<=":
            threshold = float(criterion["target"])
            passed = value <= threshold
            limit = {"target": threshold}
        elif op == ">=":
            threshold = float(criterion["target"])
            passed = value >= threshold
            limit = {"target": threshold}
        elif op == "between":
            lo, hi = float(criterion["minimum"]), float(criterion["maximum"])
            passed = lo <= value <= hi
            limit = {"minimum": lo, "maximum": hi}
        else:
            raise ValueError(f"Unsupported physical test criterion operator: {op}")
        results.append({
            "measurement": name,
            "unit": expected_unit,
            "value": value,
            "op": op,
            **limit,
            "required": bool(criterion.get("required", True)),
            "status": "pass" if passed else "fail",
            "passed": passed,
        })

    if missing:
        raise ValueError("Physical retest is missing required measurements: " + ", ".join(sorted(missing)))
    derived = "failed" if any(row.get("passed") is False for row in results) else "passed"
    return results, derived


def _append_unique(meta: dict[str, Any], key: str, value: str) -> None:
    values = [str(row) for row in meta.get(key) or []]
    if value not in values:
        values.append(value)
    meta[key] = values


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
    criteria = _validate_criteria(request.criteria)

    source_branch = core.ACTIVE_DESIGN
    source_fingerprint = design_fingerprint()
    with core.LOCK:
        source_meta = core.DESIGNS.setdefault(source_branch, {})
        source_meta["physical_verified"] = False
        source_meta["physical_status"] = "failed_current_physical_evidence"
        source_meta["failed_physical_evidence_id"] = request.failed_evidence_id
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
    cycle_id = core.uid()
    cycle = {
        "id": cycle_id,
        "schema": "forgecad-physical-retest-cycle/2",
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
        "failure_assessment": {
            "observation_evidence_id": request.failed_evidence_id,
            "observation_status": "failed",
            "observed_measurements": deepcopy(failed.get("measurements") or []),
            "hypothesis": request.diagnosis,
            "causality_status": "unproven_hypothesis",
            "interpretation_policy": "Physical evidence establishes the observation, not the cause. Redesign causality requires independent analysis or discriminating retest evidence.",
        },
        "test_criteria": criteria,
        "criterion_results": [],
        "derived_retest_status": None,
        "semantic_diff_count": int(diff.get("count", 0)),
        "status": "pending_retest",
        "retest_evidence_id": None,
        "retest_design_fingerprint": None,
        "physical_validation_claimed": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("physical_retest_cycles", []).append(deepcopy(cycle))
        source_meta = core.DESIGNS.setdefault(source_branch, {})
        redesign_meta = core.DESIGNS.setdefault(redesign_branch, {})
        _append_unique(source_meta, "physical_retest_cycle_ids", cycle_id)
        _append_unique(source_meta, "physical_redesign_branches", redesign_branch)
        source_meta.setdefault("physical_retest_cycle_status", {})[cycle_id] = "pending_retest"
        _append_unique(redesign_meta, "physical_retest_cycle_ids", cycle_id)
        redesign_meta["physical_source_branch"] = source_branch
        redesign_meta["physical_source_evidence_id"] = request.failed_evidence_id
        redesign_meta.setdefault("physical_retest_cycle_status", {})[cycle_id] = "pending_retest"
        redesign_meta["physical_verified"] = False
        redesign_meta["physical_status"] = "pending_retest"
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

    criterion_results, derived_status = _evaluate_criteria(
        [deepcopy(row) for row in cycle.get("test_criteria") or []],
        list(request.measurements),
    )
    if derived_status is not None and request.status != derived_status:
        raise ValueError(
            f"Declared retest status {request.status!r} contradicts criterion-derived status {derived_status!r}"
        )

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
        cycle["criterion_results"] = deepcopy(criterion_results)
        cycle["derived_retest_status"] = derived_status
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
        for branch in {str(cycle.get("source_branch") or ""), str(cycle.get("redesign_branch") or "")}:
            if not branch:
                continue
            branch_meta = core.DESIGNS.setdefault(branch, {})
            branch_meta.setdefault("physical_retest_cycle_status", {})[cycle_id] = cycle["status"]
        core.push_history("v6 physical retest", "human", f"{cycle['requirement_id']}: {request.status}")
        core.persist()

    return {
        "ok": request.status == "passed",
        "cycle": deepcopy(_cycle(cycle_id)),
        "evidence": deepcopy(evidence),
        "criterion_results": deepcopy(criterion_results),
        "derived_retest_status": derived_status,
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


def physical_retest_lineage() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for branch, raw_meta in sorted(core.DESIGNS.items()):
        meta = deepcopy(raw_meta or {})
        cycle_ids = [str(row) for row in meta.get("physical_retest_cycle_ids") or []]
        if not cycle_ids:
            continue
        rows.append({
            "branch": branch,
            "cycle_ids": cycle_ids,
            "cycle_status": deepcopy(meta.get("physical_retest_cycle_status") or {}),
            "source_branch": meta.get("physical_source_branch"),
            "source_evidence_id": meta.get("physical_source_evidence_id"),
            "redesign_branches": deepcopy(meta.get("physical_redesign_branches") or []),
            "physical_status": meta.get("physical_status"),
            "physical_verified": bool(meta.get("physical_verified", False)),
        })
    return {
        "items": rows,
        "count": len(rows),
        "active_branch": core.ACTIVE_DESIGN,
        "policy": "Branch lineage links physical observations to redesign experiments without copying evidence across design fingerprints.",
    }
