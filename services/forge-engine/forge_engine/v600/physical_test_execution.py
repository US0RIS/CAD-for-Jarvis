from __future__ import annotations

"""Repeatable physical-test execution contracts for ForgeCAD 6.0 milestone 5.

A single favorable measurement is not repeatability evidence. This module locks a
physical-test procedure to the exact pending redesign fingerprint, records explicit
run/specimen/environment identity, and derives conservative completion measurements
from the worst observed required run. Test-run records are observations, not design
truth, and are projected into the Engineering Graph as evidence on the exact CAD
identities exercised by the physical criteria.

Procedure hashes and artifact integrity prove byte identity only. They do not prove
that a procedure is technically adequate, that an operator followed it, or that a
specimen was actually manufactured from the claimed design; those remain separate
physical-validation questions.
"""

from copy import deepcopy
import re
from typing import Any

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import Measurement, design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from .physical_artifacts import artifact_records_for_cycle


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class EnvironmentRequirement(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    unit: str = Field(default="", max_length=64)


class PhysicalTestExecutionContractRequest(BaseModel):
    procedure_id: str = Field(min_length=1, max_length=256)
    procedure_revision: str = Field(min_length=1, max_length=128)
    procedure_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    procedure_artifact_id: str | None = Field(default=None, max_length=256)
    require_verified_procedure_artifact: bool = False
    min_runs: int = Field(default=3, ge=1, le=50)
    require_unique_specimens: bool = True
    environment_requirements: list[EnvironmentRequirement] = Field(default_factory=list, max_length=16)


class EnvironmentObservation(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str = Field(default="", max_length=64)


class PhysicalTestRun(BaseModel):
    run_id: str = Field(min_length=1, max_length=256)
    specimen_id: str = Field(min_length=1, max_length=256)
    operator_ref: str | None = Field(default=None, max_length=256)
    fixture_id: str | None = Field(default=None, max_length=256)
    measurements: list[Measurement] = Field(min_length=1, max_length=64)
    environment: list[EnvironmentObservation] = Field(default_factory=list, max_length=32)
    artifact_ids: list[str] = Field(default_factory=list, max_length=32)
    note: str = Field(default="", max_length=2000)


class PhysicalTestRunSubmissionRequest(BaseModel):
    runs: list[PhysicalTestRun] = Field(min_length=1, max_length=50)


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
        raise ValueError(f"Physical test execution requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Physical test execution must occur on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    if not expected or design_fingerprint() != expected:
        raise ValueError("Physical test execution rejected because the redesign fingerprint changed")


def _criteria(cycle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("measurement") or "").strip().casefold(): deepcopy(row)
        for row in cycle.get("test_criteria") or []
        if str(row.get("measurement") or "").strip()
    }


def _verified_procedure_artifact(cycle_id: str, artifact_id: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in artifact_records_for_cycle(cycle_id)
            if str(row.get("id")) == artifact_id
            and bool(row.get("integrity_verified"))
            and str(row.get("artifact_kind") or "") in {"report", "other"}
        ),
        None,
    )


def set_execution_contract(
    cycle_id: str,
    request: PhysicalTestExecutionContractRequest,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("physical_test_execution_contract"):
        raise ValueError("Physical test execution contract is already locked for this retest cycle")
    if physical_test_runs_for_cycle(cycle_id):
        raise ValueError("Physical test execution contract cannot be changed after runs are recorded")
    criteria = _criteria(cycle)
    if not any(bool(row.get("required", True)) for row in criteria.values()):
        raise ValueError("Physical test execution requires at least one required physical criterion")

    digest = request.procedure_sha256.lower() if request.procedure_sha256 else None
    if digest is not None and not _SHA256.fullmatch(digest):
        raise ValueError("procedure_sha256 must be a 64-character hexadecimal digest")

    environment_requirements: list[dict[str, Any]] = []
    seen_environment: set[str] = set()
    for requirement in request.environment_requirements:
        key = requirement.name.strip().casefold()
        if key in seen_environment:
            raise ValueError(f"Environment requirement {requirement.name!r} is duplicated")
        seen_environment.add(key)
        row = requirement.model_dump()
        row["name"] = requirement.name.strip()
        row["unit"] = requirement.unit.strip()
        environment_requirements.append(row)

    procedure_artifact = None
    if request.procedure_artifact_id:
        procedure_artifact = _verified_procedure_artifact(cycle_id, request.procedure_artifact_id)
        if procedure_artifact is None:
            raise ValueError(
                f"Procedure artifact {request.procedure_artifact_id!r} is not an integrity-verified report/other artifact on this retest cycle"
            )
        artifact_digest = str(procedure_artifact.get("sha256") or "").lower()
        if digest is not None and artifact_digest != digest:
            raise ValueError("procedure_sha256 does not match the referenced verified procedure artifact")
        if digest is None:
            digest = artifact_digest
    if request.require_verified_procedure_artifact and procedure_artifact is None:
        raise ValueError("Physical test execution contract requires an integrity-verified procedure artifact")

    contract = {
        "procedure_id": request.procedure_id.strip(),
        "procedure_revision": request.procedure_revision.strip(),
        "procedure_sha256": digest,
        "procedure_artifact_id": request.procedure_artifact_id,
        "procedure_integrity_verified": procedure_artifact is not None,
        "procedure_authenticity_verified": False,
        "min_runs": int(request.min_runs),
        "require_unique_specimens": bool(request.require_unique_specimens),
        "environment_requirements": environment_requirements,
        "aggregation_policy": "worst_observed_required_run",
        "design_fingerprint": design_fingerprint(),
    }
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["physical_test_execution_contract"] = deepcopy(contract)
        cycle["physical_test_run_ids"] = []
        cycle["physical_test_run_evidence_ids"] = []
        core.push_history(
            "v6 physical test execution contract",
            "human",
            f"locked procedure {contract['procedure_id']}@{contract['procedure_revision']} for cycle {cycle_id}",
        )
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "locked": True,
        "contract": deepcopy(contract),
        "policy": "procedure byte identity is not procedure adequacy or execution proof",
    }


def _graph_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    return EngineeringEvidence(
        id=f"physical-test-run:{row['id']}",
        kind="physical_test_run",
        subject_node_ids=[f"cad:{object_id}" for object_id in row.get("object_ids") or []],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=deepcopy(row.get("measurements") or []),
        status="observed_test_run",
        method="physical_test_execution",
        source_ids=[str(row["id"])],
        assumptions=[
            "specimen identity and test execution were supplied by the test operator",
            "procedure authenticity and operator compliance are not externally verified by ForgeCAD",
        ],
        confidence=0.8,
        metadata=deepcopy(row),
    )


def submit_test_runs(
    cycle_id: str,
    request: PhysicalTestRunSubmissionRequest,
    graph: EngineeringGraphStore,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    contract = deepcopy(cycle.get("physical_test_execution_contract") or {})
    if not contract:
        raise ValueError("Lock a physical test execution contract before recording test runs")
    criteria = _criteria(cycle)
    required_criteria = {key: row for key, row in criteria.items() if bool(row.get("required", True))}
    existing = physical_test_runs_for_cycle(cycle_id)
    existing_run_ids = {str(row.get("run_id") or "").casefold() for row in existing}
    existing_specimens = {str(row.get("specimen_id") or "").casefold() for row in existing}
    artifact_by_id = {str(row.get("id")): row for row in artifact_records_for_cycle(cycle_id)}
    expected_fingerprint = str(cycle.get("redesign_design_fingerprint") or "")
    object_ids = sorted({str(row.get("object_id")) for row in criteria.values() if row.get("object_id")})
    for object_id in object_ids:
        graph.node(f"cad:{object_id}")

    environment_requirements = {
        str(row.get("name") or "").casefold(): row
        for row in contract.get("environment_requirements") or []
    }
    prepared: list[dict[str, Any]] = []
    batch_run_ids: set[str] = set()
    batch_specimens: set[str] = set()
    for run in request.runs:
        run_key = run.run_id.strip().casefold()
        if run_key in existing_run_ids or run_key in batch_run_ids:
            raise ValueError(f"Physical test run_id {run.run_id!r} is duplicated")
        batch_run_ids.add(run_key)
        specimen_key = run.specimen_id.strip().casefold()
        if bool(contract.get("require_unique_specimens")):
            if specimen_key in existing_specimens or specimen_key in batch_specimens:
                raise ValueError(f"Physical test specimen_id {run.specimen_id!r} is duplicated but unique specimens are required")
            batch_specimens.add(specimen_key)

        measurements: dict[str, Measurement] = {}
        for measurement in run.measurements:
            key = measurement.name.strip().casefold()
            if key in measurements:
                raise ValueError(f"Run {run.run_id!r} contains duplicate measurement {measurement.name!r}")
            measurements[key] = measurement
        missing = sorted(set(required_criteria) - set(measurements))
        if missing:
            raise ValueError(f"Run {run.run_id!r} is missing required measurements: {', '.join(missing)}")
        for key, measurement in measurements.items():
            criterion = criteria.get(key)
            if criterion is None:
                continue
            expected_unit = str(criterion.get("unit") or "").strip()
            if measurement.unit.strip().casefold() != expected_unit.casefold():
                raise ValueError(
                    f"Run {run.run_id!r} measurement {measurement.name!r} uses unit {measurement.unit!r}; criterion requires {expected_unit!r}"
                )

        environment: dict[str, EnvironmentObservation] = {}
        for observation in run.environment:
            key = observation.name.strip().casefold()
            if key in environment:
                raise ValueError(f"Run {run.run_id!r} contains duplicate environment observation {observation.name!r}")
            environment[key] = observation
        missing_environment = sorted(set(environment_requirements) - set(environment))
        if missing_environment:
            raise ValueError(
                f"Run {run.run_id!r} is missing required environment observations: {', '.join(missing_environment)}"
            )
        for key, requirement in environment_requirements.items():
            observation = environment[key]
            expected_unit = str(requirement.get("unit") or "").strip()
            if observation.unit.strip().casefold() != expected_unit.casefold():
                raise ValueError(
                    f"Run {run.run_id!r} environment {observation.name!r} uses unit {observation.unit!r}; contract requires {expected_unit!r}"
                )

        artifact_ids = [str(row) for row in run.artifact_ids]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError(f"Run {run.run_id!r} contains duplicate artifact references")
        unknown_artifacts = [artifact_id for artifact_id in artifact_ids if artifact_id not in artifact_by_id]
        if unknown_artifacts:
            raise ValueError(f"Run {run.run_id!r} references artifacts outside this retest cycle: {unknown_artifacts}")

        prepared.append({
            "id": core.uid(),
            "kind": "physical_test_run",
            "cycle_id": cycle_id,
            "requirement_id": str(cycle.get("requirement_id") or ""),
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": expected_fingerprint,
            "run_id": run.run_id.strip(),
            "specimen_id": run.specimen_id.strip(),
            "operator_ref": run.operator_ref,
            "fixture_id": run.fixture_id,
            "procedure_id": contract.get("procedure_id"),
            "procedure_revision": contract.get("procedure_revision"),
            "procedure_sha256": contract.get("procedure_sha256"),
            "procedure_artifact_id": contract.get("procedure_artifact_id"),
            "procedure_integrity_verified": bool(contract.get("procedure_integrity_verified")),
            "procedure_authenticity_verified": False,
            "object_ids": object_ids,
            "measurements": [row.model_dump() for row in run.measurements],
            "environment": [row.model_dump() for row in run.environment],
            "artifact_ids": artifact_ids,
            "note": run.note,
            "inspection_ids": [],
            "physical_evidence": True,
        })

    if len(existing) + len(prepared) > 100:
        raise ValueError("A physical retest cycle may contain at most 100 recorded test runs")

    rows: list[dict[str, Any]] = []
    graph_evidence: list[dict[str, Any]] = []
    with core.LOCK:
        collection = core.PROJECT.setdefault("physical_test_runs", [])
        for row in prepared:
            collection.append(deepcopy(row))
            rows.append(deepcopy(row))
        core.push_history(
            "v6 physical test runs",
            "human",
            f"recorded {len(rows)} physical test run(s) for cycle {cycle_id}",
        )
        core.persist()
    for row in rows:
        graph_evidence.append(graph.add_evidence(_graph_evidence(row)).model_dump(mode="json"))
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["physical_test_run_ids"] = [
            *[str(row) for row in cycle.get("physical_test_run_ids") or []],
            *[str(row["id"]) for row in rows],
        ]
        cycle["physical_test_run_evidence_ids"] = [
            *[str(row) for row in cycle.get("physical_test_run_evidence_ids") or []],
            *[str(row["id"]) for row in graph_evidence],
        ]
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "items": rows,
        "count": len(rows),
        "total_run_count": len(existing) + len(rows),
        "graph_evidence": graph_evidence,
    }


def physical_test_runs_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in core.PROJECT.get("physical_test_runs") or []
        if str(row.get("cycle_id")) == cycle_id
    ]


