from __future__ import annotations

"""Canonical multi-body steady-state thermal-network analysis for ForgeCAD 2.0.

The v1.1 engine retains a useful one-body lumped thermal preview. This module adds the
project-level model needed by the v2 design loop: explicit heat generation, convection,
fixed-temperature sinks, inter-body thermal conductance, and temperature limits stored
in the canonical loads/constraints graph.

The network deliberately does not invent contact conductance, airflow, radiation, or
interface resistance. If a body has no modeled path to a thermal boundary, the solve
fails closed rather than manufacturing a plausible temperature.
"""

from copy import deepcopy
import math
from types import MethodType
from typing import Any, Callable

import numpy as np
from fastapi import Depends, HTTPException

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import parametric_expressions, project_structural


_INSTALLED = False
_ORIGINAL_VALIDATION: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_PROJECT_BOUNDARY_CONDITIONS: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_RUN_SIMULATION: Callable[..., dict[str, Any]] | None = None

_HEAT_TYPES = {"heat", "heat_power", "thermal_power", "heat_generation", "dissipation"}
_CONVECTION_TYPES = {"convection", "thermal_convection", "ambient_convection"}
_FIXED_TEMPERATURE_TYPES = {"fixed_temperature", "temperature", "thermal_sink", "temperature_boundary"}
_LINK_TYPES = {"thermal_link", "thermal_conductance", "conductive_link"}
_LIMIT_TYPES = {"temperature_limit", "thermal_limit", "max_temperature"}
_THERMAL_CONSTRAINT_TYPES = _CONVECTION_TYPES | _FIXED_TEMPERATURE_TYPES | _LINK_TYPES | _LIMIT_TYPES
_THERMAL_TYPES = _HEAT_TYPES | _THERMAL_CONSTRAINT_TYPES


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _target_id(row: dict[str, Any]) -> str | None:
    for key in ("object_id", "part_id", "target_id", "body_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _row_type(row: dict[str, Any], default: str = "") -> str:
    return str(row.get("type", row.get("kind", default))).strip().lower()


def _resolved_project(project: dict[str, Any]) -> dict[str, Any]:
    env = parametric_expressions.resolve_parameters(project)
    resolved = deepcopy(project)
    resolved["loads"] = parametric_expressions._resolve_tree(resolved.get("loads") or [], env)
    resolved["constraints"] = parametric_expressions._resolve_tree(resolved.get("constraints") or [], env)
    return resolved


def _object_map(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id") and obj.get("visible", True)
    }


def _thermal_record_count(project: dict[str, Any]) -> int:
    count = 0
    for row in project.get("loads") or []:
        if isinstance(row, dict) and _row_type(row) in _HEAT_TYPES:
            count += 1
    for row in project.get("constraints") or []:
        if isinstance(row, dict) and _row_type(row) in _THERMAL_CONSTRAINT_TYPES:
            count += 1
    return count


def _link_ids(row: dict[str, Any]) -> tuple[str, str]:
    a = row.get("a_id", row.get("from_object_id", row.get("source_id", row.get("object_id"))))
    b = row.get("b_id", row.get("to_object_id", row.get("target_object_id", row.get("peer_object_id"))))
    if a in (None, "") or b in (None, ""):
        raise ValueError("Thermal link requires a_id and b_id (or equivalent source/target object IDs)")
    if str(a) == str(b):
        raise ValueError("Thermal link endpoints must be different objects")
    return str(a), str(b)


def _exposed_area_m2(row: dict[str, Any], obj: dict[str, Any]) -> float:
    explicit = row.get("area_mm2", row.get("exposed_area_mm2"))
    if explicit is not None:
        area_mm2 = _finite(explicit, "convection area_mm2")
    else:
        area_mm2 = _finite(core.object_metrics(obj).get("area_mm2"), "object surface area")
        fraction = _finite(row.get("exposed_fraction", 1.0), "convection exposed_fraction")
        if fraction <= 0.0 or fraction > 1.0:
            raise ValueError("convection exposed_fraction must be > 0 and <= 1")
        area_mm2 *= fraction
    if area_mm2 <= 0.0:
        raise ValueError("convection area must be positive")
    return area_mm2 * 1e-6


def _conductance_w_k(row: dict[str, Any]) -> float:
    direct = row.get("conductance_w_k", row.get("g_w_k"))
    if direct is not None:
        conductance = _finite(direct, "thermal link conductance_w_k")
    else:
        area_mm2 = _finite(row.get("area_mm2"), "thermal link area_mm2")
        length_mm = _finite(row.get("length_mm"), "thermal link length_mm")
        conductivity = _finite(row.get("thermal_w_mk", row.get("conductivity_w_mk")), "thermal link thermal_w_mk")
        if area_mm2 <= 0.0 or length_mm <= 0.0 or conductivity <= 0.0:
            raise ValueError("derived thermal link conductance requires positive area_mm2, length_mm and thermal_w_mk")
        conductance = conductivity * area_mm2 * 1e-6 / (length_mm * 1e-3)
    if conductance <= 0.0:
        raise ValueError("thermal link conductance must be positive")
    return conductance


def solve_thermal_network(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    if not _thermal_record_count(source):
        return {
            "requested": False,
            "supported": True,
            "ok": True,
            "solver": "ForgeCAD ThermalNetwork",
            "solver_version": "2.0.0",
            "solver_grade": "not_requested",
            "nodes": [],
            "links": [],
            "limits": [],
            "physical_verification": False,
        }

    resolved = _resolved_project(source)
    objects = _object_map(resolved)
    if not objects:
        raise ValueError("Thermal network requires at least one visible object")

    heat: dict[str, float] = {}
    convection: dict[str, list[dict[str, float]]] = {}
    fixed: dict[str, float] = {}
    links: list[dict[str, Any]] = []
    limits: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def require_object(object_id: str, label: str) -> dict[str, Any]:
        if object_id not in objects:
            raise ValueError(f"{label} references unknown or hidden object {object_id}")
        node_ids.add(object_id)
        return objects[object_id]

    for row in resolved.get("loads") or []:
        if not isinstance(row, dict) or _row_type(row) not in _HEAT_TYPES:
            continue
        object_id = _target_id(row)
        if not object_id:
            raise ValueError("Thermal heat load requires object_id")
        require_object(object_id, "Thermal heat load")
        power = _finite(row.get("heat_w", row.get("power_w", row.get("value"))), "thermal heat_w")
        heat[object_id] = heat.get(object_id, 0.0) + power

    for row in resolved.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        typ = _row_type(row)
        if typ in _CONVECTION_TYPES:
            object_id = _target_id(row)
            if not object_id:
                raise ValueError("Convection constraint requires object_id")
            obj = require_object(object_id, "Convection constraint")
            h = _finite(row.get("h_w_m2k", row.get("h", row.get("film_coefficient_w_m2k"))), "convection h_w_m2k")
            if h <= 0.0:
                raise ValueError("convection h_w_m2k must be positive")
            ambient = _finite(row.get("ambient_c", row.get("temperature_c", 22.0)), "convection ambient_c")
            area = _exposed_area_m2(row, obj)
            convection.setdefault(object_id, []).append({
                "h_w_m2k": h,
                "ambient_c": ambient,
                "area_m2": area,
                "conductance_w_k": h * area,
            })
        elif typ in _FIXED_TEMPERATURE_TYPES:
            object_id = _target_id(row)
            if not object_id:
                raise ValueError("Fixed-temperature constraint requires object_id")
            require_object(object_id, "Fixed-temperature constraint")
            temperature = _finite(row.get("temperature_c", row.get("fixed_temp_c", row.get("value"))), "fixed temperature_c")
            if object_id in fixed and abs(fixed[object_id] - temperature) > 1e-9:
                raise ValueError(f"Object {object_id} has conflicting fixed temperatures")
            fixed[object_id] = temperature
        elif typ in _LINK_TYPES:
            a_id, b_id = _link_ids(row)
            require_object(a_id, "Thermal link")
            require_object(b_id, "Thermal link")
            links.append({
                "id": str(row.get("id") or ""),
                "a_id": a_id,
                "b_id": b_id,
                "conductance_w_k": _conductance_w_k(row),
            })
        elif typ in _LIMIT_TYPES:
            object_id = _target_id(row)
            if not object_id:
                raise ValueError("Temperature limit requires object_id")
            require_object(object_id, "Temperature limit")
            maximum = row.get("max_temperature_c", row.get("max_c", row.get("temperature_c") if typ == "max_temperature" else None))
            minimum = row.get("min_temperature_c", row.get("min_c"))
            if maximum is None and minimum is None:
                raise ValueError("Temperature limit requires max_temperature_c and/or min_temperature_c")
            limits.append({
                "id": str(row.get("id") or ""),
                "object_id": object_id,
                "max_temperature_c": None if maximum is None else _finite(maximum, "max_temperature_c"),
                "min_temperature_c": None if minimum is None else _finite(minimum, "min_temperature_c"),
            })

    if not node_ids:
        raise ValueError("Thermal records do not reference any visible objects")

    ids = sorted(node_ids)
    index = {object_id: i for i, object_id in enumerate(ids)}
    n = len(ids)
    conductance = np.zeros((n, n), dtype=float)
    rhs = np.zeros(n, dtype=float)
    heat_vector = np.zeros(n, dtype=float)
    convection_rows: list[dict[str, Any]] = []

    for object_id, power in heat.items():
        i = index[object_id]
        heat_vector[i] += power
        rhs[i] += power

    for link in links:
        i, j = index[link["a_id"]], index[link["b_id"]]
        g = float(link["conductance_w_k"])
        conductance[i, i] += g
        conductance[j, j] += g
        conductance[i, j] -= g
        conductance[j, i] -= g

    for object_id, rows in convection.items():
        i = index[object_id]
        for row in rows:
            g = float(row["conductance_w_k"])
            ambient = float(row["ambient_c"])
            conductance[i, i] += g
            rhs[i] += g * ambient
            convection_rows.append({"object_id": object_id, **row})

    fixed_indices = np.asarray(sorted(index[object_id] for object_id in fixed), dtype=int)
    unknown_indices = np.asarray([i for i in range(n) if i not in set(fixed_indices.tolist())], dtype=int)
    temperatures = np.zeros(n, dtype=float)
    for object_id, temperature in fixed.items():
        temperatures[index[object_id]] = temperature

    if not len(fixed_indices) and not convection_rows:
        raise ValueError("Thermal network has no modeled temperature boundary; add convection or a fixed-temperature sink")

    if len(unknown_indices):
        matrix = conductance[np.ix_(unknown_indices, unknown_indices)]
        unknown_rhs = rhs[unknown_indices].copy()
        if len(fixed_indices):
            unknown_rhs -= conductance[np.ix_(unknown_indices, fixed_indices)] @ temperatures[fixed_indices]
        try:
            temperatures[unknown_indices] = np.linalg.solve(matrix, unknown_rhs)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Thermal network is singular; one or more bodies have no conductive/convective path to a temperature boundary") from exc
    if not np.all(np.isfinite(temperatures)):
        raise ValueError("Thermal network produced non-finite temperatures")

    residual = conductance @ temperatures - rhs
    unknown_residual = residual[unknown_indices] if len(unknown_indices) else np.asarray([], dtype=float)
    max_node_residual = float(np.max(np.abs(unknown_residual))) if len(unknown_residual) else 0.0

    convection_dissipation = 0.0
    for row in convection_rows:
        temperature = temperatures[index[str(row["object_id"])]]
        convection_dissipation += float(row["conductance_w_k"]) * (temperature - float(row["ambient_c"]))
    fixed_sink_removal = -sum(float(residual[i]) for i in fixed_indices)
    generated = float(np.sum(heat_vector))
    balance = generated - convection_dissipation - fixed_sink_removal

    nodes = []
    for object_id in ids:
        i = index[object_id]
        obj = objects[object_id]
        nodes.append({
            "object_id": object_id,
            "name": str(obj.get("name") or object_id),
            "temperature_c": float(temperatures[i]),
            "heat_generation_w": float(heat_vector[i]),
            "fixed_temperature": object_id in fixed,
            "convection_boundaries": deepcopy(convection.get(object_id, [])),
        })

    limit_results: list[dict[str, Any]] = []
    for limit in limits:
        temperature = float(temperatures[index[limit["object_id"]]])
        maximum = limit.get("max_temperature_c")
        minimum = limit.get("min_temperature_c")
        passed = (maximum is None or temperature <= float(maximum)) and (minimum is None or temperature >= float(minimum))
        limit_results.append({**limit, "temperature_c": temperature, "passed": passed})

    return {
        "requested": True,
        "supported": True,
        "ok": all(bool(item["passed"]) for item in limit_results),
        "solver": "ForgeCAD ThermalNetwork",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "method": "steady-state linear lumped thermal conductance network",
        "node_count": n,
        "nodes": nodes,
        "links": deepcopy(links),
        "limits": limit_results,
        "energy_balance": {
            "generated_heat_w": generated,
            "convection_dissipation_w": convection_dissipation,
            "fixed_sink_removal_w": fixed_sink_removal,
            "residual_w": balance,
            "max_unknown_node_residual_w": max_node_residual,
        },
        "assumptions": [
            "Steady state with temperature-independent linear conductances.",
            "Each ForgeCAD object is one isothermal lumped thermal node.",
            "Thermal links use only explicit conductance or explicit k*A/L inputs; contact conductance is never inferred from CAD proximity.",
            "Convection uses the explicitly supplied coefficient and exposed area (or the object's full B-rep surface area when area is omitted).",
            "Radiation, airflow/CFD, phase change, transient thermal mass, anisotropy, interface resistance and temperature-dependent properties are not modeled.",
        ],
        "physical_verification": False,
    }


def analyze_thermal(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    if not _thermal_record_count(source):
        result = solve_thermal_network(source)
        return {**result, "counts": {"error": 0, "warning": 0, "info": 0}, "risks": []}
    try:
        result = solve_thermal_network(source)
    except Exception as exc:
        risk = {"severity": "error", "code": "thermal_model_invalid", "message": str(exc)}
        return {
            "requested": True,
            "supported": False,
            "ok": False,
            "solver": "ForgeCAD ThermalNetwork",
            "solver_version": "2.0.0",
            "solver_grade": "invalid_model",
            "counts": {"error": 1, "warning": 0, "info": 0},
            "risks": [risk],
            "physical_verification": False,
        }

    risks: list[dict[str, Any]] = []
    for limit in result.get("limits") or []:
        if limit.get("passed"):
            continue
        risks.append({
            "severity": "error",
            "code": "temperature_limit_exceeded",
            "object_id": limit["object_id"],
            "constraint_id": limit.get("id"),
            "message": (
                f"{limit['object_id']} steady-state temperature {float(limit['temperature_c']):.3f} °C violates modeled temperature limit"
                + (f" <= {float(limit['max_temperature_c']):.3f} °C" if limit.get("max_temperature_c") is not None else "")
                + (f" >= {float(limit['min_temperature_c']):.3f} °C" if limit.get("min_temperature_c") is not None else "")
                + "."
            ),
        })
    counts = {level: sum(1 for risk in risks if risk["severity"] == level) for level in ("error", "warning", "info")}
    return {**result, "ok": counts["error"] == 0, "counts": counts, "risks": risks}


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    thermal = analyze_thermal(core.PROJECT)
    combined = list(base.get("risks") or []) + list(thermal.get("risks") or [])
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in combined:
        if not isinstance(risk, dict):
            continue
        key = (
            str(risk.get("code") or ""),
            str(risk.get("object_id") or risk.get("connection_id") or risk.get("net_id") or ""),
            str(risk.get("message") or ""),
        )
        deduped[key] = risk
    risks = sorted(
        deduped.values(),
        key=lambda risk: (
            {"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3),
            str(risk.get("code") or ""),
            str(risk.get("message") or ""),
        ),
    )
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["thermal"] = thermal
    return base


def _project_boundary_conditions_without_thermal(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    assert _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS is not None
    filtered = deepcopy(project)
    filtered["loads"] = [
        row for row in filtered.get("loads") or []
        if not isinstance(row, dict) or _row_type(row) not in _HEAT_TYPES
    ]
    filtered["constraints"] = [
        row for row in filtered.get("constraints") or []
        if not isinstance(row, dict) or _row_type(row) not in _THERMAL_CONSTRAINT_TYPES
    ]
    return _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS(filtered, object_id)


def _run_simulation(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_SIMULATION is not None
    result = _ORIGINAL_RUN_SIMULATION(selected_object_id, payload)
    thermal = analyze_thermal(core.PROJECT)
    if thermal.get("requested"):
        result["thermal_network"] = thermal
        for simulation in reversed(core.PROJECT.get("simulations") or []):
            if simulation.get("kind") == "engineering_screen" and not simulation.get("stale"):
                simulation["result"] = deepcopy(result)
                core.persist()
                break
    return result


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_VALIDATION, _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS, _ORIGINAL_RUN_SIMULATION
    if _INSTALLED:
        return
    _ORIGINAL_VALIDATION = EngineeringProject.validation
    EngineeringProject.validation = _validation
    _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS = project_structural.project_boundary_conditions
    project_structural.project_boundary_conditions = _project_boundary_conditions_without_thermal
    _ORIGINAL_RUN_SIMULATION = legacy.PROJECT.run_simulation
    legacy.PROJECT.run_simulation = MethodType(_run_simulation, legacy.PROJECT)

    app = legacy.app

    @app.get("/v2/analysis/thermal-network", dependencies=[Depends(legacy.require_session)])
    async def thermal_network() -> dict[str, Any]:
        result = analyze_thermal(core.PROJECT)
        if result.get("requested") and not result.get("supported", True):
            raise HTTPException(status_code=400, detail=str((result.get("risks") or [{}])[0].get("message") or "Invalid thermal model"))
        return result

    _INSTALLED = True
