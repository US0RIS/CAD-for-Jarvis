from __future__ import annotations

"""Fabrication-package and physical-specimen lineage for ForgeCAD 6.0 milestone 5.

ForgeCAD can prove the exact bytes of a fabrication archive it generated and bind that
archive to the current engineering fingerprint. A human can then register a physical
specimen as claimed to have been produced from that package. A matching manufacturing
evidence record strengthens the lineage by showing that the same package hash was used
for a recorded fabrication outcome, but neither mechanism proves that the physical
object in hand is actually that specimen. Physical specimen identity therefore remains
explicitly unverified until an independent identification/traceability mechanism exists.
"""

from copy import deepcopy
import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import design_fingerprint, evidence_applies
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore
from ..v310.fabrication_archive import create_fabrication_archive


class PhysicalFabricationPackageRequest(BaseModel):
    name: str = Field(default="Physical Test Fabrication Package", min_length=1, max_length=256)
    processes: dict[str, str] = Field(default_factory=dict)
    include_step: bool = True
    include_stl: bool = True


class PhysicalSpecimenRegistrationRequest(BaseModel):
    specimen_id: str = Field(min_length=1, max_length=256)
    fabrication_package_id: str = Field(min_length=1, max_length=256)
    manufacturing_evidence_id: str | None = Field(default=None, max_length=256)
    label: str | None = Field(default=None, max_length=256)
    note: str = Field(default="", max_length=2000)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


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
        raise ValueError(f"Physical specimen operation requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Physical specimen operation must occur on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    if not expected or design_fingerprint() != expected:
        raise ValueError("Physical specimen operation rejected because the redesign fingerprint changed")


def _scope_object_ids(cycle: dict[str, Any]) -> list[str]:
    scope = [str(row) for row in cycle.get("scope_object_ids") or [] if str(row)]
    if not scope:
        scope = sorted({
            str(row.get("object_id"))
            for row in cycle.get("test_criteria") or []
            if row.get("object_id")
        })
    for object_id in scope:
        core.object_by_id(object_id)
    return scope


def _package_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    return EngineeringEvidence(
        id=f"physical-fabrication-package:{row['id']}",
        kind="physical_fabrication_package",
        subject_node_ids=[f"cad:{object_id}" for object_id in row.get("object_ids") or []],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=str(row.get("archive_sha256") or ""),
        status="forgecad_generated_package",
        method="forgecad_fabrication_archive",
        source_ids=[str(row["id"])],
        assumptions=[
            "ForgeCAD generated and hashed the exact archive bytes returned by the package endpoint",
            "package generation does not prove that any physical object was fabricated from those bytes",
        ],
        confidence=1.0,
        metadata=deepcopy(row),
    )


def generate_fabrication_package(
    cycle_id: str,
    request: PhysicalFabricationPackageRequest,
    graph: EngineeringGraphStore,
) -> tuple[bytes, dict[str, Any]]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    fingerprint = design_fingerprint()
    object_ids = _scope_object_ids(cycle)
    archive_bytes, info = create_fabrication_archive(
        graph,
        name=request.name,
        processes=dict(request.processes),
        include_step=bool(request.include_step),
        include_stl=bool(request.include_stl),
    )
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if archive_sha256 != str(info.get("archive_sha256") or ""):
        raise RuntimeError("ForgeCAD fabrication archive hash disagrees with returned archive bytes")
    if design_fingerprint() != fingerprint:
        raise RuntimeError("Generating a fabrication package unexpectedly changed the engineering design fingerprint")
    manifest = deepcopy(info.get("manifest") or {})
    record = {
        "id": core.uid(),
        "kind": "physical_fabrication_package",
        "cycle_id": cycle_id,
        "requirement_id": str(cycle.get("requirement_id") or ""),
        "branch": core.ACTIVE_DESIGN,
        "design_fingerprint": fingerprint,
        "object_ids": object_ids,
        "name": request.name,
        "filename": str(info.get("filename") or "fabrication.forgefab.zip"),
        "archive_sha256": archive_sha256,
        "archive_bytes": int(len(archive_bytes)),
        "raw_archive_persisted": False,
        "format": manifest.get("format"),
        "format_version": manifest.get("format_version"),
        "project_revision": manifest.get("project_revision"),
        "engineering_graph_revision": manifest.get("engineering_graph_revision"),
        "manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
        "file_count": len(manifest.get("files") or {}),
        "export_errors": deepcopy(manifest.get("export_errors") or []),
        "generated_by_forgecad": True,
        "package_identity_verified": True,
        "physical_build_verified": False,
        "physical_specimen_identity_verified": False,
    }
    with core.LOCK:
        core.PROJECT.setdefault("physical_fabrication_packages", []).append(deepcopy(record))
        cycle = _cycle(cycle_id)
        cycle.setdefault("physical_fabrication_package_ids", []).append(str(record["id"]))
        core.push_history(
            "v6 physical fabrication package",
            "human",
            f"generated package {record['id']} for physical retest cycle {cycle_id}",
        )
        core.persist()
    evidence = graph.add_evidence(_package_evidence(record)).model_dump(mode="json")
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle.setdefault("physical_fabrication_package_evidence_ids", []).append(str(evidence["id"]))
        core.persist()
    return archive_bytes, {"record": deepcopy(record), "graph_evidence": evidence}


def fabrication_packages_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in core.PROJECT.get("physical_fabrication_packages") or []
        if str(row.get("cycle_id")) == cycle_id
    ]


