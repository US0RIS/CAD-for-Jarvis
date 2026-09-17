from __future__ import annotations

"""Canonical steady-state incompressible fluid-network analysis for ForgeCAD 2.0.

ForgeCAD's design-intelligence contract explicitly includes fluid systems. This module
adds a deterministic project-level network model for hydraulic/liquid systems using
canonical project loads and constraints. It supports explicit pressure boundaries,
flow injection/demand, linear hydraulic resistance, circular-tube Hagen-Poiseuille
resistance, nodal pressure solve, edge flow/velocity, and pressure/flow limits.

It deliberately does not pretend to be CFD. Geometry proximity never creates a pipe,
seal, valve or pressure boundary. Compressible-gas/pneumatic flow, turbulent pressure
loss, pumps/valves with nonlinear curves, cavitation, two-phase flow and transients are
outside this solver and remain explicit verification gaps.
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

_PRESSURE_TYPES = {"fluid_pressure", "pressure_boundary", "hydraulic_pressure"}
_LINK_TYPES = {"fluid_link", "hydraulic_link", "tube", "pipe"}
_PRESSURE_LIMIT_TYPES = {"fluid_pressure_limit", "pressure_limit"}
_FLOW_LIMIT_TYPES = {"fluid_flow_limit", "flow_limit"}
_FLUID_CONSTRAINT_TYPES = _PRESSURE_TYPES | _LINK_TYPES | _PRESSURE_LIMIT_TYPES | _FLOW_LIMIT_TYPES
_DEMAND_TYPES = {"fluid_demand", "flow_demand", "hydraulic_demand"}
_INJECTION_TYPES = {"fluid_injection", "flow_injection", "hydraulic_injection"}
_FLUID_LOAD_TYPES = _DEMAND_TYPES | _INJECTION_TYPES


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _row_type(row: dict[str, Any]) -> str:
    return str(row.get("type", row.get("kind", ""))).strip().lower()


def _target_id(row: dict[str, Any]) -> str | None:
    for key in ("object_id", "part_id", "target_id", "body_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _resolved_project(project: dict[str, Any]) -> dict[str, Any]:
    env = parametric_expressions.resolve_parameters(project)
    resolved = deepcopy(project)
    resolved["loads"] = parametric_expressions._resolve_tree(resolved.get("loads") or [], env)
    resolved["constraints"] = parametric_expressions._resolve_tree(resolved.get("constraints") or [], env)
    return resolved


def _objects(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id") and obj.get("visible", True)
    }


def _record_count(project: dict[str, Any]) -> int:
    count = 0
    for row in project.get("loads") or []:
        if isinstance(row, dict) and _row_type(row) in _FLUID_LOAD_TYPES:
            count += 1
    for row in project.get("constraints") or []:
        if isinstance(row, dict) and _row_type(row) in _FLUID_CONSTRAINT_TYPES:
            count += 1
    return count


def _pressure_pa(row: dict[str, Any], *, prefix: str = "") -> float:
    keys = [
        (f"{prefix}pressure_pa", 1.0),
        (f"{prefix}pressure_kpa", 1_000.0),
        (f"{prefix}pressure_kpa_g", 1_000.0),
        (f"{prefix}pressure_bar", 100_000.0),
        (f"{prefix}pressure_psi", 6_894.757293168),
    ]
    for key, scale in keys:
        if row.get(key) is not None:
            return _finite(row.get(key), key) * scale
    if not prefix and row.get("value") is not None:
        return _finite(row.get("value"), "pressure value")
    raise ValueError(f"Missing {prefix}pressure; use pressure_pa, pressure_kpa, pressure_bar or pressure_psi")


def _optional_pressure_pa(row: dict[str, Any], prefix: str) -> float | None:
    for key in (
        f"{prefix}pressure_pa",
        f"{prefix}pressure_kpa",
        f"{prefix}pressure_kpa_g",
        f"{prefix}pressure_bar",
        f"{prefix}pressure_psi",
    ):
        if row.get(key) is not None:
            return _pressure_pa(row, prefix=prefix)
    return None


def _flow_m3_s(row: dict[str, Any]) -> float:
    candidates = [
        ("flow_m3_s", 1.0),
        ("flow_l_s", 1e-3),
        ("flow_l_min", 1e-3 / 60.0),
        ("flow_ml_min", 1e-6 / 60.0),
    ]
    for key, scale in candidates:
        if row.get(key) is not None:
            return _finite(row.get(key), key) * scale
    if row.get("value") is not None:
        return _finite(row.get("value"), "flow value")
    raise ValueError("Missing flow; use flow_m3_s, flow_l_s, flow_l_min or flow_ml_min")


def _link_ids(row: dict[str, Any]) -> tuple[str, str]:
    a = row.get("a_id", row.get("from_object_id", row.get("source_id", row.get("object_id"))))
    b = row.get("b_id", row.get("to_object_id", row.get("target_object_id", row.get("peer_object_id"))))
    if a in (None, "") or b in (None, ""):
        raise ValueError("Fluid link requires a_id and b_id (or equivalent source/target object IDs)")
    if str(a) == str(b):
        raise ValueError("Fluid link endpoints must be different objects")
    return str(a), str(b)


def _resistance(row: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    direct = row.get("resistance_pa_s_m3", row.get("hydraulic_resistance_pa_s_m3"))
    if direct is not None:
        resistance = _finite(direct, "fluid resistance_pa_s_m3")
        if resistance <= 0.0:
            raise ValueError("fluid resistance must be positive")
        return resistance, {"model": "explicit_linear_resistance"}

    length_mm = _finite(row.get("length_mm"), "tube length_mm")
    diameter_mm = _finite(row.get("inner_diameter_mm", row.get("diameter_mm")), "tube inner_diameter_mm")
    viscosity = _finite(row.get("dynamic_viscosity_pa_s"), "tube dynamic_viscosity_pa_s")
    if length_mm <= 0.0 or diameter_mm <= 0.0 or viscosity <= 0.0:
        raise ValueError("tube model requires positive length_mm, inner_diameter_mm and dynamic_viscosity_pa_s")
    length_m = length_mm * 1e-3
    diameter_m = diameter_mm * 1e-3
    resistance = 128.0 * viscosity * length_m / (math.pi * diameter_m ** 4)
    meta: dict[str, Any] = {
        "model": "Hagen-Poiseuille circular tube",
        "length_mm": length_mm,
        "inner_diameter_mm": diameter_mm,
        "dynamic_viscosity_pa_s": viscosity,
    }
    if row.get("density_kg_m3") is not None:
        density = _finite(row.get("density_kg_m3"), "tube density_kg_m3")
        if density <= 0.0:
            raise ValueError("tube density_kg_m3 must be positive")
        meta["density_kg_m3"] = density
    return resistance, meta


def solve_fluid_network(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    if not _record_count(source):
        return {
            "requested": False,
            "supported": True,
            "ok": True,
            "solver": "ForgeCAD FluidNetwork",
            "solver_version": "2.0.0",
            "solver_grade": "not_requested",
            "nodes": [],
            "links": [],
            "limits": [],
            "physical_verification": False,
        }

    resolved = _resolved_project(source)
    objects = _objects(resolved)
    if not objects:
        raise ValueError("Fluid network requires at least one visible object")

    pressure_boundaries: dict[str, float] = {}
    net_injection: dict[str, float] = {}
    links: list[dict[str, Any]] = []
    pressure_limits: list[dict[str, Any]] = []
    flow_limits: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def require_object(object_id: str, label: str) -> None:
        if object_id not in objects:
            raise ValueError(f"{label} references unknown or hidden object {object_id}")
        node_ids.add(object_id)

    for row in resolved.get("loads") or []:
        if not isinstance(row, dict):
            continue
        typ = _row_type(row)
        if typ not in _FLUID_LOAD_TYPES:
            continue
        object_id = _target_id(row)
        if not object_id:
            raise ValueError("Fluid demand/injection requires object_id")
        require_object(object_id, "Fluid load")
        flow = _flow_m3_s(row)
        # Positive injection adds fluid to the node. Positive demand removes it.
        signed = flow if typ in _INJECTION_TYPES else -flow
        net_injection[object_id] = net_injection.get(object_id, 0.0) + signed

    for row in resolved.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        typ = _row_type(row)
        if typ in _PRESSURE_TYPES:
            object_id = _target_id(row)
            if not object_id:
                raise ValueError("Fluid pressure boundary requires object_id")
            require_object(object_id, "Fluid pressure boundary")
            pressure = _pressure_pa(row)
            if object_id in pressure_boundaries and abs(pressure_boundaries[object_id] - pressure) > 1e-6:
                raise ValueError(f"Object {object_id} has conflicting fluid pressure boundaries")
            pressure_boundaries[object_id] = pressure
        elif typ in _LINK_TYPES:
            a_id, b_id = _link_ids(row)
            require_object(a_id, "Fluid link")
            require_object(b_id, "Fluid link")
            resistance, model = _resistance(row)
            links.append({
                "id": str(row.get("id") or ""),
                "a_id": a_id,
                "b_id": b_id,
                "resistance_pa_s_m3": resistance,
                **model,
                "max_velocity_m_s": None if row.get("max_velocity_m_s") is None else _finite(row.get("max_velocity_m_s"), "max_velocity_m_s"),
                "max_flow_m3_s": None if row.get("max_flow_m3_s") is None else _finite(row.get("max_flow_m3_s"), "max_flow_m3_s"),
                "max_delta_pressure_pa": None if row.get("max_delta_pressure_pa") is None else _finite(row.get("max_delta_pressure_pa"), "max_delta_pressure_pa"),
            })
        elif typ in _PRESSURE_LIMIT_TYPES:
            object_id = _target_id(row)
            if not object_id:
                raise ValueError("Fluid pressure limit requires object_id")
            require_object(object_id, "Fluid pressure limit")
            minimum = _optional_pressure_pa(row, "min_")
            maximum = _optional_pressure_pa(row, "max_")
            if minimum is None and maximum is None:
                raise ValueError("Fluid pressure limit requires min_pressure_* and/or max_pressure_*")
            pressure_limits.append({
                "id": str(row.get("id") or ""),
                "object_id": object_id,
                "min_pressure_pa": minimum,
                "max_pressure_pa": maximum,
            })
        elif typ in _FLOW_LIMIT_TYPES:
            link_id = str(row.get("link_id") or row.get("connection_id") or "").strip()
            if not link_id:
                raise ValueError("Fluid flow limit requires link_id")
            maximum = _flow_m3_s(row)
            if maximum < 0.0:
                raise ValueError("Fluid flow limit must be non-negative")
            flow_limits.append({
                "id": str(row.get("id") or ""),
                "link_id": link_id,
                "max_abs_flow_m3_s": maximum,
            })

    if not node_ids:
        raise ValueError("Fluid records do not reference any visible objects")
    if not links:
        raise ValueError("Fluid network requires at least one explicit fluid_link/tube/pipe")
    if not pressure_boundaries:
        raise ValueError("Fluid network requires at least one explicit pressure boundary")

    ids = sorted(node_ids)
    index = {object_id: i for i, object_id in enumerate(ids)}
    n = len(ids)
    matrix = np.zeros((n, n), dtype=float)
    rhs = np.zeros(n, dtype=float)

    for object_id, value in net_injection.items():
        rhs[index[object_id]] += value

    for link in links:
        i, j = index[link["a_id"]], index[link["b_id"]]
        conductance = 1.0 / float(link["resistance_pa_s_m3"])
        matrix[i, i] += conductance
        matrix[j, j] += conductance
        matrix[i, j] -= conductance
        matrix[j, i] -= conductance

    fixed_indices = np.asarray(sorted(index[object_id] for object_id in pressure_boundaries), dtype=int)
    fixed_set = set(fixed_indices.tolist())
    unknown_indices = np.asarray([i for i in range(n) if i not in fixed_set], dtype=int)
    pressures = np.zeros(n, dtype=float)
    for object_id, pressure in pressure_boundaries.items():
        pressures[index[object_id]] = pressure

    if len(unknown_indices):
        reduced = matrix[np.ix_(unknown_indices, unknown_indices)]
        reduced_rhs = rhs[unknown_indices].copy()
        if len(fixed_indices):
            reduced_rhs -= matrix[np.ix_(unknown_indices, fixed_indices)] @ pressures[fixed_indices]
        try:
            pressures[unknown_indices] = np.linalg.solve(reduced, reduced_rhs)
        except np.linalg.LinAlgError as exc:
            raise ValueError("Fluid network is singular; one or more nodes lack a hydraulic path to a pressure boundary") from exc
    if not np.all(np.isfinite(pressures)):
        raise ValueError("Fluid network produced non-finite pressures")

    solved_links: list[dict[str, Any]] = []
    for link in links:
        a_id, b_id = str(link["a_id"]), str(link["b_id"])
        delta_p = float(pressures[index[a_id]] - pressures[index[b_id]])
        flow = delta_p / float(link["resistance_pa_s_m3"])
        solved = {**deepcopy(link), "delta_pressure_pa": delta_p, "flow_m3_s": flow, "flow_l_min": flow * 60_000.0}
        diameter_mm = link.get("inner_diameter_mm")
        if diameter_mm is not None:
            diameter_m = float(diameter_mm) * 1e-3
            area = math.pi * diameter_m * diameter_m / 4.0
            velocity = flow / area
            solved["velocity_m_s"] = velocity
            density = link.get("density_kg_m3")
            viscosity = link.get("dynamic_viscosity_pa_s")
            if density is not None and viscosity is not None:
                reynolds = abs(float(density) * velocity * diameter_m / float(viscosity))
                solved["reynolds_number"] = reynolds
                solved["laminar_model_valid"] = reynolds < 2300.0
        solved_links.append(solved)

    residual = matrix @ pressures - rhs
    unknown_residual = residual[unknown_indices] if len(unknown_indices) else np.asarray([], dtype=float)
    max_unknown_residual = float(np.max(np.abs(unknown_residual))) if len(unknown_residual) else 0.0
    boundary_net_flow = {ids[i]: float(residual[i]) for i in fixed_indices}

    limit_results: list[dict[str, Any]] = []
    for limit in pressure_limits:
        pressure = float(pressures[index[limit["object_id"]]])
        minimum = limit.get("min_pressure_pa")
        maximum = limit.get("max_pressure_pa")
        passed = (minimum is None or pressure >= float(minimum)) and (maximum is None or pressure <= float(maximum))
        limit_results.append({**limit, "kind": "pressure", "pressure_pa": pressure, "passed": passed})

    links_by_id = {str(link.get("id") or ""): link for link in solved_links if str(link.get("id") or "")}
    for limit in flow_limits:
        if limit["link_id"] not in links_by_id:
            raise ValueError(f"Fluid flow limit references unknown link {limit['link_id']}")
        flow = abs(float(links_by_id[limit["link_id"]]["flow_m3_s"]))
        limit_results.append({**limit, "kind": "flow", "flow_m3_s": flow, "passed": flow <= float(limit["max_abs_flow_m3_s"])})

    nodes = [
        {
            "object_id": object_id,
            "name": str(objects[object_id].get("name") or object_id),
            "pressure_pa": float(pressures[index[object_id]]),
            "pressure_kpa": float(pressures[index[object_id]]) / 1000.0,
            "net_injection_m3_s": float(net_injection.get(object_id, 0.0)),
            "pressure_boundary": object_id in pressure_boundaries,
        }
        for object_id in ids
    ]

    return {
        "requested": True,
        "supported": True,
        "ok": all(bool(item["passed"]) for item in limit_results),
        "solver": "ForgeCAD FluidNetwork",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "method": "steady-state linear incompressible hydraulic resistance network",
        "node_count": n,
        "nodes": nodes,
        "links": solved_links,
        "limits": limit_results,
        "continuity": {
            "max_unknown_node_residual_m3_s": max_unknown_residual,
            "pressure_boundary_net_flow_m3_s": boundary_net_flow,
            "specified_net_injection_m3_s": float(sum(net_injection.values())),
        },
        "assumptions": [
            "Steady-state incompressible single-phase flow.",
            "Each explicit link is a linear hydraulic resistance; circular-tube derived resistance uses Hagen-Poiseuille laminar flow.",
            "Positive fluid_injection adds flow to a node; positive fluid_demand removes flow from a node.",
            "No pipe, hose, seal, valve, pump or fluid path is inferred from CAD proximity or mates.",
            "Compressibility, turbulent/minor losses, nonlinear pump/valve curves, cavitation, water hammer, two-phase flow, leakage and CFD are not modeled.",
        ],
        "physical_verification": False,
    }


def analyze_fluid(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    if not _record_count(source):
        result = solve_fluid_network(source)
        return {**result, "counts": {"error": 0, "warning": 0, "info": 0}, "risks": []}
    try:
        result = solve_fluid_network(source)
    except Exception as exc:
        return {
            "requested": True,
            "supported": False,
            "ok": False,
            "solver": "ForgeCAD FluidNetwork",
            "solver_version": "2.0.0",
            "solver_grade": "invalid_model",
            "counts": {"error": 1, "warning": 0, "info": 0},
            "risks": [{"severity": "error", "code": "fluid_model_invalid", "message": str(exc)}],
            "physical_verification": False,
        }

    risks: list[dict[str, Any]] = []
    for limit in result.get("limits") or []:
        if limit.get("passed"):
            continue
        if limit.get("kind") == "pressure":
            message = f"{limit['object_id']} pressure {float(limit['pressure_pa']) / 1000.0:.3f} kPa violates modeled pressure limit."
            risks.append({"severity": "error", "code": "fluid_pressure_limit_exceeded", "object_id": limit["object_id"], "constraint_id": limit.get("id"), "message": message})
        else:
            message = f"Fluid link {limit['link_id']} flow {float(limit['flow_m3_s']) * 60_000.0:.6g} L/min exceeds modeled flow limit."
            risks.append({"severity": "error", "code": "fluid_flow_limit_exceeded", "link_id": limit["link_id"], "constraint_id": limit.get("id"), "message": message})

    for link in result.get("links") or []:
        if link.get("laminar_model_valid") is False:
            risks.append({
                "severity": "error",
                "code": "fluid_laminar_model_invalid",
                "link_id": link.get("id"),
                "message": f"Fluid link {link.get('id') or '(unnamed)'} has Reynolds number {float(link['reynolds_number']):.1f}; Hagen-Poiseuille laminar resistance is outside its valid regime.",
            })
        max_velocity = link.get("max_velocity_m_s")
        if max_velocity is not None and link.get("velocity_m_s") is not None and abs(float(link["velocity_m_s"])) > float(max_velocity):
            risks.append({"severity": "error", "code": "fluid_velocity_limit_exceeded", "link_id": link.get("id"), "message": f"Fluid link {link.get('id') or '(unnamed)'} velocity {abs(float(link['velocity_m_s'])):.3f} m/s exceeds modeled {float(max_velocity):.3f} m/s limit."})
        max_flow = link.get("max_flow_m3_s")
        if max_flow is not None and abs(float(link.get("flow_m3_s") or 0.0)) > float(max_flow):
            risks.append({"severity": "error", "code": "fluid_link_flow_limit_exceeded", "link_id": link.get("id"), "message": f"Fluid link {link.get('id') or '(unnamed)'} exceeds its modeled maximum flow."})
        max_dp = link.get("max_delta_pressure_pa")
        if max_dp is not None and abs(float(link.get("delta_pressure_pa") or 0.0)) > float(max_dp):
            risks.append({"severity": "error", "code": "fluid_pressure_drop_limit_exceeded", "link_id": link.get("id"), "message": f"Fluid link {link.get('id') or '(unnamed)'} pressure drop exceeds its modeled limit."})

    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    return {**result, "ok": counts["error"] == 0, "counts": counts, "risks": risks}


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    fluid = analyze_fluid(core.PROJECT)
    combined = list(base.get("risks") or []) + list(fluid.get("risks") or [])
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in combined:
        if not isinstance(risk, dict):
            continue
        key = (
            str(risk.get("code") or ""),
            str(risk.get("object_id") or risk.get("link_id") or risk.get("connection_id") or risk.get("net_id") or ""),
            str(risk.get("message") or ""),
        )
        deduped[key] = risk
    risks = sorted(deduped.values(), key=lambda risk: ({"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3), str(risk.get("code") or ""), str(risk.get("message") or "")))
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["fluid"] = fluid
    return base


def _project_boundary_conditions_without_fluid(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    assert _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS is not None
    filtered = deepcopy(project)
    filtered["loads"] = [row for row in filtered.get("loads") or [] if not isinstance(row, dict) or _row_type(row) not in _FLUID_LOAD_TYPES]
    filtered["constraints"] = [row for row in filtered.get("constraints") or [] if not isinstance(row, dict) or _row_type(row) not in _FLUID_CONSTRAINT_TYPES]
    return _ORIGINAL_PROJECT_BOUNDARY_CONDITIONS(filtered, object_id)


def _run_simulation(self: Any, selected_object_id: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_RUN_SIMULATION is not None
    result = _ORIGINAL_RUN_SIMULATION(selected_object_id, payload)
    fluid = analyze_fluid(core.PROJECT)
    if fluid.get("requested"):
        result["fluid_network"] = fluid
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
    project_structural.project_boundary_conditions = _project_boundary_conditions_without_fluid
    _ORIGINAL_RUN_SIMULATION = legacy.PROJECT.run_simulation
    legacy.PROJECT.run_simulation = MethodType(_run_simulation, legacy.PROJECT)

    app = legacy.app

    @app.get("/v2/analysis/fluid-network", dependencies=[Depends(legacy.require_session)])
    async def fluid_network() -> dict[str, Any]:
        result = analyze_fluid(core.PROJECT)
        if result.get("requested") and not result.get("supported", True):
            raise HTTPException(status_code=400, detail=str((result.get("risks") or [{}])[0].get("message") or "Invalid fluid model"))
        return result

    _INSTALLED = True
