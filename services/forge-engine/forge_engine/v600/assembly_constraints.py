from __future__ import annotations

"""ForgeCAD 6.0 milestone: deterministic interface-constrained assembly.

This module deliberately operates on the existing canonical project objects.
It does not create a second assembly model. A mate is recorded as both:
- a canonical project ``joint`` describing degrees of freedom and tolerances; and
- a project ``connection`` tying exact object/interface identities together.

The solver performs rigid placement only. Dynamic motion and contact are separate
analysis concerns. The important 6.0 invariant is that autonomous placement must
be derived from declared engineering interfaces, never from guessed bounding boxes.
"""

from copy import deepcopy
import math
from typing import Any, Literal
import uuid

import numpy as np
from pydantic import BaseModel, Field

from ..v110 import component_registry as registry
from ..v110 import physical_components


MateType = Literal["fixed", "revolute", "prismatic", "cylindrical", "planar"]
AxisRelation = Literal["auto", "aligned", "opposed"]

MATE_DOF: dict[str, dict[str, Any]] = {
    "fixed": {"count": 0, "allowed": []},
    "revolute": {"count": 1, "allowed": ["rotation_about_axis"]},
    "prismatic": {"count": 1, "allowed": ["translation_along_axis"]},
    "cylindrical": {"count": 2, "allowed": ["rotation_about_axis", "translation_along_axis"]},
    "planar": {"count": 3, "allowed": ["translation_in_plane_x", "translation_in_plane_y", "rotation_about_normal"]},
}

_FACE_KINDS = {
    "mount_face",
    "mount_pattern",
    "motor_mount",
    "servo_mount",
    "fan_mount",
    "sensor_mount",
    "power_supply_mount",
    "board_standoffs",
    "mount_hole",
}
_COAXIAL_KINDS = {
    "shaft",
    "cylindrical_mate",
    "shaft_coupler",
    "bearing_pocket",
    "rotary_output",
    "linear_output",
    "linkage",
}


class MateRequest(BaseModel):
    source_id: str
    target_id: str
    source_interface: str
    target_interface: str
    mate_type: MateType = "fixed"
    gap_mm: float = 0.0
    axis_relation: AxisRelation = "auto"
    clocking_deg: float = 0.0
    position_tolerance_mm: float = Field(default=0.05, gt=0.0, le=10.0)
    axis_tolerance_deg: float = Field(default=0.25, gt=0.0, le=10.0)
    allow_occupied: bool = False
    name: str | None = None


def _vec(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,):
        raise ValueError("Expected a 3-vector")
    return arr


def _unit(value: Any) -> np.ndarray:
    arr = _vec(value)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise ValueError("Interface axis cannot be zero")
    return arr / norm


def _rotation_xyz(deg: Any) -> np.ndarray:
    x, y, z = np.radians(_vec(deg))
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def _euler_xyz(matrix: np.ndarray) -> list[float]:
    m = np.asarray(matrix, dtype=float)
    y = math.asin(max(-1.0, min(1.0, -float(m[2, 0]))))
    if abs(math.cos(y)) > 1e-8:
        x = math.atan2(float(m[2, 1]), float(m[2, 2]))
        z = math.atan2(float(m[1, 0]), float(m[0, 0]))
    else:
        x = math.atan2(-float(m[1, 2]), float(m[1, 1]))
        z = 0.0
    return [math.degrees(x), math.degrees(y), math.degrees(z)]


def _axis_angle(axis: Any, angle_rad: float) -> np.ndarray:
    x, y, z = _unit(axis)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    C = 1.0 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ]
    )


def _align_axis(source_axis: Any, desired_axis: Any) -> np.ndarray:
    a = _unit(source_axis)
    b = _unit(desired_axis)
    cosine = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if cosine > 1.0 - 1e-12:
        return np.eye(3)
    if cosine < -1.0 + 1e-12:
        trial = np.array([1.0, 0.0, 0.0]) if abs(float(a[0])) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = _unit(np.cross(a, trial))
        return _axis_angle(axis, math.pi)
    cross = np.cross(a, b)
    sine = float(np.linalg.norm(cross))
    axis = cross / sine
    return _axis_angle(axis, math.atan2(sine, cosine))


