from __future__ import annotations

"""ForgeCAD 6.0 milestone 2: geometry-backed mounting truth.

Milestone 1 proved that exact interface identities can drive deterministic rigid
placement. This module closes the next gap: a purchased component's declared
mounting pattern must correspond to actual editable geometry in the fabricated
part that receives it.

The implementation intentionally remains fail-closed. It only materializes
mounts whose authoritative component snapshot contains enough pattern geometry
to determine every hole center and diameter. Ambiguous patterns are rejected
rather than guessed.
"""

from copy import deepcopy
import math
from typing import Any

import cadquery as cq
import numpy as np
from pydantic import BaseModel, Field

from ..v110 import core, physical_components
from ..v310 import cad_features


class MountGeometryRequest(BaseModel):
    component_id: str
    host_id: str
    component_interface: str
    host_interface: str
    host_hole_diameter_mm: float | None = Field(default=None, gt=0.0, le=100.0)
    radial_clearance_mm: float = Field(default=0.0, ge=0.0, le=10.0)
    position_tolerance_mm: float = Field(default=0.05, gt=0.0, le=5.0)
    diameter_tolerance_mm: float = Field(default=0.05, gt=0.0, le=5.0)


def _vec(value: Any) -> np.ndarray:
    arr = np.asarray(value, dtype=float)
    if arr.shape != (3,):
        raise ValueError("Expected a 3-vector")
    return arr


def _unit(value: Any) -> np.ndarray:
    arr = _vec(value)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise ValueError("Interface frame axis cannot be zero")
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


