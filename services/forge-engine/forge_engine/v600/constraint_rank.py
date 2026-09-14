from __future__ import annotations

"""Numerical spatial constraint-rank analysis for ForgeCAD 6.0 Milestone 2.

A list of mates can look plausible while still being underconstrained, redundant,
or contradictory.  This module linearizes the actual canonical mate residuals with
respect to rigid-body twists and computes the numerical Jacobian rank per connected
assembly component.

The result is diagnostic engineering truth, not a dynamics solver.  It reports
mobility and redundancy without pretending that intentional mechanism DOFs are
errors.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from . import assembly_frame_constraints, interface_frames


_CONSTRAINT_ROWS = {
    "fixed": 6,
    "revolute": 5,
    "prismatic": 5,
    "cylindrical": 4,
    "planar": 3,
}


def _object(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects") or []:
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _rotation_vector(matrix: np.ndarray) -> np.ndarray:
    r = np.asarray(matrix, dtype=float)
    cosine = float(np.clip((np.trace(r) - 1.0) / 2.0, -1.0, 1.0))
    theta = math.acos(cosine)
    skew = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]], dtype=float)
    if theta < 1e-8:
        return 0.5 * skew
    sine = math.sin(theta)
    if abs(sine) > 1e-7:
        return skew * (theta / (2.0 * sine))
    # Stable pi-angle fallback.  Sign is immaterial for local Jacobian rank but
    # deterministic output is still useful for diagnostics.
    diag = np.maximum(0.0, (np.diag(r) + 1.0) / 2.0)
    axis = np.sqrt(diag)
    if axis[0] >= max(axis[1], axis[2]) and axis[0] > 1e-9:
        axis[1] = math.copysign(axis[1], r[0, 1] + r[1, 0])
        axis[2] = math.copysign(axis[2], r[0, 2] + r[2, 0])
    elif axis[1] >= axis[2] and axis[1] > 1e-9:
        axis[0] = math.copysign(axis[0], r[0, 1] + r[1, 0])
        axis[2] = math.copysign(axis[2], r[1, 2] + r[2, 1])
    elif axis[2] > 1e-9:
        axis[0] = math.copysign(axis[0], r[0, 2] + r[2, 0])
        axis[1] = math.copysign(axis[1], r[1, 2] + r[2, 1])
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12:
        axis = np.array([1.0, 0.0, 0.0])
    else:
        axis /= norm
    return axis * theta


def _constrained_connections(project: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for connection in project.get("connections") or []:
        constraint = connection.get("constraint")
        if str(connection.get("kind") or "") != "mechanical" or not isinstance(constraint, dict):
            continue
        mate_type = str(constraint.get("mate_type") or "")
        if mate_type not in _CONSTRAINT_ROWS:
            continue
        rows.append(connection)
    return rows


def _relation(constraint: dict[str, Any]) -> str:
    value = str(constraint.get("axis_relation") or "opposed")
    return value if value in {"aligned", "opposed"} else "opposed"


def _residual_for_connection(project: dict[str, Any], connection: dict[str, Any]) -> np.ndarray:
    constraint = connection.get("constraint") or {}
    mate_type = str(constraint.get("mate_type") or "")
    a_ref, b_ref = connection.get("a") or {}, connection.get("b") or {}
    source = _object(project, str(a_ref.get("object_id") or ""))
    target = _object(project, str(b_ref.get("object_id") or ""))
    sf = interface_frames.object_interface_frame(source, str(a_ref.get("interface_id") or ""))
    tf = interface_frames.object_interface_frame(target, str(b_ref.get("interface_id") or ""))
    relation = _relation(constraint)
    gap = float(constraint.get("gap_mm", 0.0))
    clocking = float(constraint.get("clocking_deg", 0.0))
    desired = interface_frames.desired_mating_frame(tf, relation, clocking if mate_type in {"fixed", "prismatic"} else 0.0)

    ps = interface_frames.vec3(sf["world_origin_mm"])
    pt = interface_frames.vec3(tf["world_origin_mm"])
    target_axis = interface_frames.unit(tf["world_z_axis"])
    desired_origin = pt + target_axis * gap
    delta = ps - desired_origin
    sx = interface_frames.unit(sf["world_x_axis"])
    sz = interface_frames.unit(sf["world_z_axis"])
    dx, dy, dz = desired[:, 0], desired[:, 1], desired[:, 2]
    axis_difference = sz - dz

    if mate_type == "fixed":
        actual = np.asarray(sf["world_matrix"], dtype=float)
        orientation = _rotation_vector(desired.T @ actual)
        return np.concatenate((delta, orientation))
    if mate_type == "prismatic":
        actual = np.asarray(sf["world_matrix"], dtype=float)
        orientation = _rotation_vector(desired.T @ actual)
        return np.array([float(np.dot(delta, dx)), float(np.dot(delta, dy)), *orientation], dtype=float)
    if mate_type == "revolute":
        return np.array([*delta, float(np.dot(axis_difference, dx)), float(np.dot(axis_difference, dy))], dtype=float)
    if mate_type == "cylindrical":
        return np.array(
            [
                float(np.dot(delta, dx)),
                float(np.dot(delta, dy)),
                float(np.dot(axis_difference, dx)),
                float(np.dot(axis_difference, dy)),
            ],
            dtype=float,
        )
    if mate_type == "planar":
        return np.array(
            [
                float(np.dot(delta, dz)),
                float(np.dot(axis_difference, dx)),
                float(np.dot(axis_difference, dy)),
            ],
            dtype=float,
        )
    raise ValueError(f"Unsupported mate type: {mate_type}")


def _connected_components(connections: list[dict[str, Any]]) -> list[tuple[list[str], list[dict[str, Any]]]]:
    adjacency: dict[str, set[str]] = {}
    for connection in connections:
        a = str((connection.get("a") or {}).get("object_id") or "")
        b = str((connection.get("b") or {}).get("object_id") or "")
        if not a or not b:
            continue
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    seen: set[str] = set()
    result: list[tuple[list[str], list[dict[str, Any]]]] = []
    for start in sorted(adjacency):
        if start in seen:
            continue
        stack, bodies = [start], set()
        while stack:
            current = stack.pop()
            if current in bodies:
                continue
            bodies.add(current)
            seen.add(current)
            stack.extend(sorted(adjacency.get(current, set()) - bodies))
        body_ids = sorted(bodies)
        edge_rows = [
            connection
            for connection in connections
            if str((connection.get("a") or {}).get("object_id") or "") in bodies
            and str((connection.get("b") or {}).get("object_id") or "") in bodies
        ]
        result.append((body_ids, edge_rows))
    return result


def _component_residual(project: dict[str, Any], connections: list[dict[str, Any]]) -> np.ndarray:
    if not connections:
        return np.zeros((0,), dtype=float)
    return np.concatenate([_residual_for_connection(project, connection) for connection in connections])


def _perturb(project: dict[str, Any], object_id: str, dof: int, epsilon_translation_mm: float, epsilon_rotation_rad: float) -> dict[str, Any]:
    perturbed = deepcopy(project)
    obj = _object(perturbed, object_id)
    transform = obj.setdefault("transform", {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]})
    if dof < 3:
        position = [float(value) for value in transform.get("position", [0.0, 0.0, 0.0])]
        position[dof] += epsilon_translation_mm
        transform["position"] = position
    else:
        axis = np.eye(3)[dof - 3]
        rotation = interface_frames.rotation_xyz(transform.get("rotation_deg", [0.0, 0.0, 0.0]))
        perturbed_rotation = interface_frames.axis_angle(axis, epsilon_rotation_rad) @ rotation
        transform["rotation_deg"] = interface_frames.euler_xyz(perturbed_rotation)
    return perturbed


def analyze_constraint_rank(
    project: dict[str, Any],
    *,
    epsilon_translation_mm: float = 1e-4,
    epsilon_rotation_rad: float = 1e-6,
    relative_rank_tolerance: float = 1e-8,
) -> dict[str, Any]:
    connections = _constrained_connections(project)
    validation = assembly_frame_constraints.validate_constraint_set(project)
    error_connection_ids = {
        str(item.get("connection_id"))
        for item in validation.get("findings") or []
        if item.get("severity") == "error" and item.get("connection_id")
    }
    components: list[dict[str, Any]] = []

    for body_ids, edges in _connected_components(connections):
        anchor = body_ids[0]
        variables = [body for body in body_ids if body != anchor]
        base = _component_residual(project, edges)
        columns: list[np.ndarray] = []
        for object_id in variables:
            for dof in range(6):
                if dof < 3:
                    epsilon = epsilon_translation_mm
                else:
                    epsilon = epsilon_rotation_rad
                perturbed = _perturb(project, object_id, dof, epsilon_translation_mm, epsilon_rotation_rad)
                derivative = (_component_residual(perturbed, edges) - base) / epsilon
                columns.append(derivative)
        jacobian = np.column_stack(columns) if columns else np.zeros((len(base), 0), dtype=float)
        singular_values = np.linalg.svd(jacobian, compute_uv=False) if jacobian.size else np.zeros((0,), dtype=float)
        if singular_values.size:
            threshold = max(jacobian.shape) * max(float(singular_values[0]), 1.0) * float(relative_rank_tolerance)
            rank = int(np.sum(singular_values > threshold))
        else:
            threshold, rank = 0.0, 0
        variable_dof = 6 * len(variables)
        scalar_constraints = int(sum(_CONSTRAINT_ROWS[str((edge.get("constraint") or {}).get("mate_type"))] for edge in edges))
        mobility = max(0, variable_dof - rank)
        ideal_mobility = max(0, variable_dof - scalar_constraints)
        unexpected_mobility = max(0, mobility - ideal_mobility)
        redundant_rows = max(0, scalar_constraints - rank)
        edge_ids = [str(edge.get("id") or "") for edge in edges]
        inconsistent = bool(error_connection_ids.intersection(edge_ids))
        if inconsistent:
            status = "inconsistent"
        elif unexpected_mobility > 0:
            status = "underconstrained"
        elif redundant_rows > 0:
            status = "constrained_with_redundancy"
        elif mobility > 0:
            status = "mechanism"
        else:
            status = "fully_constrained"
        components.append(
            {
                "body_ids": body_ids,
                "anchor_id": anchor,
                "connection_ids": edge_ids,
                "body_count": len(body_ids),
                "mate_count": len(edges),
                "variable_dof": variable_dof,
                "scalar_constraint_rows": scalar_constraints,
                "jacobian_rank": rank,
                "mobility_dof": mobility,
                "ideal_independent_constraint_mobility_dof": ideal_mobility,
                "unexpected_mobility_dof": unexpected_mobility,
                "redundant_constraint_rows": redundant_rows,
                "inconsistent": inconsistent,
                "status": status,
                "rank_threshold": threshold,
                "singular_values": [float(value) for value in singular_values],
            }
        )

    return {
        "ok": bool(validation.get("ok")),
        "component_count": len(components),
        "components": components,
        "summary": {
            "fully_constrained": sum(row["status"] == "fully_constrained" for row in components),
            "mechanisms": sum(row["status"] == "mechanism" for row in components),
            "underconstrained": sum(row["status"] == "underconstrained" for row in components),
            "with_redundancy": sum(row["redundant_constraint_rows"] > 0 for row in components),
            "inconsistent": sum(row["inconsistent"] for row in components),
        },
        "validation": validation,
        "method": "finite-difference rigid-body constraint Jacobian with one gauge anchor removed per connected component",
        "limitations": [
            "local linearization around the current canonical pose",
            "rank identifies mobility/redundancy but does not replace nonlinear mechanism/contact solution",
            "legacy inferred secondary datums remain distinguishable from authoritative declared datums",
        ],
    }
