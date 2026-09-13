from __future__ import annotations

"""Machine-readable engineering-analysis contracts for ForgeCAD 2.0.

The local planner should not have to infer what the deterministic solver supports from
prose. These contracts travel in planner context and are also exposed through the local
API. They describe *implemented* capability only; unsupported physics stays explicit so
the model cannot quietly invent pressure/contact/moment support that the solver does not
have.
"""

from copy import deepcopy
from typing import Any

from fastapi import Depends

from . import design_intelligence, project_structural


_INSTALLED = False
_ORIGINAL_BUILD_CONTEXT = None


STRUCTURAL_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-solid-fea-2.0",
    "solver": "ForgeCAD SolidFEA",
    "grade": "engineering_iteration",
    "geometry": {
        "supported": ["exact unfeatured box"],
        "unsupported": [
            "featured box",
            "constrained_sketch_extrude",
            "revolve",
            "imported STEP",
            "purchased component",
            "assembly/contact model",
        ],
        "policy": "fail_closed",
    },
    "project_boundary_conditions": {
        "target_keys": ["object_id", "part_id", "target_id", "body_id"],
        "faces": ["x_min", "x_max", "y_min", "y_max", "z_min", "z_max"],
        "support": {
            "operation": "add_constraint",
            "schema": {
                "object_id": "$part",
                "type": "fixed",
                "face": "x_min",
                "dofs": ["x", "y", "z"],
            },
            "supported_types": ["fixed", "fixed_support", "support", "clamp", "clamped", "encastre"],
            "supported_dofs": ["x", "y", "z"],
        },
        "force": {
            "operation": "add_load",
            "schema_vector": {
                "object_id": "$part",
                "type": "force",
                "face": "x_max",
                "vector_n": [0.0, 0.0, -100.0],
            },
            "schema_axis": {
                "object_id": "$part",
                "type": "force",
                "face": "x_max",
                "force_n": 100.0,
                "direction": "-z",
            },
            "supported_types": ["force", "face_force", "distributed_force", "force_vector"],
            "distribution": "uniform nodal force over selected orthogonal face",
        },
        "unsupported_physics": [
            "pressure",
            "moment",
            "torque",
            "point force",
            "contact",
            "bolt preload",
            "joint compliance",
            "prescribed displacement",
        ],
        "policy": "A targeted unsupported load or constraint blocks the canonical project-BC SolidFEA solve instead of being ignored.",
    },
    "result_precedence": {
        "when_project_boundary_conditions_supported": "structural_3d_project",
        "otherwise_supported_preview": "structural_3d",
        "reduced_order_retained": True,
    },
    "limitations": [
        "small-strain linear isotropic elasticity",
        "no plasticity, geometric nonlinearity, contact, fracture or fatigue",
        "homogeneous isotropic material",
        "not certification evidence",
    ],
}


MANUFACTURING_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "bambu-lab-p2s-screening-2.0",
    "resource_id": "bambu-lab-p2s",
    "primary_exchange_format": "3mf",
    "forgecad_screening": [
        "build-volume fit",
        "24 orthogonal orientation screen",
        "downward-face support-risk proxy",
        "conservative rectangular plate packing",
        "solid-material mass estimate when density is known",
    ],
    "authoritative_external_stage": ["Bambu Studio arrangement", "support generation", "slicing"],
    "direct_printer_control": False,
    "oversize_adaptation_operation": "split_for_manufacturing",
}


def contracts() -> dict[str, Any]:
    return {
        "version": "2.0.0",
        "structural": deepcopy(STRUCTURAL_ANALYSIS_CONTRACT),
        "manufacturing": deepcopy(MANUFACTURING_ANALYSIS_CONTRACT),
    }


def _build_context(text: str, architecture: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    assert _ORIGINAL_BUILD_CONTEXT is not None
    context = _ORIGINAL_BUILD_CONTEXT(text, architecture, project)
    context["analysis_contracts"] = contracts()
    return context


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_BUILD_CONTEXT
    if _INSTALLED:
        return

    # `_face` normalizes a leading '+' to `max*` before alias lookup. Keep those aliases
    # explicit so +X/+Y/+Z input forms accepted by the contract resolve consistently.
    project_structural._FACE_ALIASES.update({"maxx": "x_max", "maxy": "y_max", "maxz": "z_max"})

    _ORIGINAL_BUILD_CONTEXT = design_intelligence.build_planner_context
    design_intelligence.build_planner_context = _build_context

    app = legacy.app

    @app.get("/v2/analysis/contracts", dependencies=[Depends(legacy.require_session)])
    async def analysis_contracts() -> dict[str, Any]:
        return contracts()

    _INSTALLED = True
