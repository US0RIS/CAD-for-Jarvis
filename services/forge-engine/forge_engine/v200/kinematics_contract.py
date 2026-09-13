from __future__ import annotations

"""Planner-visible mechanism-kinematics contract for ForgeCAD 2.0."""

from copy import deepcopy
from typing import Any, Callable

from . import analysis_contracts


_INSTALLED = False
_ORIGINAL_CONTRACTS: Callable[..., dict[str, Any]] | None = None


KINEMATICS_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-mechanism-kinematics-2.0",
    "solver": "ForgeCAD MechanismKinematics",
    "grade": "engineering_iteration",
    "analysis_endpoint": "/v2/analysis/kinematics",
    "sweep_endpoint": "/v2/analysis/kinematics/sweep",
    "joint_operation": {
        "operation": "add_joint",
        "revolute_schema": {
            "name": "arm hinge",
            "type": "revolute",
            "parent_id": "$base",
            "child_id": "$arm",
            "origin_mm": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0],
            "lower_deg": -30.0,
            "upper_deg": 90.0,
            "home_deg": 0.0,
            "validate_sweep": True,
        },
        "prismatic_schema": {
            "name": "linear slide",
            "type": "prismatic",
            "parent_id": "$frame",
            "child_id": "$carriage",
            "origin_mm": [0.0, 0.0, 0.0],
            "axis": [1.0, 0.0, 0.0],
            "lower_mm": 0.0,
            "upper_mm": 120.0,
            "home_mm": 0.0,
            "validate_sweep": True,
        },
    },
    "outputs": [
        "deterministic child pose at a requested joint coordinate",
        "sampled motion sweep across canonical limits",
        "exact B-rep intersection volume against modeled obstacles at sampled poses",
        "swept world-space bounds",
        "project validation gate for sampled mechanism interference",
    ],
    "fail_closed": [
        "joint missing explicit parent/child/origin/limits",
        "home coordinate outside joint limits",
        "multiple independently analyzed joints assigned to one moving child",
        "unsupported revolute axis/base-rotation composition",
        "sampled B-rep collision when validate_sweep is enabled",
    ],
    "limitations": [
        "single-joint rigid sweep from stored zero pose; no joint-chain or closed-loop solve yet",
        "revolute joints currently require a world-principal axis and zero child base rotation",
        "no compliance, backlash, contact response, actuator force/torque, controls or dynamic loading",
        "sampled motion can miss interference between samples",
        "collision fidelity cannot exceed the geometry fidelity of purchased-component proxies",
        "not physical verification",
    ],
}


def _contracts() -> dict[str, Any]:
    assert _ORIGINAL_CONTRACTS is not None
    result = _ORIGINAL_CONTRACTS()
    result["kinematics"] = deepcopy(KINEMATICS_ANALYSIS_CONTRACT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_CONTRACTS
    if _INSTALLED:
        return
    _ORIGINAL_CONTRACTS = analysis_contracts.contracts
    analysis_contracts.contracts = _contracts
    _INSTALLED = True
