from __future__ import annotations

"""Deterministic single-joint mechanism kinematics for ForgeCAD 2.0.

ForgeCAD already stores joints and exact B-rep geometry. This layer makes revolute and
prismatic joints executable engineering state: joint limits, poses, swept bounds and
sampled exact B-rep interference checks. It is intentionally a rigid kinematics screen,
not a multibody dynamics or motion-planning solver.

Initial v2 scope is deliberately fail-closed: prismatic joints may use any finite axis;
revolute joints use a world-principal axis and require zero base Euler rotation on the
moving child so the pose composition is unambiguous. Each moving child may belong to at
most one analyzed joint. Joint chains and closed loops remain explicit limitations.
"""

from copy import deepcopy
import math
from typing import Any

import numpy as np
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..engineering_state import EngineeringProject
from ..v110 import core


_INSTALLED = False
_ORIGINAL_VALIDATION = None
_SUPPORTED = {"revolute", "prismatic"}


class KinematicsRequest(BaseModel):
    joint_id: str | None = None
    samples: int = Field(default=11, ge=2, le=41)


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _vec3(value: Any, label: str) -> np.ndarray:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must contain three values")
    out = np.asarray([_finite(v, label) for v in value], dtype=float)
    norm = float(np.linalg.norm(out))
    if norm <= 1e-12:
        raise ValueError(f"{label} must be non-zero")
    return out / norm


def _principal_axis(axis: np.ndarray) -> tuple[int, float]:
    absolute = np.abs(axis)
    index = int(np.argmax(absolute))
    if absolute[index] < 1.0 - 1e-9 or sum(absolute[i] for i in range(3) if i != index) > 1e-9:
        raise ValueError("Revolute kinematics currently requires a world-principal axis [±1,0,0], [0,±1,0], or [0,0,±1]")
    return index, 1.0 if axis[index] >= 0.0 else -1.0


def _joint_type(row: dict[str, Any]) -> str:
    return str(row.get("type", row.get("kind", ""))).strip().lower()


def _objects(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(obj.get("id")): obj
        for obj in project.get("objects") or []
        if isinstance(obj, dict) and obj.get("id") and obj.get("visible", True)
    }


def _joint(project: dict[str, Any], joint_id: str) -> dict[str, Any]:
    row = next((item for item in project.get("joints") or [] if isinstance(item, dict) and str(item.get("id") or "") == joint_id), None)
    if row is None:
        raise KeyError(joint_id)
    return row


def _normalized_joint(row: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    typ = _joint_type(row)
    if typ not in _SUPPORTED:
        raise ValueError(f"Unsupported kinematic joint type {typ!r}; use revolute or prismatic")
    objects = _objects(project)
    parent_id = str(row.get("parent_id", row.get("source_id", ""))).strip()
    child_id = str(row.get("child_id", row.get("target_id", ""))).strip()
    if not parent_id or parent_id not in objects:
        raise ValueError("Kinematic joint requires a visible parent_id")
    if not child_id or child_id not in objects:
        raise ValueError("Kinematic joint requires a visible child_id")
    if parent_id == child_id:
        raise ValueError("Kinematic joint parent_id and child_id must differ")
    axis = _vec3(row.get("axis", [0.0, 0.0, 1.0]), "joint axis")
    origin_raw = row.get("origin_mm")
    if not isinstance(origin_raw, (list, tuple)) or len(origin_raw) != 3:
        raise ValueError("Kinematic joint requires explicit world-space origin_mm [x,y,z]")
    origin = np.asarray([_finite(v, "joint origin_mm") for v in origin_raw], dtype=float)

    if typ == "revolute":
        lower = _finite(row.get("lower_deg"), "revolute lower_deg")
        upper = _finite(row.get("upper_deg"), "revolute upper_deg")
        home = _finite(row.get("home_deg", 0.0), "revolute home_deg")
        _principal_axis(axis)
        base_rotation = [float(v) for v in (objects[child_id].get("transform") or {}).get("rotation_deg", [0.0, 0.0, 0.0])]
        if any(abs(v) > 1e-9 for v in base_rotation):
            raise ValueError("Revolute child must have zero base rotation in the current kinematics solver; bake/normalize its zero pose first")
        unit = "deg"
    else:
        lower = _finite(row.get("lower_mm"), "prismatic lower_mm")
        upper = _finite(row.get("upper_mm"), "prismatic upper_mm")
        home = _finite(row.get("home_mm", 0.0), "prismatic home_mm")
        unit = "mm"
    if lower > upper:
        raise ValueError("Kinematic joint lower limit cannot exceed upper limit")
    if home < lower - 1e-9 or home > upper + 1e-9:
        raise ValueError("Kinematic joint home position lies outside its limits")
    excludes = {str(v) for v in row.get("collision_exclude_ids") or []}
    unknown = sorted(excludes - set(objects))
    if unknown:
        raise ValueError("Kinematic joint collision_exclude_ids contains unknown objects: " + ", ".join(unknown))
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or f"{typ.title()} joint"),
        "type": typ,
        "parent_id": parent_id,
        "child_id": child_id,
        "axis": axis.tolist(),
        "origin_mm": origin.tolist(),
        "lower": lower,
        "upper": upper,
        "home": home,
        "unit": unit,
        "collision_exclude_ids": sorted(excludes),
        "validate_sweep": bool(row.get("validate_sweep", True)),
    }