def physical_test_execution(cycle_id: str) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    rows = physical_test_runs_for_cycle(cycle_id)
    return {
        "cycle_id": cycle_id,
        "contract": deepcopy(cycle.get("physical_test_execution_contract")),
        "items": rows,
        "count": len(rows),
        "design_fingerprint": str(cycle.get("redesign_design_fingerprint") or ""),
    }


def _nominal_pass(criterion: dict[str, Any], value: float) -> bool:
    op = str(criterion.get("op") or "")
    if op == ">=":
        return value >= float(criterion["target"])
    if op == "<=":
        return value <= float(criterion["target"])
    if op == "between":
        return float(criterion["minimum"]) <= value <= float(criterion["maximum"])
    raise ValueError(f"Unsupported physical criterion operator: {op}")


def _representative_value(criterion: dict[str, Any], values: list[float]) -> float:
    op = str(criterion.get("op") or "")
    if op == ">=":
        return min(values)
    if op == "<=":
        return max(values)
    if op == "between":
        minimum, maximum = float(criterion["minimum"]), float(criterion["maximum"])
        violating = [value for value in values if value < minimum or value > maximum]
        if violating:
            return max(
                violating,
                key=lambda value: (minimum - value) if value < minimum else (value - maximum),
            )
        return min(values, key=lambda value: min(value - minimum, maximum - value))
    raise ValueError(f"Unsupported physical criterion operator: {op}")


