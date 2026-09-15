from __future__ import annotations

"""Content-addressed physical-test artifacts for ForgeCAD 6.0 milestone 5.

Artifact metadata is evidence, not design truth, so records live in canonical project
physical evidence state and are deliberately excluded from the design fingerprint.
When inline bytes are supplied ForgeCAD verifies SHA-256 and byte length itself before
recording the descriptor. For external references ForgeCAD preserves the caller's hash
but marks content integrity as unverified rather than claiming it inspected the file.
Raw inline bytes are never persisted in the project record.

Artifact requirements are locked onto a pending retest before artifact submission. The
normal retest completion route checks that contract, so callers cannot bypass a planned
trace/photo/report requirement by omitting the files at completion time.
"""

import base64
import binascii
from copy import deepcopy
import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core
from ..v200.physical_evidence import design_fingerprint
from ..v310.engineering_graph import EngineeringEvidence, EngineeringGraphStore


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


ArtifactKind = Literal["sensor_trace", "photo", "video", "log", "report", "other"]


class PhysicalArtifactDescriptor(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    kind: ArtifactKind
    media_type: str = Field(min_length=1, max_length=128)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0, le=10_000_000_000)
    source_ref: str | None = Field(default=None, max_length=2048)
    content_base64: str | None = Field(default=None, max_length=2_000_000)
    captured_at: str | None = Field(default=None, max_length=128)
    note: str = Field(default="", max_length=2000)
    object_ids: list[str] = Field(default_factory=list, max_length=32)


class PhysicalArtifactRequirement(BaseModel):
    kind: ArtifactKind
    min_count: int = Field(default=1, ge=1, le=16)
    require_integrity_verified: bool = True


class PhysicalArtifactContractRequest(BaseModel):
    requirements: list[PhysicalArtifactRequirement] = Field(min_length=1, max_length=8)


class PhysicalArtifactSubmissionRequest(BaseModel):
    artifacts: list[PhysicalArtifactDescriptor] = Field(min_length=1, max_length=16)


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
        raise ValueError(f"Physical artifact operation requires a pending retest cycle, got {cycle.get('status')}")
    if core.ACTIVE_DESIGN != str(cycle.get("redesign_branch") or ""):
        raise ValueError("Physical artifact operation must occur on the redesign branch")
    expected = str(cycle.get("redesign_design_fingerprint") or "")
    current = design_fingerprint()
    if not expected or current != expected:
        raise ValueError("Physical artifact operation rejected because the redesign fingerprint changed")


def _normalized_requirements(requirements: list[PhysicalArtifactRequirement]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for requirement in requirements:
        if requirement.kind in seen:
            raise ValueError(f"Physical artifact requirement kind {requirement.kind!r} is duplicated")
        seen.add(requirement.kind)
        rows.append(requirement.model_dump())
    return rows


def validate_artifact_requirements(requirements: list[PhysicalArtifactRequirement]) -> list[dict[str, Any]]:
    return _normalized_requirements(requirements)


def set_artifact_contract(cycle_id: str, request: PhysicalArtifactContractRequest) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("artifact_requirements"):
        raise ValueError("Physical artifact contract is already locked for this retest cycle")
    if any(str(row.get("cycle_id")) == cycle_id for row in core.PROJECT.get("physical_test_artifacts") or []):
        raise ValueError("Physical artifact contract cannot be changed after artifact submission")
    requirements = validate_artifact_requirements(request.requirements)
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["artifact_requirements"] = deepcopy(requirements)
        cycle["artifact_contract_design_fingerprint"] = design_fingerprint()
        cycle["artifact_contract_locked"] = True
        cycle["artifact_ids"] = []
        cycle["artifact_submission_complete"] = False
        core.push_history(
            "v6 physical artifact contract",
            "human",
            f"locked {len(requirements)} physical artifact requirement(s) for cycle {cycle_id}",
        )
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "design_fingerprint": design_fingerprint(),
        "requirements": deepcopy(requirements),
        "locked": True,
    }