def _object(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects", []):
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _snapshot_interface(component: dict[str, Any], interface_id: str) -> dict[str, Any]:
    snapshot = component.get("component_snapshot") or {}
    for interface in snapshot.get("interfaces") or []:
        if str(interface.get("id")) == str(interface_id):
            return deepcopy(interface)
    raise KeyError(interface_id)


def _interface_basis(interface: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, str]:
    """Return a deterministic right-handed full interface frame."""

    z_axis = _unit(interface.get("axis", [0.0, 0.0, 1.0]))
    metadata = interface.get("metadata") or {}
    explicit = interface.get("x_axis")
    if explicit is None and isinstance(metadata, dict):
        explicit = metadata.get("x_axis")
    provenance = "declared_secondary_datum" if explicit is not None else "canonical_object_axis"
    hint = _vec(explicit if explicit is not None else [1.0, 0.0, 0.0])
    x_axis = hint - z_axis * float(np.dot(hint, z_axis))
    if float(np.linalg.norm(x_axis)) < 1e-9:
        hint = np.array([0.0, 1.0, 0.0])
        x_axis = hint - z_axis * float(np.dot(hint, z_axis))
    x_axis = _unit(x_axis)
    y_axis = _unit(np.cross(z_axis, x_axis))
    return x_axis, y_axis, z_axis, provenance


def interface_frame(obj: dict[str, Any], interface_id: str) -> dict[str, Any]:
    interface = physical_components.object_interface(obj, interface_id)
    x_local, y_local, z_local, provenance = _interface_basis(interface)
    transform = obj.get("transform") or {}
    rotation = _rotation_xyz(transform.get("rotation_deg", [0.0, 0.0, 0.0]))
    object_origin = _vec(transform.get("position", [0.0, 0.0, 0.0]))
    local_origin = _vec(interface.get("position_mm", [0.0, 0.0, 0.0]))
    return {
        "interface_id": interface_id,
        "local_origin_mm": local_origin.tolist(),
        "local_x_axis": x_local.tolist(),
        "local_y_axis": y_local.tolist(),
        "local_z_axis": z_local.tolist(),
        "world_origin_mm": (object_origin + rotation @ local_origin).tolist(),
        "world_x_axis": _unit(rotation @ x_local).tolist(),
        "world_y_axis": _unit(rotation @ y_local).tolist(),
        "world_z_axis": _unit(rotation @ z_local).tolist(),
        "secondary_datum_provenance": provenance,
    }


def mount_pattern_definition(interface: dict[str, Any]) -> dict[str, Any]:
    metadata = interface.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("Mount interface metadata must be an object")

    diameter = metadata.get("hole_diameter_mm")
    if diameter is None:
        raise ValueError("Mount interface does not declare hole_diameter_mm; geometry cannot be inferred safely")
    diameter = float(diameter)
    if not math.isfinite(diameter) or diameter <= 0:
        raise ValueError("hole_diameter_mm must be finite and positive")

    explicit = metadata.get("hole_centers_mm")
    centers: list[list[float]] = []
    source = ""
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            raise ValueError("hole_centers_mm must be a non-empty list")
        for raw in explicit:
            if not isinstance(raw, (list, tuple)) or len(raw) not in {2, 3}:
                raise ValueError("Every hole center must contain two or three coordinates")
            row = [float(raw[0]), float(raw[1]), float(raw[2]) if len(raw) == 3 else 0.0]
            if not all(math.isfinite(value) for value in row):
                raise ValueError("Hole-center coordinates must be finite")
            centers.append(row)
        source = "explicit_hole_centers"
    else:
        spacing = metadata.get("pattern_mm") or metadata.get("hole_spacing_mm")
        if not isinstance(spacing, (list, tuple)) or len(spacing) != 2:
            raise ValueError("Mount interface must declare hole_centers_mm or a two-axis pattern_mm/hole_spacing_mm")
        sx, sy = float(spacing[0]), float(spacing[1])
        if not all(math.isfinite(value) and value > 0 for value in (sx, sy)):
            raise ValueError("Mount-pattern spacing must be finite and positive")
        count = metadata.get("count")
        pattern_name = str(metadata.get("pattern") or "").lower()
        if count is not None and int(count) != 4 and "4-hole" not in pattern_name:
            raise ValueError(
                f"Mount pattern declares count={count} without explicit hole centers; ForgeCAD will not guess its topology"
            )
        centers = [
            [-sx / 2.0, -sy / 2.0, 0.0],
            [sx / 2.0, -sy / 2.0, 0.0],
            [sx / 2.0, sy / 2.0, 0.0],
            [-sx / 2.0, sy / 2.0, 0.0],
        ]
        source = "derived_rectangular_pattern_from_declared_spacing"

    return {
        "hole_centers_mm": centers,
        "hole_diameter_mm": diameter,
        "hole_count": len(centers),
        "source": source,
        "fastener": metadata.get("fastener"),
        "pattern_metadata": deepcopy(metadata),
    }


def _mechanically_connected(project: dict[str, Any], request: MountGeometryRequest) -> dict[str, Any]:
    expected = {
        (str(request.component_id), str(request.component_interface)),
        (str(request.host_id), str(request.host_interface)),
    }
    for connection in project.get("connections") or []:
        if str(connection.get("kind") or "") != "mechanical":
            continue
        a = connection.get("a") or {}
        b = connection.get("b") or {}
        actual = {
            (str(a.get("object_id") or ""), str(a.get("interface_id") or "")),
            (str(b.get("object_id") or ""), str(b.get("interface_id") or "")),
        }
        if actual == expected:
            return connection
    raise ValueError("Geometry-backed mount requires an existing mechanical mate between the exact interfaces")


def _cardinal_axis(axis: np.ndarray) -> str:
    unit = _unit(axis)
    index = int(np.argmax(np.abs(unit)))
    if abs(float(unit[index])) < 0.999999:
        raise ValueError(
            "Host mount normal is not aligned to a local X/Y/Z machining axis; generalized directed-hole CAD is not yet validated"
        )
    return ("x", "y", "z")[index]


def _binding_id(request: MountGeometryRequest) -> str:
    return f"mount::{request.component_id}::{request.component_interface}::{request.host_id}::{request.host_interface}"


def plan_mount_geometry(project: dict[str, Any], request: MountGeometryRequest) -> dict[str, Any]:
    component = _object(project, request.component_id)
    host = _object(project, request.host_id)
    if component.get("kind") != "component" or not component.get("component_ref"):
        raise ValueError("component_id must identify an authoritative purchased-component instance")
    if host.get("kind") == "component":
        raise ValueError("Mount geometry can only be materialized into editable fabricated/custom geometry")

    connection = _mechanically_connected(project, request)
    source_interface = _snapshot_interface(component, request.component_interface)
    pattern = mount_pattern_definition(source_interface)
    source_frame = interface_frame(component, request.component_interface)
    host_frame = interface_frame(host, request.host_interface)

    source_origin = _vec(source_frame["world_origin_mm"])
    source_x = _unit(source_frame["world_x_axis"])
    source_y = _unit(source_frame["world_y_axis"])
    host_plane_origin = _vec(host_frame["world_origin_mm"])
    host_plane_normal = _unit(host_frame["world_z_axis"])
    relative_origin = source_origin - host_plane_origin
    axial_separation = float(np.dot(relative_origin, host_plane_normal))
    in_plane_offset = relative_origin - host_plane_normal * axial_separation
    pattern_origin_on_host = host_plane_origin + in_plane_offset

    host_transform = host.get("transform") or {}
    host_rotation = _rotation_xyz(host_transform.get("rotation_deg", [0.0, 0.0, 0.0]))
    host_origin = _vec(host_transform.get("position", [0.0, 0.0, 0.0]))
    host_interface = physical_components.object_interface(host, request.host_interface)
    drill_axis = _cardinal_axis(_unit(host_interface.get("axis", [0.0, 0.0, 1.0])))

    target_diameter = (
        float(request.host_hole_diameter_mm)
        if request.host_hole_diameter_mm is not None
        else float(pattern["hole_diameter_mm"]) + 2.0 * float(request.radial_clearance_mm)
    )
    if target_diameter <= 0:
        raise ValueError("Resolved host hole diameter must be positive")

    holes: list[dict[str, Any]] = []
    for index, offset in enumerate(pattern["hole_centers_mm"]):
        dx, dy, dz = [float(value) for value in offset]
        if abs(dz) > 1e-9:
            raise ValueError(
                "Host-hole materialization currently requires mounting-pattern centers to lie in the component interface plane"
            )
        # Preserve component clocking and any in-plane mate error, but deliberately
        # remove the axial mate gap.  A standoff can separate the component from
        # the host by several millimeters while the required drilled holes still
        # belong on the host's physical mounting plane.
        world = pattern_origin_on_host + source_x * dx + source_y * dy
        local = host_rotation.T @ (world - host_origin)
        holes.append(
            {
                "index": index,
                "component_offset_mm": [dx, dy, dz],
                "world_center_mm": [float(value) for value in world],
                "host_local_center_mm": [float(value) for value in local],
                "diameter_mm": target_diameter,
                "source_hole_diameter_mm": float(pattern["hole_diameter_mm"]),
                "axis": drill_axis,
            }
        )

    return {
        "binding_id": _binding_id(request),
        "component_id": str(component["id"]),
        "component_ref": str(component.get("component_ref")),
        "component_interface": request.component_interface,
        "host_id": str(host["id"]),
        "host_interface": request.host_interface,
        "connection_id": str(connection.get("id") or ""),
        "mate_gap_mm": float((connection.get("constraint") or {}).get("gap_mm", axial_separation)),
        "measured_axial_separation_mm": axial_separation,
        "component_snapshot_revision": (component.get("component_snapshot") or {}).get("revision"),
        "component_snapshot_trust": int((component.get("component_snapshot") or {}).get("trust_score", 0) or 0),
        "pattern": pattern,
        "source_frame": source_frame,
        "host_frame": host_frame,
        "holes": holes,
        "drill_axis": drill_axis,
        "scope": "mount-hole geometry only; fastener selection, threads/inserts, countersinks/counterbores and structural joint capacity remain separate",
    }


def _mount_features(host: dict[str, Any], binding_id: str) -> list[dict[str, Any]]:
    return [
        feature
        for feature in host.get("features") or []
        if isinstance(feature, dict)
        and isinstance(feature.get("mount_binding"), dict)
        and str(feature["mount_binding"].get("binding_id") or "") == binding_id
    ]


def _feature_center(feature: dict[str, Any]) -> np.ndarray:
    return np.asarray(
        [float(feature.get("x", 0.0)), float(feature.get("y", 0.0)), float(feature.get("z", 0.0))],
        dtype=float,
    )


def _witness_overlap_mm3(host: dict[str, Any], hole: dict[str, Any], host_frame: dict[str, Any]) -> float:
    shape = core.build_shape(host)
    bb = shape.BoundingBox()
    diagonal = math.sqrt(float(bb.xlen) ** 2 + float(bb.ylen) ** 2 + float(bb.zlen) ** 2)
    length = max(20.0, diagonal + 20.0)
    radius = max(0.05, float(hole["diameter_mm"]) * 0.2)
    center = _vec(hole["world_center_mm"])
    normal = _unit(host_frame["world_z_axis"])
    x_axis = _unit(host_frame["world_x_axis"])
    start = center - normal * (length / 2.0)
    plane = cq.Plane(
        origin=tuple(float(value) for value in start),
        xDir=tuple(float(value) for value in x_axis),
        normal=tuple(float(value) for value in normal),
    )
    witness = cq.Workplane(plane).circle(radius).extrude(length).val()
    overlap = shape.intersect(witness)
    return abs(float(overlap.Volume()))


def audit_mount_geometry(project: dict[str, Any], request: MountGeometryRequest) -> dict[str, Any]:
    plan = plan_mount_geometry(project, request)
    host = _object(project, request.host_id)
    features = _mount_features(host, plan["binding_id"])
    by_index = {
        int((feature.get("mount_binding") or {}).get("pattern_index")): feature
        for feature in features
        if (feature.get("mount_binding") or {}).get("pattern_index") is not None
    }
    findings: list[dict[str, Any]] = []

    if len(by_index) != len(plan["holes"]):
        findings.append(
            {
                "severity": "error",
                "code": "mount_feature_count_mismatch",
                "expected": len(plan["holes"]),
                "actual": len(by_index),
            }
        )

    for hole in plan["holes"]:
        index = int(hole["index"])
        feature = by_index.get(index)
        if feature is None:
            findings.append({"severity": "error", "code": "mount_hole_feature_missing", "pattern_index": index})
            continue
        center_error = float(np.linalg.norm(_feature_center(feature) - _vec(hole["host_local_center_mm"])))
        diameter_error = abs(float(feature.get("diameter", 0.0)) - float(hole["diameter_mm"]))
        if center_error > float(request.position_tolerance_mm):
            findings.append(
                {
                    "severity": "error",
                    "code": "mount_hole_position_mismatch",
                    "pattern_index": index,
                    "error_mm": center_error,
                    "tolerance_mm": float(request.position_tolerance_mm),
                }
            )
        if diameter_error > float(request.diameter_tolerance_mm):
            findings.append(
                {
                    "severity": "error",
                    "code": "mount_hole_diameter_mismatch",
                    "pattern_index": index,
                    "error_mm": diameter_error,
                    "tolerance_mm": float(request.diameter_tolerance_mm),
                }
            )

    if not any(item["severity"] == "error" for item in findings):
        for hole in plan["holes"]:
            overlap = _witness_overlap_mm3(host, hole, plan["host_frame"])
            radius = max(0.05, float(hole["diameter_mm"]) * 0.2)
            shape = core.build_shape(host)
            bb = shape.BoundingBox()
            diagonal = math.sqrt(float(bb.xlen) ** 2 + float(bb.ylen) ** 2 + float(bb.zlen) ** 2)
            witness_volume = math.pi * radius * radius * max(20.0, diagonal + 20.0)
            tolerance_volume = max(1e-6, witness_volume * 1e-7)
            if overlap > tolerance_volume:
                findings.append(
                    {
                        "severity": "error",
                        "code": "mount_hole_not_open_in_brep",
                        "pattern_index": int(hole["index"]),
                        "interference_volume_mm3": overlap,
                        "tolerance_volume_mm3": tolerance_volume,
                    }
                )

    counts = {severity: sum(item["severity"] == severity for item in findings) for severity in ("error", "warning", "info")}
    return {
        "ok": counts["error"] == 0,
        "binding_id": plan["binding_id"],
        "component_ref": plan["component_ref"],
        "host_id": plan["host_id"],
        "hole_count": len(plan["holes"]),
        "features_found": len(features),
        "counts": counts,
        "findings": findings,
        "plan": plan,
        "evidence": {
            "feature_history_checked": True,
            "final_brep_clearance_checked": not any(item["severity"] == "error" for item in findings if item["code"] != "mount_hole_not_open_in_brep"),
            "component_pattern_source": plan["pattern"]["source"],
            "component_snapshot_trust": plan["component_snapshot_trust"],
        },
    }


def materialize_mount_geometry(project: dict[str, Any], request: MountGeometryRequest, *, actor: str = "human") -> dict[str, Any]:
    plan = plan_mount_geometry(project, request)
    host = _object(project, request.host_id)
    if _mount_features(host, plan["binding_id"]):
        audit = audit_mount_geometry(project, request)
        if audit["ok"]:
            return {"ok": True, "created": [], "idempotent": True, "audit": audit}
        raise ValueError("Existing mount features for this binding do not satisfy the authoritative component pattern")

    before_features = deepcopy(host.get("features") or [])
    before_semantic = deepcopy(host.get("semantic") or {})
    created: list[dict[str, Any]] = []
    try:
        for hole in plan["holes"]:
            x, y, z = [float(value) for value in hole["host_local_center_mm"]]
            feature = cad_features.normalize_feature(
                {
                    "type": "hole",
                    "name": f"{plan['component_ref']} mount hole {int(hole['index']) + 1}",
                    "diameter": float(hole["diameter_mm"]),
                    "axis": str(hole["axis"]),
                    "x": x,
                    "y": y,
                    "z": z,
                    "mount_binding": {
                        "binding_id": plan["binding_id"],
                        "pattern_index": int(hole["index"]),
                        "component_id": plan["component_id"],
                        "component_ref": plan["component_ref"],
                        "component_interface": plan["component_interface"],
                        "host_interface": plan["host_interface"],
                        "source_pattern": plan["pattern"]["source"],
                        "source_hole_diameter_mm": float(hole["source_hole_diameter_mm"]),
                        "expected_world_center_mm": deepcopy(hole["world_center_mm"]),
                    },
                    "provenance": {
                        "actor": actor,
                        "method": "forgecad_v600_geometry_backed_mount",
                        "component_ref": plan["component_ref"],
                        "component_snapshot_revision": plan["component_snapshot_revision"],
                    },
                },
                actor=actor,
            )
            host.setdefault("features", []).append(feature)
            created.append(deepcopy(feature))

        host.setdefault("semantic", {}).setdefault("geometry_backed_mounts", []).append(
            {
                "binding_id": plan["binding_id"],
                "component_id": plan["component_id"],
                "component_ref": plan["component_ref"],
                "component_interface": plan["component_interface"],
                "host_interface": plan["host_interface"],
                "feature_ids": [str(feature["id"]) for feature in created],
                "hole_count": len(created),
                "pattern_source": plan["pattern"]["source"],
                "component_snapshot_trust": plan["component_snapshot_trust"],
            }
        )
        core.build_shape(host)
        audit = audit_mount_geometry(project, request)
        if not audit["ok"]:
            raise ValueError(f"Materialized mounting geometry failed independent audit: {audit['findings']}")
        return {"ok": True, "created": created, "idempotent": False, "audit": audit}
    except Exception:
        host["features"] = before_features
        host["semantic"] = before_semantic
        raise
