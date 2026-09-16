from __future__ import annotations

"""Constraint-driven 2D sketch solving for ForgeCAD 2.0.

This closes an important gap between primitive geometry generation and real parametric
CAD. A ``constrained_sketch_extrude`` object stores the original point guesses and
constraints as canonical design data. The B-rep is regenerated from the solved sketch,
so changing a dimension constraint changes the physical solid without replacing it by
an opaque mesh.

Supported constraints intentionally start with the high-value mechanical subset:
fixed, fixed_x, fixed_y, horizontal, vertical, coincident, distance, x_distance,
y_distance, equal_length, parallel, perpendicular, angle, and midpoint.
"""

import math
from typing import Any

import cadquery as cq
import numpy as np
from scipy.optimize import least_squares
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core


_INSTALLED = False
_ORIGINAL_BASE_SHAPE = None


class SketchSolveRequest(BaseModel):
    points: list[list[float]] = Field(min_length=3)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    tolerance: float = 1e-5


def _point_index(value: Any, count: int, label: str) -> int:
    index = int(value)
    if index < 0 or index >= count:
        raise ValueError(f"Sketch constraint {label} point index {index} is out of range")
    return index


def _segment_indices(constraint: dict[str, Any], count: int) -> tuple[int, int, int, int]:
    a = _point_index(constraint.get("a", constraint.get("a1")), count, "a")
    b = _point_index(constraint.get("b", constraint.get("b1")), count, "b")
    c = _point_index(constraint.get("c", constraint.get("a2")), count, "c")
    d = _point_index(constraint.get("d", constraint.get("b2")), count, "d")
    return a, b, c, d


def _polygon_area(points: np.ndarray) -> float:
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - y * np.roll(x, -1)))


