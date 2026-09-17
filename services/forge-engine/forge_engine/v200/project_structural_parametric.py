from __future__ import annotations

"""Parametric-expression integration for canonical project SolidFEA.

Geometry dimensions and load magnitudes may share the same named design variables. The
base parametric layer already resolves symbolic custom geometry before ordinary
SolidFEA. This adapter applies the same safe expression environment to canonical project
loads and constraints before the project-boundary-condition solver sees them, while
leaving the stored project symbolic and editable.
"""

from copy import deepcopy
from typing import Any, Callable

from ..v110 import core
from . import parametric_expressions, project_structural


_INSTALLED = False
_ORIGINAL_SOLVE_PROJECT_BOX: Callable[..., dict[str, Any]] | None = None


def resolved_analysis_project(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    env = parametric_expressions.resolve_parameters(source)
    resolved = deepcopy(source)
    resolved["loads"] = parametric_expressions._resolve_tree(resolved.get("loads") or [], env)
    resolved["constraints"] = parametric_expressions._resolve_tree(resolved.get("constraints") or [], env)
    return resolved


def _solve_project_box(obj: dict[str, Any], project: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    assert _ORIGINAL_SOLVE_PROJECT_BOX is not None
    source = project if project is not None else core.PROJECT
    resolved_project = resolved_analysis_project(source)
    resolved_object = parametric_expressions.resolve_object(obj, source)
    result = _ORIGINAL_SOLVE_PROJECT_BOX(resolved_object, resolved_project, **kwargs)
    if result.get("supported"):
        result.setdefault("provenance", {})["parametric_inputs"] = "resolved from canonical named design parameters without mutating stored project data"
        result["design_parameter_values"] = parametric_expressions.resolve_parameters(source)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_SOLVE_PROJECT_BOX
    if _INSTALLED:
        return
    _ORIGINAL_SOLVE_PROJECT_BOX = project_structural.solve_project_box
    project_structural.solve_project_box = _solve_project_box
    _INSTALLED = True