def _object_by_id(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects", []):
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _interface(obj: dict[str, Any], interface_id: str) -> dict[str, Any]:
    return physical_components.object_interface(obj, interface_id)


def _world_frame(obj: dict[str, Any], interface_id: str) -> dict[str, Any]:
    interface = _interface(obj, interface_id)
    transform = obj.get("transform") or {}
    rotation = _rotation_xyz(transform.get("rotation_deg", [0.0, 0.0, 0.0]))
    origin = _vec(transform.get("position", [0.0, 0.0, 0.0]))
    local_position = _vec(interface.get("position_mm", [0.0, 0.0, 0.0]))
    local_axis = _unit(interface.get("axis", [0.0, 0.0, 1.0]))
    world_position = origin + rotation @ local_position
    world_axis = _unit(rotation @ local_axis)
    return {
        **deepcopy(interface),
        "world_position_mm": world_position.tolist(),
        "world_axis": world_axis.tolist(),
    }


def _resolved_axis_relation(a: dict[str, Any], b: dict[str, Any], explicit: str, mate_type: str) -> str:
    if explicit != "auto":
        return explicit
    kinds = {str(a.get("kind") or ""), str(b.get("kind") or "")}
    if mate_type == "planar" or kinds & _FACE_KINDS:
        return "opposed"
    if mate_type in {"revolute", "prismatic", "cylindrical"} or kinds & _COAXIAL_KINDS:
        return "aligned"
    return "opposed"


def _exclusive_interface(interface: dict[str, Any]) -> bool:
    metadata = interface.get("metadata") or {}
    if "max_connections" in metadata:
        return int(metadata["max_connections"]) <= 1
    kind = str(interface.get("kind") or "")
    if kind.startswith("electrical") or kind in {
        "digital_io",
        "pwm_input",
        "pwm_output",
        "i2c",
        "spi",
        "uart",
        "airflow",
        "fan_power",
        "motor_power",
        "motor_output",
        "switched_power",
    }:
        return False
    return True


def _occupied(project: dict[str, Any], object_id: str, interface_id: str) -> list[str]:
    hits: list[str] = []
    for row in project.get("connections", []):
        for side in ("a", "b"):
            endpoint = row.get(side) or {}
            if str(endpoint.get("object_id")) == str(object_id) and str(endpoint.get("interface_id")) == str(interface_id):
                hits.append(str(row.get("id") or "connection"))
    return hits


def solve_mate_transform(project: dict[str, Any], request: MateRequest) -> dict[str, Any]:
    source = _object_by_id(project, request.source_id)
    target = _object_by_id(project, request.target_id)
    if source is target:
        raise ValueError("Cannot mate an object to itself")

    source_interface = _interface(source, request.source_interface)
    target_interface = _interface(target, request.target_interface)
    compatibility = registry.interface_compatibility(source_interface, target_interface)
    if not compatibility["compatible"]:
        raise ValueError("Incompatible interfaces: " + "; ".join(compatibility["reasons"]))

    if not request.allow_occupied:
        for obj, interface_id, interface in (
            (source, request.source_interface, source_interface),
            (target, request.target_interface, target_interface),
        ):
            uses = _occupied(project, str(obj["id"]), interface_id)
            if uses and _exclusive_interface(interface):
                raise ValueError(f"Interface {obj.get('name') or obj['id']}:{interface_id} is already occupied by {uses}")

    target_frame = _world_frame(target, request.target_interface)
    target_axis = _unit(target_frame["world_axis"])
    relation = _resolved_axis_relation(source_interface, target_interface, request.axis_relation, request.mate_type)
    desired_source_axis = target_axis if relation == "aligned" else -target_axis

    rotation = _align_axis(source_interface.get("axis", [0.0, 0.0, 1.0]), desired_source_axis)
    if abs(float(request.clocking_deg)) > 1e-12:
        rotation = _axis_angle(desired_source_axis, math.radians(float(request.clocking_deg))) @ rotation

    source_local_position = _vec(source_interface.get("position_mm", [0.0, 0.0, 0.0]))
    target_position = _vec(target_frame["world_position_mm"])
    desired_interface_position = target_position + target_axis * float(request.gap_mm)
    source_origin = desired_interface_position - rotation @ source_local_position

    transform = {
        "position": [float(v) for v in source_origin],
        "rotation_deg": [float(v) for v in _euler_xyz(rotation)],
        "scale": [1.0, 1.0, 1.0],
    }
    solved_source = deepcopy(source)
    solved_source["transform"] = deepcopy(transform)
    residual = mate_residual(solved_source, target, request.source_interface, request.target_interface, relation, request.gap_mm)
    return {
        "source_id": request.source_id,
        "target_id": request.target_id,
        "source_interface": request.source_interface,
        "target_interface": request.target_interface,
        "mate_type": request.mate_type,
        "axis_relation": relation,
        "transform": transform,
        "residual": residual,
        "degrees_of_freedom": deepcopy(MATE_DOF[request.mate_type]),
        "compatibility": compatibility,
    }


def mate_residual(
    source: dict[str, Any],
    target: dict[str, Any],
    source_interface_id: str,
    target_interface_id: str,
    axis_relation: str,
    gap_mm: float,
) -> dict[str, float]:
    source_frame = _world_frame(source, source_interface_id)
    target_frame = _world_frame(target, target_interface_id)
    source_position = _vec(source_frame["world_position_mm"])
    target_position = _vec(target_frame["world_position_mm"])
    target_axis = _unit(target_frame["world_axis"])
    desired_position = target_position + target_axis * float(gap_mm)
    position_error = float(np.linalg.norm(source_position - desired_position))

    source_axis = _unit(source_frame["world_axis"])
    desired_axis = target_axis if axis_relation == "aligned" else -target_axis
    cosine = float(np.clip(np.dot(source_axis, desired_axis), -1.0, 1.0))
    axis_error = math.degrees(math.acos(cosine))
    return {
        "position_error_mm": position_error,
        "axis_error_deg": axis_error,
    }


def apply_mate(project: dict[str, Any], request: MateRequest) -> dict[str, Any]:
    solved = solve_mate_transform(project, request)
    source = _object_by_id(project, request.source_id)
    target = _object_by_id(project, request.target_id)
    source["transform"] = deepcopy(solved["transform"])

    mate_id = f"mate-{uuid.uuid4()}"
    connection_id = f"connection-{uuid.uuid4()}"
    joint = {
        "id": mate_id,
        "name": request.name or f"{source.get('name') or source['id']} ↔ {target.get('name') or target['id']}",
        "type": request.mate_type,
        "a_id": str(source["id"]),
        "b_id": str(target["id"]),
        "a_interface": request.source_interface,
        "b_interface": request.target_interface,
        "axis_relation": solved["axis_relation"],
        "gap_mm": float(request.gap_mm),
        "clocking_deg": float(request.clocking_deg),
        "degrees_of_freedom": deepcopy(solved["degrees_of_freedom"]),
        "position_tolerance_mm": float(request.position_tolerance_mm),
        "axis_tolerance_deg": float(request.axis_tolerance_deg),
        "solver": "forgecad.v600.interface_mate",
    }
    connection = {
        "id": connection_id,
        "kind": "mechanical",
        "a": {"object_id": str(source["id"]), "interface_id": request.source_interface},
        "b": {"object_id": str(target["id"]), "interface_id": request.target_interface},
        "compatibility": deepcopy(solved["compatibility"]),
        "constraint_id": mate_id,
        "constraint": {
            "mate_type": request.mate_type,
            "axis_relation": solved["axis_relation"],
            "gap_mm": float(request.gap_mm),
            "position_tolerance_mm": float(request.position_tolerance_mm),
            "axis_tolerance_deg": float(request.axis_tolerance_deg),
        },
    }
    project.setdefault("joints", []).append(joint)
    project.setdefault("connections", []).append(connection)
    return {
        "ok": True,
        "mate": deepcopy(joint),
        "connection": deepcopy(connection),
        "transform": deepcopy(solved["transform"]),
        "residual": deepcopy(solved["residual"]),
    }


def validate_constraint_set(
    project: dict[str, Any],
    *,
    default_position_tolerance_mm: float = 0.05,
    default_axis_tolerance_deg: float = 0.25,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    checked = 0
    constrained = 0
    usage: dict[tuple[str, str], list[str]] = {}

    for connection in project.get("connections", []):
        connection_id = str(connection.get("id") or "connection")
        a_ref = connection.get("a") or {}
        b_ref = connection.get("b") or {}
        a_id, b_id = str(a_ref.get("object_id") or ""), str(b_ref.get("object_id") or "")
        a_interface_id, b_interface_id = str(a_ref.get("interface_id") or ""), str(b_ref.get("interface_id") or "")
        if not all((a_id, b_id, a_interface_id, b_interface_id)):
            findings.append({"severity": "error", "code": "malformed_connection", "connection_id": connection_id})
            continue
        for endpoint in ((a_id, a_interface_id), (b_id, b_interface_id)):
            usage.setdefault(endpoint, []).append(connection_id)
        try:
            a = _object_by_id(project, a_id)
            b = _object_by_id(project, b_id)
            ia = _interface(a, a_interface_id)
            ib = _interface(b, b_interface_id)
        except KeyError as exc:
            findings.append({
                "severity": "error",
                "code": "missing_connection_endpoint",
                "connection_id": connection_id,
                "message": f"Connection references missing object/interface {exc.args[0]}",
            })
            continue
        compatibility = registry.interface_compatibility(ia, ib)
        checked += 1
        if not compatibility["compatible"]:
            findings.append({
                "severity": "error",
                "code": "interface_incompatible",
                "connection_id": connection_id,
                "reasons": compatibility["reasons"],
            })

        constraint = connection.get("constraint")
        if not isinstance(constraint, dict) or str(connection.get("kind") or "") != "mechanical":
            continue
        constrained += 1
        relation = str(constraint.get("axis_relation") or "opposed")
        gap = float(constraint.get("gap_mm", 0.0))
        residual = mate_residual(a, b, a_interface_id, b_interface_id, relation, gap)
        pos_tol = float(constraint.get("position_tolerance_mm", default_position_tolerance_mm))
        axis_tol = float(constraint.get("axis_tolerance_deg", default_axis_tolerance_deg))
        if residual["position_error_mm"] > pos_tol:
            findings.append({
                "severity": "error",
                "code": "mate_position_residual",
                "connection_id": connection_id,
                "residual_mm": residual["position_error_mm"],
                "tolerance_mm": pos_tol,
            })
        if residual["axis_error_deg"] > axis_tol:
            findings.append({
                "severity": "error",
                "code": "mate_axis_residual",
                "connection_id": connection_id,
                "residual_deg": residual["axis_error_deg"],
                "tolerance_deg": axis_tol,
            })

    for (object_id, interface_id), connection_ids in sorted(usage.items()):
        if len(connection_ids) <= 1:
            continue
        try:
            interface = _interface(_object_by_id(project, object_id), interface_id)
        except KeyError:
            continue
        if _exclusive_interface(interface):
            findings.append({
                "severity": "error",
                "code": "exclusive_interface_overconstrained",
                "object_id": object_id,
                "interface_id": interface_id,
                "connection_ids": connection_ids,
            })

    counts = {severity: sum(item["severity"] == severity for item in findings) for severity in ("error", "warning", "info")}
    return {
        "ok": counts["error"] == 0,
        "connections_checked": checked,
        "constrained_mechanical_connections": constrained,
        "counts": counts,
        "findings": findings,
        "scope": "interface compatibility, occupancy, and rigid mate residuals; dynamic/contact solution is separate",
    }
