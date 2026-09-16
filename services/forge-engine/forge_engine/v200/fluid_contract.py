from __future__ import annotations

"""Planner-visible capability contract for ForgeCAD 2.0 fluid networks."""

from copy import deepcopy
from typing import Any, Callable

from . import analysis_contracts


_INSTALLED = False
_ORIGINAL_CONTRACTS: Callable[..., dict[str, Any]] | None = None


FLUID_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-fluid-network-2.0",
    "solver": "ForgeCAD FluidNetwork",
    "grade": "engineering_iteration",
    "analysis_endpoint": "/v2/analysis/fluid-network",
    "canonical_source": "project fluid loads + project fluid constraints",
    "pressure_boundary": {
        "operation": "add_constraint",
        "schema": {
            "object_id": "$reservoir",
            "type": "fluid_pressure",
            "pressure_kpa": 250.0,
        },
        "accepted_units": ["pressure_pa", "pressure_kpa", "pressure_bar", "pressure_psi"],
    },
    "flow_demand": {
        "operation": "add_load",
        "schema": {
            "object_id": "$actuator",
            "type": "fluid_demand",
            "flow_l_min": 0.5,
        },
        "sign_policy": "Positive fluid_demand removes flow from the node; positive fluid_injection adds flow to the node.",
    },
    "fluid_link": {
        "operation": "add_constraint",
        "schema_linear": {
            "type": "fluid_link",
            "a_id": "$pump",
            "b_id": "$actuator",
            "resistance_pa_s_m3": 2.0e9,
        },
        "schema_tube": {
            "type": "tube",
            "a_id": "$pump",
            "b_id": "$actuator",
            "length_mm": 500.0,
            "inner_diameter_mm": 4.0,
            "dynamic_viscosity_pa_s": 0.001,
            "density_kg_m3": 998.0,
        },
        "policy": "No hose, pipe, valve, seal or hydraulic path is inferred from CAD proximity or mates; every solved path must be explicit.",
    },
    "pressure_limit": {
        "operation": "add_constraint",
        "schema": {
            "object_id": "$actuator",
            "type": "fluid_pressure_limit",
            "min_pressure_kpa": 150.0,
            "max_pressure_kpa": 300.0,
        },
    },
    "outputs": [
        "steady-state nodal pressure",
        "signed link flow and pressure drop",
        "tube velocity and Reynolds number when tube properties are explicit",
        "continuity residuals and pressure-boundary net flow",
        "pressure/flow/velocity limit pass-fail evidence",
    ],
    "fail_closed": [
        "fluid records referencing unknown bodies",
        "network without an explicit pressure boundary",
        "floating/singular hydraulic subnetwork",
        "Hagen-Poiseuille tube used outside laminar regime when Reynolds data are available",
        "modeled pressure/flow/velocity limit violation",
    ],
    "unknown_policy": "Do not invent pipe diameter, viscosity, density, hydraulic resistance, pump pressure, flow demand, leakage, valve loss or pressure limits.",
    "limitations": [
        "steady-state incompressible single-phase network only",
        "linear hydraulic resistance model",
        "Hagen-Poiseuille circular-tube resistance is valid only in laminar flow",
        "no compressible pneumatic/gas solver",
        "no turbulent/minor-loss model",
        "no nonlinear pump or valve curves",
        "no cavitation, water hammer, leakage, two-phase flow or CFD",
        "not certification evidence",
    ],
}


def _contracts() -> dict[str, Any]:
    assert _ORIGINAL_CONTRACTS is not None
    result = _ORIGINAL_CONTRACTS()
    result["fluid"] = deepcopy(FLUID_ANALYSIS_CONTRACT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_CONTRACTS
    if _INSTALLED:
        return
    _ORIGINAL_CONTRACTS = analysis_contracts.contracts
    analysis_contracts.contracts = _contracts
    _INSTALLED = True