def _orient(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _segments_intersect(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray, eps: float = 1e-9) -> bool:
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    return ((o1 > eps and o2 < -eps) or (o1 < -eps and o2 > eps)) and ((o3 > eps and o4 < -eps) or (o3 < -eps and o4 > eps))


def _self_intersections(points: np.ndarray) -> list[tuple[int, int]]:
    count = len(points)
    hits: list[tuple[int, int]] = []
    for i in range(count):
        a, b = points[i], points[(i + 1) % count]
        for j in range(i + 1, count):
            if j == i or (j + 1) % count == i or (i + 1) % count == j:
                continue
            if i == 0 and j == count - 1:
                continue
            c, d = points[j], points[(j + 1) % count]
            if _segments_intersect(a, b, c, d):
                hits.append((i, j))
    return hits


def solve_sketch(points: list[list[float]], constraints: list[dict[str, Any]], *, tolerance: float = 1e-5) -> dict[str, Any]:
    if len(points) < 3:
        raise ValueError("A closed ForgeCAD sketch needs at least three points")
    initial = np.asarray(points, dtype=float)
    if initial.shape != (len(points), 2) or not np.all(np.isfinite(initial)):
        raise ValueError("Sketch points must be finite [x, y] pairs")
    count = len(points)
    scale = max(1.0, float(np.ptp(initial[:, 0])), float(np.ptp(initial[:, 1])))

    # Validate all indices and capture fixed constraints' implicit target coordinates from
    # the initial sketch before optimization starts.
    prepared: list[dict[str, Any]] = []
    for raw in constraints:
        if not isinstance(raw, dict):
            raise ValueError("Sketch constraints must be objects")
        c = dict(raw)
        typ = str(c.get("type") or "").lower().strip()
        if not typ:
            raise ValueError("Sketch constraint is missing type")
        if typ in {"fixed", "fixed_x", "fixed_y"}:
            p = _point_index(c.get("point", c.get("a")), count, "point")
            c["point"] = p
            c.setdefault("x", float(initial[p, 0]))
            c.setdefault("y", float(initial[p, 1]))
        elif typ in {"horizontal", "vertical", "coincident", "distance", "x_distance", "y_distance"}:
            c["a"] = _point_index(c.get("a"), count, "a")
            c["b"] = _point_index(c.get("b"), count, "b")
        elif typ in {"equal_length", "parallel", "perpendicular", "angle"}:
            a, b, cc, d = _segment_indices(c, count)
            c.update({"a": a, "b": b, "c": cc, "d": d})
        elif typ == "midpoint":
            c["point"] = _point_index(c.get("point", c.get("p")), count, "point")
            c["a"] = _point_index(c.get("a"), count, "a")
            c["b"] = _point_index(c.get("b"), count, "b")
        else:
            raise ValueError(f"Unsupported sketch constraint: {typ}")
        c["type"] = typ
        prepared.append(c)

    def residual(vector: np.ndarray) -> np.ndarray:
        p = vector.reshape((count, 2))
        values: list[float] = []
        for c in prepared:
            typ = c["type"]
            if typ == "fixed":
                point = p[c["point"]]
                values.extend([float(point[0]) - float(c["x"]), float(point[1]) - float(c["y"])])
            elif typ == "fixed_x":
                values.append(float(p[c["point"], 0]) - float(c["x"]))
            elif typ == "fixed_y":
                values.append(float(p[c["point"], 1]) - float(c["y"]))
            elif typ == "horizontal":
                values.append(float(p[c["a"], 1] - p[c["b"], 1]))
            elif typ == "vertical":
                values.append(float(p[c["a"], 0] - p[c["b"], 0]))
            elif typ == "coincident":
                values.extend((p[c["a"]] - p[c["b"]]).tolist())
            elif typ == "distance":
                values.append(float(np.linalg.norm(p[c["b"]] - p[c["a"]])) - float(c.get("value", c.get("distance", 0.0))))
            elif typ == "x_distance":
                values.append(float(p[c["b"], 0] - p[c["a"], 0]) - float(c.get("value", 0.0)))
            elif typ == "y_distance":
                values.append(float(p[c["b"], 1] - p[c["a"], 1]) - float(c.get("value", 0.0)))
            elif typ == "equal_length":
                first = float(np.linalg.norm(p[c["b"]] - p[c["a"]]))
                second = float(np.linalg.norm(p[c["d"]] - p[c["c"]]))
                values.append(first - second)
            elif typ in {"parallel", "perpendicular", "angle"}:
                u = p[c["b"]] - p[c["a"]]
                v = p[c["d"]] - p[c["c"]]
                un = max(float(np.linalg.norm(u)), 1e-9)
                vn = max(float(np.linalg.norm(v)), 1e-9)
                cross = float(u[0] * v[1] - u[1] * v[0]) / (un * vn)
                dot = float(np.dot(u, v)) / (un * vn)
                if typ == "parallel":
                    values.append(cross * scale)
                elif typ == "perpendicular":
                    values.append(dot * scale)
                else:
                    actual = math.atan2(cross, dot)
                    target = math.radians(float(c.get("deg", c.get("angle_deg", 0.0))))
                    delta = math.atan2(math.sin(actual - target), math.cos(actual - target))
                    values.append(delta * scale)
            elif typ == "midpoint":
                midpoint = (p[c["a"]] + p[c["b"]]) * 0.5
                values.extend((p[c["point"]] - midpoint).tolist())
        return np.asarray(values, dtype=float)

    x0 = initial.reshape(-1)
    if prepared:
        result = least_squares(residual, x0, method="trf", xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=3000)
        solved = result.x.reshape((count, 2))
        residuals = residual(result.x)
        jacobian = np.asarray(result.jac, dtype=float)
        rank = int(np.linalg.matrix_rank(jacobian, tol=1e-8)) if jacobian.size else 0
        success = bool(result.success)
        iterations = int(result.nfev)
    else:
        solved = initial.copy()
        residuals = np.asarray([], dtype=float)
        rank = 0
        success = True
        iterations = 0

    max_residual = float(np.max(np.abs(residuals))) if residuals.size else 0.0
    dof = max(0, int(solved.size) - rank)
    redundant = max(0, int(residuals.size) - rank)
    intersections = _self_intersections(solved)
    area = _polygon_area(solved)
    geometry_valid = abs(area) > max(float(tolerance) ** 2, 1e-9) and not intersections
    constraints_satisfied = success and max_residual <= float(tolerance)
    fully_constrained = constraints_satisfied and dof == 0 and geometry_valid
    status = "fully_constrained" if fully_constrained else "under_constrained" if constraints_satisfied and dof > 0 and geometry_valid else "invalid_geometry" if not geometry_valid else "unsatisfied"

    return {
        "status": status,
        "fully_constrained": fully_constrained,
        "constraints_satisfied": constraints_satisfied,
        "geometry_valid": geometry_valid,
        "points": [[round(float(x), 9), round(float(y), 9)] for x, y in solved],
        "degrees_of_freedom": dof,
        "jacobian_rank": rank,
        "equation_count": int(residuals.size),
        "redundant_equations": redundant,
        "max_residual": max_residual,
        "signed_area_mm2": area,
        "self_intersections": [{"segment_a": a, "segment_b": b} for a, b in intersections],
        "iterations": iterations,
        "solver": "scipy.optimize.least_squares",
        "tolerance": float(tolerance),
    }


def _constrained_base_shape(obj: dict[str, Any]):
    assert _ORIGINAL_BASE_SHAPE is not None
    if str(obj.get("kind") or "") != "constrained_sketch_extrude":
        return _ORIGINAL_BASE_SHAPE(obj)
    params = obj.get("params") or {}
    sketch = params.get("sketch") if isinstance(params.get("sketch"), dict) else {}
    report = solve_sketch(
        sketch.get("points") or [],
        sketch.get("constraints") or [],
        tolerance=float(sketch.get("tolerance", 1e-5)),
    )
    if bool(sketch.get("require_fully_constrained", True)) and not report["fully_constrained"]:
        raise ValueError(
            f"Sketch is {report['status']} ({report['degrees_of_freedom']} DOF, max residual {report['max_residual']:.3g}); fully constrained geometry is required"
        )
    height = float(params.get("height", 10.0))
    if not math.isfinite(height) or abs(height) <= 1e-9:
        raise ValueError("constrained_sketch_extrude requires a non-zero finite height")
    return cq.Workplane("XY").polyline([(x, y) for x, y in report["points"]]).close().extrude(height, both=True).val()


def sketch_report_for_object(obj: dict[str, Any]) -> dict[str, Any]:
    if str(obj.get("kind") or "") != "constrained_sketch_extrude":
        raise ValueError("Object is not constrained_sketch_extrude")
    params = obj.get("params") or {}
    sketch = params.get("sketch") if isinstance(params.get("sketch"), dict) else {}
    return solve_sketch(sketch.get("points") or [], sketch.get("constraints") or [], tolerance=float(sketch.get("tolerance", 1e-5)))


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_BASE_SHAPE
    if _INSTALLED:
        return
    _ORIGINAL_BASE_SHAPE = core._base_shape
    core._base_shape = _constrained_base_shape

    app = legacy.app

    @app.post("/v2/sketch/solve", dependencies=[Depends(legacy.require_session)])
    async def solve_sketch_api(request: SketchSolveRequest) -> dict[str, Any]:
        try:
            return solve_sketch(request.points, request.constraints, tolerance=max(1e-9, min(float(request.tolerance), 1e-2)))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _INSTALLED = True
