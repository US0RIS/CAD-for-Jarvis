from __future__ import annotations

"""Canonical project-SolidFEA gating for ForgeCAD 2.0 autonomous campaigns.

The campaign engine originally used the reduced-order cantilever screen because no
project-defined 3D boundary-condition solver existed yet. Once a design contains
canonical loads/supports, an optimizer must not rank geometry against a different hidden
load case. This adapter post-processes every generated sibling branch with the same
project SolidFEA contract used by interactive simulation, replaces structural campaign
gates/scores with that result, and reselects the winner.

If no project BC targets the optimized object, the existing preview campaign behavior is
left intact. If project BCs *do* target it but are unsupported/incomplete, candidates fail
closed instead of silently falling back to the implicit cantilever.
"""

from copy import deepcopy
import math
from types import MethodType
from typing import Any

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import project_structural


_INSTALLED = False
_ORIGINAL_RUN_CAMPAIGN = None


def _constraint_number(result: dict[str, Any], key: str, default: float) -> float:
    value = (result.get("constraints") or {}).get(key, default)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return number if math.isfinite(number) else default


def _rescore(objective: str, row: dict[str, Any], solid: dict[str, Any]) -> float:
    objective = objective.lower().strip()
    if objective in {"deflection", "displacement", "stiffness"}:
        return float(solid.get("max_displacement_mm", float("inf")))
    if objective in {"safety", "safety_margin", "fos"}:
        return -float(solid.get("yield_fos", 0.0))
    if objective in {"temperature", "thermal"}:
        return float((row.get("thermal") or {}).get("max_temperature_c", float("inf")))
    return float((row.get("metrics") or {}).get("mass_kg", float("inf")))


def _replace_structural_gates(row: dict[str, Any], solid: dict[str, Any], *, deflection_max_mm: float, yield_fos_min: float) -> None:
    verifier = row.setdefault("verifier", {"role": "verifier", "gates": {}})
    gates = verifier.setdefault("gates", {})
    legacy_consistency = gates.get("structural_consistency")
    verifier["legacy_preview_consistency"] = legacy_consistency
    verifier["structural_authority"] = "canonical_project_solid_fea"
    gates["project_boundary_conditions"] = True
    gates["structural_consistency"] = True
    gates["structural_equilibrium"] = float(solid.get("equilibrium_relative_error", float("inf"))) <= 1e-6
    gates["deflection"] = float(solid.get("max_displacement_mm", float("inf"))) <= deflection_max_mm
    gates["yield_fos"] = float(solid.get("yield_fos", 0.0)) >= yield_fos_min
    verifier["passed"] = all(bool(value) for value in gates.values())
    row["feasible"] = bool(verifier["passed"])


def _block_structural_gates(row: dict[str, Any], solid: dict[str, Any]) -> None:
    verifier = row.setdefault("verifier", {"role": "verifier", "gates": {}})
    gates = verifier.setdefault("gates", {})
    verifier["structural_authority"] = "canonical_project_solid_fea"
    verifier["project_structural_reason"] = solid.get("reason")
    gates["project_boundary_conditions"] = False
    verifier["passed"] = False
    row["feasible"] = False
    row["score"] = float("inf")


def _update_status(branch: str, feasible: bool) -> None:
    core.set_design_status(
        branch,
        "unverified" if feasible else "not_working",
        note=(
            "Passed autonomous campaign gates using canonical project SolidFEA; physical verification still required"
            if feasible
            else "Rejected by autonomous campaign gates using canonical project SolidFEA"
        ),
        physical_verified=False,
    )


