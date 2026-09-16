from __future__ import annotations

"""Structured 3D transient heat-conduction field solver for ForgeCAD 6.1.

The assembly thermal network intentionally treats each object as one thermal mass. This
solver covers a different fidelity layer: spatial temperature gradients inside a single
supported solid. It currently supports exact, unfeatured rectangular box solids only.
Unsupported CAD geometry fails closed rather than being silently replaced by a bounding
box.

The finite-volume update conserves internal conductive exchange face-by-face, applies
explicit all-surface convection/radiation boundary fluxes, and automatically subdivides
requested timesteps to satisfy a conservative explicit stability limit.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import core


_SIGMA = 5.670374419e-8


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _supported_box(obj: dict[str, Any]) -> tuple[bool, str | None]:
    if str(obj.get("kind") or "").lower() != "box":
        return False, "3D thermal field solve currently supports exact box solids only"
    if obj.get("features"):
        return False, "3D thermal field solve does not approximate featured box geometry as an unfeatured box"
    params = obj.get("params") or {}
    if not all(params.get(key) is not None for key in ("x", "y", "z")):
        return False, "box geometry requires x/y/z dimensions"
    return True, None


def _material(obj: dict[str, Any]) -> tuple[str, dict[str, float]]:
    material_id = str(obj.get("material") or "")
    raw = core.MATERIALS.get(material_id)
    if raw is None:
        raise ValueError(f"Unknown material {material_id!r}")
    required = {
        "density_kg_m3": raw.get("density_kg_m3"),
        "specific_heat_j_kgk": raw.get("specific_heat_j_kgk"),
        "thermal_w_mk": raw.get("thermal_w_mk"),
    }
    values: dict[str, float] = {}
    for key, value in required.items():
        parsed = _finite(value, f"material {material_id} {key}")
        if parsed <= 0.0:
            raise ValueError(f"material {material_id} {key} must be positive")
        values[key] = parsed
    return material_id, values


def _grid(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError("grid must contain nx, ny, nz")
    try:
        dims = tuple(int(v) for v in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("grid must contain integer nx, ny, nz") from exc
    if any(v < 3 or v > 36 for v in dims):
        raise ValueError("each thermal field grid dimension must be between 3 and 36")
    if math.prod(dims) > 24_000:
        raise ValueError("thermal field grid exceeds the 24,000-cell interactive limit")
    return dims  # type: ignore[return-value]


def _surface_energy_rate(
    temperature_c: np.ndarray,
    *,
    h: float,
    ambient_c: float,
    emissivity: float,
    area: float,
) -> tuple[np.ndarray, np.ndarray]:
    convection = h * area * (ambient_c - temperature_c)
    if emissivity <= 0.0:
        return convection, np.zeros_like(temperature_c)
    body_k = np.maximum(temperature_c + 273.15, 1.0)
    ambient_k = max(ambient_c + 273.15, 1.0)
    radiation = emissivity * _SIGMA * area * (ambient_k ** 4 - body_k ** 4)
    return convection, radiation


def _center_axis(length_m: float, cells: int) -> list[float]:
    spacing = length_m / cells
    start = -length_m / 2.0 + spacing / 2.0
    return [float((start + i * spacing) * 1000.0) for i in range(cells)]


def solve_box_thermal_field(
    project: dict[str, Any],
    object_id: str,
    *,
    duration_s: float,
    timestep_s: float,
    initial_temperature_c: float,
    heat_w: float,
    convection_h_w_m2k: float,
    ambient_temperature_c: float,
    emissivity: float = 0.0,
    grid: list[int] | tuple[int, int, int] = (12, 8, 6),
    max_samples: int = 120,
) -> dict[str, Any]:
    obj = next((row for row in project.get("objects") or [] if isinstance(row, dict) and str(row.get("id")) == str(object_id)), None)
    if obj is None:
        raise KeyError(object_id)
    supported, reason = _supported_box(obj)
    if not supported:
        return {
            "requested": True,
            "supported": False,
            "ok": False,
            "solver": "ForgeCAD ThermalField3D",
            "solver_version": "6.1.0",
            "solver_grade": "unsupported",
            "object_id": str(object_id),
            "reason": reason,
            "limitations": [
                "Unsupported geometry is never replaced with a bounding box for a field solve.",
                "Use the lumped assembly thermal network when the object is outside the exact built-in field-solver scope.",
            ],
            "physical_verification": False,
        }

    duration = _finite(duration_s, "duration_s")
    requested_dt = _finite(timestep_s, "timestep_s")
    initial = _finite(initial_temperature_c, "initial_temperature_c")
    source_w = _finite(heat_w, "heat_w")
    h = _finite(convection_h_w_m2k, "convection_h_w_m2k")
    ambient = _finite(ambient_temperature_c, "ambient_temperature_c")
    eps = _finite(emissivity, "emissivity")
    if duration <= 0.0 or requested_dt <= 0.0:
        raise ValueError("duration_s and timestep_s must be positive")
    if h < 0.0:
        raise ValueError("convection_h_w_m2k must be non-negative")
    if not 0.0 <= eps <= 1.0:
        raise ValueError("emissivity must be between 0 and 1")
    nx, ny, nz = _grid(grid)
    sample_limit = max(2, min(500, int(max_samples)))

    params = obj.get("params") or {}
    lx = _finite(params.get("x"), "box x") * 1e-3
    ly = _finite(params.get("y"), "box y") * 1e-3
    lz = _finite(params.get("z"), "box z") * 1e-3
    if min(lx, ly, lz) <= 0.0:
        raise ValueError("box dimensions must be positive")
    dx, dy, dz = lx / nx, ly / ny, lz / nz
    cell_volume = dx * dy * dz
    face_yz, face_xz, face_xy = dy * dz, dx * dz, dx * dy

    material_id, material = _material(obj)
    rho = material["density_kg_m3"]
    cp = material["specific_heat_j_kgk"]
    conductivity = material["thermal_w_mk"]
    cell_capacity = rho * cp * cell_volume
    gx = conductivity * face_yz / dx
    gy = conductivity * face_xz / dy
    gz = conductivity * face_xy / dz

    # Conservative explicit stability bound. The boundary contribution assumes a
    # worst-case corner cell with convection on all three exposed faces and a linearized
    # radiative conductance at the hotter of initial/ambient plus a 100 K margin.
    reference_k = max(initial, ambient) + 273.15 + 100.0
    radiation_h = 4.0 * eps * _SIGMA * reference_k ** 3
    boundary_g = (h + radiation_h) * (face_yz + face_xz + face_xy)
    max_local_g = 2.0 * (gx + gy + gz) + boundary_g
    stable_dt = 0.45 * cell_capacity / max(max_local_g, 1e-18)
    integration_dt_target = min(requested_dt, stable_dt)
    steps = int(math.ceil(duration / integration_dt_target))
    if steps > 50_000:
        raise ValueError(
            f"Thermal field solve requires {steps} stable integration steps; coarsen the grid, shorten duration, or use the lumped thermal model"
        )
    dt = duration / steps

    temperature = np.full((nx, ny, nz), initial, dtype=float)
    source_per_cell_w = source_w / float(nx * ny * nz)
    stride = max(1, int(math.ceil(steps / max(1, sample_limit - 1))))
    samples: list[dict[str, Any]] = []
    generated_j = 0.0
    convection_out_j = 0.0
    radiation_out_j = 0.0

    def sample(step: int) -> None:
        samples.append({
            "time_s": float(step * dt),
            "minimum_temperature_c": float(np.min(temperature)),
            "mean_temperature_c": float(np.mean(temperature)),
            "maximum_temperature_c": float(np.max(temperature)),
        })

    sample(0)
    for step in range(1, steps + 1):
        net = np.full_like(temperature, source_per_cell_w)

        qx = gx * (temperature[1:, :, :] - temperature[:-1, :, :])
        net[:-1, :, :] += qx
        net[1:, :, :] -= qx
        qy = gy * (temperature[:, 1:, :] - temperature[:, :-1, :])
        net[:, :-1, :] += qy
        net[:, 1:, :] -= qy
        qz = gz * (temperature[:, :, 1:] - temperature[:, :, :-1])
        net[:, :, :-1] += qz
        net[:, :, 1:] -= qz

        convection_in_w = 0.0
        radiation_in_w = 0.0
        for boundary, area in (
            (temperature[0, :, :], face_yz),
            (temperature[-1, :, :], face_yz),
            (temperature[:, 0, :], face_xz),
            (temperature[:, -1, :], face_xz),
            (temperature[:, :, 0], face_xy),
            (temperature[:, :, -1], face_xy),
        ):
            conv, rad = _surface_energy_rate(boundary, h=h, ambient_c=ambient, emissivity=eps, area=area)
            convection_in_w += float(np.sum(conv))
            radiation_in_w += float(np.sum(rad))

        conv, rad = _surface_energy_rate(temperature[0, :, :], h=h, ambient_c=ambient, emissivity=eps, area=face_yz)
        net[0, :, :] += conv + rad
        conv, rad = _surface_energy_rate(temperature[-1, :, :], h=h, ambient_c=ambient, emissivity=eps, area=face_yz)
        net[-1, :, :] += conv + rad
        conv, rad = _surface_energy_rate(temperature[:, 0, :], h=h, ambient_c=ambient, emissivity=eps, area=face_xz)
        net[:, 0, :] += conv + rad
        conv, rad = _surface_energy_rate(temperature[:, -1, :], h=h, ambient_c=ambient, emissivity=eps, area=face_xz)
        net[:, -1, :] += conv + rad
        conv, rad = _surface_energy_rate(temperature[:, :, 0], h=h, ambient_c=ambient, emissivity=eps, area=face_xy)
        net[:, :, 0] += conv + rad
        conv, rad = _surface_energy_rate(temperature[:, :, -1], h=h, ambient_c=ambient, emissivity=eps, area=face_xy)
        net[:, :, -1] += conv + rad

        next_temperature = temperature + (dt / cell_capacity) * net
        if not np.all(np.isfinite(next_temperature)):
            raise ValueError("3D thermal field solve produced non-finite temperatures")
        if float(np.min(next_temperature)) < -273.15:
            raise ValueError("3D thermal field solve produced a nonphysical temperature below absolute zero")
        generated_j += source_w * dt
        convection_out_j += -convection_in_w * dt
        radiation_out_j += -radiation_in_w * dt
        temperature = next_temperature
        if step % stride == 0 or step == steps:
            sample(step)

    total_capacity = cell_capacity * nx * ny * nz
    stored_j = total_capacity * (float(np.mean(temperature)) - initial)
    residual_j = generated_j - convection_out_j - radiation_out_j - stored_j
    gradients = np.gradient(temperature, dx, dy, dz, edge_order=1)
    gradient_magnitude = np.sqrt(sum(component * component for component in gradients))
    center = (nx // 2, ny // 2, nz // 2)

    return {
        "requested": True,
        "supported": True,
        "ok": True,
        "solver": "ForgeCAD ThermalField3D",
        "solver_version": "6.1.0",
        "solver_grade": "engineering_iteration",
        "method": "structured cell-centered finite-volume transient conduction with explicit conservative integration",
        "object_id": str(object_id),
        "object_name": str(obj.get("name") or object_id),
        "material": material_id,
        "material_properties": deepcopy(material),
        "dimensions_m": [lx, ly, lz],
        "grid": [nx, ny, nz],
        "cell_size_m": [dx, dy, dz],
        "requested_timestep_s": requested_dt,
        "stability_limit_s": stable_dt,
        "actual_timestep_s": dt,
        "integration_steps": steps,
        "duration_s": duration,
        "heat_w": source_w,
        "convection_h_w_m2k": h,
        "ambient_temperature_c": ambient,
        "emissivity": eps,
        "temperature": {
            "initial_c": initial,
            "minimum_c": float(np.min(temperature)),
            "mean_c": float(np.mean(temperature)),
            "maximum_c": float(np.max(temperature)),
            "center_c": float(temperature[center]),
            "maximum_gradient_k_m": float(np.max(gradient_magnitude)),
        },
        "energy_balance": {
            "generated_heat_j": generated_j,
            "convection_rejection_j": convection_out_j,
            "radiation_rejection_j": radiation_out_j,
            "stored_energy_change_j": stored_j,
            "residual_j": residual_j,
        },
        "axes_mm": {
            "x": _center_axis(lx, nx),
            "y": _center_axis(ly, ny),
            "z": _center_axis(lz, nz),
        },
        "final_temperature_field_c": temperature.tolist(),
        "center_slices_c": {
            "xy": temperature[:, :, center[2]].tolist(),
            "xz": temperature[:, center[1], :].tolist(),
            "yz": temperature[center[0], :, :].tolist(),
        },
        "samples": samples,
        "limitations": [
            "Exact built-in geometry scope is currently an unfeatured rectangular box; unsupported CAD fails closed rather than using an envelope.",
            "Heat generation is uniformly volumetric within the selected solid.",
            "Convection and radiation are applied uniformly to all six external faces; face-specific or contact-specific boundary conditions are not inferred.",
            "Temperature-dependent material properties, phase change, contact conductance, fluid advection and conjugate heat transfer are not modeled in this solver.",
            "This numerical prediction is not physical verification or thermal certification.",
        ],
        "physical_verification": False,
    }
