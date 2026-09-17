from __future__ import annotations

"""Aerodynamic integral-load simulation for ForgeCAD 6.1.

ForgeCAD must not call a coefficient calculation CFD. This built-in solver therefore
has a narrow, explicit job: given real assembly geometry, an explicit relative-air
state and explicit aerodynamic coefficients, compute reference geometry, dynamic
pressure and integrated lift/drag loads. It can feed those loads into the canonical
mechanical simulation stack.

A general OpenFOAM adapter remains fail-closed until a validated case generator and
result parser exist for the current geometry. Merely finding an OpenFOAM executable is
not treated as a solved CFD problem.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import core
from ..v600 import external_solvers


def _vec3(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three values")
    out = np.asarray([float(v) for v in value], dtype=float)
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{label} must contain finite values")
    return out


def _selected_objects(project: dict[str, Any], object_ids: list[str] | None) -> list[dict[str, Any]]:
    selected = {str(value) for value in object_ids or []}
    objects = [
        obj for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id") and obj.get("visible", True)
        and (not selected or str(obj.get("id")) in selected)
    ]
    if selected:
        found = {str(obj.get("id")) for obj in objects}
        missing = sorted(selected - found)
        if missing:
            raise ValueError("Unknown or hidden aerodynamic object IDs: " + ", ".join(missing))
    if not objects:
        raise ValueError("Aerodynamic simulation requires at least one visible object")
    return objects


def _assembly_bounds_mm(objects: list[dict[str, Any]]) -> dict[str, float]:
    bounds = {
        "xmin": float("inf"), "xmax": float("-inf"),
        "ymin": float("inf"), "ymax": float("-inf"),
        "zmin": float("inf"), "zmax": float("-inf"),
    }
    for obj in objects:
        try:
            bb = core.build_shape(obj).BoundingBox()
        except Exception as exc:
            raise ValueError(f"Cannot build aerodynamic geometry for {obj.get('name') or obj.get('id')}: {exc}") from exc
        bounds["xmin"] = min(bounds["xmin"], float(bb.xmin)); bounds["xmax"] = max(bounds["xmax"], float(bb.xmax))
        bounds["ymin"] = min(bounds["ymin"], float(bb.ymin)); bounds["ymax"] = max(bounds["ymax"], float(bb.ymax))
        bounds["zmin"] = min(bounds["zmin"], float(bb.zmin)); bounds["zmax"] = max(bounds["zmax"], float(bb.zmax))
    return bounds


def _projected_box_area_m2(bounds: dict[str, float], direction: np.ndarray) -> tuple[float, list[float]]:
    dx = max(0.0, bounds["xmax"] - bounds["xmin"]) * 1e-3
    dy = max(0.0, bounds["ymax"] - bounds["ymin"]) * 1e-3
    dz = max(0.0, bounds["zmax"] - bounds["zmin"]) * 1e-3
    n = np.abs(direction)
    # Orthographic silhouette area of the assembly's world-axis bounding box.
    area = float(n[0] * dy * dz + n[1] * dx * dz + n[2] * dx * dy)
    return area, [dx, dy, dz]


def openfoam_readiness() -> dict[str, Any]:
    status = external_solvers.solver_status("openfoam")
    return {
        **status,
        "case_generator_validated": False,
        "usable_for_general_forgecad_geometry": False,
        "reason": (
            "OpenFOAM executable availability alone is insufficient. ForgeCAD 6.1 does not yet claim a validated general B-rep domain/mesh/boundary-condition case generator."
        ),
    }


def solve_integral_aerodynamics(
    project: dict[str, Any],
    *,
    relative_air_velocity_m_s: list[float],
    air_density_kg_m3: float,
    drag_coefficient: float,
    object_ids: list[str] | None = None,
    reference_area_m2: float | None = None,
    lift_coefficient: float = 0.0,
    lift_direction: list[float] | None = None,
    dynamic_viscosity_pa_s: float | None = None,
    characteristic_length_m: float | None = None,
    center_of_pressure_mm: list[float] | None = None,
    moment_reference_mm: list[float] | None = None,
) -> dict[str, Any]:
    objects = _selected_objects(project, object_ids)
    velocity = _vec3(relative_air_velocity_m_s, "relative_air_velocity_m_s")
    speed = float(np.linalg.norm(velocity))
    if speed <= 1e-12:
        raise ValueError("relative_air_velocity_m_s must be non-zero")
    flow = velocity / speed
    density = float(air_density_kg_m3)
    cd = float(drag_coefficient)
    cl = float(lift_coefficient)
    if not math.isfinite(density) or density <= 0.0:
        raise ValueError("air_density_kg_m3 must be positive and finite")
    if not math.isfinite(cd) or cd < 0.0:
        raise ValueError("drag_coefficient must be finite and non-negative")
    if not math.isfinite(cl):
        raise ValueError("lift_coefficient must be finite")

    bounds = _assembly_bounds_mm(objects)
    derived_area, extents_m = _projected_box_area_m2(bounds, flow)
    if reference_area_m2 is None:
        area = derived_area
        area_source = "world-axis assembly bounding-box orthographic projection"
        area_fidelity = "conservative_geometry_envelope"
    else:
        area = float(reference_area_m2)
        area_source = "explicit_input"
        area_fidelity = "user_supplied"
    if not math.isfinite(area) or area <= 0.0:
        raise ValueError("reference aerodynamic area must be positive and finite")

    q = 0.5 * density * speed * speed
    drag_n = q * area * cd
    drag_vector = flow * drag_n
    lift_vector = np.zeros(3, dtype=float)
    if abs(cl) > 0.0:
        if lift_direction is None:
            raise ValueError("A non-zero lift_coefficient requires an explicit lift_direction")
        lift_axis = _vec3(lift_direction, "lift_direction")
        lift_axis = lift_axis - flow * float(np.dot(lift_axis, flow))
        lift_norm = float(np.linalg.norm(lift_axis))
        if lift_norm <= 1e-9:
            raise ValueError("lift_direction must have a component perpendicular to the relative airflow")
        lift_axis /= lift_norm
        lift_vector = lift_axis * (q * area * cl)
    total_force = drag_vector + lift_vector

    characteristic = float(characteristic_length_m) if characteristic_length_m is not None else max(extents_m)
    characteristic_source = "explicit_input" if characteristic_length_m is not None else "maximum assembly bounding-box extent"
    reynolds = None
    if dynamic_viscosity_pa_s is not None:
        viscosity = float(dynamic_viscosity_pa_s)
        if not math.isfinite(viscosity) or viscosity <= 0.0:
            raise ValueError("dynamic_viscosity_pa_s must be positive and finite")
        if characteristic <= 0.0:
            raise ValueError("characteristic_length_m must be positive")
        reynolds = density * speed * characteristic / viscosity

    moment = None
    if center_of_pressure_mm is not None or moment_reference_mm is not None:
        if center_of_pressure_mm is None or moment_reference_mm is None:
            raise ValueError("center_of_pressure_mm and moment_reference_mm must be provided together to compute an aerodynamic moment")
        cp = _vec3(center_of_pressure_mm, "center_of_pressure_mm") * 1e-3
        reference = _vec3(moment_reference_mm, "moment_reference_mm") * 1e-3
        moment = np.cross(cp - reference, total_force).tolist()

    return {
        "supported": True,
        "solver": "ForgeCAD IntegralAerodynamics",
        "solver_version": "6.1.0",
        "solver_grade": "screening",
        "method": "quasi-steady coefficient-based integrated aerodynamic load calculation",
        "object_ids": [str(obj["id"]) for obj in objects],
        "relative_air_velocity_m_s": velocity.tolist(),
        "speed_m_s": speed,
        "air_density_kg_m3": density,
        "dynamic_pressure_pa": q,
        "drag_coefficient": cd,
        "lift_coefficient": cl,
        "reference_area_m2": area,
        "reference_area_source": area_source,
        "reference_area_fidelity": area_fidelity,
        "assembly_bounds_mm": deepcopy(bounds),
        "drag_force_n": drag_n,
        "drag_force_vector_n": drag_vector.tolist(),
        "lift_force_vector_n": lift_vector.tolist(),
        "total_aerodynamic_force_n": total_force.tolist(),
        "aerodynamic_power_w": float(np.dot(total_force, velocity)),
        "moment_nm": moment,
        "characteristic_length_m": characteristic,
        "characteristic_length_source": characteristic_source,
        "reynolds_number": reynolds,
        "openfoam": openfoam_readiness(),
        "limitations": [
            "This is an integrated coefficient model, not CFD and not a pressure/velocity field solution.",
            "Drag/lift coefficients are explicit engineering inputs; ForgeCAD does not invent them from visual shape.",
            "When reference_area_m2 is omitted, the projected world-axis assembly bounding box is used and its fidelity is reported.",
            "Loads are quasi-steady; gusts, separation, wake interaction, ground effect, compressibility and aeroelasticity are not solved.",
            "A general OpenFOAM run fails closed until a validated ForgeCAD case generator exists even if OpenFOAM is installed.",
        ],
        "physical_verification": False,
    }
