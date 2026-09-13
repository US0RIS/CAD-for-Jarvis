from __future__ import annotations

"""Canonical real-world evidence for ForgeCAD 2.0.

Simulation results are predictions. A prototype, measurement, or test is evidence. This
module keeps the distinction explicit and branch-local. Recording evidence does not
silently change CAD geometry or mark a design physically verified; branch status remains
an explicit user action through the existing branch-status contract.
"""

from copy import deepcopy
from datetime import datetime, timezone
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
    item = {
        "id": evidence_id,
        "kind": "manufacturing_evidence",
        "at": _now(),
        "branch": core.ACTIVE_DESIGN,
        "project_name": str(core.PROJECT.get("name") or "Untitled Design"),
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
    rows = [
        deepcopy(row)
        for row in core.PROJECT.get("notebook", [])
        if isinstance(row, dict) and row.get("kind") in {"manufacturing_evidence", "requirement_verification"}
    ]
    if kind:
        rows = [row for row in rows if row.get("kind") == kind]
    return rows


def _requirement_checks_with_evidence() -> list[dict[str, Any]]:
    assert _ORIGINAL_REQUIREMENT_CHECKS is not None
    rows = _ORIGINAL_REQUIREMENT_CHECKS()
    requirements = {str(row.get("id")): row for row in core.PROJECT.get("requirements", []) if isinstance(row, dict)}
    for result in rows:
        requirement = requirements.get(str(result.get("id")))
        evidence = list((requirement or {}).get("verification_evidence") or [])
        latest = evidence[-1] if evidence else None
        result["verification_evidence"] = deepcopy(evidence)
        result["verification_status"] = (latest or {}).get("status")
        result["verification_method"] = (latest or {}).get("method")
        # Quantitative deterministic checks remain authoritative if a metric exists.
        # Physical evidence fills qualitative requirements that otherwise have no metric.
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
        return {"branch": core.ACTIVE_DESIGN, "items": rows, "count": len(rows)}

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
