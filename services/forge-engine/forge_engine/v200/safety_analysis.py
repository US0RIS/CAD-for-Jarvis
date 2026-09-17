from __future__ import annotations

"""Canonical safety/failure-mode analysis for ForgeCAD 2.0.

Safety is project state, not a paragraph in the agent response. Failure modes carry an
explicit consequence, severity, optional occurrence/detection rankings, controls and a
verification method. RPN is computed only when all three ordinal inputs are explicit;
ForgeCAD never invents failure probabilities from prose.

High-severity hazards fail closed until current-design verification evidence is recorded
through the human verification endpoint. The engineering agent may add/update/delete
failure modes and propose controls, but ordinary typed plan operations cannot mark a
hazard verified.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import physical_evidence


_INSTALLED = False
_PREVIOUS_EXECUTE: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_VALIDATION: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_SNAPSHOT: Callable[..., dict[str, Any]] | None = None
_CATEGORIES = {"mechanical", "electrical", "thermal", "fluid", "software", "control", "human", "environmental", "manufacturing", "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rank(value: Any, label: str, *, required: bool = False) -> int | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{label} is required")
        return None
    try:
        rank = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer from 1 to 10") from exc
    if rank < 1 or rank > 10:
        raise ValueError(f"{label} must be an integer from 1 to 10")
    return rank


def _object_ids(value: Any, project: dict[str, Any]) -> list[str]:
    if value in (None, ""):
        return []
    raw = value if isinstance(value, list) else [value]
    known = {str(obj.get("id")) for obj in project.get("objects") or [] if isinstance(obj, dict) and obj.get("id")}
    out: list[str] = []
    for item in raw:
        object_id = str(item)
        if object_id not in known:
            raise ValueError(f"Failure mode references unknown object {object_id}")
        if object_id not in out:
            out.append(object_id)
    return out


def _controls(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    raw = value if isinstance(value, list) else [value]
    out = [str(item).strip() for item in raw if str(item).strip()]
    return list(dict.fromkeys(out))


def normalize_failure_mode(raw: dict[str, Any], project: dict[str, Any], *, failure_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Failure mode must be an object")
    name = str(raw.get("name") or raw.get("failure") or "").strip()
    effect = str(raw.get("effect") or raw.get("consequence") or "").strip()
    if not name:
        raise ValueError("Failure mode name is required")
    if not effect:
        raise ValueError("Failure mode effect/consequence is required")
    category = str(raw.get("category") or "other").strip().lower()
    if category not in _CATEGORIES:
        raise ValueError("failure mode category must be mechanical, electrical, thermal, fluid, software, control, human, environmental, manufacturing, or other")
    severity = _rank(raw.get("severity"), "severity", required=True)
    occurrence = _rank(raw.get("occurrence"), "occurrence")
    detection = _rank(raw.get("detection"), "detection")
    verification_method = str(raw.get("verification_method") or raw.get("verification") or "").strip()
    controls = _controls(raw.get("controls", raw.get("mitigations")))
    evidence = [deepcopy(row) for row in raw.get("verification_evidence") or [] if isinstance(row, dict)]
    return {
        "id": failure_id or str(raw.get("id") or core.uid()),
        "name": name,
        "category": category,
        "description": str(raw.get("description") or "").strip(),
        "cause": str(raw.get("cause") or "").strip(),
        "effect": effect,
        "object_ids": _object_ids(raw.get("object_ids", raw.get("object_id")), project),
        "severity": severity,
        "occurrence": occurrence,
        "detection": detection,
        "controls": controls,
        "verification_method": verification_method,
        "owner": str(raw.get("owner") or "").strip() or None,
        "notes": str(raw.get("notes") or raw.get("note") or "").strip(),
        "verification_evidence": evidence,
    }


def _current_verification(mode: dict[str, Any], project: dict[str, Any]) -> dict[str, Any] | None:
    fingerprint = physical_evidence.design_fingerprint(project)
    current = [
        row for row in mode.get("verification_evidence") or []
        if isinstance(row, dict) and str(row.get("design_fingerprint") or "") == fingerprint
    ]
    return deepcopy(current[-1]) if current else None


def analyze_safety(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    modes: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for index, raw in enumerate(source.get("failure_modes") or []):
        if not isinstance(raw, dict):
            risks.append({"severity": "error", "code": "failure_mode_invalid", "message": f"Failure mode record {index + 1} is not an object."})
            continue
        try:
            mode = normalize_failure_mode(raw, source, failure_id=str(raw.get("id") or core.uid()))
        except Exception as exc:
            risks.append({"severity": "error", "code": "failure_mode_invalid", "failure_mode_id": str(raw.get("id") or ""), "message": str(exc)})
            continue
        current = _current_verification(mode, source)
        occurrence = mode.get("occurrence")
        detection = mode.get("detection")
        rpn = int(mode["severity"] * occurrence * detection) if occurrence is not None and detection is not None else None
        status = str((current or {}).get("status") or "unverified")
        verified = status == "passed"
        row = {
            **deepcopy(mode),
            "rpn": rpn,
            "rpn_available": rpn is not None,
            "verification_status": status,
            "verification_current": current is not None,
            "current_verification": current,
            "stale_verification_count": sum(
                1 for evidence in mode.get("verification_evidence") or []
                if isinstance(evidence, dict) and str(evidence.get("design_fingerprint") or "") != physical_evidence.design_fingerprint(source)
            ),
            "verified_mitigated": bool(verified and mode.get("controls")),
        }
        modes.append(row)

        if status == "failed":
            risks.append({
                "severity": "error",
                "code": "failure_mode_verification_failed",
                "failure_mode_id": mode["id"],
                "message": f"Failure mode {mode['name']} failed current-design verification.",
            })
            continue
        if int(mode["severity"]) >= 8 and not row["verified_mitigated"]:
            risks.append({
                "severity": "error",
                "code": "critical_failure_mode_unverified",
                "failure_mode_id": mode["id"],
                "message": f"High-severity failure mode {mode['name']} (severity {mode['severity']}/10) requires explicit controls and current-design verification before release.",
            })
        elif int(mode["severity"]) >= 4 and not verified:
            risks.append({
                "severity": "warning",
                "code": "failure_mode_unverified",
                "failure_mode_id": mode["id"],
                "message": f"Failure mode {mode['name']} (severity {mode['severity']}/10) remains unverified for the current design.",
            })
        elif int(mode["severity"]) < 4 and not verified:
            risks.append({
                "severity": "info",
                "code": "failure_mode_open_low_severity",
                "failure_mode_id": mode["id"],
                "message": f"Low-severity failure mode {mode['name']} remains open/unverified.",
            })

        if not mode.get("controls") and int(mode["severity"]) >= 6:
            risks.append({
                "severity": "warning",
                "code": "failure_mode_controls_missing",
                "failure_mode_id": mode["id"],
                "message": f"Failure mode {mode['name']} has severity {mode['severity']}/10 but no explicit risk controls.",
            })
        if not mode.get("verification_method") and int(mode["severity"]) >= 6:
            risks.append({
                "severity": "warning",
                "code": "failure_mode_verification_method_missing",
                "failure_mode_id": mode["id"],
                "message": f"Failure mode {mode['name']} has no explicit verification method.",
            })

    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    return {
        "solver": "ForgeCAD SafetyRegister",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_process",
        "count": len(modes),
        "failure_modes": modes,
        "ok": counts["error"] == 0,
        "counts": counts,
        "risks": risks,
        "policy": {
            "critical_severity_threshold": 8,
            "rpn": "severity × occurrence × detection, reported only when all three 1–10 ordinal rankings are explicitly supplied",
            "verification": "High-severity modes require controls plus current-design verification evidence. Agent plan operations cannot self-certify verification.",
        },
        "limitations": [
            "Ordinal severity/occurrence/detection rankings are engineering inputs, not measured probabilities.",
            "RPN is a prioritization heuristic and is never treated as an absolute safety proof.",
            "Hazard discovery is not guaranteed exhaustive; domain standards, specialist review and physical validation remain required where applicable.",
            "A passed verification record applies only to the exact current design fingerprint.",
        ],
        "physical_verification": False,
    }


class FailureVerificationRequest(BaseModel):
    status: Literal["passed", "failed", "inconclusive"]
    method: str
    note: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


def verify_failure_mode(failure_mode_id: str, request: FailureVerificationRequest) -> dict[str, Any]:
    mode = next((row for row in core.PROJECT.get("failure_modes") or [] if isinstance(row, dict) and str(row.get("id")) == failure_mode_id), None)
    if mode is None:
        raise KeyError(failure_mode_id)
    method = str(request.method or "").strip()
    if not method:
        raise ValueError("Failure-mode verification method is required")
    evidence = {
        "id": core.uid(),
        "kind": "failure_mode_verification",
        "at": _now(),
        "branch": core.ACTIVE_DESIGN,
        "design_fingerprint": physical_evidence.design_fingerprint(),
        "failure_mode_id": failure_mode_id,
        "status": request.status,
        "method": method,
        "note": request.note,
        "evidence_ids": list(request.evidence_ids),
        "physical_evidence": True,
    }
    with core.LOCK:
        mode.setdefault("verification_evidence", []).append(deepcopy(evidence))
        core.PROJECT.setdefault("notebook", []).append(deepcopy(evidence))
        core.PROJECT.setdefault("ledger", []).append({
            "at": evidence["at"],
            "actor": "human",
            "action": "verify_failure_mode",
            "reason": f"{failure_mode_id}: {request.status} via {method}",
            "design": core.ACTIVE_DESIGN,
        })
        core.BRANCHES[core.ACTIVE_DESIGN] = deepcopy(core.PROJECT)
        core.persist()
    return deepcopy(evidence)


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _PREVIOUS_EXECUTE is not None
    payload = deepcopy(args or {})
    if op not in {"add_failure_mode", "update_failure_mode", "delete_failure_mode"}:
        return _PREVIOUS_EXECUTE(op, payload, actor=actor, reason=reason)

    with core.LOCK:
        core.ensure_mutable(actor, reason or op)
        modes = core.PROJECT.setdefault("failure_modes", [])
        if not isinstance(modes, list):
            raise ValueError("project.failure_modes must be a list")
        if op == "add_failure_mode":
            # Verification evidence is always created through the explicit human endpoint.
            payload.pop("verification_evidence", None)
            mode = normalize_failure_mode(payload, core.PROJECT)
            modes.append(mode)
            result_mode = mode
        elif op == "update_failure_mode":
            failure_id = str(payload.get("id") or "")
            index = next((i for i, row in enumerate(modes) if isinstance(row, dict) and str(row.get("id") or "") == failure_id), None)
            if index is None:
                raise KeyError(f"Failure mode not found: {failure_id}")
            merged = deepcopy(modes[index])
            existing_evidence = deepcopy(merged.get("verification_evidence") or [])
            merged.update({key: value for key, value in payload.items() if key not in {"id", "verification_evidence"}})
            merged["verification_evidence"] = existing_evidence
            mode = normalize_failure_mode(merged, core.PROJECT, failure_id=failure_id)
            modes[index] = mode
            result_mode = mode
        else:
            failure_id = str(payload.get("id") or "")
            index = next((i for i, row in enumerate(modes) if isinstance(row, dict) and str(row.get("id") or "") == failure_id), None)
            if index is None:
                raise KeyError(f"Failure mode not found: {failure_id}")
            result_mode = modes.pop(index)
        core.mark_simulations_stale(None)
        core.push_history(op, actor, reason or op)
        core.persist()
    return {"ok": True, "op": op, "failure_mode": deepcopy(result_mode), "project": core.PROJECT, "active_design": core.ACTIVE_DESIGN}


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    safety = analyze_safety(core.PROJECT)
    combined = list(base.get("risks") or []) + list(safety.get("risks") or [])
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in combined:
        if not isinstance(risk, dict):
            continue
        key = (
            str(risk.get("code") or ""),
            str(risk.get("failure_mode_id") or risk.get("route_id") or risk.get("object_id") or risk.get("link_id") or risk.get("connection_id") or ""),
            str(risk.get("message") or ""),
        )
        deduped[key] = risk
    risks = sorted(deduped.values(), key=lambda risk: ({"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3), str(risk.get("code") or ""), str(risk.get("message") or "")))
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["safety"] = safety
    return base


def _snapshot(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_SNAPSHOT is not None
    result = _ORIGINAL_SNAPSHOT(self)
    result["failure_modes"] = deepcopy(core.PROJECT.get("failure_modes") or [])
    result["safety"] = analyze_safety(core.PROJECT)
    return result


def install(legacy: Any) -> None:
    global _INSTALLED, _PREVIOUS_EXECUTE, _ORIGINAL_VALIDATION, _ORIGINAL_SNAPSHOT
    if _INSTALLED:
        return
    core.PROJECT.setdefault("failure_modes", [])
    _PREVIOUS_EXECUTE = core.execute
    core.execute = _execute
    _ORIGINAL_VALIDATION = EngineeringProject.validation
    EngineeringProject.validation = _validation
    _ORIGINAL_SNAPSHOT = EngineeringProject.snapshot
    EngineeringProject.snapshot = _snapshot
    app = legacy.app

    @app.get("/v2/safety/failure-modes", dependencies=[Depends(legacy.require_session)])
    async def failure_modes() -> dict[str, Any]:
        return {"failure_modes": deepcopy(core.PROJECT.get("failure_modes") or []), "analysis": analyze_safety(core.PROJECT)}

    @app.get("/v2/analysis/safety", dependencies=[Depends(legacy.require_session)])
    async def safety_analysis() -> dict[str, Any]:
        return analyze_safety(core.PROJECT)

    @app.post("/v2/safety/failure-modes/{failure_mode_id}/verify", dependencies=[Depends(legacy.require_session)])
    async def verify_mode(failure_mode_id: str, request: FailureVerificationRequest) -> dict[str, Any]:
        try:
            evidence = verify_failure_mode(failure_mode_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Failure mode not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"evidence": evidence, "project": snapshot, "validation": legacy.PROJECT.validation()}

    _INSTALLED = True
