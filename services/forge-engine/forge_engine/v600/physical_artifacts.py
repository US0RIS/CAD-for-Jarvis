from __future__ import annotations

"""Content-addressed physical-test artifacts for ForgeCAD 6.0 milestone 5.

Artifact metadata is evidence, not design truth, so records live in canonical project
physical evidence state and are deliberately excluded from the design fingerprint.
When inline bytes are supplied ForgeCAD verifies SHA-256 and byte length itself before
recording the descriptor. For external references ForgeCAD preserves the caller's hash
but marks content integrity as unverified rather than claiming it inspected the file.
Raw inline bytes are never persisted in the project record.
"""

import base64
import binascii
from copy import deepcopy
import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..v110 import core


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


def physical_test_artifacts() -> dict[str, Any]:
    rows = deepcopy(core.PROJECT.get("physical_test_artifacts") or [])
    return {
        "items": rows,
        "count": len(rows),
        "active_branch": core.ACTIVE_DESIGN,
        "integrity_verified_count": sum(bool(row.get("integrity_verified")) for row in rows),
        "policy": "Inline bytes are SHA-256 verified and discarded after hashing; external references remain explicitly unverified unless their bytes are supplied.",
    }
