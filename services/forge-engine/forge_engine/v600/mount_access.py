from __future__ import annotations

"""Physical envelope and tool-access validation for realized mounting hardware.

A dimensionally valid fastener stack can still be impossible to assemble if a
neighboring object occupies the standoff envelope or blocks driver access. This
module constructs explicit world-space clearance volumes from the same canonical
mount geometry/hardware plan and intersects them with actual ForgeCAD B-reps.

A critical evidence boundary is enforced here: neighboring project objects are
hard collision evidence because their canonical B-reps are the design truth. A
purchased component's *own* tool-access obstruction is only a hard result when
its resolved geometry is externally authoritative (official/verified CAD). A
ForgeCAD-derived fallback is useful for visualization and many deterministic
checks, but it cannot silently become manufacturer truth for package clearance.

The controlled capability is deliberately geometric only. It does not claim
ergonomic reachability, flexible-tool access, preload/torque adequacy or strength.
"""

from typing import Any

import cadquery as cq
import numpy as np
from pydantic import BaseModel, Field

from ..v110 import core, physical_components
from .mount_hardware import MountHardwareRequest, audit_mount_hardware


_AUTHORITATIVE_SELF_ACCESS_FIDELITIES = {"official_step", "official_cad", "verified_step"}


class MountAccessRequest(MountHardwareRequest):
    standoff_outer_diameter_mm: float = Field(gt=0.0, le=50.0)
    top_tool_clearance_diameter_mm: float = Field(gt=0.0, le=100.0)
    top_tool_clearance_height_mm: float = Field(gt=0.0, le=250.0)
    bottom_tool_clearance_diameter_mm: float = Field(gt=0.0, le=100.0)
    bottom_tool_clearance_height_mm: float = Field(gt=0.0, le=250.0)
    surface_epsilon_mm: float = Field(default=0.05, gt=0.0, le=1.0)
    interference_volume_tolerance_mm3: float = Field(default=1e-5, ge=0.0, le=10.0)


def _vec(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,):
        raise ValueError("Expected a 3-vector")
    return arr


def _unit(value: Any) -> np.ndarray:
    arr = _vec(value)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise ValueError("Envelope axis cannot be zero")
    return arr / norm


def _cylinder(start: np.ndarray, direction: np.ndarray, length_mm: float, diameter_mm: float, x_axis: np.ndarray):
    direction = _unit(direction)
    x_axis = _unit(x_axis)
    # Keep xDir perpendicular to the extrusion direction even if a future frame
    # arrives with slight numerical drift.
    x_axis = x_axis - direction * float(np.dot(x_axis, direction))
    x_axis = _unit(x_axis)
    plane = cq.Plane(
        origin=tuple(float(value) for value in start),
        xDir=tuple(float(value) for value in x_axis),
        normal=tuple(float(value) for value in direction),
    )
    return cq.Workplane(plane).circle(float(diameter_mm) / 2.0).extrude(float(length_mm)).val()


