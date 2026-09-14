from __future__ import annotations

"""Full interface-coordinate frames for ForgeCAD 6.0 assembly truth.

An engineering interface is more than a point and a normal.  Fixed/prismatic
assembly needs an in-plane datum as well, otherwise rotation about the interface
normal is mathematically unspecified and autonomous placement can be arbitrary.

The canonical frame is right handed (X, Y, Z):
- Z is the declared interface ``axis``;
- X is an explicit ``x_axis`` datum when supplied, otherwise the object's local
  +X direction projected into the interface plane (falling back to +Y);
- Y = Z x X.

The fallback is deterministic and explicitly marked as inferred.  It is useful for
legacy records but is not equivalent to manufacturer-validated rotational datum.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import physical_components


def vec3(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,) or not np.all(np.isfinite(arr)):
        raise ValueError("Expected a finite 3-vector")
    return arr


def unit(value: Any) -> np.ndarray:
    arr = vec3(value)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise ValueError("Interface frame axis cannot be zero")
    return arr / norm


def rotation_xyz(deg: Any) -> np.ndarray:
    x, y, z = np.radians(vec3(deg))
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def euler_xyz(matrix: np.ndarray) -> list[float]:
    m = np.asarray(matrix, dtype=float)
    if m.shape != (3, 3):
        raise ValueError("Expected 3x3 rotation matrix")
    y = math.asin(max(-1.0, min(1.0, -float(m[2, 0]))))
    if abs(math.cos(y)) > 1e-8:
        x = math.atan2(float(m[2, 1]), float(m[2, 2]))
        z = math.atan2(float(m[1, 0]), float(m[0, 0]))
    else:
        x = math.atan2(-float(m[1, 2]), float(m[1, 1]))
        z = 0.0
    return [math.degrees(x), math.degrees(y), math.degrees(z)]


def axis_angle(axis: Any, angle_rad: float) -> np.ndarray:
    x, y, z = unit(axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    C = 1.0 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ]
    )


def align_axis(source_axis: Any, desired_axis: Any) -> np.ndarray:
    a, b = unit(source_axis), unit(desired_axis)
    cosine = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if cosine > 1.0 - 1e-12:
        return np.eye(3)
    if cosine < -1.0 + 1e-12:
        trial = np.array([1.0, 0.0, 0.0]) if abs(float(a[0])) < 0.9 else np.array([0.0, 1.0, 0.0])
        return axis_angle(unit(np.cross(a, trial)), math.pi)
    cross = np.cross(a, b)
    sine = float(np.linalg.norm(cross))
    return axis_angle(cross / sine, math.atan2(sine, cosine))


def local_basis(interface: dict[str, Any]) -> dict[str, Any]:
    z_axis = unit(interface.get("axis", [0.0, 0.0, 1.0]))
    metadata = interface.get("metadata") or {}
    explicit = interface.get("x_axis")
    if explicit is None and isinstance(metadata, dict):
        explicit = metadata.get("x_axis")
    provenance = "declared_secondary_datum" if explicit is not None else "canonical_object_axis_inferred"
    hint = vec3(explicit if explicit is not None else [1.0, 0.0, 0.0])
    x_axis = hint - z_axis * float(np.dot(hint, z_axis))
    if float(np.linalg.norm(x_axis)) < 1e-9:
        hint = np.array([0.0, 1.0, 0.0])
        x_axis = hint - z_axis * float(np.dot(hint, z_axis))
    x_axis = unit(x_axis)
    y_axis = unit(np.cross(z_axis, x_axis))
    matrix = np.column_stack((x_axis, y_axis, z_axis))
    if float(np.linalg.det(matrix)) < 0.999999:
        raise ValueError("Interface frame is not right handed")
    return {
        "x_axis": x_axis,
        "y_axis": y_axis,
        "z_axis": z_axis,
        "matrix": matrix,
        "secondary_datum_provenance": provenance,
        "secondary_datum_declared": explicit is not None,
    }


def object_interface_frame(obj: dict[str, Any], interface_id: str) -> dict[str, Any]:
    interface = physical_components.object_interface(obj, interface_id)
    local = local_basis(interface)
    transform = obj.get("transform") or {}
    object_rotation = rotation_xyz(transform.get("rotation_deg", [0.0, 0.0, 0.0]))
    object_origin = vec3(transform.get("position", [0.0, 0.0, 0.0]))
    local_origin = vec3(interface.get("position_mm", [0.0, 0.0, 0.0]))
    world_matrix = object_rotation @ local["matrix"]
    world_origin = object_origin + object_rotation @ local_origin
    return {
        "interface": deepcopy(interface),
        "interface_id": interface_id,
        "local_origin_mm": local_origin.tolist(),
        "local_x_axis": local["x_axis"].tolist(),
        "local_y_axis": local["y_axis"].tolist(),
        "local_z_axis": local["z_axis"].tolist(),
        "local_matrix": local["matrix"],
        "world_origin_mm": world_origin.tolist(),
        "world_x_axis": world_matrix[:, 0].tolist(),
        "world_y_axis": world_matrix[:, 1].tolist(),
        "world_z_axis": world_matrix[:, 2].tolist(),
        "world_matrix": world_matrix,
        "object_rotation": object_rotation,
        "object_origin_mm": object_origin.tolist(),
        "secondary_datum_provenance": local["secondary_datum_provenance"],
        "secondary_datum_declared": local["secondary_datum_declared"],
    }


def desired_mating_frame(target_frame: dict[str, Any], relation: str, clocking_deg: float = 0.0) -> np.ndarray:
    target = np.asarray(target_frame["world_matrix"], dtype=float)
    tx, ty, tz = target[:, 0], target[:, 1], target[:, 2]
    if relation == "aligned":
        desired = np.column_stack((tx, ty, tz))
    elif relation == "opposed":
        # Face-to-face orientation while preserving a right-handed frame.
        desired = np.column_stack((tx, -ty, -tz))
    else:
        raise ValueError(f"Unsupported axis relation: {relation}")
    if abs(float(clocking_deg)) > 1e-12:
        desired = axis_angle(desired[:, 2], math.radians(float(clocking_deg))) @ desired
    return desired


def signed_clocking_error_deg(actual_x: Any, desired_x: Any, about_axis: Any) -> float:
    axis = unit(about_axis)
    a = unit(vec3(actual_x) - axis * float(np.dot(vec3(actual_x), axis)))
    b = unit(vec3(desired_x) - axis * float(np.dot(vec3(desired_x), axis)))
    sine = float(np.dot(axis, np.cross(b, a)))
    cosine = float(np.clip(np.dot(b, a), -1.0, 1.0))
    return math.degrees(math.atan2(sine, cosine))
