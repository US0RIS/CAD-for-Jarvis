from __future__ import annotations

"""Milestone-2 full-frame assembly constraints.

Milestone 1 aligned interface points and normals.  This layer preserves that
validated substrate while removing the remaining arbitrary rotation about a
normal for mate types that should lock clocking (fixed and prismatic).

Revolute, cylindrical, and planar mates deliberately retain their legitimate
rotational degree of freedom and continue to use the Milestone-1 solver.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np
from pydantic import Field

from ..v110 import physical_components
from . import assembly_constraints as base
from . import interface_frames


_FRAME_LOCKED_TYPES = {"fixed", "prismatic"}


class MateRequest(base.MateRequest):
    clocking_tolerance_deg: float = Field(default=0.25, gt=0.0, le=10.0)
    require_declared_secondary_datum: bool = False


def _object(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects") or []:
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _resolved_relation(source_interface: dict[str, Any], target_interface: dict[str, Any], request: MateRequest) -> str:
    if request.axis_relation != "auto":
        return str(request.axis_relation)
    face_kinds = {
        "mount_face", "mount_pattern", "motor_mount", "servo_mount", "fan_mount",
        "sensor_mount", "power_supply_mount", "board_standoffs", "mount_hole",
    }
    coaxial_kinds = {
        "shaft", "cylindrical_mate", "shaft_coupler", "bearing_pocket",
        "rotary_output", "linear_output", "linkage",
    }
    kinds = {str(source_interface.get("kind") or ""), str(target_interface.get("kind") or "")}
    if request.mate_type == "planar" or kinds & face_kinds:
        return "opposed"
    if request.mate_type in {"revolute", "prismatic", "cylindrical"} or kinds & coaxial_kinds:
        return "aligned"
    return "opposed"


def _frame_residual(
    source: dict[str, Any],
    target: dict[str, Any],
    request: MateRequest,
    relation: str,
) -> dict[str, float]:
    source_frame = interface_frames.object_interface_frame(source, request.source_interface)
    target_frame = interface_frames.object_interface_frame(target, request.target_interface)
    desired = interface_frames.desired_mating_frame(target_frame, relation, request.clocking_deg)
    source_origin = interface_frames.vec3(source_frame["world_origin_mm"])
    target_origin = interface_frames.vec3(target_frame["world_origin_mm"])
    target_axis = interface_frames.unit(target_frame["world_z_axis"])
    desired_origin = target_origin + target_axis * float(request.gap_mm)
    position_error = float(np.linalg.norm(source_origin - desired_origin))
    source_axis = interface_frames.unit(source_frame["world_z_axis"])
    desired_axis = interface_frames.unit(desired[:, 2])
    axis_cosine = float(np.clip(np.dot(source_axis, desired_axis), -1.0, 1.0))
    axis_error = math.degrees(math.acos(axis_cosine))
    clocking_error = abs(
        interface_frames.signed_clocking_error_deg(
            source_frame["world_x_axis"], desired[:, 0], desired_axis
        )
    )
    return {
        "position_error_mm": position_error,
        "axis_error_deg": axis_error,
        "clocking_error_deg": clocking_error,
    }


def solve_mate_transform(project: dict[str, Any], request: MateRequest) -> dict[str, Any]:
    # Base solve remains the authority for endpoint existence, compatibility,
    # occupancy and the unlocked mate families.
    baseline = base.solve_mate_transform(project, request)
    if request.mate_type not in _FRAME_LOCKED_TYPES:
        baseline["frame_lock"] = False
        baseline["clocking_residual_applicable"] = False
        return baseline

    source = _object(project, request.source_id)
    target = _object(project, request.target_id)
    source_interface = physical_components.object_interface(source, request.source_interface)
    target_interface = physical_components.object_interface(target, request.target_interface)
    source_local = interface_frames.local_basis(source_interface)
    target_frame = interface_frames.object_interface_frame(target, request.target_interface)
    relation = _resolved_relation(source_interface, target_interface, request)

    if request.require_declared_secondary_datum:
        if not bool(source_local["secondary_datum_declared"]):
            raise ValueError(
                f"{source.get('name') or source['id']}:{request.source_interface} lacks a declared secondary rotational datum"
            )
        if not bool(target_frame["secondary_datum_declared"]):
            raise ValueError(
                f"{target.get('name') or target['id']}:{request.target_interface} lacks a declared secondary rotational datum"
            )

    desired_frame = interface_frames.desired_mating_frame(target_frame, relation, request.clocking_deg)
    object_rotation = desired_frame @ np.asarray(source_local["matrix"], dtype=float).T
    target_origin = interface_frames.vec3(target_frame["world_origin_mm"])
    target_axis = interface_frames.unit(target_frame["world_z_axis"])
    desired_source_origin = target_origin + target_axis * float(request.gap_mm)
    local_interface_origin = interface_frames.vec3(source_interface.get("position_mm", [0.0, 0.0, 0.0]))
    object_origin = desired_source_origin - object_rotation @ local_interface_origin

    transform = {
        "position": [float(value) for value in object_origin],
        "rotation_deg": [float(value) for value in interface_frames.euler_xyz(object_rotation)],
        "scale": [1.0, 1.0, 1.0],
    }
    solved_source = deepcopy(source)
    solved_source["transform"] = deepcopy(transform)
    residual = _frame_residual(solved_source, target, request, relation)
    return {
        **baseline,
        "axis_relation": relation,
        "transform": transform,
        "residual": residual,
        "frame_lock": True,
        "clocking_residual_applicable": True,
        "source_secondary_datum": source_local["secondary_datum_provenance"],
        "target_secondary_datum": target_frame["secondary_datum_provenance"],
        "secondary_datums_declared": bool(source_local["secondary_datum_declared"] and target_frame["secondary_datum_declared"]),
        "solver": "forgecad.v600.full_interface_frame",
    }


def apply_mate(project: dict[str, Any], request: MateRequest) -> dict[str, Any]:
    solved = solve_mate_transform(project, request)
    # Reuse the already validated canonical record creation from Milestone 1,
    # then strengthen the transform/record with full-frame semantics.
    result = base.apply_mate(project, request)
    source = _object(project, request.source_id)
    source["transform"] = deepcopy(solved["transform"])

    mate_id = str(result["mate"]["id"])
    connection_id = str(result["connection"]["id"])
    joint = next(row for row in project.get("joints") or [] if str(row.get("id")) == mate_id)
    connection = next(row for row in project.get("connections") or [] if str(row.get("id")) == connection_id)
    if solved.get("frame_lock"):
        joint.update(
            {
                "solver": "forgecad.v600.full_interface_frame",
                "frame_lock": True,
                "clocking_tolerance_deg": float(request.clocking_tolerance_deg),
                "source_secondary_datum": solved["source_secondary_datum"],
                "target_secondary_datum": solved["target_secondary_datum"],
                "secondary_datums_declared": solved["secondary_datums_declared"],
            }
        )
        constraint = connection.setdefault("constraint", {})
        constraint.update(
            {
                "frame_lock": True,
                "clocking_deg": float(request.clocking_deg),
                "clocking_tolerance_deg": float(request.clocking_tolerance_deg),
                "source_secondary_datum": solved["source_secondary_datum"],
                "target_secondary_datum": solved["target_secondary_datum"],
            }
        )
    result.update(
        {
            "mate": deepcopy(joint),
            "connection": deepcopy(connection),
            "transform": deepcopy(solved["transform"]),
            "residual": deepcopy(solved["residual"]),
            "frame_lock": bool(solved.get("frame_lock")),
            "secondary_datums_declared": solved.get("secondary_datums_declared"),
        }
    )
    return result


def validate_constraint_set(
    project: dict[str, Any],
    *,
    default_position_tolerance_mm: float = 0.05,
    default_axis_tolerance_deg: float = 0.25,
    default_clocking_tolerance_deg: float = 0.25,
) -> dict[str, Any]:
    result = base.validate_constraint_set(
        project,
        default_position_tolerance_mm=default_position_tolerance_mm,
        default_axis_tolerance_deg=default_axis_tolerance_deg,
    )
    findings = list(result.get("findings") or [])
    joint_map = {str(row.get("id") or ""): row for row in project.get("joints") or [] if isinstance(row, dict)}

    for connection in project.get("connections") or []:
        if str(connection.get("kind") or "") != "mechanical":
            continue
        constraint = connection.get("constraint") or {}
        if not isinstance(constraint, dict) or not bool(constraint.get("frame_lock")):
            continue
        a_ref, b_ref = connection.get("a") or {}, connection.get("b") or {}
        try:
            source = _object(project, str(a_ref.get("object_id") or ""))
            target = _object(project, str(b_ref.get("object_id") or ""))
            req = MateRequest(
                source_id=str(a_ref.get("object_id") or ""),
                target_id=str(b_ref.get("object_id") or ""),
                source_interface=str(a_ref.get("interface_id") or ""),
                target_interface=str(b_ref.get("interface_id") or ""),
                mate_type=str(constraint.get("mate_type") or "fixed"),
                axis_relation=str(constraint.get("axis_relation") or "opposed"),
                gap_mm=float(constraint.get("gap_mm", 0.0)),
                clocking_deg=float(constraint.get("clocking_deg", 0.0)),
                position_tolerance_mm=float(constraint.get("position_tolerance_mm", default_position_tolerance_mm)),
                axis_tolerance_deg=float(constraint.get("axis_tolerance_deg", default_axis_tolerance_deg)),
                clocking_tolerance_deg=float(constraint.get("clocking_tolerance_deg", default_clocking_tolerance_deg)),
                allow_occupied=True,
            )
            residual = _frame_residual(source, target, req, str(req.axis_relation))
        except (KeyError, ValueError) as exc:
            findings.append(
                {
                    "severity": "error",
                    "code": "mate_frame_validation_failed",
                    "connection_id": str(connection.get("id") or "connection"),
                    "message": str(exc),
                }
            )
            continue
        if residual["clocking_error_deg"] > float(req.clocking_tolerance_deg):
            findings.append(
                {
                    "severity": "error",
                    "code": "mate_clocking_residual",
                    "connection_id": str(connection.get("id") or "connection"),
                    "residual_deg": residual["clocking_error_deg"],
                    "tolerance_deg": float(req.clocking_tolerance_deg),
                }
            )
        constraint_id = str(connection.get("constraint_id") or "")
        joint = joint_map.get(constraint_id) or {}
        if not bool(joint.get("secondary_datums_declared")):
            findings.append(
                {
                    "severity": "info",
                    "code": "mate_secondary_datum_inferred",
                    "connection_id": str(connection.get("id") or "connection"),
                    "message": "Full-frame clocking is deterministic but at least one secondary datum is inferred from the canonical object axes rather than declared by authoritative source data.",
                }
            )

    counts = {severity: sum(item.get("severity") == severity for item in findings) for severity in ("error", "warning", "info")}
    return {
        **result,
        "ok": counts["error"] == 0,
        "counts": counts,
        "findings": findings,
        "scope": "interface compatibility, occupancy, rigid mate residuals, and full-frame clocking for fixed/prismatic mates; dynamic/contact solution is separate",
    }