def _run_campaign(self: EngineeringProject, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_CAMPAIGN is not None
    result = _ORIGINAL_RUN_CAMPAIGN(selected_object_id, payload)
    object_id = str(result.get("source_object_id") or selected_object_id or "")
    source_branch = str(result.get("source_branch") or core.ACTIVE_DESIGN)
    candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
    if not object_id or not candidates:
        return result

    # Determine whether the campaign source actually requested project-defined structural
    # physics. Absence means preserve the old preview behavior exactly.
    current_branch = core.ACTIVE_DESIGN
    try:
        core.switch_branch(source_branch)
        source_boundary = project_structural.project_boundary_conditions(core.PROJECT, object_id)
    finally:
        core.switch_branch(current_branch)

    result["project_structural_campaign"] = {
        "requested": bool(source_boundary.get("targeted_record_count")),
        "source_boundary_conditions": deepcopy(source_boundary),
        "policy": "canonical project loads/supports replace implicit structural preview gates when present",
    }
    if not source_boundary.get("targeted_record_count"):
        result["project_structural_campaign"]["applied"] = False
        return result

    objective = str(result.get("objective") or "mass")
    deflection_max_mm = _constraint_number(result, "deflection_max_mm", 1.0)
    yield_fos_min = _constraint_number(result, "yield_fos_min", 1.5)
    evaluated = 0
    supported = 0

    try:
        for row in candidates:
            if not isinstance(row, dict) or row.get("error"):
                continue
            branch = str(row.get("branch") or "")
            if not branch:
                continue
            core.switch_branch(branch)
            try:
                obj = core.object_by_id(object_id)
                solid = project_structural.solve_project_box(obj, core.PROJECT)
            except Exception as exc:
                solid = {
                    "supported": False,
                    "solver_grade": "evaluation_error",
                    "reason": str(exc),
                    "boundary_conditions": project_structural.project_boundary_conditions(core.PROJECT, object_id),
                }
            row["structural_project"] = solid
            evaluated += 1
            if solid.get("supported"):
                supported += 1
                _replace_structural_gates(
                    row,
                    solid,
                    deflection_max_mm=deflection_max_mm,
                    yield_fos_min=yield_fos_min,
                )
                row["score"] = _rescore(objective, row, solid)
            else:
                _block_structural_gates(row, solid)
            _update_status(branch, bool(row.get("feasible")))

        feasible = [
            row for row in candidates
            if isinstance(row, dict)
            and row.get("feasible")
            and math.isfinite(float(row.get("score", float("inf"))))
        ]
        feasible.sort(key=lambda row: (float(row["score"]), str(row.get("branch") or "")))
        winner = feasible[0] if feasible else None
        ranked = sorted(
            candidates,
            key=lambda row: (
                not bool(row.get("feasible")) if isinstance(row, dict) else True,
                float(row.get("score", float("inf"))) if isinstance(row, dict) else float("inf"),
                str(row.get("branch") or "") if isinstance(row, dict) else "",
            ),
        )
        result["candidates"] = ranked
        result["winner"] = deepcopy(winner)
        result["winner_branch"] = winner.get("branch") if winner else None
        result["status"] = "candidate_selected" if winner else "no_feasible_candidate"
        result.setdefault("roles", {}).setdefault("analyst", {})["structural_authority"] = "canonical_project_solid_fea"
        analyses = result.setdefault("roles", {}).setdefault("analyst", {}).setdefault("analyses", [])
        if "project_structural_3d" not in analyses:
            analyses.append("project_structural_3d")
        result.setdefault("roles", {}).setdefault("verifier", {})["equilibrium_gate"] = True
        result["project_structural_campaign"].update({
            "applied": True,
            "evaluated_candidates": evaluated,
            "supported_candidates": supported,
            "deflection_max_mm": deflection_max_mm,
            "yield_fos_min": yield_fos_min,
        })

        if winner:
            core.switch_branch(str(winner["branch"]))
        else:
            core.switch_branch(source_branch)
        result["active_branch"] = core.ACTIVE_DESIGN
        result["project"] = self.snapshot()
        core.record_simulation(
            "autonomous_campaign_project_structural",
            object_id,
            deepcopy(payload or {}),
            {
                "source_branch": source_branch,
                "winner_branch": result.get("winner_branch"),
                "objective": objective,
                "project_structural_campaign": deepcopy(result["project_structural_campaign"]),
                "candidates": deepcopy(ranked),
            },
        )
        return result
    except Exception:
        # A post-processing defect must never strand the user on an arbitrary candidate.
        if source_branch in core.BRANCHES:
            core.switch_branch(source_branch)
        raise


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_RUN_CAMPAIGN
    if _INSTALLED:
        return
    _ORIGINAL_RUN_CAMPAIGN = legacy.PROJECT.run_campaign
    legacy.PROJECT.run_campaign = MethodType(_run_campaign, legacy.PROJECT)
    _INSTALLED = True
