from __future__ import annotations

"""Optional specimen-lineage gate for milestone-5 physical test runs.

This layer is deliberately additive to the already validated repeatability engine.
When a cycle opts in, every run must use a specimen registered against a ForgeCAD-
generated fabrication package; the contract may additionally require a matching
successful manufacturing-evidence record for that package hash. Neither condition is
allowed to claim that the physical object was independently authenticated.
"""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from ..v110 import core
from ..v200.physical_evidence import design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from .physical_specimens import specimen_for_run


class PhysicalSpecimenContractRequest(BaseModel):
    require_registered_specimens: bool = True
    require_matching_manufacturing_evidence: bool = False


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
        raise ValueError(f"Physical specimen contract requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Physical specimen contract must operate on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    if not expected or design_fingerprint() != expected:
        raise ValueError("Physical specimen contract rejected because the redesign fingerprint changed")


def set_specimen_contract(cycle_id: str, request: PhysicalSpecimenContractRequest) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("physical_specimen_contract"):
        raise ValueError("Physical specimen contract is already locked for this retest cycle")
    if core.PROJECT.get("physical_test_runs") and any(
        str(row.get("cycle_id")) == cycle_id for row in core.PROJECT.get("physical_test_runs") or []
    ):
        raise ValueError("Physical specimen contract cannot be locked after test runs are recorded")
    if request.require_matching_manufacturing_evidence and not request.require_registered_specimens:
        raise ValueError("Matching manufacturing evidence requires registered physical specimens")
    contract = {
        "require_registered_specimens": bool(request.require_registered_specimens),
        "require_matching_manufacturing_evidence": bool(request.require_matching_manufacturing_evidence),
        "design_fingerprint": design_fingerprint(),
        "physical_specimen_identity_verified": False,
    }
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["physical_specimen_contract"] = deepcopy(contract)
        core.push_history(
            "v6 physical specimen contract",
            "human",
            f"locked physical specimen lineage policy for cycle {cycle_id}",
        )
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "locked": True,
        "contract": deepcopy(contract),
        "policy": "registered package lineage is required when enabled; physical specimen identity remains unverified",
    }


def validate_run_specimens(cycle_id: str, specimen_ids: list[str]) -> dict[str, dict[str, Any]]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    contract = deepcopy(cycle.get("physical_specimen_contract") or {})
    if not contract or not bool(contract.get("require_registered_specimens")):
        return {}
    resolved: dict[str, dict[str, Any]] = {}
    for specimen_id in specimen_ids:
        key = specimen_id.strip().casefold()
        if key in resolved:
            continue
        specimen = specimen_for_run(cycle_id, specimen_id)
        if specimen is None:
            raise ValueError(
                f"Physical test specimen {specimen_id!r} is not registered to a ForgeCAD fabrication package for this retest cycle"
            )
        if str(specimen.get("design_fingerprint") or "") != design_fingerprint():
            raise ValueError(f"Physical specimen {specimen_id!r} belongs to a different engineering fingerprint")
        if bool(contract.get("require_matching_manufacturing_evidence")) and not bool(specimen.get("matching_manufacturing_evidence")):
            raise ValueError(
                f"Physical specimen {specimen_id!r} lacks matching successful manufacturing evidence for its fabrication package"
            )
        resolved[key] = specimen
    return resolved


def _enriched_run_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    source_ids = [str(row["id"])]
    for key in ("specimen_registration_id", "fabrication_package_id", "manufacturing_evidence_id"):
        value = str(row.get(key) or "")
        if value:
            source_ids.append(value)
    return EngineeringEvidence(
        id=f"physical-test-run:{row['id']}",
        kind="physical_test_run",
        subject_node_ids=[f"cad:{object_id}" for object_id in row.get("object_ids") or []],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=deepcopy(row.get("measurements") or []),
        status="observed_test_run",
        method="physical_test_execution_with_specimen_lineage",
        source_ids=source_ids,
        assumptions=[
            "ForgeCAD generated and content-hashed the referenced fabrication package",
            "specimen-to-package association is operator-declared and not independently physically authenticated",
            "a matching manufacturing-evidence package hash records fabrication activity but does not authenticate the tested object",
            "procedure authenticity and operator compliance are not externally verified by ForgeCAD",
        ],
        confidence=0.85 if row.get("matching_manufacturing_evidence") else 0.65,
        metadata=deepcopy(row),
    )


def attach_specimen_lineage_to_runs(
    cycle_id: str,
    run_rows: list[dict[str, Any]],
    resolved_specimens: dict[str, dict[str, Any]],
    graph: EngineeringGraphStore,
) -> list[dict[str, Any]]:
    if not resolved_specimens or not run_rows:
        return deepcopy(run_rows)
    wanted = {str(row.get("id")) for row in run_rows}
    updated: list[dict[str, Any]] = []
    with core.LOCK:
        for row in core.PROJECT.get("physical_test_runs") or []:
            if str(row.get("id")) not in wanted:
                continue
            specimen = resolved_specimens.get(str(row.get("specimen_id") or "").strip().casefold())
            if specimen is None:
                raise RuntimeError(f"Missing resolved specimen lineage for run {row.get('run_id')}")
            row["specimen_registration_id"] = str(specimen["id"])
            row["fabrication_package_id"] = str(specimen["fabrication_package_id"])
            row["fabrication_package_sha256"] = str(specimen["fabrication_package_sha256"])
            row["manufacturing_evidence_id"] = specimen.get("manufacturing_evidence_id")
            row["matching_manufacturing_evidence"] = bool(specimen.get("matching_manufacturing_evidence"))
            row["package_identity_verified"] = bool(specimen.get("package_identity_verified"))
            row["physical_specimen_identity_verified"] = False
            row["specimen_provenance_claim_level"] = specimen.get("provenance_claim_level")
            updated.append(deepcopy(row))
        core.persist()
    for row in updated:
        graph.add_evidence(_enriched_run_evidence(row))
    return updated


def refresh_specimen_linked_run_evidence(
    cycle_id: str,
    graph: EngineeringGraphStore,
) -> list[dict[str, Any]]:
    rows = [
        deepcopy(row)
        for row in core.PROJECT.get("physical_test_runs") or []
        if str(row.get("cycle_id")) == cycle_id and row.get("specimen_registration_id")
    ]
    for row in rows:
        graph.add_evidence(_enriched_run_evidence(row))
    return rows
