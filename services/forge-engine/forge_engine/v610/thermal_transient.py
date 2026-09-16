from __future__ import annotations

"""Transient multi-body thermal simulation for ForgeCAD 6.1.

This extends the canonical v2 steady-state thermal network rather than inventing a
second thermal model. Heat loads, conductive links, convection and fixed-temperature
boundaries remain canonical project records. 6.1 adds body thermal capacitance,
implicit time integration and explicit nonlinear radiation boundaries.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import core
from ..v200 import thermal_network


_SIGMA = 5.670374419e-8
_RADIATION_TYPES = {"radiation", "thermal_radiation", "radiative_boundary"}


def _thermal_capacity_j_k(obj: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    metrics = core.object_metrics(obj)
    mass = float(metrics.get("mass_kg") or 0.0)
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError(f"Object {obj.get('id')} has no positive finite mass for transient thermal analysis")
    material_id = str(obj.get("material") or "")
    material = core.MATERIALS.get(material_id)
    if material is None or material.get("specific_heat_j_kgk") is None:
        raise ValueError(f"Object {obj.get('id')} material {material_id!r} lacks specific_heat_j_kgk")
    cp = float(material["specific_heat_j_kgk"])
    if not math.isfinite(cp) or cp <= 0.0:
        raise ValueError(f"Material {material_id!r} has invalid specific heat")
    return mass * cp, {"mass_kg": mass, "specific_heat_j_kgk": cp, "material": material_id}


def _radiation_area_m2(row: dict[str, Any], obj: dict[str, Any]) -> float:
    explicit = row.get("area_mm2", row.get("exposed_area_mm2"))
    if explicit is not None:
        area_mm2 = float(explicit)
    else:
        area_mm2 = float(core.object_metrics(obj).get("area_mm2") or 0.0)
        fraction = float(row.get("exposed_fraction", 1.0))
        if not (0.0 < fraction <= 1.0):
            raise ValueError("radiation exposed_fraction must be > 0 and <= 1")
        area_mm2 *= fraction
    if not math.isfinite(area_mm2) or area_mm2 <= 0.0:
        raise ValueError("radiation area must be positive")
    return area_mm2 * 1e-6


def solve_transient_thermal(
    project: dict[str, Any],
    *,
    duration_s: float,
    timestep_s: float,
    initial_temperature_c: float,
    max_samples: int = 240,
) -> dict[str, Any]:
    duration = float(duration_s)
    timestep = float(timestep_s)
    initial = float(initial_temperature_c)
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError("duration_s must be positive and finite")
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("timestep_s must be positive and finite")
    if not math.isfinite(initial):
        raise ValueError("initial_temperature_c must be finite")
    steps = int(math.ceil(duration / timestep))
    if steps > 20_000:
        raise ValueError("Transient thermal solve exceeds the 20,000-step interactive safety limit")
    actual_dt = duration / steps

    resolved = thermal_network._resolved_project(project)
    objects = thermal_network._object_map(resolved)
    heat: dict[str, float] = {}
    convection: dict[str, list[dict[str, float]]] = {}
    fixed: dict[str, float] = {}
    links: list[dict[str, Any]] = []
    radiation: list[dict[str, Any]] = []
    limits: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    def require_object(object_id: str, label: str) -> dict[str, Any]:
        if object_id not in objects:
            raise ValueError(f"{label} references unknown or hidden object {object_id}")
        node_ids.add(object_id)
        return objects[object_id]

    for row in resolved.get("loads") or []:
        if not isinstance(row, dict) or thermal_network._row_type(row) not in thermal_network._HEAT_TYPES:
            continue
        object_id = thermal_network._target_id(row)
        if not object_id:
            raise ValueError("Thermal heat load requires object_id")
        require_object(object_id, "Thermal heat load")
        power = thermal_network._finite(row.get("heat_w", row.get("power_w", row.get("value"))), "thermal heat_w")
        heat[object_id] = heat.get(object_id, 0.0) + power

    for row in resolved.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        typ = thermal_network._row_type(row)
        if typ in thermal_network._CONVECTION_TYPES:
            object_id = thermal_network._target_id(row)
            if not object_id:
                raise ValueError("Convection constraint requires object_id")
            obj = require_object(object_id, "Convection constraint")
            h = thermal_network._finite(row.get("h_w_m2k", row.get("h", row.get("film_coefficient_w_m2k"))), "convection h_w_m2k")
            if h <= 0.0:
                raise ValueError("convection h_w_m2k must be positive")
            ambient = thermal_network._finite(row.get("ambient_c", row.get("temperature_c", 22.0)), "convection ambient_c")
            area = thermal_network._exposed_area_m2(row, obj)
            convection.setdefault(object_id, []).append({
                "h_w_m2k": h,
                "ambient_c": ambient,
                "area_m2": area,
                "conductance_w_k": h * area,
            })
        elif typ in thermal_network._FIXED_TEMPERATURE_TYPES:
            object_id = thermal_network._target_id(row)
            if not object_id:
                raise ValueError("Fixed-temperature constraint requires object_id")
            require_object(object_id, "Fixed-temperature constraint")
            temperature = thermal_network._finite(row.get("temperature_c", row.get("fixed_temp_c", row.get("value"))), "fixed temperature_c")
            if object_id in fixed and abs(fixed[object_id] - temperature) > 1e-9:
                raise ValueError(f"Object {object_id} has conflicting fixed temperatures")
            fixed[object_id] = temperature
        elif typ in thermal_network._LINK_TYPES:
            a_id, b_id = thermal_network._link_ids(row)
            require_object(a_id, "Thermal link")
            require_object(b_id, "Thermal link")
            links.append({"id": str(row.get("id") or ""), "a_id": a_id, "b_id": b_id, "conductance_w_k": thermal_network._conductance_w_k(row)})
        elif typ in thermal_network._LIMIT_TYPES:
            object_id = thermal_network._target_id(row)
            if not object_id:
                raise ValueError("Temperature limit requires object_id")
            require_object(object_id, "Temperature limit")
            maximum = row.get("max_temperature_c", row.get("max_c", row.get("temperature_c") if typ == "max_temperature" else None))
            minimum = row.get("min_temperature_c", row.get("min_c"))
            limits.append({
                "id": str(row.get("id") or ""),
                "object_id": object_id,
                "max_temperature_c": None if maximum is None else float(maximum),
                "min_temperature_c": None if minimum is None else float(minimum),
            })
        elif typ in _RADIATION_TYPES:
            object_id = thermal_network._target_id(row)
            if not object_id:
                raise ValueError("Radiation boundary requires object_id")
            obj = require_object(object_id, "Radiation boundary")
            emissivity = float(row.get("emissivity"))
            ambient = float(row.get("ambient_c", row.get("surroundings_c")))
            if not math.isfinite(emissivity) or not (0.0 < emissivity <= 1.0):
                raise ValueError("radiation emissivity must be > 0 and <= 1")
            if not math.isfinite(ambient):
                raise ValueError("radiation ambient_c/surroundings_c must be finite")
            radiation.append({
                "object_id": object_id,
                "emissivity": emissivity,
                "ambient_c": ambient,
                "area_m2": _radiation_area_m2(row, obj),
            })

    if not node_ids:
        raise ValueError("Transient thermal simulation requires canonical heat/boundary/link records")
    if not fixed and not convection and not radiation:
        raise ValueError("Transient thermal network has no modeled heat-rejection or fixed-temperature boundary")

    ids = sorted(node_ids)
    index = {object_id: i for i, object_id in enumerate(ids)}
    n = len(ids)
    capacity = np.zeros(n, dtype=float)
    capacity_meta: dict[str, dict[str, Any]] = {}
    for object_id in ids:
        capacity[index[object_id]], capacity_meta[object_id] = _thermal_capacity_j_k(objects[object_id])

    base_g = np.zeros((n, n), dtype=float)
    base_rhs = np.zeros(n, dtype=float)
    heat_vector = np.zeros(n, dtype=float)
    convection_rows: list[dict[str, Any]] = []
    for object_id, power in heat.items():
        i = index[object_id]
        heat_vector[i] += power
        base_rhs[i] += power
    for link in links:
        i, j = index[link["a_id"]], index[link["b_id"]]
        g = float(link["conductance_w_k"])
        base_g[i, i] += g; base_g[j, j] += g
        base_g[i, j] -= g; base_g[j, i] -= g
    for object_id, rows in convection.items():
        i = index[object_id]
        for row in rows:
            g = float(row["conductance_w_k"])
            base_g[i, i] += g
            base_rhs[i] += g * float(row["ambient_c"])
            convection_rows.append({"object_id": object_id, **row})

    fixed_indices = np.asarray(sorted(index[object_id] for object_id in fixed), dtype=int)
    fixed_set = set(fixed_indices.tolist())
    unknown_indices = np.asarray([i for i in range(n) if i not in fixed_set], dtype=int)
    temperature = np.full(n, initial, dtype=float)
    for object_id, value in fixed.items():
        temperature[index[object_id]] = float(value)
    initial_vector = temperature.copy()

    stride = max(1, int(math.ceil(steps / max(2, int(max_samples) - 1))))
    samples: list[dict[str, Any]] = []

    def append_sample(step_index: int, current: np.ndarray) -> None:
        samples.append({
            "time_s": float(step_index * actual_dt),
            "temperatures_c": {object_id: float(current[index[object_id]]) for object_id in ids},
        })

    append_sample(0, temperature)
    generated_j = 0.0
    convection_j = 0.0
    radiation_j = 0.0
    fixed_sink_j = 0.0

    for step_index in range(1, steps + 1):
        g = base_g.copy()
        rhs = base_rhs.copy()
        rad_rows: list[tuple[int, float, float]] = []
        for row in radiation:
            i = index[str(row["object_id"])]
            body_k = max(float(temperature[i]) + 273.15, 1.0)
            ambient_k = max(float(row["ambient_c"]) + 273.15, 1.0)
            # q = eps*sigma*A*(T^4-Ta^4) = G_rad(T-Ta). Updating G_rad
            # from the previous implicit step is stable and preserves the exact
            # fourth-power secant coefficient for that linearization point.
            g_rad = float(row["emissivity"]) * _SIGMA * float(row["area_m2"]) * (body_k + ambient_k) * (body_k * body_k + ambient_k * ambient_k)
            g[i, i] += g_rad
            rhs[i] += g_rad * float(row["ambient_c"])
            rad_rows.append((i, g_rad, float(row["ambient_c"])))

        a = g + np.diag(capacity / actual_dt)
        b = rhs + (capacity / actual_dt) * temperature
        next_temperature = temperature.copy()
        if len(unknown_indices):
            reduced = a[np.ix_(unknown_indices, unknown_indices)]
            reduced_rhs = b[unknown_indices].copy()
            if len(fixed_indices):
                fixed_values = np.asarray([fixed[ids[i]] for i in fixed_indices], dtype=float)
                reduced_rhs -= a[np.ix_(unknown_indices, fixed_indices)] @ fixed_values
            try:
                next_temperature[unknown_indices] = np.linalg.solve(reduced, reduced_rhs)
            except np.linalg.LinAlgError as exc:
                raise ValueError("Transient thermal matrix is singular; one or more thermal masses have no modeled path to a boundary") from exc
        for object_id, value in fixed.items():
            next_temperature[index[object_id]] = float(value)
        if not np.all(np.isfinite(next_temperature)):
            raise ValueError("Transient thermal simulation produced non-finite temperatures")

        generated_j += float(np.sum(heat_vector)) * actual_dt
        convection_j += sum(
            float(row["conductance_w_k"]) * (float(next_temperature[index[str(row["object_id"])]]) - float(row["ambient_c"])) * actual_dt
            for row in convection_rows
        )
        radiation_j += sum(g_rad * (float(next_temperature[i]) - ambient) * actual_dt for i, g_rad, ambient in rad_rows)
        conduction_residual = g @ next_temperature - rhs
        fixed_sink_j += -sum(float(conduction_residual[i]) for i in fixed_indices) * actual_dt
        temperature = next_temperature
        if step_index % stride == 0 or step_index == steps:
            append_sample(step_index, temperature)

    stored_j = float(np.sum(capacity * (temperature - initial_vector)))
    balance_j = generated_j - convection_j - radiation_j - fixed_sink_j - stored_j
    nodes = [
        {
            "object_id": object_id,
            "name": str(objects[object_id].get("name") or object_id),
            "initial_temperature_c": float(initial_vector[index[object_id]]),
            "final_temperature_c": float(temperature[index[object_id]]),
            "max_temperature_c": max(float(sample["temperatures_c"][object_id]) for sample in samples),
            "thermal_capacity_j_k": float(capacity[index[object_id]]),
            **capacity_meta[object_id],
        }
        for object_id in ids
    ]
    limit_results = []
    for limit in limits:
        object_id = str(limit["object_id"])
        peak = max(float(sample["temperatures_c"][object_id]) for sample in samples)
        trough = min(float(sample["temperatures_c"][object_id]) for sample in samples)
        maximum = limit.get("max_temperature_c")
        minimum = limit.get("min_temperature_c")
        passed = (maximum is None or peak <= float(maximum)) and (minimum is None or trough >= float(minimum))
        limit_results.append({**deepcopy(limit), "peak_temperature_c": peak, "minimum_temperature_c_observed": trough, "passed": passed})

    return {
        "requested": True,
        "supported": True,
        "ok": all(bool(row["passed"]) for row in limit_results),
        "solver": "ForgeCAD TransientThermal",
        "solver_version": "6.1.0",
        "solver_grade": "engineering_iteration",
        "method": "lumped multi-body thermal capacitance network with implicit Euler and temperature-updated radiative conductance",
        "duration_s": duration,
        "timestep_s": actual_dt,
        "integration_steps": steps,
        "node_count": n,
        "nodes": nodes,
        "links": deepcopy(links),
        "radiation_boundaries": deepcopy(radiation),
        "limits": limit_results,
        "samples": samples,
        "energy_balance": {
            "generated_heat_j": generated_j,
            "convection_rejection_j": convection_j,
            "radiation_rejection_j": radiation_j,
            "fixed_temperature_sink_j": fixed_sink_j,
            "stored_energy_change_j": stored_j,
            "residual_j": balance_j,
        },
        "limitations": [
            "Each ForgeCAD object is modeled as one isothermal thermal mass; intra-body temperature gradients require a field solver.",
            "Conductive/contact links exist only when explicitly modeled; CAD contact does not invent contact conductance.",
            "Convection coefficients, emissivity and surroundings are engineering inputs and are never inferred from appearance.",
            "Radiation uses a temperature-updated secant conductance each implicit step; participating-media radiation is not modeled.",
            "Fluid advection and conjugate CFD heat transfer require a CFD-capable external solver/case adapter.",
        ],
        "physical_verification": False,
    }
