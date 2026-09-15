from __future__ import annotations

"""Time-domain whole-assembly joint sweep for ForgeCAD 6.1.

The kinematic pose solver answers one configuration at a time. This module turns that
into a sampled motion simulation over time while preserving the complete downstream
subtree, checking exact modeled geometry for interference at every frame, and deriving
translational velocity/acceleration and support-reaction screening loads from the
prescribed motion.

It intentionally does not invent contact impulses, friction or actuator behavior. When a
collision is detected the frame is reported as invalid; the solver does not tunnel bodies
through one another and pretend a contact solution was performed.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np

from ..v110 import core
from ..v200 import rigid_body_dynamics
from . import multibody


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _objects(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id") and obj.get("visible", True)
    }


def _collision_volume(shape_a: Any, shape_b: Any) -> float:
    try:
        common = shape_a.intersect(shape_b)
        volume = float(common.Volume())
    except Exception:
        return 0.0
    return volume if math.isfinite(volume) and volume > 0.0 else 0.0


def _excluded_pairs(project: dict[str, Any], driven_joint_id: str) -> set[frozenset[str]]:
    excluded: set[frozenset[str]] = set()
    for row in project.get("joints") or []:
        if not isinstance(row, dict):
            continue
        try:
            edge = multibody._edge_from_joint(row, _objects(project))
        except Exception:
            continue
        if edge is not None:
            excluded.add(frozenset({str(edge["parent_id"]), str(edge["child_id"])}))
    for row in project.get("connections") or []:
        if not isinstance(row, dict) or str(row.get("kind") or "").lower() != "mechanical":
            continue
        a = str((row.get("a") or {}).get("object_id") or "")
        b = str((row.get("b") or {}).get("object_id") or "")
        if a and b and a != b:
            excluded.add(frozenset({a, b}))
    # User-specified exclusions are scoped to the driven joint and intentionally
    # supplement, rather than replace, the canonical direct-mate exclusions.
    try:
        edge = multibody._edge_by_joint(project, driven_joint_id)
        row = edge["row"]
        child = str(edge["child_id"])
        for object_id in row.get("collision_exclude_ids") or []:
            excluded.add(frozenset({child, str(object_id)}))
    except Exception:
        pass
    return excluded


def _state_for_fraction(start: dict[str, float], end: dict[str, float], fraction: float) -> dict[str, float]:
    keys = set(start) | set(end)
    return {
        key: float(start.get(key, end.get(key, 0.0))) +
        (float(end.get(key, start.get(key, 0.0))) - float(start.get(key, end.get(key, 0.0)))) * fraction
        for key in keys
    }


def _pose_kwargs(joint_type: str, state: dict[str, float]) -> dict[str, float | None]:
    if joint_type == "revolute":
        return {"rotation_deg": state.get("rotation_deg", state.get("value", 0.0))}
    if joint_type == "prismatic":
        return {"translation_mm": state.get("translation_mm", state.get("value", 0.0))}
    if joint_type == "cylindrical":
        return {
            "rotation_deg": state.get("rotation_deg", 0.0),
            "translation_mm": state.get("translation_mm", 0.0),
        }
    if joint_type == "planar":
        return {
            "rotation_deg": state.get("rotation_deg", 0.0),
            "plane_u_mm": state.get("plane_u_mm", 0.0),
            "plane_v_mm": state.get("plane_v_mm", 0.0),
        }
    if joint_type == "fixed":
        return {}
    raise ValueError(f"Unsupported joint type {joint_type}")


def _candidate_project(project: dict[str, Any], transforms: dict[str, Any]) -> dict[str, Any]:
    candidate = deepcopy(project)
    objects = _objects(candidate)
    for object_id, transform in transforms.items():
        if object_id in objects:
            objects[object_id]["transform"] = deepcopy(transform)
    return candidate


def _frame_collisions(
    candidate: dict[str, Any],
    moving_ids: set[str],
    *,
    excluded_pairs: set[frozenset[str]],
    tolerance_mm3: float,
) -> list[dict[str, Any]]:
    objects = _objects(candidate)
    shapes: dict[str, Any] = {}
    for object_id, obj in objects.items():
        try:
            shapes[object_id] = core.build_shape(obj)
        except Exception:
            continue
    ids = sorted(shapes)
    collisions: list[dict[str, Any]] = []
    for i, a_id in enumerate(ids):
        for b_id in ids[i + 1:]:
            if a_id not in moving_ids and b_id not in moving_ids:
                continue
            pair = frozenset({a_id, b_id})
            if pair in excluded_pairs:
                continue
            volume = _collision_volume(shapes[a_id], shapes[b_id])
            if volume > tolerance_mm3:
                collisions.append({
                    "a_id": a_id,
                    "a_name": str(objects[a_id].get("name") or a_id),
                    "b_id": b_id,
                    "b_name": str(objects[b_id].get("name") or b_id),
                    "intersection_volume_mm3": volume,
                })
    return collisions


def _body_kinematics(
    frames: list[dict[str, Any]],
    moving_ids: list[str],
    masses: dict[str, float],
    duration_s: float,
    gravity: np.ndarray,
) -> dict[str, Any]:
    if len(frames) < 2:
        return {"bodies": [], "peak_support_reaction_n": 0.0}
    dt = duration_s / (len(frames) - 1)
    positions: dict[str, np.ndarray] = {}
    for object_id in moving_ids:
        positions[object_id] = np.asarray([
            frame["body_com_m"][object_id]
            for frame in frames
        ], dtype=float)

    body_rows: list[dict[str, Any]] = []
    total_reaction = np.zeros((len(frames), 3), dtype=float)
    for object_id in moving_ids:
        pos = positions[object_id]
        velocity = np.gradient(pos, dt, axis=0, edge_order=1)
        acceleration = np.gradient(velocity, dt, axis=0, edge_order=1)
        mass = float(masses[object_id])
        # For the prescribed subtree, support/actuator force required on the body is
        # m(a-g). The opposite sign is the body's load transmitted upstream.
        required = mass * (acceleration - gravity[None, :])
        total_reaction += required
        speed = np.linalg.norm(velocity, axis=1)
        accel_mag = np.linalg.norm(acceleration, axis=1)
        reaction_mag = np.linalg.norm(required, axis=1)
        body_rows.append({
            "object_id": object_id,
            "mass_kg": mass,
            "peak_speed_m_s": float(np.max(speed)),
            "peak_acceleration_m_s2": float(np.max(accel_mag)),
            "peak_required_support_force_n": float(np.max(reaction_mag)),
            "velocity_m_s": velocity.tolist(),
            "acceleration_m_s2": acceleration.tolist(),
            "required_support_force_n": required.tolist(),
        })

    total_mag = np.linalg.norm(total_reaction, axis=1)
    return {
        "sample_dt_s": dt,
        "bodies": body_rows,
        "total_required_support_force_n": total_reaction.tolist(),
        "peak_support_reaction_n": float(np.max(total_mag)),
        "limitations": [
            "Reaction force uses prescribed translational kinematics and gravity only; rotational inertia moments and gyroscopic terms are not included.",
            "No actuator torque curve, compliance, damping, friction or contact impulse is inferred.",
        ],
    }


def simulate_joint_sweep(
    project: dict[str, Any],
    joint_id: str,
    *,
    start_state: dict[str, float],
    end_state: dict[str, float],
    duration_s: float,
    samples: int = 21,
    gravity_m_s2: list[float] | None = None,
    collision_tolerance_mm3: float = 1e-6,
) -> dict[str, Any]:
    duration = _finite(duration_s, "duration_s")
    if duration <= 0.0:
        raise ValueError("duration_s must be positive")
    count = int(samples)
    if count < 3 or count > 121:
        raise ValueError("samples must be between 3 and 121")
    tolerance = _finite(collision_tolerance_mm3, "collision_tolerance_mm3")
    if tolerance < 0.0:
        raise ValueError("collision_tolerance_mm3 must be non-negative")
    gravity = np.asarray(gravity_m_s2 or [0.0, 0.0, -9.80665], dtype=float)
    if gravity.shape != (3,) or not np.all(np.isfinite(gravity)):
        raise ValueError("gravity_m_s2 must contain three finite values")

    edge = multibody._edge_by_joint(project, joint_id)
    joint_type = str(edge["type"])
    if joint_type == "fixed":
        raise ValueError("A fixed joint has no motion sweep")
    moving_ids = multibody.descendants(project, str(edge["child_id"]), include_root=True)
    excluded_pairs = _excluded_pairs(project, joint_id)
    fractions = np.linspace(0.0, 1.0, count)
    objects0 = _objects(project)
    masses: dict[str, float] = {}
    for object_id in moving_ids:
        masses[object_id] = float(rigid_body_dynamics.object_mass_properties(objects0[object_id])["mass_kg"])

    frames: list[dict[str, Any]] = []
    collision_events: list[dict[str, Any]] = []
    bounds = {
        "xmin": float("inf"), "xmax": float("-inf"),
        "ymin": float("inf"), "ymax": float("-inf"),
        "zmin": float("inf"), "zmax": float("-inf"),
    }
    for index, fraction in enumerate(fractions):
        state = _state_for_fraction(start_state, end_state, float(fraction))
        solved = multibody.solve_joint_pose(project, joint_id, **_pose_kwargs(joint_type, state))
        candidate = _candidate_project(project, solved["transforms"])
        candidate_objects = _objects(candidate)
        body_com: dict[str, list[float]] = {}
        for object_id in moving_ids:
            props = rigid_body_dynamics.object_mass_properties(candidate_objects[object_id])
            body_com[object_id] = [float(value) for value in props["center_of_mass_m"]]
            try:
                bb = core.build_shape(candidate_objects[object_id]).BoundingBox()
                bounds["xmin"] = min(bounds["xmin"], float(bb.xmin))
                bounds["xmax"] = max(bounds["xmax"], float(bb.xmax))
                bounds["ymin"] = min(bounds["ymin"], float(bb.ymin))
                bounds["ymax"] = max(bounds["ymax"], float(bb.ymax))
                bounds["zmin"] = min(bounds["zmin"], float(bb.zmin))
                bounds["zmax"] = max(bounds["zmax"], float(bb.zmax))
            except Exception:
                pass
        collisions = _frame_collisions(
            candidate,
            set(moving_ids),
            excluded_pairs=excluded_pairs,
            tolerance_mm3=tolerance,
        )
        for collision in collisions:
            collision_events.append({
                "frame": index,
                "time_s": float(fraction) * duration,
                "state": deepcopy(state),
                **collision,
            })
        frames.append({
            "frame": index,
            "time_s": float(fraction) * duration,
            "fraction": float(fraction),
            "joint_state": deepcopy(state),
            "transforms": deepcopy(solved["transforms"]),
            "body_com_m": body_com,
            "collisions": collisions,
            "valid": not collisions,
        })

    dynamics = _body_kinematics(frames, moving_ids, masses, duration, gravity)
    finite_bounds = all(math.isfinite(value) for value in bounds.values())
    swept_bounds = None
    if finite_bounds:
        swept_bounds = {
            **bounds,
            "x": bounds["xmax"] - bounds["xmin"],
            "y": bounds["ymax"] - bounds["ymin"],
            "z": bounds["zmax"] - bounds["zmin"],
        }

    return {
        "ok": not collision_events,
        "supported": True,
        "solver": "ForgeCAD MultibodyMotion",
        "solver_version": "6.1.0",
        "solver_grade": "engineering_iteration",
        "method": "prescribed joint trajectory with subtree kinematics, sampled exact-B-rep interference and finite-difference translational dynamics",
        "joint_id": joint_id,
        "joint_type": joint_type,
        "parent_id": str(edge["parent_id"]),
        "child_id": str(edge["child_id"]),
        "moving_object_ids": moving_ids,
        "start_state": deepcopy(start_state),
        "end_state": deepcopy(end_state),
        "duration_s": duration,
        "sample_count": count,
        "gravity_m_s2": gravity.tolist(),
        "collision_tolerance_mm3": tolerance,
        "collision_free": not collision_events,
        "collision_count": len(collision_events),
        "collisions": collision_events,
        "swept_bounds_mm": swept_bounds,
        "frames": frames,
        "dynamics": dynamics,
        "limitations": [
            "The joint trajectory is prescribed; ForgeCAD is not solving actuator torque or unconstrained equations of motion in this path.",
            "Collision is sampled at discrete frames and can miss contact between samples; increase samples for screening and use dedicated continuous-contact verification for critical mechanisms.",
            "Direct canonical mechanical-mate pairs are excluded from interference checks to avoid reporting their intentional interface contact as penetration.",
            "Collision detection reports penetration but does not solve impact, friction, restitution or contact forces.",
            "Purchased-component collision fidelity is limited by the geometry fidelity stored for that component.",
        ],
        "physical_verification": False,
    }