def physical_fabrication_packages(cycle_id: str) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    rows = fabrication_packages_for_cycle(cycle_id)
    return {
        "cycle_id": cycle_id,
        "items": rows,
        "count": len(rows),
        "design_fingerprint": str(cycle.get("redesign_design_fingerprint") or ""),
        "policy": "ForgeCAD package byte identity is verified; physical fabrication from the package is not implied.",
    }


def _manufacturing_evidence(evidence_id: str) -> dict[str, Any]:
    row = next(
        (
            item
            for item in core.PROJECT.get("notebook") or []
            if isinstance(item, dict)
            and str(item.get("id")) == evidence_id
            and item.get("kind") == "manufacturing_evidence"
        ),
        None,
    )
    if row is None:
        raise KeyError(evidence_id)
    return row


def _specimen_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    matched = bool(row.get("matching_manufacturing_evidence"))
    source_ids = [str(row["id"]), str(row.get("fabrication_package_id") or "")]
    if row.get("manufacturing_evidence_id"):
        source_ids.append(str(row["manufacturing_evidence_id"]))
    return EngineeringEvidence(
        id=f"physical-specimen:{row['id']}",
        kind="physical_specimen_provenance",
        subject_node_ids=[f"cad:{object_id}" for object_id in row.get("object_ids") or []],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=str(row.get("specimen_id") or ""),
        status="declared_specimen_from_recorded_package",
        method="operator_specimen_registration",
        source_ids=[value for value in source_ids if value],
        assumptions=[
            "specimen identity and its association to the fabrication package were supplied by the operator",
            "a matching package hash/manufacturing record does not physically authenticate the specimen",
        ],
        confidence=0.75 if matched else 0.5,
        metadata=deepcopy(row),
    )


