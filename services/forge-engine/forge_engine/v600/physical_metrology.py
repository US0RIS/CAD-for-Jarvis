from __future__ import annotations

"""Uncertainty-aware metrology contracts for ForgeCAD 6.0 milestone 5.

A measurement near an acceptance boundary is not a trustworthy pass merely because
its nominal value is on the favorable side. This module binds per-measurement
instrument context and uncertainty to the exact pending physical-retest fingerprint,
then evaluates the complete uncertainty interval conservatively against the locked
criterion. Intervals that cross a limit are indeterminate and block completion until
a better measurement is supplied.

Calibration references are provenance claims. Even when a calibration report artifact
has ForgeCAD-verified bytes, that verifies file integrity only; ForgeCAD does not claim
that the issuing lab, certificate, calibration state, or chain of traceability is
externally authentic unless a separate external-validation capability proves it.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import Measurement, design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from .physical_artifacts import artifact_records_for_cycle


class MetrologyRequirement(BaseModel):
    measurement: str = Field(min_length=1, max_length=128)
    max_uncertainty: float | None = Field(default=None, ge=0.0)
    require_calibration_reference: bool = False
    require_verified_calibration_artifact: bool = False


class MetrologyContractRequest(BaseModel):
    requirements: list[MetrologyRequirement] = Field(min_length=1, max_length=16)


class MeasurementMetrologyContext(BaseModel):
    measurement: str = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=256)
    manufacturer: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=256)
    serial: str | None = Field(default=None, max_length=256)
    uncertainty: float = Field(ge=0.0)
    unit: str = Field(default="", max_length=64)
    confidence_level: float | None = Field(default=None, gt=0.0, le=1.0)
    calibration_ref: str | None = Field(default=None, max_length=2048)
    calibration_artifact_id: str | None = Field(default=None, max_length=256)
    note: str = Field(default="", max_length=2000)


class MetrologySubmissionRequest(BaseModel):
    contexts: list[MeasurementMetrologyContext] = Field(min_length=1, max_length=16)


def _cycle(cycle_id: str) -> dict[str, Any]:
    row = next(
        (item for item in core.PROJECT.get("physical_retest_cycles") or [] if str(item.get("id")) == cycle_id),
        None,
    )
    if row is None:
        raise KeyError(cycle_id)
    return row


def _assert_pending_current_cycle(cycle: dict[str, Any]) -> None:
    if cycle.get("status") != "pending_retest":
        raise ValueError(f"Metrology operation requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Metrology operation must occur on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    if not expected or design_fingerprint() != expected:
        raise ValueError("Metrology operation rejected because the redesign fingerprint changed")


def _criteria(cycle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("measurement") or "").strip().casefold(): deepcopy(row)
        for row in cycle.get("test_criteria") or []
        if str(row.get("measurement") or "").strip()
    }


def set_metrology_contract(cycle_id: str, request: MetrologyContractRequest) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("metrology_requirements"):
        raise ValueError("Metrology contract is already locked for this retest cycle")
    criteria = _criteria(cycle)
    seen: set[str] = set()
    requirements: list[dict[str, Any]] = []
    for requirement in request.requirements:
        key = requirement.measurement.strip().casefold()
        if key in seen:
            raise ValueError(f"Metrology requirement {requirement.measurement!r} is duplicated")
        seen.add(key)
        if key not in criteria:
            raise ValueError(f"Metrology requirement {requirement.measurement!r} has no matching physical test criterion")
        row = requirement.model_dump()
        row["measurement"] = str(criteria[key]["measurement"])
        requirements.append(row)
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["metrology_requirements"] = deepcopy(requirements)
        cycle["metrology_contract_design_fingerprint"] = design_fingerprint()
        cycle["metrology_contract_locked"] = True
        cycle["metrology_record_ids"] = []
        cycle["metrology_evidence_ids"] = []
        cycle["metrology_submission_complete"] = False
        core.push_history(
            "v6 physical metrology contract",
            "human",
            f"locked {len(requirements)} metrology requirement(s) for cycle {cycle_id}",
        )
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "design_fingerprint": design_fingerprint(),
        "requirements": deepcopy(requirements),
        "locked": True,
    }


def _verified_calibration_artifact(cycle_id: str, artifact_id: str) -> dict[str, Any] | None:
    return next(
        (
            row for row in artifact_records_for_cycle(cycle_id)
            if str(row.get("id")) == artifact_id
            and bool(row.get("integrity_verified"))
            and str(row.get("artifact_kind")) in {"report", "other"}
        ),
        None,
    )


def _graph_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    return EngineeringEvidence(
        id=f"physical-metrology:{row['id']}",
        kind="physical_metrology_context",
        subject_node_ids=[f"cad:{row['object_id']}"],
        requirement_ids=[str(row["requirement_id"])],
        value=float(row["uncertainty"]),
        status="metrology_context_recorded",
        method="declared_instrument_uncertainty",
        source_ids=[str(row["id"])],
        assumptions=[
            "instrument identity and uncertainty were supplied by the test operator",
            "calibration reference authenticity is not externally verified by ForgeCAD",
        ],
        confidence=float(row.get("confidence_level") or 0.8),
        metadata=deepcopy(row),
    )


def submit_metrology(
    cycle_id: str,
    request: MetrologySubmissionRequest,
    graph: EngineeringGraphStore,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("metrology_submission_complete"):
        raise ValueError("Metrology submission is already complete for this retest cycle")
    requirements = {
        str(row.get("measurement") or "").casefold(): row
        for row in cycle.get("metrology_requirements") or []
    }
    if not requirements:
        raise ValueError("Lock a metrology contract before submitting measurement context")
    criteria = _criteria(cycle)
    seen: set[str] = set()
    prepared: list[dict[str, Any]] = []
    for context in request.contexts:
        key = context.measurement.strip().casefold()
        if key in seen:
            raise ValueError(f"Metrology context {context.measurement!r} is duplicated")
        seen.add(key)
        requirement = requirements.get(key)
        criterion = criteria.get(key)
        if requirement is None or criterion is None:
            raise ValueError(f"Metrology context {context.measurement!r} is not required by the locked contract")
        expected_unit = str(criterion.get("unit") or "").strip()
        if context.unit.strip().casefold() != expected_unit.casefold():
            raise ValueError(
                f"Metrology context {context.measurement!r} uses unit {context.unit!r}; criterion requires {expected_unit!r}"
            )
        if requirement.get("max_uncertainty") is not None and float(context.uncertainty) > float(requirement["max_uncertainty"]):
            raise ValueError(
                f"Metrology uncertainty {context.uncertainty:g} {expected_unit} exceeds locked maximum {float(requirement['max_uncertainty']):g} {expected_unit} for {context.measurement}"
            )
        calibration_ref = (context.calibration_ref or "").strip()
        if requirement.get("require_calibration_reference") and not calibration_ref and not context.calibration_artifact_id:
            raise ValueError(f"Metrology context {context.measurement!r} requires a calibration reference")
        calibration_artifact = None
        if context.calibration_artifact_id:
            calibration_artifact = _verified_calibration_artifact(cycle_id, context.calibration_artifact_id)
            if calibration_artifact is None:
                raise ValueError(
                    f"Calibration artifact {context.calibration_artifact_id!r} for {context.measurement} is not a verified report artifact on this retest cycle"
                )
        if requirement.get("require_verified_calibration_artifact") and calibration_artifact is None:
            raise ValueError(f"Metrology context {context.measurement!r} requires a verified calibration report artifact")
        object_id = str(criterion.get("object_id") or "")
        graph.node(f"cad:{object_id}")
        prepared.append({
            "id": core.uid(),
            "kind": "physical_metrology_context",
            "cycle_id": cycle_id,
            "requirement_id": str(cycle.get("requirement_id") or ""),
            "measurement": str(criterion.get("measurement") or context.measurement),
            "object_id": object_id,
            "instrument_id": context.instrument_id,
            "manufacturer": context.manufacturer,
            "model": context.model,
            "serial": context.serial,
            "uncertainty": float(context.uncertainty),
            "unit": expected_unit,
            "confidence_level": context.confidence_level,
            "calibration_ref": calibration_ref or None,
            "calibration_artifact_id": context.calibration_artifact_id,
            "calibration_artifact_integrity_verified": calibration_artifact is not None,
            "calibration_authenticity_verified": False,
            "note": context.note,
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": design_fingerprint(),
            "inspection_ids": [],
        })
    missing = sorted(set(requirements) - seen)
    if missing:
        raise ValueError("Metrology submission is missing required measurement contexts: " + ", ".join(missing))

    rows: list[dict[str, Any]] = []
    graph_evidence: list[dict[str, Any]] = []
    with core.LOCK:
        collection = core.PROJECT.setdefault("physical_metrology_records", [])
        for prepared_row in prepared:
            collection.append(deepcopy(prepared_row))
            rows.append(deepcopy(prepared_row))
        core.push_history("v6 physical metrology", "human", f"recorded {len(rows)} metrology context record(s)")
        core.persist()
    for row in rows:
        graph_evidence.append(graph.add_evidence(_graph_evidence(row)).model_dump(mode="json"))
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["metrology_record_ids"] = [str(row["id"]) for row in rows]
        cycle["metrology_evidence_ids"] = [str(row["id"]) for row in graph_evidence]
        cycle["metrology_submission_complete"] = True
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "items": rows,
        "count": len(rows),
        "graph_evidence": graph_evidence,
        "calibration_authenticity_verified": False,
    }


def metrology_records_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in core.PROJECT.get("physical_metrology_records") or []
        if str(row.get("cycle_id")) == cycle_id
    ]


def _conservative_classification(criterion: dict[str, Any], value: float, uncertainty: float) -> dict[str, Any]:
    lower, upper = value - uncertainty, value + uncertainty
    op = str(criterion.get("op") or "")
    if op == ">=":
        target = float(criterion["target"])
        status = "pass" if lower >= target else "fail" if upper < target else "indeterminate"
        limits = {"target": target}
    elif op == "<=":
        target = float(criterion["target"])
        status = "pass" if upper <= target else "fail" if lower > target else "indeterminate"
        limits = {"target": target}
    elif op == "between":
        minimum, maximum = float(criterion["minimum"]), float(criterion["maximum"])
        if lower >= minimum and upper <= maximum:
            status = "pass"
        elif upper < minimum or lower > maximum:
            status = "fail"
        else:
            status = "indeterminate"
        limits = {"minimum": minimum, "maximum": maximum}
    else:
        raise ValueError(f"Unsupported physical test criterion operator: {op}")
    return {
        "measurement": criterion.get("measurement"),
        "object_id": criterion.get("object_id"),
        "unit": criterion.get("unit"),
        "nominal_value": value,
        "uncertainty": uncertainty,
        "interval": [lower, upper],
        "op": op,
        **limits,
        "status": status,
        "passed": True if status == "pass" else False if status == "fail" else None,
        "policy": "complete uncertainty interval must lie on the passing side of the acceptance boundary",
    }


def assert_metrology_contract_satisfied(cycle_id: str, measurements: list[Measurement]) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    requirements = cycle.get("metrology_requirements") or []
    if not requirements:
        return {"required": False, "results": [], "evidence_ids": [], "record_ids": []}
    if not cycle.get("metrology_submission_complete"):
        raise ValueError("Physical retest metrology contract is not satisfied: no completed metrology submission")
    records = {str(row.get("measurement") or "").casefold(): row for row in metrology_records_for_cycle(cycle_id)}
    measurements_by_name = {row.name.strip().casefold(): row for row in measurements}
    criteria = _criteria(cycle)
    results: list[dict[str, Any]] = []
    for requirement in requirements:
        key = str(requirement.get("measurement") or "").casefold()
        record = records.get(key)
        measurement = measurements_by_name.get(key)
        criterion = criteria.get(key)
        if record is None:
            raise ValueError(f"Physical retest metrology contract is missing context for {requirement.get('measurement')}")
        if measurement is None:
            raise ValueError(f"Physical retest metrology contract is missing measurement {requirement.get('measurement')}")
        if criterion is None:
            raise RuntimeError(f"Locked metrology requirement {key} lost its physical test criterion")
        if measurement.unit.strip().casefold() != str(record.get("unit") or "").strip().casefold():
            raise ValueError(f"Physical retest measurement unit changed after metrology context was locked for {measurement.name}")
        result = _conservative_classification(criterion, float(measurement.value), float(record["uncertainty"]))
        result["metrology_record_id"] = record["id"]
        result["instrument_id"] = record["instrument_id"]
        result["calibration_ref"] = record.get("calibration_ref")
        result["calibration_artifact_id"] = record.get("calibration_artifact_id")
        result["calibration_authenticity_verified"] = False
        results.append(result)
    indeterminate = [row for row in results if row["status"] == "indeterminate"]
    if indeterminate:
        names = ", ".join(str(row["measurement"]) for row in indeterminate)
        raise ValueError(
            "Physical retest is metrologically indeterminate because uncertainty crosses an acceptance boundary for: "
            + names
            + ". Acquire a lower-uncertainty measurement or change the test plan; ForgeCAD will not convert this into a pass."
        )
    return {
        "required": True,
        "results": results,
        "evidence_ids": [str(row) for row in cycle.get("metrology_evidence_ids") or []],
        "record_ids": [str(row) for row in cycle.get("metrology_record_ids") or []],
    }


def link_metrology_to_inspections(cycle_id: str, inspection_ids: list[str], graph: EngineeringGraphStore) -> list[dict[str, Any]]:
    rows = metrology_records_for_cycle(cycle_id)
    if not rows:
        return []
    wanted = {str(row["id"]) for row in rows}
    updated: list[dict[str, Any]] = []
    with core.LOCK:
        for row in core.PROJECT.get("physical_metrology_records") or []:
            if str(row.get("id")) in wanted:
                row["inspection_ids"] = list(inspection_ids)
                updated.append(deepcopy(row))
        core.persist()
    for row in updated:
        graph.add_evidence(_graph_evidence(row))
    return updated


def physical_metrology(cycle_id: str | None = None) -> dict[str, Any]:
    rows = deepcopy(core.PROJECT.get("physical_metrology_records") or [])
    if cycle_id is not None:
        rows = [row for row in rows if str(row.get("cycle_id")) == cycle_id]
    return {
        "items": rows,
        "count": len(rows),
        "active_branch": core.ACTIVE_DESIGN,
        "policy": "uncertainty intervals crossing an acceptance boundary are indeterminate; calibration provenance is recorded but not externally authenticated",
    }