def _rotation_matrix(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    x, y, z = axis
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    one = 1.0 - c
    return np.asarray([
        [c + x*x*one, x*y*one - z*s, x*z*one + y*s],
        [y*x*one + z*s, c + y*y*one, y*z*one - x*s],
        [z*x*one - y*s, z*y*one + x*s, c + z*z*one],
    ], dtype=float)


def pose_for_joint(project: dict[str, Any], joint_id: str, value: float) -> dict[str, Any]:
    joint = _normalized_joint(_joint(project, joint_id), project)
    position_value = _finite(value, "joint value")
    if position_value < joint["lower"] - 1e-9 or position_value > joint["upper"] + 1e-9:
        raise ValueError(f"Joint value {position_value:g} {joint['unit']} is outside [{joint['lower']:g}, {joint['upper']:g}]")
    child = _objects(project)[joint["child_id"]]
    transform = deepcopy(child.get("transform") or {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]})
    base_position = np.asarray(transform.get("position", [0.0, 0.0, 0.0]), dtype=float)
    axis = np.asarray(joint["axis"], dtype=float)
    delta = position_value - float(joint["home"])
    if joint["type"] == "prismatic":
        position = base_position + axis * delta
        rotation = [float(v) for v in transform.get("rotation_deg", [0.0, 0.0, 0.0])]
    else:
        origin = np.asarray(joint["origin_mm"], dtype=float)
        matrix = _rotation_matrix(axis, math.radians(delta))
        position = origin + matrix @ (base_position - origin)
        index, sign = _principal_axis(axis)
        rotation = [0.0, 0.0, 0.0]
        rotation[index] = sign * delta
    return {
        "joint_id": joint_id,
        "joint_value": position_value,
        "unit": joint["unit"],
        "child_id": joint["child_id"],
        "transform": {
            "position": position.tolist(),
            "rotation_deg": rotation,
            "scale": [float(v) for v in transform.get("scale", [1.0, 1.0, 1.0])],
        },
    }


def _collision_volume(shape_a: Any, shape_b: Any) -> float:
    try:
        common = shape_a.intersect(shape_b)
        volume = float(common.Volume())
    except Exception:
        return 0.0
    return volume if math.isfinite(volume) and volume > 1e-9 else 0.0


def sweep_joint(project: dict[str, Any], joint_id: str, *, samples: int = 11) -> dict[str, Any]:
    joint = _normalized_joint(_joint(project, joint_id), project)
    count = max(2, min(int(samples), 41))
    values = np.linspace(float(joint["lower"]), float(joint["upper"]), count).tolist()
    objects = _objects(project)
    child = objects[joint["child_id"]]
    excluded = set(joint["collision_exclude_ids"]) | {joint["child_id"], joint["parent_id"]}
    obstacles: dict[str, Any] = {}
    for object_id, obj in objects.items():
        if object_id in excluded:
            continue
        try:
            obstacles[object_id] = core.build_shape(obj)
        except Exception:
            continue

    rows: list[dict[str, Any]] = []
    collision_events: list[dict[str, Any]] = []
    bounds = {"xmin": float("inf"), "xmax": float("-inf"), "ymin": float("inf"), "ymax": float("-inf"), "zmin": float("inf"), "zmax": float("-inf")}
    for value in values:
        pose = pose_for_joint(project, joint_id, value)
        moved = deepcopy(child)
        moved["transform"] = deepcopy(pose["transform"])
        shape = core.build_shape(moved)
        bb = shape.BoundingBox()
        bounds["xmin"] = min(bounds["xmin"], float(bb.xmin)); bounds["xmax"] = max(bounds["xmax"], float(bb.xmax))
        bounds["ymin"] = min(bounds["ymin"], float(bb.ymin)); bounds["ymax"] = max(bounds["ymax"], float(bb.ymax))
        bounds["zmin"] = min(bounds["zmin"], float(bb.zmin)); bounds["zmax"] = max(bounds["zmax"], float(bb.zmax))
        collisions = []
        for object_id, obstacle_shape in obstacles.items():
            volume = _collision_volume(shape, obstacle_shape)
            if volume > 0.0:
                event = {"joint_value": value, "unit": joint["unit"], "object_id": object_id, "object_name": str(objects[object_id].get("name") or object_id), "intersection_volume_mm3": volume}
                collisions.append(event)
                collision_events.append(event)
        rows.append({**pose, "collisions": collisions})

    return {
        "solver": "ForgeCAD MechanismKinematics",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "joint": joint,
        "samples": rows,
        "sample_count": count,
        "collision_free": not collision_events,
        "collisions": collision_events,
        "swept_bounds_mm": {
            "x": bounds["xmax"] - bounds["xmin"],
            "y": bounds["ymax"] - bounds["ymin"],
            "z": bounds["zmax"] - bounds["zmin"],
            **bounds,
        },
        "limitations": [
            "Rigid single-joint sweep; each moving child is analyzed independently from its stored zero pose.",
            "Revolute joints currently require a world-principal axis and zero child base rotation.",
            "Joint chains, closed loops, compliance, backlash, contact response, motors/actuators and dynamic loads are not solved.",
            "Collision is exact B-rep intersection for the geometry ForgeCAD has; proxy purchased-component geometry remains proxy fidelity.",
            "Sampled sweep can miss a collision between samples; increase sample count or perform dedicated continuous motion verification for critical mechanisms.",
        ],
        "physical_verification": False,
    }


