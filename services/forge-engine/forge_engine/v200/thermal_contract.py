from __future__ import annotations

"""Planner-visible capability contract for ForgeCAD 2.0 thermal networks."""

from copy import deepcopy
from typing import Any, Callable

from . import analysis_contracts


_INSTALLED = False
_ORIGINAL_CONTRACTS: Callable[..., dict[str, Any]] | None = None


THERMAL_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-thermal-network-2.0",
    "solver": "ForgeCAD ThermalNetwork",
    "grade": "engineering_iteration",
    "analysis_endpoint": "/v2/analysis/thermal-network",
    "canonical_source": "project loads + project constraints + canonical object geometry",
    "heat_load": {
        "operation": "add_load",
        "schema": {
            "object_id": "$electronics",
            "type": "heat",
            "heat_w": 12.0,
        },
        "supported_types": ["heat", "heat_power", "thermal_power", "heat_generation", "dissipation"],
    },
    "convection_boundary": {
        "operation": "add_constraint",
        "schema": {
            "object_id": "$enclosure",
            "type": "convection",
            "ambient_c": 25.0,
            "h_w_m2k": 8.0,
            "exposed_fraction": 0.8,
        },
        "area_policy": "Use explicit area_mm2 when known; otherwise ForgeCAD uses B-rep surface area times exposed_fraction.",
    },
    "fixed_temperature_boundary": {
        "operation": "add_constraint",
        "schema": {
            "object_id": "$cold_plate",
            "type": "fixed_temperature",
            "temperature_c": 35.0,
        },
    },
    "thermal_link": {
        "operation": "add_constraint",
        "schema_conductance": {
            "type": "thermal_link",
            "a_id": "$electronics",
            "b_id": "$cold_plate",
            "conductance_w_k": 2.5,
        },
        "schema_kal": {
            "type": "thermal_link",
            "a_id": "$electronics",
            "b_id": "$cold_plate",
            "area_mm2": 400.0,
            "length_mm": 1.0,
            "thermal_w_mk": 1.5,
        },
        "policy": "Never infer contact conductance from CAD touching/proximity. Supply conductance_w_k or explicit k*A/L inputs.",
    },
    "temperature_limit": {
        "operation": "add_constraint",
        "schema": {
            "object_id": "$electronics",
            "type": "temperature_limit",
            "max_temperature_c": 85.0,
        },
    },
    "outputs": [
        "steady-state temperature of every modeled body",
        "heat generation and explicit thermal-boundary provenance",
        "convection dissipation and fixed-sink heat removal",
        "global and node-level energy-balance residuals",
        "temperature-limit pass/fail evidence",
    ],
    "fail_closed": [
        "thermal records referencing unknown bodies",
        "conflicting fixed temperatures on one body",
        "network with no convection or fixed-temperature boundary",
        "singular/floating thermal subnetwork",
        "modeled temperature-limit violation",
    ],
    "unknown_policy": "Do not invent convection coefficients, contact conductance, interface resistance, heat dissipation, ambient temperature, or temperature limits.",
    "limitations": [
        "steady-state lumped isothermal body nodes only",
        "no transient thermal capacitance",
        "no radiation",
        "no CFD/airflow field",
        "no phase change or temperature-dependent material properties",
        "no inferred contact/interface conductance",
        "not certification evidence",
    ],
}


def _contracts() -> dict[str, Any]:
    assert _ORIGINAL_CONTRACTS is not None
    result = _ORIGINAL_CONTRACTS()
    result["thermal"] = deepcopy(THERMAL_ANALYSIS_CONTRACT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_CONTRACTS
    if _INSTALLED:
        return
    _ORIGINAL_CONTRACTS = analysis_contracts.contracts
    analysis_contracts.contracts = _contracts
    _INSTALLED = True