def _decode_and_verify(descriptor: PhysicalArtifactDescriptor) -> tuple[bool, str]:
    digest = descriptor.sha256.lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"Physical artifact {descriptor.name!r} sha256 must be a 64-character hexadecimal digest")
    if descriptor.content_base64 is None:
        if not (descriptor.source_ref or "").strip():
            raise ValueError(
                f"Physical artifact {descriptor.name!r} must provide either inline content_base64 or an external source_ref"
            )
        return False, "declared_hash_unverified_content"
    try:
        payload = base64.b64decode(descriptor.content_base64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as exc:
        raise ValueError(f"Physical artifact {descriptor.name!r} content_base64 is invalid") from exc
    if len(payload) != descriptor.size_bytes:
        raise ValueError(
            f"Physical artifact {descriptor.name!r} byte length {len(payload)} does not match declared size {descriptor.size_bytes}"
        )
    computed = hashlib.sha256(payload).hexdigest()
    if computed != digest:
        raise ValueError(
            f"Physical artifact {descriptor.name!r} SHA-256 mismatch: computed {computed}, declared {digest}"
        )
    return True, "verified_inline_content"


def prepare_physical_artifacts(
    descriptors: list[PhysicalArtifactDescriptor],
    requirements: list[dict[str, Any]],
    *,
    cycle_id: str,
    requirement_id: str,
    design_fingerprint: str,
    default_object_ids: list[str],
) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    allowed_objects = {str(row) for row in default_object_ids}
    for descriptor in descriptors:
        digest = descriptor.sha256.lower()
        if digest in seen_hashes:
            raise ValueError(f"Physical retest contains duplicate artifact SHA-256 {digest}")
        seen_hashes.add(digest)
        integrity_verified, integrity_status = _decode_and_verify(descriptor)
        object_ids = [str(row) for row in descriptor.object_ids] or sorted(allowed_objects)
        if len(object_ids) != len(set(object_ids)):
            raise ValueError(f"Physical artifact {descriptor.name!r} contains duplicate object identities")
        if allowed_objects and any(object_id not in allowed_objects for object_id in object_ids):
            outside = sorted(object_id for object_id in object_ids if object_id not in allowed_objects)
            raise ValueError(
                f"Physical artifact {descriptor.name!r} references objects outside the retest requirement scope: {outside}"
            )
        for object_id in object_ids:
            core.object_by_id(object_id)
        prepared.append({
            "id": core.uid(),
            "kind": "physical_test_artifact",
            "artifact_kind": descriptor.kind,
            "name": descriptor.name.strip(),
            "media_type": descriptor.media_type.strip(),
            "sha256": digest,
            "size_bytes": int(descriptor.size_bytes),
            "source_ref": (descriptor.source_ref or "").strip() or None,
            "captured_at": descriptor.captured_at,
            "note": descriptor.note,
            "object_ids": object_ids,
            "requirement_id": requirement_id,
            "cycle_id": cycle_id,
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": design_fingerprint,
            "integrity_verified": integrity_verified,
            "integrity_status": integrity_status,
            "content_persisted": False,
            "inspection_ids": [],
            "physical_evidence": True,
        })

    counts: dict[str, int] = {}
    verified_counts: dict[str, int] = {}
    for row in prepared:
        kind = str(row["artifact_kind"])
        counts[kind] = counts.get(kind, 0) + 1
        if row["integrity_verified"]:
            verified_counts[kind] = verified_counts.get(kind, 0) + 1
    for requirement in requirements:
        kind = str(requirement.get("kind") or "")
        minimum = int(requirement.get("min_count", 1))
        actual = verified_counts.get(kind, 0) if requirement.get("require_integrity_verified", True) else counts.get(kind, 0)
        if actual < minimum:
            qualifier = "integrity-verified " if requirement.get("require_integrity_verified", True) else ""
            raise ValueError(
                f"Physical retest requires at least {minimum} {qualifier}{kind} artifact(s); received {actual}"
            )
    return prepared


def register_physical_artifacts(
    prepared: list[dict[str, Any]],
    *,
    inspection_ids: list[str],
) -> list[dict[str, Any]]:
    if not prepared:
        return []
    current_fingerprint = None
    for row in prepared:
        fingerprint = str(row.get("design_fingerprint") or "")
        if current_fingerprint is None:
            current_fingerprint = fingerprint
        elif fingerprint != current_fingerprint:
            raise ValueError("Prepared physical artifacts do not share one design fingerprint")
    rows = []
    with core.LOCK:
        collection = core.PROJECT.setdefault("physical_test_artifacts", [])
        for prepared_row in prepared:
            row = deepcopy(prepared_row)
            row["inspection_ids"] = list(inspection_ids)
            collection.append(row)
            rows.append(deepcopy(row))
        core.push_history(
            "v6 physical test artifacts",
            "human",
            f"recorded {len(rows)} content-addressed physical test artifact(s)",
        )
        core.persist()
    return rows


def _artifact_evidence(row: dict[str, Any]) -> EngineeringEvidence:
    verified = bool(row.get("integrity_verified"))
    return EngineeringEvidence(
        id=f"physical-artifact:{row['id']}",
        kind="physical_test_artifact",
        subject_node_ids=[f"cad:{object_id}" for object_id in row.get("object_ids") or []],
        requirement_ids=[str(row.get("requirement_id"))] if row.get("requirement_id") else [],
        value=str(row.get("sha256") or ""),
        status="verified_content" if verified else "declared_unverified_content",
        method="sha256_inline_content_verification" if verified else "caller_declared_external_hash",
        source_ids=[str(row.get("id"))],
        assumptions=[] if verified else ["artifact bytes were not available to ForgeCAD; content hash remains caller-declared"],
        confidence=1.0 if verified else 0.5,
        metadata=deepcopy(row),
    )


def project_artifacts_to_graph(graph: EngineeringGraphStore, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for row in rows:
        evidence = graph.add_evidence(_artifact_evidence(row))
        projected.append(evidence.model_dump(mode="json"))
    return projected


def submit_artifacts(
    cycle_id: str,
    request: PhysicalArtifactSubmissionRequest,
    graph: EngineeringGraphStore,
) -> dict[str, Any]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    if cycle.get("artifact_submission_complete"):
        raise ValueError("Physical artifact submission is already complete for this retest cycle")
    requirements = deepcopy(cycle.get("artifact_requirements") or [])
    scope = [str(row) for row in cycle.get("scope_object_ids") or []]
    if not scope:
        scope = sorted({
            str(row.get("object_id"))
            for row in cycle.get("test_criteria") or []
            if row.get("object_id")
        })
    prepared = prepare_physical_artifacts(
        request.artifacts,
        requirements,
        cycle_id=cycle_id,
        requirement_id=str(cycle.get("requirement_id") or ""),
        design_fingerprint=design_fingerprint(),
        default_object_ids=scope,
    )
    rows = register_physical_artifacts(prepared, inspection_ids=[])
    graph_evidence = project_artifacts_to_graph(graph, rows)
    with core.LOCK:
        cycle = _cycle(cycle_id)
        cycle["artifact_ids"] = [str(row["id"]) for row in rows]
        cycle["artifact_evidence_ids"] = [str(row["id"]) for row in graph_evidence]
        cycle["artifact_submission_complete"] = True
        core.persist()
    return {
        "ok": True,
        "cycle_id": cycle_id,
        "items": deepcopy(rows),
        "count": len(rows),
        "graph_evidence": graph_evidence,
        "integrity_verified_count": sum(bool(row.get("integrity_verified")) for row in rows),
    }


def artifact_records_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    return [
        deepcopy(row)
        for row in core.PROJECT.get("physical_test_artifacts") or []
        if str(row.get("cycle_id")) == cycle_id
    ]


def assert_artifact_contract_satisfied(cycle_id: str) -> list[dict[str, Any]]:
    cycle = _cycle(cycle_id)
    _assert_pending_current_cycle(cycle)
    requirements = deepcopy(cycle.get("artifact_requirements") or [])
    if not requirements:
        return artifact_records_for_cycle(cycle_id)
    if not cycle.get("artifact_submission_complete"):
        raise ValueError("Physical retest artifact contract is not satisfied: no completed artifact submission")
    rows = artifact_records_for_cycle(cycle_id)
    counts: dict[str, int] = {}
    verified_counts: dict[str, int] = {}
    for row in rows:
        kind = str(row.get("artifact_kind") or "")
        counts[kind] = counts.get(kind, 0) + 1
        if row.get("integrity_verified"):
            verified_counts[kind] = verified_counts.get(kind, 0) + 1
    for requirement in requirements:
        kind = str(requirement.get("kind") or "")
        minimum = int(requirement.get("min_count", 1))
        actual = verified_counts.get(kind, 0) if requirement.get("require_integrity_verified", True) else counts.get(kind, 0)
        if actual < minimum:
            qualifier = "integrity-verified " if requirement.get("require_integrity_verified", True) else ""
            raise ValueError(
                f"Physical retest artifact contract is not satisfied: requires {minimum} {qualifier}{kind} artifact(s), has {actual}"
            )
    return rows


def link_cycle_artifacts_to_inspections(
    cycle_id: str,
    inspection_ids: list[str],
    graph: EngineeringGraphStore,
) -> list[dict[str, Any]]:
    rows = artifact_records_for_cycle(cycle_id)
    if not rows:
        return []
    updated: list[dict[str, Any]] = []
    wanted_ids = {str(row["id"]) for row in rows}
    with core.LOCK:
        for row in core.PROJECT.get("physical_test_artifacts") or []:
            if str(row.get("id")) in wanted_ids:
                row["inspection_ids"] = list(inspection_ids)
                updated.append(deepcopy(row))
        core.persist()
    project_artifacts_to_graph(graph, updated)
    return updated


def artifact_evidence_ids(cycle_id: str) -> list[str]:
    cycle = _cycle(cycle_id)
    return [str(row) for row in cycle.get("artifact_evidence_ids") or []]


def physical_test_artifacts(cycle_id: str | None = None) -> dict[str, Any]:
    rows = deepcopy(core.PROJECT.get("physical_test_artifacts") or [])
    if cycle_id is not None:
        rows = [row for row in rows if str(row.get("cycle_id")) == cycle_id]
    return {
        "items": rows,
        "count": len(rows),
        "active_branch": core.ACTIVE_DESIGN,
        "integrity_verified_count": sum(bool(row.get("integrity_verified")) for row in rows),
        "policy": "Inline bytes are SHA-256 verified and discarded after hashing; external references remain explicitly unverified unless their bytes are supplied.",
    }
