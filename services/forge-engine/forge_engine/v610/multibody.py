from __future__ import annotations

"""Constraint-preserving multibody kinematics for ForgeCAD 6.1.

The 6.0 assembly layer records real mechanical mates but intentionally performs only
one-time placement. The original v2 mechanism solver is likewise deliberately limited
to a single moving child. 6.1 makes the canonical joint graph executable:

* moving an upstream body carries every downstream body with the same rigid delta;
* actuating a revolute/prismatic/cylindrical/planar joint moves the complete child
  subtree rather than one isolated mesh;
* joint motion is solved with homogeneous rigid transforms, so arbitrary body
  orientation and arbitrary joint axes are supported;
* cycles and ambiguous multi-parent trees fail closed instead of guessing ownership;
* scale is not used as a kinematic degree of freedom.

This is rigid multibody kinematics. Dynamic contact, compliance, friction and impact
remain separate solver concerns and are never implied by a successful pose solve.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import physical_components


_SUPPORTED = {"fixed", "revolute", "prismatic", "cylindrical", "planar"}


def _finite(value: Any, label: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _vec3(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three values")
    out = np.asarray([_finite(v, label) for v in value], dtype=float)
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{label} must be finite")
    return out


def _unit(value: Any, label: str) -> np.ndarray:
    out = _vec3(value, label)
    norm = float(np.linalg.norm(out))
    if norm <= 1e-12:
        raise ValueError(f"{label} must be non-zero")
    return out / norm


def _rotation_xyz(rotation_deg: Any) -> np.ndarray:
    x, y, z = np.radians(_vec3(rotation_deg, "rotation_deg"))
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rz = np.asarray([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
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
    x, y, z = _unit(axis, "axis")
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    one = 1.0 - c
    return np.asarray([
        [c + x*x*one, x*y*one - z*s, x*z*one + y*s],
        [y*x*one + z*s, c + y*y*one, y*z*one - x*s],
        [z*x*one - y*s, z*y*one + x*s, c + z*z*one],
    ], dtype=float)


def _translation(vector: Any) -> np.ndarray:
    out = np.eye(4, dtype=float)
    out[:3, 3] = _vec3(vector, "translation")
    return out


def _rotation4(axis: Any, angle_rad: float) -> np.ndarray:
    out = np.eye(4, dtype=float)
    out[:3, :3] = _axis_angle(axis, angle_rad)
    return out


def rigid_matrix(transform: dict[str, Any] | None) -> np.ndarray:
    value = transform or {}
    out = np.eye(4, dtype=float)
    out[:3, :3] = _rotation_xyz(value.get("rotation_deg", [0.0, 0.0, 0.0]))
    out[:3, 3] = _vec3(value.get("position", [0.0, 0.0, 0.0]), "position")
    return out


def transform_from_matrix(matrix: np.ndarray, *, scale: Any = None) -> dict[str, list[float]]:
    m = np.asarray(matrix, dtype=float)
    if m.shape != (4, 4) or not np.all(np.isfinite(m)):
        raise ValueError("Rigid transform matrix must be finite 4x4")
    rotation = m[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-7) or np.linalg.det(rotation) < 0.999999:
        raise ValueError("Simulation transform is not a proper rigid rotation")
    preserved_scale = [1.0, 1.0, 1.0] if scale is None else [float(v) for v in scale]
    return {
        "position": [float(v) for v in m[:3, 3]],
        "rotation_deg": [float(v) for v in _euler_xyz(rotation)],
        "scale": preserved_scale,
    }


def _objects(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id")
    }


def _joint_type(row: dict[str, Any]) -> str:
    return str(row.get("type", row.get("kind", "fixed"))).strip().lower()


def _edge_from_joint(row: dict[str, Any], objects: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    typ = _joint_type(row)
    if typ not in _SUPPORTED:
        return None

    if row.get("parent_id") not in (None, "") and row.get("child_id") not in (None, ""):
        parent_id = str(row["parent_id"])
        child_id = str(row["child_id"])
        orientation_source = "explicit_parent_child"
    elif row.get("a_id") not in (None, "") and row.get("b_id") not in (None, ""):
        # v600 apply_mate moves A/source into B/target. Therefore B is the supporting
        # parent and A is the downstream child for kinematic propagation.
        parent_id = str(row["b_id"])
        child_id = str(row["a_id"])
        orientation_source = "v600_mate"
    elif row.get("source_id") not in (None, "") and row.get("target_id") not in (None, ""):
        parent_id = str(row["source_id"])
        child_id = str(row["target_id"])
        orientation_source = "legacy_source_target"
    else:
        return None

    if parent_id == child_id:
        raise ValueError(f"Joint {row.get('id')} connects an object to itself")
    if parent_id not in objects or child_id not in objects:
        missing = parent_id if parent_id not in objects else child_id
        raise ValueError(f"Joint {row.get('id')} references missing object {missing}")
    return {
        "joint_id": str(row.get("id") or ""),
        "name": str(row.get("name") or row.get("id") or typ),
        "type": typ,
        "parent_id": parent_id,
        "child_id": child_id,
        "orientation_source": orientation_source,
        "row": row,
    }


def assembly_graph(project: dict[str, Any]) -> dict[str, Any]:
    objects = _objects(project)
    edges: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    parent_edge: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {object_id: [] for object_id in objects}

    for row in project.get("joints") or []:
        if not isinstance(row, dict):
            continue
        try:
            edge = _edge_from_joint(row, objects)
        except ValueError as exc:
            errors.append({"code": "invalid_joint", "joint_id": str(row.get("id") or ""), "message": str(exc)})
            continue
        if edge is None:
            continue
        child_id = edge["child_id"]
        if child_id in parent_edge:
            errors.append({
                "code": "multiple_kinematic_parents",
                "object_id": child_id,
                "joint_ids": [parent_edge[child_id]["joint_id"], edge["joint_id"]],
                "message": f"Object {child_id} has more than one kinematic parent; 6.1 fails closed rather than choosing a chain.",
            })
            continue
        parent_edge[child_id] = edge
        children.setdefault(edge["parent_id"], []).append(child_id)
        edges.append(edge)

    cycle_nodes: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle_nodes.add(node)
            return
        visiting.add(node)
        for child in children.get(node, []):
            if child in visiting:
                cycle_nodes.update({node, child})
            visit(child)
        visiting.discard(node)
        visited.add(node)

    for object_id in objects:
        visit(object_id)
    if cycle_nodes:
        errors.append({
            "code": "closed_kinematic_loop",
            "object_ids": sorted(cycle_nodes),
            "message": "Closed-loop kinematics requires a simultaneous constraint solve and is not silently reduced to a tree.",
        })

    public_edges = [{key: value for key, value in edge.items() if key != "row"} for edge in edges]
    roots = sorted(object_id for object_id in objects if object_id not in parent_edge)
    return {
        "ok": not errors,
        "solver": "ForgeCAD MultibodyKinematics",
        "solver_version": "6.1.0",
        "object_count": len(objects),
        "joint_count": len(edges),
        "roots": roots,
        "edges": public_edges,
        "errors": errors,
        "limitations": [
            "Rigid-body connectivity only; deformation, backlash, friction and impact are not implied.",
            "Closed kinematic loops fail closed until a simultaneous loop-closure solver is selected.",
        ],
    }


def _graph_runtime(project: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, dict[str, Any]]]:
    objects = _objects(project)
    children: dict[str, list[str]] = {object_id: [] for object_id in objects}
    parent_edge: dict[str, dict[str, Any]] = {}
    for row in project.get("joints") or []:
        if not isinstance(row, dict):
            continue
        edge = _edge_from_joint(row, objects)
        if edge is None:
            continue
        if edge["child_id"] in parent_edge:
            raise ValueError(f"Object {edge['child_id']} has multiple kinematic parents")
        parent_edge[edge["child_id"]] = edge
        children.setdefault(edge["parent_id"], []).append(edge["child_id"])

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("Closed kinematic loop requires simultaneous constraint solving")
        if node in visited:
            return
        visiting.add(node)
        for child in children.get(node, []):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for object_id in objects:
        visit(object_id)
    return objects, children, parent_edge


def descendants(project: dict[str, Any], root_id: str, *, include_root: bool = False) -> list[str]:
    objects, children, _ = _graph_runtime(project)
    if root_id not in objects:
        raise KeyError(root_id)
    out: list[str] = [root_id] if include_root else []
    stack = list(reversed(children.get(root_id, [])))
    while stack:
        current = stack.pop()
        out.append(current)
        stack.extend(reversed(children.get(current, [])))
    return out


def _same_scale(a: Any, b: Any) -> bool:
    try:
        aa = np.asarray([float(v) for v in a], dtype=float)
        bb = np.asarray([float(v) for v in b], dtype=float)
    except Exception:
        return False
    return aa.shape == (3,) and bb.shape == (3,) and bool(np.allclose(aa, bb, atol=1e-9))


def _interface_frame(obj: dict[str, Any], interface_id: str) -> tuple[np.ndarray, np.ndarray]:
    interface = physical_components.object_interface(obj, interface_id)
    body = rigid_matrix(obj.get("transform"))
    local_position = _vec3(interface.get("position_mm", [0.0, 0.0, 0.0]), "interface position")
    local_axis = _unit(interface.get("axis", [0.0, 0.0, 1.0]), "interface axis")
    return body[:3, :3] @ local_position + body[:3, 3], _unit(body[:3, :3] @ local_axis, "world interface axis")


def _mate_residual_for_dof(project: dict[str, Any], connection: dict[str, Any]) -> dict[str, float]:
    objects = _objects(project)
    a = connection.get("a") or {}
    b = connection.get("b") or {}
    a_id, b_id = str(a.get("object_id") or ""), str(b.get("object_id") or "")
    if a_id not in objects or b_id not in objects:
        raise ValueError("Mechanical connection references a missing object")
    ia, ib = str(a.get("interface_id") or ""), str(b.get("interface_id") or "")
    pa, aa = _interface_frame(objects[a_id], ia)
    pb, ab = _interface_frame(objects[b_id], ib)
    constraint = connection.get("constraint") or {}
    typ = str(constraint.get("mate_type") or "fixed").lower()
    relation = str(constraint.get("axis_relation") or "opposed")
    gap = float(constraint.get("gap_mm", 0.0))
    desired_axis = ab if relation == "aligned" else -ab
    cosine = float(np.clip(np.dot(aa, desired_axis), -1.0, 1.0))
    axis_error = math.degrees(math.acos(cosine))
    delta = pa - (pb + ab * gap)
    if typ in {"prismatic", "cylindrical"}:
        position_error = float(np.linalg.norm(delta - ab * float(np.dot(delta, ab))))
    elif typ == "planar":
        position_error = abs(float(np.dot(delta, ab)))
    else:
        position_error = float(np.linalg.norm(delta))
    return {"position_error_mm": position_error, "axis_error_deg": axis_error}


def _validate_affected_connections(project: dict[str, Any], affected: set[str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for connection in project.get("connections") or []:
        if not isinstance(connection, dict) or str(connection.get("kind") or "") != "mechanical":
            continue
        constraint = connection.get("constraint")
        if not isinstance(constraint, dict):
            continue
        a = connection.get("a") or {}
        b = connection.get("b") or {}
        ids = {str(a.get("object_id") or ""), str(b.get("object_id") or "")}
        if not (ids & affected):
            continue
        residual = _mate_residual_for_dof(project, connection)
        pos_tol = float(constraint.get("position_tolerance_mm", 0.05))
        axis_tol = float(constraint.get("axis_tolerance_deg", 0.25))
        if residual["position_error_mm"] > pos_tol or residual["axis_error_deg"] > axis_tol:
            findings.append({
                "connection_id": str(connection.get("id") or ""),
                "constraint_id": str(connection.get("constraint_id") or ""),
                "mate_type": str(constraint.get("mate_type") or "fixed"),
                "residual": residual,
                "position_tolerance_mm": pos_tol,
                "axis_tolerance_deg": axis_tol,
            })
    return findings


def solve_driver_transform(project: dict[str, Any], driver_id: str, transform: dict[str, Any]) -> dict[str, Any]:
    objects, _, parent_edge = _graph_runtime(project)
    if driver_id not in objects:
        raise KeyError(driver_id)
    driver = objects[driver_id]
    current = driver.get("transform") or {}
    requested_scale = transform.get("scale", current.get("scale", [1.0, 1.0, 1.0]))
    current_scale = current.get("scale", [1.0, 1.0, 1.0])
    if not _same_scale(requested_scale, current_scale):
        raise ValueError("Scale is not a physical joint degree of freedom; bake geometry dimensions before simulating an assembly")

    # A free viewport transform is an assembly-frame move, not a joint actuator. If
    # the selected body itself has a kinematic parent, forcing it independently would
    # make the input ambiguous. Explicit joint actuation handles that case.
    if driver_id in parent_edge:
        edge = parent_edge[driver_id]
        raise ValueError(
            f"{driver.get('name') or driver_id} is the child of {edge['name']}; drive joint {edge['joint_id']} instead of breaking its constraint with a free transform"
        )

    desired = {
        "position": [float(v) for v in transform.get("position", current.get("position", [0.0, 0.0, 0.0]))],
        "rotation_deg": [float(v) for v in transform.get("rotation_deg", current.get("rotation_deg", [0.0, 0.0, 0.0]))],
        "scale": [float(v) for v in current_scale],
    }
    old_driver = rigid_matrix(current)
    new_driver = rigid_matrix(desired)
    delta = new_driver @ np.linalg.inv(old_driver)
    affected_ids = descendants(project, driver_id, include_root=True)
    transforms: dict[str, dict[str, list[float]]] = {}
    for object_id in affected_ids:
        obj = objects[object_id]
        if object_id == driver_id:
            transforms[object_id] = desired
            continue
        old = rigid_matrix(obj.get("transform"))
        transforms[object_id] = transform_from_matrix(
            delta @ old,
            scale=(obj.get("transform") or {}).get("scale", [1.0, 1.0, 1.0]),
        )

    candidate = deepcopy(project)
    candidate_objects = _objects(candidate)
    for object_id, solved in transforms.items():
        candidate_objects[object_id]["transform"] = deepcopy(solved)
    findings = _validate_affected_connections(candidate, set(affected_ids))
    if findings:
        raise ValueError("Requested assembly transform violates one or more canonical mechanical mates")
    return {
        "ok": True,
        "solver": "ForgeCAD MultibodyKinematics",
        "solver_version": "6.1.0",
        "mode": "rigid_subtree_propagation",
        "driver_id": driver_id,
        "affected_ids": affected_ids,
        "transforms": transforms,
        "constraint_residuals": findings,
        "physical_verification": False,
    }


def apply_driver_transform(project: dict[str, Any], driver_id: str, transform: dict[str, Any]) -> dict[str, Any]:
    result = solve_driver_transform(project, driver_id, transform)
    objects = _objects(project)
    for object_id, solved in result["transforms"].items():
        objects[object_id]["transform"] = deepcopy(solved)
    return result


def _edge_by_joint(project: dict[str, Any], joint_id: str) -> dict[str, Any]:
    objects = _objects(project)
    for row in project.get("joints") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == joint_id:
            edge = _edge_from_joint(row, objects)
            if edge is None:
                raise ValueError(f"Joint {joint_id} is not a supported rigid kinematic joint")
            return edge
    raise KeyError(joint_id)


def _joint_local_frame(project: dict[str, Any], edge: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    objects = _objects(project)
    parent = objects[edge["parent_id"]]
    row = edge["row"]
    parent_matrix = rigid_matrix(parent.get("transform"))

    parent_interface = row.get("b_interface") if edge["orientation_source"] == "v600_mate" else row.get("parent_interface")
    if parent_interface:
        interface = physical_components.object_interface(parent, str(parent_interface))
        pivot = _vec3(interface.get("position_mm", [0.0, 0.0, 0.0]), "joint interface position")
        axis = _unit(interface.get("axis", [0.0, 0.0, 1.0]), "joint interface axis")
        return pivot, axis

    origin = row.get("origin_mm")
    axis_world = row.get("axis")
    if origin is None or axis_world is None:
        raise ValueError(f"Joint {edge['joint_id']} lacks an interface frame or explicit origin_mm/axis")
    origin_world = _vec3(origin, "joint origin_mm")
    axis_world_vec = _unit(axis_world, "joint axis")
    inv_parent = np.linalg.inv(parent_matrix)
    pivot_local = (inv_parent @ np.asarray([*origin_world, 1.0]))[:3]
    axis_local = _unit(parent_matrix[:3, :3].T @ axis_world_vec, "joint local axis")
    return pivot_local, axis_local


def _orthogonal_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    trial = np.asarray([1.0, 0.0, 0.0]) if abs(float(axis[0])) < 0.8 else np.asarray([0.0, 1.0, 0.0])
    u = _unit(np.cross(axis, trial), "planar basis")
    v = _unit(np.cross(axis, u), "planar basis")
    return u, v


def _limit(row: dict[str, Any], value: float, lower_key: str, upper_key: str, label: str) -> None:
    if row.get(lower_key) is not None and value < float(row[lower_key]) - 1e-9:
        raise ValueError(f"{label} {value:g} is below {lower_key}={float(row[lower_key]):g}")
    if row.get(upper_key) is not None and value > float(row[upper_key]) + 1e-9:
        raise ValueError(f"{label} {value:g} is above {upper_key}={float(row[upper_key]):g}")


def solve_joint_pose(
    project: dict[str, Any],
    joint_id: str,
    *,
    value: float | None = None,
    rotation_deg: float | None = None,
    translation_mm: float | None = None,
    plane_u_mm: float = 0.0,
    plane_v_mm: float = 0.0,
) -> dict[str, Any]:
    objects, _, _ = _graph_runtime(project)
    edge = _edge_by_joint(project, joint_id)
    row = edge["row"]
    typ = edge["type"]
    parent = objects[edge["parent_id"]]
    child = objects[edge["child_id"]]
    parent_matrix = rigid_matrix(parent.get("transform"))
    child_matrix = rigid_matrix(child.get("transform"))
    pivot, axis = _joint_local_frame(project, edge)

    reference = row.get("simulation_reference") if isinstance(row.get("simulation_reference"), dict) else None
    if reference and isinstance(reference.get("parent_to_child"), list):
        relative0 = np.asarray(reference["parent_to_child"], dtype=float)
        if relative0.shape != (4, 4):
            reference = None
    if not reference:
        relative0 = np.linalg.inv(parent_matrix) @ child_matrix
    home = float(row.get("home_deg", row.get("home_mm", 0.0)) or 0.0)

    motion = np.eye(4, dtype=float)
    state: dict[str, float] = {}
    if typ == "fixed":
        if value not in (None, 0, 0.0) or rotation_deg not in (None, 0, 0.0) or translation_mm not in (None, 0, 0.0):
            raise ValueError("A fixed joint has no actuatable degree of freedom")
    elif typ == "revolute":
        angle = float(rotation_deg if rotation_deg is not None else (value if value is not None else home))
        _limit(row, angle, "lower_deg", "upper_deg", "joint angle")
        delta = angle - float(row.get("home_deg", 0.0) or 0.0)
        motion = _translation(pivot) @ _rotation4(axis, math.radians(delta)) @ _translation(-pivot)
        state["rotation_deg"] = angle
    elif typ == "prismatic":
        distance = float(translation_mm if translation_mm is not None else (value if value is not None else home))
        _limit(row, distance, "lower_mm", "upper_mm", "joint translation")
        delta = distance - float(row.get("home_mm", 0.0) or 0.0)
        motion = _translation(axis * delta)
        state["translation_mm"] = distance
    elif typ == "cylindrical":
        angle = float(rotation_deg or 0.0)
        distance = float(translation_mm or 0.0)
        _limit(row, angle, "lower_deg", "upper_deg", "joint angle")
        _limit(row, distance, "lower_mm", "upper_mm", "joint translation")
        motion = _translation(axis * distance) @ _translation(pivot) @ _rotation4(axis, math.radians(angle)) @ _translation(-pivot)
        state.update({"rotation_deg": angle, "translation_mm": distance})
    elif typ == "planar":
        angle = float(rotation_deg or 0.0)
        u, v = _orthogonal_basis(axis)
        motion = _translation(u * float(plane_u_mm) + v * float(plane_v_mm)) @ _translation(pivot) @ _rotation4(axis, math.radians(angle)) @ _translation(-pivot)
        state.update({"rotation_deg": angle, "plane_u_mm": float(plane_u_mm), "plane_v_mm": float(plane_v_mm)})
    else:  # pragma: no cover - normalized earlier
        raise ValueError(f"Unsupported joint type {typ}")

    new_child = parent_matrix @ motion @ relative0
    old_child = child_matrix
    delta_child = new_child @ np.linalg.inv(old_child)
    affected_ids = descendants(project, edge["child_id"], include_root=True)
    transforms: dict[str, dict[str, list[float]]] = {}
    for object_id in affected_ids:
        obj = objects[object_id]
        old = rigid_matrix(obj.get("transform"))
        solved_matrix = new_child if object_id == edge["child_id"] else delta_child @ old
        transforms[object_id] = transform_from_matrix(
            solved_matrix,
            scale=(obj.get("transform") or {}).get("scale", [1.0, 1.0, 1.0]),
        )

    candidate = deepcopy(project)
    candidate_objects = _objects(candidate)
    for object_id, solved in transforms.items():
        candidate_objects[object_id]["transform"] = deepcopy(solved)
    findings = _validate_affected_connections(candidate, set(affected_ids) | {edge["parent_id"]})
    if findings:
        raise ValueError("Solved joint pose exceeds the canonical mate tolerances")
    return {
        "ok": True,
        "solver": "ForgeCAD MultibodyKinematics",
        "solver_version": "6.1.0",
        "mode": "joint_actuation",
        "joint_id": joint_id,
        "joint_type": typ,
        "parent_id": edge["parent_id"],
        "child_id": edge["child_id"],
        "state": state,
        "affected_ids": affected_ids,
        "transforms": transforms,
        "constraint_residuals": findings,
        "reference": {
            "parent_to_child": relative0.tolist(),
            "pivot_parent_mm": pivot.tolist(),
            "axis_parent": axis.tolist(),
        },
        "physical_verification": False,
    }


def apply_joint_pose(project: dict[str, Any], joint_id: str, **kwargs: Any) -> dict[str, Any]:
    result = solve_joint_pose(project, joint_id, **kwargs)
    objects = _objects(project)
    edge = _edge_by_joint(project, joint_id)
    row = edge["row"]
    if not isinstance(row.get("simulation_reference"), dict):
        row["simulation_reference"] = deepcopy(result["reference"])
    row["simulation_state"] = deepcopy(result["state"])
    for object_id, solved in result["transforms"].items():
        objects[object_id]["transform"] = deepcopy(solved)
    return result