def register_specimen(
    cycle_id: str,
    request: PhysicalSpecimenRegistrationRequest,
    graph: EngineeringGraphStore,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    specimen_id = request.specimen_id.strip()
    if any(
        str(row.get("cycle_id")) == cycle_id
        and str(row.get("specimen_id") or "").casefold() == specimen_id.casefold()
        for row in core.PROJECT.get("physical_specimens") or []
    ):
        raise ValueError(f"Physical specimen_id {specimen_id!r} is already registered for this retest cycle")
    package = next(
        (
            row
            for row in fabrication_packages_for_cycle(cycle_id)
            if str(row.get("id")) == request.fabrication_package_id
        ),
        None,
    )
    if package is None:
        raise ValueError("Physical specimen must reference a ForgeCAD-generated fabrication package from the same retest cycle")
    current_fingerprint = design_fingerprint()
    if str(package.get("design_fingerprint") or "") != current_fingerprint:
        raise ValueError("Fabrication package belongs to a different engineering fingerprint")

    manufacturing_evidence = None
    matching_manufacturing_evidence = False
    manufacturing_outcome = None
    if request.manufacturing_evidence_id:
        try:
            manufacturing_evidence = _manufacturing_evidence(request.manufacturing_evidence_id)
        except KeyError as exc:
            raise ValueError(f"Unknown manufacturing evidence {request.manufacturing_evidence_id!r}") from exc
        if not evidence_applies(manufacturing_evidence, core.PROJECT):
            raise ValueError("Manufacturing evidence is stale for the current engineering fingerprint")
        evidence_hash = str(manufacturing_evidence.get("package_sha256") or "").lower()
        if evidence_hash != str(package.get("archive_sha256") or "").lower():
            raise ValueError("Manufacturing evidence package hash does not match the specimen fabrication package")
        manufacturing_outcome = str(manufacturing_evidence.get("outcome") or "")
        matching_manufacturing_evidence = manufacturing_outcome == "success"
        if not matching_manufacturing_evidence:
            raise ValueError(
                f"Manufacturing evidence outcome {manufacturing_outcome!r} does not establish a successful build from the referenced package"
            )

    object_ids = [str(row) for row in package.get("object_ids") or []]
    for object_id in object_ids:
        graph.node(f"cad:{object_id}")
    record = {
        "id": core.uid(),
        "kind": "physical_specimen_provenance",
        "cycle_id": cycle_id,
        "requirement_id": str(cycle.get("requirement_id") or ""),
        "branch": core.ACTIVE_DESIGN,
        "design_fingerprint": current_fingerprint,
        "specimen_id": specimen_id,
        "label": request.label,
        "note": request.note,
        "object_ids": object_ids,
        "fabrication_package_id": str(package["id"]),
        "fabrication_package_sha256": str(package["archive_sha256"]),
        "package_identity_verified": True,
        "manufacturing_evidence_id": request.manufacturing_evidence_id,
        "manufacturing_evidence_outcome": manufacturing_outcome,
        "matching_manufacturing_evidence": matching_manufacturing_evidence,
        "specimen_package_association_declared": True,
        "physical_specimen_identity_verified": False,
        "provenance_claim_level": "operator_declared_specimen_with_verified_package_identity",
    }
    with core.LOCK:
        core.PROJECT.setdefault("physical_specimens", []).append(deepcopy(record))
        cycle = _cycle(cycle_id)
        cycle.setdefault("physical_specimen_ids", []).append(str(record["id"]))
        core.push_history(
            "v6 physical specimen registration",
            "human",
            f"registered specimen {specimen_id} for physical retest cycle {cycle_id}",
        )
        core.persist()
    evidence = graph.add_evidence(_specimen_evidence(record)).model_dump(mode="json")
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle.setdefault("physical_specimen_evidence_ids", []).append(str(evidence["id"]))
        core.persist()
    return {
        "ok": True,
        "record": deepcopy(record),
        "graph_evidence": evidence,
        "physical_specimen_identity_verified": False,
    }


def specimens_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in core.PROJECT.get("physical_specimens") or []
        if str(row.get("cycle_id")) == cycle_id
    ]


def physical_specimens(cycle_id: str) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    rows = specimens_for_cycle(cycle_id)
    return {
        "cycle_id": cycle_id,
        "items": rows,
        "count": len(rows),
        "design_fingerprint": str(cycle.get("redesign_design_fingerprint") or ""),
        "physical_specimen_identity_verified_count": sum(bool(row.get("physical_specimen_identity_verified")) for row in rows),
        "policy": "Package generation and hashes are verifiable; physical specimen identity/package association remains an operator claim.",
    }


def specimen_for_run(cycle_id: str, specimen_id: str) -> dict[str, Any] | None:
    key = specimen_id.strip().casefold()
    return next(
        (
            row
            for row in specimens_for_cycle(cycle_id)
            if str(row.get("specimen_id") or "").strip().casefold() == key
        ),
        None,
    )
