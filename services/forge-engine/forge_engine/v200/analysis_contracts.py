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
        "nonstructural_constraint_namespaces": ["dimension_tolerance", "tolerance", "tolerance_contributor", "tolerance_spec", "stack_spec"],
        "policy": "A targeted unsupported structural load or constraint blocks canonical project-BC SolidFEA. Explicit nonstructural analysis records such as tolerance stacks are ignored by the structural BC parser.",
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


TOLERANCE_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-tolerance-stack-2.0",
    "solver": "ForgeCAD ToleranceStack",
    "grade": "engineering_iteration",
    "model": "one-dimensional linear signed stack",
    "direct_endpoint": "/v2/analysis/tolerance-stack",
    "project_endpoint": "/v2/analysis/tolerance-stacks",
    "project_storage": {
        "operation": "add_constraint",
        "contributor_schema": {
            "type": "dimension_tolerance",
            "stack": "latch_gap",
            "object_id": "$part",
            "parameter": "x",
            "coefficient": 1.0,
            "minus_mm": 0.05,
            "plus_mm": 0.10,
            "sigma_mm": 0.02,
        },
        "literal_contributor_schema": {
            "type": "dimension_tolerance",
            "stack": "latch_gap",
            "name": "assembly shim",
            "nominal_mm": 0.5,
            "coefficient": -1.0,
            "minus_mm": 0.02,
            "plus_mm": 0.02,
        },
        "design_parameter_contributor_schema": {
            "type": "dimension_tolerance",
            "stack": "latch_gap",
            "design_parameter": "latch_offset",
            "coefficient": 1.0,
            "minus_mm": 0.05,
            "plus_mm": 0.05,
        },
        "spec_schema": {
            "type": "tolerance_spec",
            "stack": "latch_gap",
            "lower_spec_mm": 0.2,
            "upper_spec_mm": 0.8,
        },
    },
    "outputs": [
        "nominal stack",
        "asymmetric worst-case limits and margins",
        "independent RSS tolerance limits",
        "contributor sensitivity ranking",
        "combined sigma and 3-sigma range when explicit sigmas are available",
        "normal-distribution yield, defect ppm, Cp and Cpk when specs and explicit sigmas are available",
    ],
    "statistical_policy": "Never infer sigma from drawing tolerance. Statistical yield is unavailable unless every active contributor supplies explicit sigma_mm.",
    "limitations": [
        "one-dimensional linear stack only",
        "independence assumed for RSS/statistical aggregation",
        "no GD&T datum/feature-zone solver",
        "no automatic process-correlation or measurement-system model",
        "thermal/deformation effects must be encoded as explicit contributors or analyzed separately",
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
        "tolerance": deepcopy(TOLERANCE_ANALYSIS_CONTRACT),
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
