from __future__ import annotations

"""Rigid multibody load transfer through the canonical joint tree."""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v200 import project_structural, rigid_body_dynamics
from . import multibody


_FORCE_TYPES = {"force", "face_force", "distributed_force", "force_vector"}


def _vec3(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three values")
    out = np.asarray([float(v) for v in value], dtype=float)
    if not np.all(np.isfinite(out)):
        raise ValueError(f"{label} must contain finite values")
    return out


def solve_joint_loads(project: dict[str, Any], *, gravity_m_s2: list[float]) -> dict[str, Any]:
    gravity = _vec3(gravity_m_s2, "gravity_m_s2")
    objects, _, _ = multibody._graph_runtime(project)
    graph = multibody.assembly_graph(project)
    if not graph["ok"]:
        raise ValueError("Joint load transfer requires an unambiguous open kinematic tree")

    properties: dict[str, dict[str, Any]] = {}
    for object_id, obj in objects.items():
        try:
            properties[object_id] = rigid_body_dynamics.object_mass_properties(obj)
        except ValueError as exc:
            raise ValueError(f"Cannot compute joint load path through {obj.get('name') or object_id}: {exc}") from exc

    explicit_forces: dict[str, list[dict[str, Any]]] = {}
    for row in project.get("loads") or []:
        if not isinstance(row, dict):
            continue
        typ = str(row.get("type", row.get("kind", ""))).strip().lower()
        if typ not in _FORCE_TYPES:
            continue
        object_id = project_structural._target_id(row)
        if not object_id or object_id not in objects:
            continue
        vector = project_structural._force_vector(row)
        point = row.get("application_point_mm", row.get("point_mm"))
        if point is None and bool(row.get("at_center_of_mass")):
            point = (np.asarray(properties[object_id]["center_of_mass_m"], dtype=float) * 1000.0).tolist()
        explicit_forces.setdefault(object_id, []).append({
            "id": str(row.get("id") or ""),
            "vector_n": vector.tolist(),
            "application_point_mm": deepcopy(point),
        })

    joints: list[dict[str, Any]] = []
    for public_edge in graph["edges"]:
        joint_id = str(public_edge["joint_id"])
        edge = multibody._edge_by_joint(project, joint_id)
        parent_id = str(edge["parent_id"])
        child_id = str(edge["child_id"])
        subtree = multibody.descendants(project, child_id, include_root=True)
        pivot_local, _ = multibody._joint_local_frame(project, edge)
        parent_matrix = multibody.rigid_matrix(objects[parent_id].get("transform"))
        pivot_world_mm = (parent_matrix @ np.asarray([*pivot_local, 1.0]))[:3]
        pivot_world_m = pivot_world_mm * 1e-3

        force = np.zeros(3, dtype=float)
        moment = np.zeros(3, dtype=float)
        total_mass = 0.0
        unresolved_moment_load_ids: list[str] = []
        body_rows: list[dict[str, Any]] = []
        for object_id in subtree:
            prop = properties[object_id]
            mass = float(prop["mass_kg"])
            com = np.asarray(prop["center_of_mass_m"], dtype=float)
            gravity_force = mass * gravity
            force += gravity_force
            moment += np.cross(com - pivot_world_m, gravity_force)
            total_mass += mass
            body_rows.append({
                "object_id": object_id,
                "mass_kg": mass,
                "center_of_mass_m": com.tolist(),
                "gravity_force_n": gravity_force.tolist(),
            })
            for load in explicit_forces.get(object_id, []):
                vector = np.asarray(load["vector_n"], dtype=float)
                force += vector
                point = load.get("application_point_mm")
                if isinstance(point, (list, tuple)) and len(point) == 3:
                    application = _vec3(point, "application_point_mm") * 1e-3
                    moment += np.cross(application - pivot_world_m, vector)
                else:
                    unresolved_moment_load_ids.append(str(load["id"] or f"force:{object_id}"))

        joints.append({
            "joint_id": joint_id,
            "joint_name": str(edge["name"]),
            "joint_type": str(edge["type"]),
            "parent_id": parent_id,
            "child_id": child_id,
            "subtree_object_ids": subtree,
            "subtree_mass_kg": total_mass,
            "joint_origin_world_mm": pivot_world_mm.tolist(),
            # This is the load the downstream subtree applies to the supporting parent.
            "load_on_parent_force_n": force.tolist(),
            "load_on_parent_moment_nm": moment.tolist(),
            "support_reaction_on_subtree_force_n": (-force).tolist(),
            "support_reaction_on_subtree_moment_nm": (-moment).tolist(),
            "unresolved_moment_load_ids": unresolved_moment_load_ids,
            "moment_complete": not unresolved_moment_load_ids,
            "bodies": body_rows,
        })

    return {
        "ok": all(bool(row["moment_complete"]) for row in joints),
        "solver": "ForgeCAD JointLoadPath",
        "solver_version": "6.1.0",
        "solver_grade": "engineering_iteration",
        "method": "rigid-body subtree equilibrium with gravity and explicit canonical forces",
        "gravity_m_s2": gravity.tolist(),
        "joint_count": len(joints),
        "joints": joints,
        "limitations": [
            "Rigid quasistatic load transfer; inertial joint loads from prescribed acceleration require a dynamics run.",
            "Canonical force loads without an explicit application point contribute to joint force but not an invented moment arm; such moments are reported incomplete.",
            "Joint stiffness, contact pressure, friction, bearing stress, bolt preload and flexible deformation require dedicated structural/contact models.",
        ],
        "physical_verification": False,
    }