def _object(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects") or []:
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _candidate_objects(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in project.get("objects") or [] if isinstance(row, dict) and row.get("visible", True)]


def _intersection_volume(shape, envelope) -> float:
    try:
        return abs(float(shape.intersect(envelope).Volume()))
    except Exception:
        # Collision analysis is fail-closed. A shape that cannot be intersected
        # is not silently declared clear.
        return float("inf")


def _component_self_access_status(component: dict[str, Any]) -> dict[str, Any]:
    status = physical_components.component_geometry_status(component)
    fidelity = str(status.get("geometry_fidelity") or "")
    checked = (
        bool(status.get("resolved"))
        and not bool(status.get("fallback"))
        and fidelity in _AUTHORITATIVE_SELF_ACCESS_FIDELITIES
    )
    return {
        "checked": checked,
        "geometry_status": status,
        "reason": (
            "component self-access checked against externally authoritative CAD"
            if checked
            else "component self-access remains unverified because current component geometry is a non-authoritative fallback/proxy"
        ),
    }


def _envelope_descriptor(
    *,
    kind: str,
    pattern_index: int,
    start: np.ndarray,
    direction: np.ndarray,
    length_mm: float,
    diameter_mm: float,
    x_axis: np.ndarray,
    exclusions: set[str],
) -> dict[str, Any]:
    direction = _unit(direction)
    center = start + direction * (float(length_mm) / 2.0)
    return {
        "kind": kind,
        "pattern_index": int(pattern_index),
        "start_world_mm": [float(v) for v in start],
        "center_world_mm": [float(v) for v in center],
        "axis_world": [float(v) for v in direction],
        "length_mm": float(length_mm),
        "diameter_mm": float(diameter_mm),
        "excluded_object_ids": sorted(exclusions),
        "_shape": _cylinder(start, direction, float(length_mm), float(diameter_mm), x_axis),
    }


def plan_mount_access(project: dict[str, Any], request: MountAccessRequest) -> dict[str, Any]:
    hardware_request = MountHardwareRequest(**request.model_dump())
    hardware_audit = audit_mount_hardware(project, hardware_request)
    if not hardware_audit.get("ok"):
        raise ValueError(f"Mount hardware must be realized and valid before access analysis: {hardware_audit.get('findings')}")

    hardware_plan = hardware_audit["plan"]
    geometry_plan = hardware_plan["geometry_audit"]["plan"]
    host_frame = geometry_plan["host_frame"]
    normal = _unit(host_frame["world_z_axis"])
    x_axis = _unit(host_frame["world_x_axis"])
    host_id = str(request.host_id)
    component_id = str(request.component_id)
    component = _object(project, component_id)
    component_self_access = _component_self_access_status(component)
    host_thickness = float(hardware_plan["host_thickness_mm"])
    component_thickness = float(hardware_plan["component_mount_thickness_mm"])
    standoff_height = float(hardware_plan["standoff_height_mm"])
    eps = float(request.surface_epsilon_mm)

    if standoff_height <= 2.0 * eps:
        raise ValueError("Standoff height is too small for the requested surface epsilon")

    envelopes: list[dict[str, Any]] = []
    for hole in geometry_plan["holes"]:
        index = int(hole["index"])
        host_plane = _vec(hole["world_center_mm"])

        # Exclude a small amount at each end so intended contact with host and
        # component surfaces does not become numerical self-interference.
        standoff_start = host_plane + normal * eps
        standoff_length = standoff_height - 2.0 * eps
        envelopes.append(
            _envelope_descriptor(
                kind="standoff_body",
                pattern_index=index,
                start=standoff_start,
                direction=normal,
                length_mm=standoff_length,
                diameter_mm=float(request.standoff_outer_diameter_mm),
                x_axis=x_axis,
                exclusions={host_id, component_id},
            )
        )

        # Source mount interface is the lower component mounting surface in this
        # validated standoff strategy. Driver access begins just above the
        # declared component mounting thickness so the PCB itself is not counted
        # as an obstruction. The mounted component is included as a possible
        # self-obstruction only when its CAD is externally authoritative.
        top_start = host_plane + normal * (standoff_height + component_thickness + eps)
        top_exclusions = {host_id}
        if not component_self_access["checked"]:
            top_exclusions.add(component_id)
        envelopes.append(
            _envelope_descriptor(
                kind="top_driver_access",
                pattern_index=index,
                start=top_start,
                direction=normal,
                length_mm=float(request.top_tool_clearance_height_mm),
                diameter_mm=float(request.top_tool_clearance_diameter_mm),
                x_axis=x_axis,
                exclusions=top_exclusions,
            )
        )

        # Bottom access begins outside the underside of the fabricated host. The
        # mounted component is on the opposite side of the host and is excluded.
        bottom_start = host_plane - normal * (host_thickness + eps)
        envelopes.append(
            _envelope_descriptor(
                kind="bottom_driver_access",
                pattern_index=index,
                start=bottom_start,
                direction=-normal,
                length_mm=float(request.bottom_tool_clearance_height_mm),
                diameter_mm=float(request.bottom_tool_clearance_diameter_mm),
                x_axis=x_axis,
                exclusions={component_id},
            )
        )

    public_envelopes = [{key: value for key, value in row.items() if key != "_shape"} for row in envelopes]
    limitations = [
        "does not prove human ergonomic access or angled/flexible driver access",
        "does not analyze fastener preload, torque, stripping, bearing stress or vibration retention",
        "hardware supplier/manufacturer identity can remain unresolved independently of geometric access",
    ]
    if not component_self_access["checked"]:
        limitations.append(
            "mounted-component self-obstruction is unresolved until externally authoritative CAD is registered to the canonical component frame"
        )
    return {
        "realization_id": hardware_plan["realization_id"],
        "binding_id": hardware_plan["binding_id"],
        "component_id": component_id,
        "host_id": host_id,
        "mount_positions": int(hardware_plan["quantity"]),
        "envelope_count": len(envelopes),
        "envelopes": public_envelopes,
        "component_self_access": component_self_access,
        "scope": "rigid world-space standoff/body and straight-driver clearance only",
        "limitations": limitations,
        "_runtime_envelopes": envelopes,
    }


def audit_mount_access(project: dict[str, Any], request: MountAccessRequest) -> dict[str, Any]:
    try:
        plan = plan_mount_access(project, request)
    except (KeyError, ValueError) as exc:
        return {
            "ok": False,
            "findings": [{"severity": "error", "code": "mount_access_prerequisite_invalid", "message": str(exc)}],
        }

    tolerance = float(request.interference_volume_tolerance_mm3)
    findings: list[dict[str, Any]] = []
    objects = _candidate_objects(project)
    shape_cache: dict[str, Any] = {}

    if not plan["component_self_access"]["checked"]:
        findings.append(
            {
                "severity": "warning",
                "code": "component_self_access_unverified",
                "object_id": plan["component_id"],
                "message": plan["component_self_access"]["reason"],
                "geometry_status": plan["component_self_access"]["geometry_status"],
            }
        )

    for envelope in plan["_runtime_envelopes"]:
        excluded = set(envelope["excluded_object_ids"])
        for obj in objects:
            object_id = str(obj.get("id") or "")
            if not object_id or object_id in excluded:
                continue
            if object_id not in shape_cache:
                try:
                    shape_cache[object_id] = core.build_shape(obj)
                except Exception as exc:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "mount_access_collision_shape_unavailable",
                            "object_id": object_id,
                            "object_name": obj.get("name"),
                            "message": str(exc),
                        }
                    )
                    continue
            overlap = _intersection_volume(shape_cache[object_id], envelope["_shape"])
            if overlap > tolerance:
                findings.append(
                    {
                        "severity": "error",
                        "code": "mount_access_interference",
                        "envelope_kind": envelope["kind"],
                        "pattern_index": int(envelope["pattern_index"]),
                        "object_id": object_id,
                        "object_name": obj.get("name"),
                        "interference_volume_mm3": overlap,
                        "tolerance_mm3": tolerance,
                    }
                )

    public_plan = {key: value for key, value in plan.items() if key != "_runtime_envelopes"}
    counts = {severity: sum(row["severity"] == severity for row in findings) for severity in ("error", "warning", "info")}
    return {
        "ok": counts["error"] == 0,
        "realization_id": plan["realization_id"],
        "mount_positions": plan["mount_positions"],
        "envelope_count": plan["envelope_count"],
        "objects_checked": len(objects),
        "counts": counts,
        "findings": findings,
        "plan": public_plan,
        "evidence": {
            "world_space_brep_intersection_checked": True,
            "neighboring_object_access_checked": True,
            "straight_driver_access_checked": True,
            "standoff_body_envelope_checked": True,
            "component_self_access_checked": bool(plan["component_self_access"]["checked"]),
        },
    }