def analyze_kinematics(project: dict[str, Any] | None = None, *, samples: int = 11) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    candidates = [row for row in source.get("joints") or [] if isinstance(row, dict) and (_joint_type(row) in _SUPPORTED or bool(row.get("kinematic")))]
    child_counts: dict[str, int] = {}
    for row in candidates:
        child_id = str(row.get("child_id", row.get("target_id", ""))).strip()
        if child_id:
            child_counts[child_id] = child_counts.get(child_id, 0) + 1
    items: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for row in candidates:
        joint_id = str(row.get("id") or "")
        child_id = str(row.get("child_id", row.get("target_id", ""))).strip()
        if child_id and child_counts.get(child_id, 0) > 1:
            risks.append({"severity": "error", "code": "kinematic_child_multiple_joints", "joint_id": joint_id, "object_id": child_id, "message": f"Moving child {child_id} is assigned to multiple independently analyzed kinematic joints."})
            continue
        try:
            normalized = _normalized_joint(row, source)
            if normalized["validate_sweep"]:
                result = sweep_joint(source, joint_id, samples=samples)
                items.append(result)
                if not result["collision_free"]:
                    risks.append({"severity": "error", "code": "kinematic_sweep_collision", "joint_id": joint_id, "object_id": normalized["child_id"], "message": f"Joint {normalized['name']} collides with other modeled geometry at {len(result['collisions'])} sampled configuration(s)."})
            else:
                items.append({"solver": "ForgeCAD MechanismKinematics", "solver_version": "2.0.0", "joint": normalized, "sweep_skipped": True, "collision_free": None})
        except Exception as exc:
            risks.append({"severity": "error", "code": "kinematic_joint_invalid", "joint_id": joint_id, "message": str(exc)})
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    return {
        "solver": "ForgeCAD MechanismKinematics",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "joint_count": len(candidates),
        "items": items,
        "ok": counts["error"] == 0,
        "counts": counts,
        "risks": risks,
        "physical_verification": False,
    }


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    kinematics = analyze_kinematics(core.PROJECT, samples=9)
    combined = list(base.get("risks") or []) + list(kinematics.get("risks") or [])
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in combined:
        if not isinstance(risk, dict):
            continue
        key = (str(risk.get("code") or ""), str(risk.get("joint_id") or risk.get("failure_mode_id") or risk.get("route_id") or risk.get("object_id") or ""), str(risk.get("message") or ""))
        deduped[key] = risk
    risks = sorted(deduped.values(), key=lambda risk: ({"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3), str(risk.get("code") or ""), str(risk.get("message") or "")))
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["kinematics"] = kinematics
    return base


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_VALIDATION
    if _INSTALLED:
        return
    _ORIGINAL_VALIDATION = EngineeringProject.validation
    EngineeringProject.validation = _validation
    app = legacy.app

    @app.get("/v2/analysis/kinematics", dependencies=[Depends(legacy.require_session)])
    async def kinematics(samples: int = 11) -> dict[str, Any]:
        try:
            return analyze_kinematics(core.PROJECT, samples=max(2, min(int(samples), 41)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v2/analysis/kinematics/sweep", dependencies=[Depends(legacy.require_session)])
    async def kinematics_sweep(request: KinematicsRequest) -> dict[str, Any]:
        if not request.joint_id:
            return analyze_kinematics(core.PROJECT, samples=request.samples)
        try:
            return sweep_joint(core.PROJECT, request.joint_id, samples=request.samples)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Joint not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _INSTALLED = True
