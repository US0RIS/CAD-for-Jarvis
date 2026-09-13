from __future__ import annotations

"""Canonical real-world evidence for ForgeCAD 2.0.

Simulation results are predictions. A prototype, measurement, or test is evidence. This
module keeps the distinction explicit and branch-local. Evidence is bound to a stable
fingerprint of the exact engineering design that was manufactured/tested. If CAD, code,
connections, BOM, loads, constraints, or requirements change, the old evidence remains
in history but no longer satisfies the current design's requirement gate.

Recording evidence never silently marks a branch physically verified; branch status
remains an explicit user action through the existing branch-status contract.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core


_INSTALLED = False
_ORIGINAL_REQUIREMENT_CHECKS = None
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint_requirement(requirement: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(requirement)
    # Verification records are observations about a design, not inputs defining it. If
    # they were hashed, recording evidence would immediately invalidate itself.
    row.pop("verification_evidence", None)
    row.pop("verification_status", None)
    row.pop("last_verified_at", None)
    return row


def design_fingerprint(project: dict[str, Any] | None = None) -> str:
    """Content hash for the engineering state to which physical evidence applies.

    Historical/audit data, simulations and evidence are deliberately excluded. Geometry,
    software attached to objects, electrical/mechanical connectivity, requirements, loads,
    constraints and BOM identity are included so evidence fails closed after a meaningful
    design change.
    """
    source = project if project is not None else core.PROJECT
    payload = {
        "objects": deepcopy(source.get("objects") or []),
        "joints": deepcopy(source.get("joints") or []),
        "loads": deepcopy(source.get("loads") or []),
        "constraints": deepcopy(source.get("constraints") or []),
        "requirements": [
            _fingerprint_requirement(row)
            for row in (source.get("requirements") or [])
            if isinstance(row, dict)
        ],
        "bom": deepcopy(source.get("bom") or []),
        "connections": deepcopy(source.get("connections") or []),
        "settings": deepcopy(source.get("settings") or {}),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class Measurement(BaseModel):
    name: str
    value: float
    unit: str = ""
    tolerance: float | None = None


class ManufacturingEvidenceRequest(BaseModel):
    package_sha256: str | None = None
    resource_id: str = "bambu-lab-p2s"
    outcome: Literal["success", "failure", "partial", "inconclusive"]
    material: str | None = None
    machine_profile: str | None = None
    process_profile: str | None = None
    filament_profiles: list[str] = Field(default_factory=list)
    slicer: str | None = "Bambu Studio"
    slicer_version: str | None = None
    estimated_duration_s: float | None = None
    actual_duration_s: float | None = None
    estimated_material_g: float | None = None
    actual_material_g: float | None = None
    measurements: list[Measurement] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    note: str = ""


class RequirementEvidenceRequest(BaseModel):
    status: Literal["passed", "failed", "inconclusive"]
    method: str
    note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)


def evidence_applies(row: dict[str, Any], project: dict[str, Any] | None = None) -> bool:
    fingerprint = str(row.get("design_fingerprint") or "")
    # Legacy evidence without a fingerprint remains visible but cannot certify a changed
    # design. Failing closed is safer than guessing whether old evidence is still valid.
    return bool(fingerprint and fingerprint == design_fingerprint(project))


def _append_evidence(item: dict[str, Any], action: str, reason: str) -> dict[str, Any]:
    with core.LOCK:
        core.PROJECT.setdefault("notebook", []).append(deepcopy(item))
        core.PROJECT.setdefault("ledger", []).append({
            "at": _now(),
            "actor": "human",
            "action": action,
            "reason": reason,
            "design": core.ACTIVE_DESIGN,
        })
        core.PROJECT["ledger"] = core.PROJECT["ledger"][-500:]
        core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
        core.persist()
    return deepcopy(item)


def record_manufacturing_evidence(request: ManufacturingEvidenceRequest) -> dict[str, Any]:
    package_hash = request.package_sha256.lower() if request.package_sha256 else None
    if package_hash is not None and not _SHA256.fullmatch(package_hash):
        raise ValueError("package_sha256 must be a 64-character SHA-256 hex digest")
    evidence_id = core.uid()
    fingerprint = design_fingerprint()
    item = {
        "id": evidence_id,
        "kind": "manufacturing_evidence",
        "at": _now(),
        "branch": core.ACTIVE_DESIGN,
        "project_name": str(core.PROJECT.get("name") or "Untitled Design"),
        "design_fingerprint": fingerprint,
        "package_sha256": package_hash,
        "resource_id": request.resource_id,
        "outcome": request.outcome,
        "material": request.material,
        "machine_profile": request.machine_profile,
        "process_profile": request.process_profile,
        "filament_profiles": list(request.filament_profiles),
        "slicer": request.slicer,
        "slicer_version": request.slicer_version,
        "estimated_duration_s": request.estimated_duration_s,
        "actual_duration_s": request.actual_duration_s,
        "estimated_material_g": request.estimated_material_g,
        "actual_material_g": request.actual_material_g,
        "measurements": [row.model_dump() for row in request.measurements],
        "observations": list(request.observations),
        "artifact_refs": list(request.artifact_refs),
        "note": request.note,
        "physical_evidence": True,
        "changes_design_status": False,
    }
    return _append_evidence(item, "record_manufacturing_evidence", f"Manufacturing outcome: {request.outcome}")


def verify_requirement(requirement_id: str, request: RequirementEvidenceRequest) -> dict[str, Any]:
    requirement = next((row for row in core.PROJECT.get("requirements", []) if str(row.get("id")) == requirement_id), None)
    if requirement is None:
        raise KeyError(requirement_id)
    evidence = {
        "id": core.uid(),
        "kind": "requirement_verification",
        "at": _now(),
        "branch": core.ACTIVE_DESIGN,
        "design_fingerprint": design_fingerprint(),
        "requirement_id": requirement_id,
        "status": request.status,
        "method": request.method,
        "note": request.note,
        "evidence_ids": list(request.evidence_ids),
        "measurements": [row.model_dump() for row in request.measurements],
        "physical_evidence": True,
    }
    with core.LOCK:
        requirement.setdefault("verification_evidence", []).append(deepcopy(evidence))
        requirement["verification_status"] = request.status
        requirement["last_verified_at"] = evidence["at"]
        core.PROJECT.setdefault("notebook", []).append(deepcopy(evidence))
        core.PROJECT.setdefault("ledger", []).append({
            "at": evidence["at"],
            "actor": "human",
            "action": "verify_requirement",
            "reason": f"{requirement_id}: {request.status} via {request.method}",
            "design": core.ACTIVE_DESIGN,
        })
        core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
        core.persist()
    return deepcopy(evidence)


def evidence_rows(kind: str | None = None) -> list[dict[str, Any]]:
    current = design_fingerprint()
    rows: list[dict[str, Any]] = []
    for raw in core.PROJECT.get("notebook", []):
        if not isinstance(raw, dict) or raw.get("kind") not in {"manufacturing_evidence", "requirement_verification"}:
            continue
        row = deepcopy(raw)
        fingerprint = str(row.get("design_fingerprint") or "")
        row["applies_to_current_design"] = bool(fingerprint and fingerprint == current)
        row["evidence_binding"] = "current" if row["applies_to_current_design"] else "stale" if fingerprint else "legacy_unbound"
        rows.append(row)
    if kind:
        rows = [row for row in rows if row.get("kind") == kind]
    return rows


def _requirement_checks_with_evidence() -> list[dict[str, Any]]:
    assert _ORIGINAL_REQUIREMENT_CHECKS is not None
    rows = _ORIGINAL_REQUIREMENT_CHECKS()
    requirements = {str(row.get("id")): row for row in core.PROJECT.get("requirements", []) if isinstance(row, dict)}
    current = design_fingerprint()
    for result in rows:
        requirement = requirements.get(str(result.get("id")))
        evidence = [deepcopy(row) for row in (requirement or {}).get("verification_evidence") or [] if isinstance(row, dict)]
        applicable = [row for row in evidence if str(row.get("design_fingerprint") or "") == current]
        latest = applicable[-1] if applicable else None
        latest_any = evidence[-1] if evidence else None
        result["verification_evidence"] = evidence
        result["applicable_verification_evidence"] = deepcopy(applicable)
        result["stale_evidence_count"] = len(evidence) - len(applicable)
        result["verification_status"] = (latest or {}).get("status") if latest else ("stale" if latest_any else None)
        result["verification_method"] = (latest or {}).get("method")
        result["physical_verification_current"] = latest is not None
        result["design_fingerprint"] = current
        # Quantitative deterministic checks remain authoritative if a metric exists.
        # Physical evidence fills qualitative requirements only when it was recorded
        # against the exact current engineering design fingerprint.
        if result.get("passed") is None and latest is not None:
            if latest.get("status") == "passed":
                result["passed"] = True
            elif latest.get("status") == "failed":
                result["passed"] = False
    return rows


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_REQUIREMENT_CHECKS
    if _INSTALLED:
        return
    _ORIGINAL_REQUIREMENT_CHECKS = core.requirement_checks
    core.requirement_checks = _requirement_checks_with_evidence
    app = legacy.app

    @app.get("/v2/evidence", dependencies=[Depends(legacy.require_session)])
    async def list_evidence(kind: str | None = None) -> dict[str, Any]:
        rows = evidence_rows(kind)
        return {
            "branch": core.ACTIVE_DESIGN,
            "design_fingerprint": design_fingerprint(),
            "items": rows,
            "count": len(rows),
            "current_count": sum(bool(row.get("applies_to_current_design")) for row in rows),
        }

    @app.post("/v2/evidence/manufacturing", dependencies=[Depends(legacy.require_session)])
    async def manufacturing_evidence(request: ManufacturingEvidenceRequest) -> dict[str, Any]:
        try:
            evidence = record_manufacturing_evidence(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"evidence": evidence, "project": snapshot}

    @app.post("/v2/requirements/{requirement_id}/verify", dependencies=[Depends(legacy.require_session)])
    async def requirement_evidence(requirement_id: str, request: RequirementEvidenceRequest) -> dict[str, Any]:
        try:
            evidence = verify_requirement(requirement_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Requirement not found") from exc
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"evidence": evidence, "project": snapshot, "validation": legacy.PROJECT.validation()}

    _INSTALLED = True