def assert_execution_contract_satisfied(cycle_id: str) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    contract = deepcopy(cycle.get("physical_test_execution_contract") or {})
    if not contract:
        return {
            "required": False,
            "derived_measurements": [],
            "criterion_results": [],
            "evidence_ids": [],
            "run_ids": [],
        }
    rows = physical_test_runs_for_cycle(cycle_id)
    minimum = int(contract.get("min_runs", 1))
    if len(rows) < minimum:
        raise ValueError(f"Physical test execution contract requires at least {minimum} runs; recorded {len(rows)}")
    expected_fingerprint = str(cycle.get("redesign_design_fingerprint") or "")
    if any(str(row.get("design_fingerprint") or "") != expected_fingerprint for row in rows):
        raise ValueError("Physical test execution contains a run bound to a different design fingerprint")
    if bool(contract.get("require_unique_specimens")):
        specimens = [str(row.get("specimen_id") or "").casefold() for row in rows]
        if len(specimens) != len(set(specimens)):
            raise ValueError("Physical test execution contract requires unique specimens across recorded runs")

    criteria = _criteria(cycle)
    required_criteria = [row for row in criteria.values() if bool(row.get("required", True))]
    derived: list[Measurement] = []
    results: list[dict[str, Any]] = []
    for criterion in required_criteria:
        key = str(criterion.get("measurement") or "").casefold()
        values: list[float] = []
        run_results: list[dict[str, Any]] = []
        for row in rows:
            measurement = next(
                (
                    item
                    for item in row.get("measurements") or []
                    if str(item.get("name") or "").strip().casefold() == key
                ),
                None,
            )
            if measurement is None:
                raise ValueError(f"Recorded run {row.get('run_id')} lost required measurement {criterion.get('measurement')}")
            value = float(measurement["value"])
            values.append(value)
            passed = _nominal_pass(criterion, value)
            run_results.append({
                "run_id": row.get("run_id"),
                "specimen_id": row.get("specimen_id"),
                "value": value,
                "passed": passed,
            })
        representative = _representative_value(criterion, values)
        all_passed = all(bool(row["passed"]) for row in run_results)
        derived.append(
            Measurement(
                name=str(criterion.get("measurement") or ""),
                value=representative,
                unit=str(criterion.get("unit") or ""),
            )
        )
        results.append({
            "measurement": criterion.get("measurement"),
            "object_id": criterion.get("object_id"),
            "unit": criterion.get("unit"),
            "run_count": len(values),
            "all_runs_passed": all_passed,
            "representative_value": representative,
            "representative_policy": "worst_observed_required_run",
            "runs": run_results,
        })

    return {
        "required": True,
        "run_count": len(rows),
        "minimum_run_count": minimum,
        "derived_measurements": [row.model_dump() for row in derived],
        "criterion_results": results,
        "evidence_ids": [str(row) for row in cycle.get("physical_test_run_evidence_ids") or []],
        "run_ids": [str(row.get("id")) for row in rows],
        "all_required_runs_passed": all(bool(row["all_runs_passed"]) for row in results),
        "procedure_integrity_verified": bool(contract.get("procedure_integrity_verified")),
        "procedure_authenticity_verified": False,
    }


def link_test_runs_to_inspections(
    cycle_id: str,
    inspection_ids: list[str],
    graph: EngineeringGraphStore,
) -> list[dict[str, Any]]:
    rows = physical_test_runs_for_cycle(cycle_id)
    if not rows:
        return []
    wanted = {str(row["id"]) for row in rows}
    updated: list[dict[str, Any]] = []
    with core.LOCK:
        for row in core.PROJECT.get("physical_test_runs") or []:
            if str(row.get("id")) in wanted:
                row["inspection_ids"] = list(inspection_ids)
                updated.append(deepcopy(row))
        core.persist()
    for row in updated:
        graph.add_evidence(_graph_evidence(row))
    return updated
