from __future__ import annotations

"""Expose ForgeCAD 2.0 engineering state through the desktop project surface.

The v1 desktop snapshot intentionally summarized parts, BOM and history. ForgeCAD 2.0
now has first-class loads, supports, named parameters, physical feedback and simulation
provenance; hiding those records behind internal state makes the UI/API unable to build
proper inspectors. This adapter enriches the existing snapshot without changing the
canonical storage format or duplicating state.
"""

from copy import deepcopy
from typing import Any, Callable

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import feedback_intelligence, parametric_expressions


_INSTALLED = False
_ORIGINAL_SNAPSHOT: Callable[..., dict[str, Any]] | None = None


def _simulation_summary(row: dict[str, Any]) -> dict[str, Any]:
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    provenance = result.get("analysis_provenance") if isinstance(result.get("analysis_provenance"), dict) else {}
    return {
        "id": str(row.get("id") or ""),
        "kind": str(row.get("kind") or ""),
        "object_id": row.get("object_id"),
        "at": row.get("at"),
        "design": row.get("design"),
        "stale": bool(row.get("stale")),
        "primary_structural_result": provenance.get("primary_structural_result"),
        "physical_verification": bool(provenance.get("physical_verification", False)),
    }


def _snapshot(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_SNAPSHOT is not None
    snapshot = _ORIGINAL_SNAPSHOT(self)
    try:
        parameter_report = parametric_expressions.parameter_report(core.PROJECT)
    except ValueError as exc:
        parameter_report = {"count": 0, "parameters": [], "values": {}, "error": str(exc)}
    try:
        physical_feedback = feedback_intelligence.branch_feedback(core.ACTIVE_DESIGN)
    except Exception as exc:
        physical_feedback = {"branch": core.ACTIVE_DESIGN, "error": str(exc)}

    snapshot["engineering_state"] = {
        "version": "2.0.0",
        "design_parameters": deepcopy(core.PROJECT.get("design_parameters") or {}),
        "parameter_report": parameter_report,
        "loads": deepcopy(core.PROJECT.get("loads") or []),
        "constraints": deepcopy(core.PROJECT.get("constraints") or []),
        "joints": deepcopy(core.PROJECT.get("joints") or []),
        "simulation_summary": [
            _simulation_summary(row)
            for row in core.PROJECT.get("simulations") or []
            if isinstance(row, dict)
        ][-40:],
        "physical_feedback": physical_feedback,
        "units": str((core.PROJECT.get("settings") or {}).get("units") or "mm"),
        "coordinate_system": str((core.PROJECT.get("settings") or {}).get("coordinate_system") or "Z-up"),
    }
    return snapshot


def install() -> None:
    global _INSTALLED, _ORIGINAL_SNAPSHOT
    if _INSTALLED:
        return
    _ORIGINAL_SNAPSHOT = EngineeringProject.snapshot
    EngineeringProject.snapshot = _snapshot  # type: ignore[method-assign]
    _INSTALLED = True
