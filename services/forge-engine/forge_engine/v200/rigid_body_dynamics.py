from __future__ import annotations

"""Assembly mass properties and rigid-body dynamics screening for ForgeCAD 2.0.

This module answers a different engineering question from SolidFEA: if an assembly is
modeled as a rigid body, what are its center of mass, inertia tensor, acceleration,
momentum and short constant-load motion? It is deliberately deterministic and explicit
about where inertia is exact for analytic primitives versus approximated from a physical
envelope.

The solver does *not* model joints, contact, flexible-body response, damping, impacts,
actuator saturation, aerodynamic drag, gyroscopic coupling over large rotations, or
closed-loop control. Those remain separate dynamics/kinematics problems.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from . import parametric_expressions


_INSTALLED = False


class RigidBodyRequest(BaseModel):
    object_ids: list[str] = Field(default_factory=list)
    force_n: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    torque_nm: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    gravity_m_s2: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    duration_s: float = 0.0
    initial_velocity_m_s: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)
    initial_angular_velocity_rad_s: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0], min_length=3, max_length=3)


def _vec3(value: list[float], label: str) -> np.ndarray:
    out = np.asarray(value, dtype=float)
    if out.shape != (3,) or not np.all(np.isfinite(out)):
        raise ValueError(f"{label} must contain exactly three finite numbers")
    return out


def _rotation_matrix(rotation_deg: list[float]) -> np.ndarray:
    rx, ry, rz = [math.radians(float(v)) for v in rotation_deg]
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    my = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    mz = np.asarray([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    # core.build_shape applies X, then Y, then Z rotations to the body.
    return mz @ my @ mx


def _box_inertia(mass_kg: float, x_mm: float, y_mm: float, z_mm: float) -> np.ndarray:
    x, y, z = x_mm / 1000.0, y_mm / 1000.0, z_mm / 1000.0
    return np.diag([
        mass_kg * (y * y + z * z) / 12.0,
        mass_kg * (x * x + z * z) / 12.0,
        mass_kg * (x * x + y * y) / 12.0,
    ])


def _local_inertia(obj: dict[str, Any], mass_kg: float) -> tuple[np.ndarray, str, list[str]]:
    resolved = parametric_expressions.resolve_object(obj)
    params = resolved.get("params") or {}
    kind = str(resolved.get("kind") or "")
    scale = (resolved.get("transform") or {}).get("scale", [1.0, 1.0, 1.0])
    uniform_scale = float(scale[0]) if len(scale) == 3 and max(abs(float(v) - float(scale[0])) for v in scale) <= 1e-9 else 1.0

    if kind == "box" and not resolved.get("features"):
        return _box_inertia(
            mass_kg,
            abs(float(params.get("x", 0.0))) * uniform_scale,
            abs(float(params.get("y", 0.0))) * uniform_scale,
            abs(float(params.get("z", 0.0))) * uniform_scale,
        ), "analytic_box", []
    if kind == "cylinder" and not resolved.get("features"):
        radius = abs(float(params.get("radius", 0.0))) * uniform_scale / 1000.0
        height = abs(float(params.get("height", 0.0))) * 2.0 * uniform_scale / 1000.0
        radial = mass_kg * (3.0 * radius * radius + height * height) / 12.0
        axial = 0.5 * mass_kg * radius * radius
        return np.diag([radial, radial, axial]), "analytic_cylinder", []
    if kind == "sphere" and not resolved.get("features"):
        radius = abs(float(params.get("radius", 0.0))) * uniform_scale / 1000.0
        inertia = 0.4 * mass_kg * radius * radius
        return np.diag([inertia, inertia, inertia]), "analytic_sphere", []

    metrics = core.object_metrics(resolved)
    bounds = metrics.get("bounds_mm") or {}
    tensor = _box_inertia(
        mass_kg,
        max(float(bounds.get("x", 0.0)), 1e-9),
        max(float(bounds.get("y", 0.0)), 1e-9),
        max(float(bounds.get("z", 0.0)), 1e-9),
    )
    return tensor, "bounding_box_approximation", [
        "Local inertia for this body is approximated as a uniform rectangular envelope; center of mass and total mass still use ForgeCAD canonical geometry/component metadata.",
    ]


def object_mass_properties(obj: dict[str, Any]) -> dict[str, Any]:
    metrics = core.object_metrics(obj)
    mass = float(metrics.get("mass_kg") or 0.0)
    if not math.isfinite(mass) or mass <= 0.0:
        raise ValueError(f"Object {obj.get('id')} has no positive finite mass")
    centroid_mm = np.asarray(metrics.get("centroid_mm") or [0.0, 0.0, 0.0], dtype=float)
    if centroid_mm.shape != (3,) or not np.all(np.isfinite(centroid_mm)):
        raise ValueError(f"Object {obj.get('id')} has invalid centroid data")

    local, fidelity, limitations = _local_inertia(obj, mass)
    rotation = _rotation_matrix(list((obj.get("transform") or {}).get("rotation_deg", [0.0, 0.0, 0.0])))
    # For envelope fallbacks object_metrics already returns world-axis bounds, so rotating
    # that tensor again would double-apply orientation. Analytic primitives are local.
    world = local if fidelity == "bounding_box_approximation" else rotation @ local @ rotation.T
    return {
        "id": str(obj.get("id") or ""),
        "name": str(obj.get("name") or obj.get("id") or "Part"),
        "mass_kg": mass,
        "center_of_mass_m": (centroid_mm / 1000.0).tolist(),
        "inertia_centroid_kg_m2": world.tolist(),
        "inertia_fidelity": fidelity,
        "limitations": limitations,
    }


def assembly_mass_properties(project: dict[str, Any], object_ids: list[str] | None = None) -> dict[str, Any]:
    selected = {str(value) for value in object_ids or []}
    objects = [
        obj for obj in project.get("objects") or []
        if obj.get("visible", True) and (not selected or str(obj.get("id")) in selected)
    ]
    if selected:
        found = {str(obj.get("id")) for obj in objects}
        missing = sorted(selected - found)
        if missing:
            raise ValueError("Unknown or hidden object IDs: " + ", ".join(missing))
    if not objects:
        raise ValueError("Rigid-body analysis requires at least one visible object")

    bodies = [object_mass_properties(obj) for obj in objects]
    total_mass = sum(float(row["mass_kg"]) for row in bodies)
    if total_mass <= 0.0:
        raise ValueError("Rigid-body assembly has no positive mass")
    com = sum(float(row["mass_kg"]) * np.asarray(row["center_of_mass_m"], dtype=float) for row in bodies) / total_mass
    inertia = np.zeros((3, 3), dtype=float)
    approximation_count = 0
    limitations: list[str] = []
    for row in bodies:
        mass = float(row["mass_kg"])
        centroid = np.asarray(row["center_of_mass_m"], dtype=float)
        delta = centroid - com
        inertia += np.asarray(row["inertia_centroid_kg_m2"], dtype=float)
        inertia += mass * ((float(np.dot(delta, delta)) * np.eye(3)) - np.outer(delta, delta))
        if row["inertia_fidelity"] != "analytic_box" and not str(row["inertia_fidelity"]).startswith("analytic_"):
            approximation_count += 1
        limitations.extend(str(item) for item in row.get("limitations") or [])

    eig = np.linalg.eigvalsh((inertia + inertia.T) * 0.5)
    return {
        "method": "rigid-body mass aggregation with parallel-axis theorem",
        "solver": "ForgeCAD RigidBody",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "object_count": len(bodies),
        "mass_kg": total_mass,
        "center_of_mass_m": com.tolist(),
        "center_of_mass_mm": (com * 1000.0).tolist(),
        "inertia_tensor_com_kg_m2": inertia.tolist(),
        "principal_moments_kg_m2": eig.tolist(),
        "bodies": bodies,
        "inertia_approximation_count": approximation_count,
        "limitations": sorted(set(limitations)),
        "physical_verification": False,
    }


def rigid_body_response(
    project: dict[str, Any],
    *,
    object_ids: list[str] | None = None,
    force_n: list[float] | None = None,
    torque_nm: list[float] | None = None,
    gravity_m_s2: list[float] | None = None,
    duration_s: float = 0.0,
    initial_velocity_m_s: list[float] | None = None,
    initial_angular_velocity_rad_s: list[float] | None = None,
) -> dict[str, Any]:
    props = assembly_mass_properties(project, object_ids)
    force = _vec3(force_n or [0.0, 0.0, 0.0], "force_n")
    torque = _vec3(torque_nm or [0.0, 0.0, 0.0], "torque_nm")
    gravity = _vec3(gravity_m_s2 or [0.0, 0.0, 0.0], "gravity_m_s2")
    velocity0 = _vec3(initial_velocity_m_s or [0.0, 0.0, 0.0], "initial_velocity_m_s")
    omega0 = _vec3(initial_angular_velocity_rad_s or [0.0, 0.0, 0.0], "initial_angular_velocity_rad_s")
    duration = float(duration_s)
    if not math.isfinite(duration) or duration < 0.0:
        raise ValueError("duration_s must be finite and non-negative")

    mass = float(props["mass_kg"])
    net_force = force + mass * gravity
    linear_acceleration = net_force / mass
    inertia = np.asarray(props["inertia_tensor_com_kg_m2"], dtype=float)
    try:
        angular_acceleration = np.linalg.solve(inertia, torque)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Assembly inertia tensor is singular; rigid-body angular response is undefined") from exc

    velocity = velocity0 + linear_acceleration * duration
    displacement = velocity0 * duration + 0.5 * linear_acceleration * duration * duration
    omega = omega0 + angular_acceleration * duration
    angular_displacement = omega0 * duration + 0.5 * angular_acceleration * duration * duration
    momentum = mass * velocity
    angular_momentum = inertia @ omega
    translational_ke = 0.5 * mass * float(np.dot(velocity, velocity))
    rotational_ke = 0.5 * float(omega @ inertia @ omega)

    return {
        **deepcopy(props),
        "load_case": {
            "applied_force_n": force.tolist(),
            "gravity_m_s2": gravity.tolist(),
            "net_force_n": net_force.tolist(),
            "applied_torque_nm": torque.tolist(),
            "duration_s": duration,
        },
        "response": {
            "linear_acceleration_m_s2": linear_acceleration.tolist(),
            "angular_acceleration_rad_s2": angular_acceleration.tolist(),
            "initial_velocity_m_s": velocity0.tolist(),
            "final_velocity_m_s": velocity.tolist(),
            "displacement_m": displacement.tolist(),
            "initial_angular_velocity_rad_s": omega0.tolist(),
            "final_angular_velocity_rad_s": omega.tolist(),
            "angular_displacement_rad": angular_displacement.tolist(),
            "linear_momentum_kg_m_s": momentum.tolist(),
            "angular_momentum_kg_m2_s": angular_momentum.tolist(),
            "translational_kinetic_energy_j": translational_ke,
            "rotational_kinetic_energy_j": rotational_ke,
            "total_kinetic_energy_j": translational_ke + rotational_ke,
        },
        "assumptions": [
            "All selected bodies are locked into one perfectly rigid assembly.",
            "Applied force, torque and gravity are constant over the requested interval.",
            "Angular integration uses constant initial-world-frame angular acceleration; large-rotation gyroscopic coupling is not modeled.",
            "No joints, contact, drag, damping, flexible response, actuator limits, control loops, impacts or collision constraints are modeled.",
        ],
        "physical_verification": False,
    }


def install(legacy: Any) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    app = legacy.app

    @app.get("/v2/analysis/mass-properties", dependencies=[Depends(legacy.require_session)])
    async def mass_properties() -> dict[str, Any]:
        try:
            return assembly_mass_properties(core.PROJECT)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v2/analysis/rigid-body", dependencies=[Depends(legacy.require_session)])
    async def rigid_body(request: RigidBodyRequest) -> dict[str, Any]:
        try:
            result = rigid_body_response(
                core.PROJECT,
                object_ids=request.object_ids or None,
                force_n=request.force_n,
                torque_nm=request.torque_nm,
                gravity_m_s2=request.gravity_m_s2,
                duration_s=request.duration_s,
                initial_velocity_m_s=request.initial_velocity_m_s,
                initial_angular_velocity_rad_s=request.initial_angular_velocity_rad_s,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        core.record_simulation("rigid_body", None, request.model_dump(), result)
        return result

    _INSTALLED = True
