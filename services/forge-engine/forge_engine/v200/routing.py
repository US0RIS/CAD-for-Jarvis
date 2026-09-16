from __future__ import annotations

"""Canonical cable/tube/hose routing for ForgeCAD 2.0.

Routes are authoritative engineering geometry, not viewport decoration. A route stores an
explicit 3D centerline and optional physical constraints such as diameter, clearance,
minimum bend radius, maximum length, endpoint objects, and electrical/fluid bindings.
ForgeCAD computes exact polyline length and deterministic circular-bend feasibility.

Obstacle screening is intentionally conservative: route centerline segments are checked
against expanded world-axis bounding boxes, not claimed to be exact B-rep collision or
flexible-body simulation. Exact placement, clips, strain relief and installation remain
physical verification concerns.
"""

from copy import deepcopy
import math
from typing import Any, Callable

import numpy as np
from fastapi import Depends, HTTPException

from ..engineering_state import EngineeringProject
from ..v110 import core


_INSTALLED = False
_PREVIOUS_EXECUTE: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_VALIDATION: Callable[..., dict[str, Any]] | None = None
_ROUTE_KINDS = {"cable", "wire", "wire_harness", "tube", "hose", "conduit", "generic"}


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _point(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must be [x, y, z] in project millimeters")
    return [_finite(value[i], f"{label}[{i}]") for i in range(3)]


def _routes(project: dict[str, Any]) -> list[dict[str, Any]]:
    routes = project.setdefault("routes", [])
    if not isinstance(routes, list):
        raise ValueError("project.routes must be a list")
    return routes


def _connection_exists(project: dict[str, Any], connection_id: str) -> bool:
    return any(
        isinstance(row, dict) and str(row.get("id") or "") == connection_id
        for row in project.get("connections") or []
    )


def _fluid_link_exists(project: dict[str, Any], link_id: str) -> bool:
    return any(
        isinstance(row, dict)
        and str(row.get("id") or "") == link_id
        and str(row.get("type", row.get("kind", ""))).strip().lower() in {"fluid_link", "hydraulic_link", "tube", "pipe"}
        for row in project.get("constraints") or []
    )


def _object_exists(project: dict[str, Any], object_id: str) -> bool:
    return any(isinstance(obj, dict) and str(obj.get("id") or "") == object_id for obj in project.get("objects") or [])


def normalize_route(raw: dict[str, Any], project: dict[str, Any], *, route_id: str | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Route must be an object")
    kind = str(raw.get("kind") or "generic").strip().lower()
    if kind not in _ROUTE_KINDS:
        raise ValueError("route kind must be cable, wire, wire_harness, tube, hose, conduit, or generic")
    points_raw = raw.get("points_mm", raw.get("points"))
    if not isinstance(points_raw, list) or len(points_raw) < 2:
        raise ValueError("Route requires at least two explicit 3D points")
    points = [_point(value, f"route point {index}") for index, value in enumerate(points_raw)]
    for index in range(len(points) - 1):
        if np.linalg.norm(np.asarray(points[index + 1]) - np.asarray(points[index])) <= 1e-12:
            raise ValueError(f"Route segment {index + 1} has zero length")

    diameter_raw = raw.get("outer_diameter_mm", raw.get("diameter_mm"))
    diameter = None if diameter_raw is None else _finite(diameter_raw, "route outer_diameter_mm")
    if diameter is not None and diameter <= 0.0:
        raise ValueError("route outer_diameter_mm must be positive")
    bend_raw = raw.get("min_bend_radius_mm")
    bend = None if bend_raw is None else _finite(bend_raw, "route min_bend_radius_mm")
    if bend is not None and bend < 0.0:
        raise ValueError("route min_bend_radius_mm cannot be negative")
    clearance = _finite(raw.get("clearance_mm", 0.0), "route clearance_mm")
    if clearance < 0.0:
        raise ValueError("route clearance_mm cannot be negative")
    max_length_raw = raw.get("max_length_mm")
    max_length = None if max_length_raw is None else _finite(max_length_raw, "route max_length_mm")
    if max_length is not None and max_length <= 0.0:
        raise ValueError("route max_length_mm must be positive")

    connection_id = str(raw.get("connection_id") or "").strip() or None
    if connection_id and not _connection_exists(project, connection_id):
        raise ValueError(f"Route references unknown electrical connection {connection_id}")
    fluid_link_id = str(raw.get("fluid_link_id") or "").strip() or None
    if fluid_link_id and not _fluid_link_exists(project, fluid_link_id):
        raise ValueError(f"Route references unknown fluid link {fluid_link_id}")

    a_object_id = str(raw.get("a_object_id") or "").strip() or None
    b_object_id = str(raw.get("b_object_id") or "").strip() or None
    for label, object_id in (("a_object_id", a_object_id), ("b_object_id", b_object_id)):
        if object_id and not _object_exists(project, object_id):
            raise ValueError(f"Route {label} references unknown object {object_id}")

    exclude = []
    for value in raw.get("exclude_object_ids") or []:
        object_id = str(value)
        if not _object_exists(project, object_id):
            raise ValueError(f"Route exclude_object_ids references unknown object {object_id}")
        if object_id not in exclude:
            exclude.append(object_id)

    return {
        "id": route_id or str(raw.get("id") or core.uid()),
        "name": str(raw.get("name") or f"{kind.replace('_', ' ').title()} route"),
        "kind": kind,
        "points_mm": points,
        "outer_diameter_mm": diameter,
        "min_bend_radius_mm": bend,
        "clearance_mm": clearance,
        "max_length_mm": max_length,
        "connection_id": connection_id,
        "net_name": str(raw.get("net_name") or "").strip() or None,
        "fluid_link_id": fluid_link_id,
        "a_object_id": a_object_id,
        "b_object_id": b_object_id,
        "exclude_object_ids": exclude,
        "hard_clearance": bool(raw.get("hard_clearance", False)),
        "metadata": deepcopy(raw.get("metadata") or {}),
    }


def _segment_lengths(points: list[list[float]]) -> list[float]:
    return [
        float(np.linalg.norm(np.asarray(points[index + 1], dtype=float) - np.asarray(points[index], dtype=float)))
        for index in range(len(points) - 1)
    ]


def _bend_report(points: list[list[float]], radius_mm: float | None) -> dict[str, Any]:
    lengths = _segment_lengths(points)
    if radius_mm is None or radius_mm <= 1e-12 or len(points) < 3:
        return {
            "checked": radius_mm is not None,
            "min_bend_radius_mm": radius_mm,
            "corners": [],
            "segment_tangent_margins_mm": lengths,
            "feasible": True,
            "smoothed_centerline_length_mm": sum(lengths),
        }

    radius = float(radius_mm)
    corners: list[dict[str, Any]] = []
    setbacks = [0.0 for _ in points]
    feasible = True
    smooth_length = sum(lengths)
    for index in range(1, len(points) - 1):
        prev = np.asarray(points[index - 1], dtype=float)
        current = np.asarray(points[index], dtype=float)
        nxt = np.asarray(points[index + 1], dtype=float)
        to_prev = prev - current
        to_next = nxt - current
        l_prev = float(np.linalg.norm(to_prev))
        l_next = float(np.linalg.norm(to_next))
        cosine = float(np.dot(to_prev, to_next) / (l_prev * l_next))
        cosine = max(-1.0, min(1.0, cosine))
        included = math.acos(cosine)
        turn = math.pi - included
        if turn <= 1e-10:
            setback = 0.0
            arc_length = 0.0
        elif turn >= math.pi - 1e-8:
            setback = float("inf")
            arc_length = float("inf")
            feasible = False
        else:
            setback = radius * math.tan(turn / 2.0)
            arc_length = radius * turn
            smooth_length += arc_length - 2.0 * setback
        setbacks[index] = setback
        corner_ok = math.isfinite(setback) and setback <= l_prev + 1e-9 and setback <= l_next + 1e-9
        feasible = feasible and corner_ok
        corners.append({
            "point_index": index,
            "turn_angle_deg": math.degrees(turn),
            "required_tangent_setback_mm": setback,
            "available_incoming_mm": l_prev,
            "available_outgoing_mm": l_next,
            "feasible": corner_ok,
        })

    margins: list[float] = []
    for index, length in enumerate(lengths):
        used = setbacks[index] + setbacks[index + 1]
        margin = length - used
        margins.append(margin)
        if not math.isfinite(margin) or margin < -1e-9:
            feasible = False
    return {
        "checked": True,
        "min_bend_radius_mm": radius,
        "corners": corners,
        "segment_tangent_margins_mm": margins,
        "feasible": feasible,
        "smoothed_centerline_length_mm": smooth_length if math.isfinite(smooth_length) else None,
    }


def _segment_intersects_aabb(p0: np.ndarray, p1: np.ndarray, bounds: tuple[float, float, float, float, float, float], pad: float) -> bool:
    xmin, xmax, ymin, ymax, zmin, zmax = bounds
    lows = np.asarray([xmin - pad, ymin - pad, zmin - pad], dtype=float)
    highs = np.asarray([xmax + pad, ymax + pad, zmax + pad], dtype=float)
    direction = p1 - p0
    t_min, t_max = 0.0, 1.0
    for axis in range(3):
        if abs(float(direction[axis])) <= 1e-12:
            if p0[axis] < lows[axis] or p0[axis] > highs[axis]:
                return False
            continue
        t1 = float((lows[axis] - p0[axis]) / direction[axis])
        t2 = float((highs[axis] - p0[axis]) / direction[axis])
        if t1 > t2:
            t1, t2 = t2, t1
        t_min = max(t_min, t1)
        t_max = min(t_max, t2)
        if t_min > t_max:
            return False
    return True


def _obstructions(route: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = set(route.get("exclude_object_ids") or [])
    excluded.update(value for value in (route.get("a_object_id"), route.get("b_object_id")) if value)
    radius = (float(route.get("outer_diameter_mm") or 0.0) / 2.0) + float(route.get("clearance_mm") or 0.0)
    points = [np.asarray(point, dtype=float) for point in route["points_mm"]]
    hits: list[dict[str, Any]] = []
    for obj in project.get("objects") or []:
        if not isinstance(obj, dict) or not obj.get("visible", True):
            continue
        object_id = str(obj.get("id") or "")
        if not object_id or object_id in excluded:
            continue
        try:
            bb = core.build_shape(obj).BoundingBox()
            bounds = (float(bb.xmin), float(bb.xmax), float(bb.ymin), float(bb.ymax), float(bb.zmin), float(bb.zmax))
        except Exception:
            continue
        segments = [
            index
            for index in range(len(points) - 1)
            if _segment_intersects_aabb(points[index], points[index + 1], bounds, radius)
        ]
        if segments:
            hits.append({
                "object_id": object_id,
                "object_name": str(obj.get("name") or object_id),
                "segment_indices": segments,
                "method": "expanded world-axis bounding-box proxy",
            })
    return hits


def analyze_route(route: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    points = route["points_mm"]
    lengths = _segment_lengths(points)
    polyline_length = sum(lengths)
    bend = _bend_report(points, route.get("min_bend_radius_mm"))
    obstructions = _obstructions(route, project)
    max_length = route.get("max_length_mm")
    length_ok = max_length is None or polyline_length <= float(max_length) + 1e-9
    return {
        **deepcopy(route),
        "segment_lengths_mm": lengths,
        "polyline_length_mm": polyline_length,
        "bend": bend,
        "obstructions": obstructions,
        "length_within_limit": length_ok,
        "binding": {
            "electrical_connection_valid": route.get("connection_id") is None or _connection_exists(project, str(route["connection_id"])),
            "fluid_link_valid": route.get("fluid_link_id") is None or _fluid_link_exists(project, str(route["fluid_link_id"])),
        },
    }


def analyze_routes(project: dict[str, Any] | None = None) -> dict[str, Any]:
    source = project if project is not None else core.PROJECT
    routes = list(source.get("routes") or [])
    items: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    for raw in routes:
        if not isinstance(raw, dict):
            risks.append({"severity": "error", "code": "route_invalid", "message": "project.routes contains a non-object record"})
            continue
        try:
            route = normalize_route(raw, source, route_id=str(raw.get("id") or core.uid()))
            result = analyze_route(route, source)
            items.append(result)
            if not result["bend"]["feasible"]:
                risks.append({"severity": "error", "code": "route_bend_radius_violation", "route_id": route["id"], "message": f"Route {route['name']} cannot realize its {float(route['min_bend_radius_mm'] or 0.0):g} mm minimum bend radius with the supplied waypoints."})
            if not result["length_within_limit"]:
                risks.append({"severity": "error", "code": "route_length_limit_exceeded", "route_id": route["id"], "message": f"Route {route['name']} length {result['polyline_length_mm']:.3f} mm exceeds modeled maximum {float(route['max_length_mm']):.3f} mm."})
            for key, valid in result["binding"].items():
                if not valid:
                    risks.append({"severity": "error", "code": "route_binding_invalid", "route_id": route["id"], "message": f"Route {route['name']} has invalid {key.replace('_', ' ')}."})
            if result["obstructions"]:
                severity = "error" if route.get("hard_clearance") else "warning"
                risks.append({
                    "severity": severity,
                    "code": "route_clearance_proxy_conflict",
                    "route_id": route["id"],
                    "message": f"Route {route['name']} intersects {len(result['obstructions'])} expanded object bounding-box proxy/proxies; inspect exact routing clearance.",
                    "obstructions": deepcopy(result["obstructions"]),
                })
        except Exception as exc:
            risks.append({"severity": "error", "code": "route_invalid", "route_id": str(raw.get("id") or ""), "message": str(exc)})

    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    return {
        "solver": "ForgeCAD RouteGeometry",
        "solver_version": "2.0.0",
        "solver_grade": "engineering_iteration",
        "count": len(items),
        "items": items,
        "ok": counts["error"] == 0,
        "counts": counts,
        "risks": risks,
        "limitations": [
            "Route waypoints are explicit centerline geometry; ForgeCAD does not infer a cable/tube path from CAD proximity.",
            "Obstacle screening uses conservative expanded world-axis bounding boxes, not exact swept-flexible-body B-rep collision.",
            "Bend feasibility assumes planar circular tangent bends local to each polyline corner and checks adjacent tangent-setback overlap.",
            "Clips, strain relief, connector service loops, installation sequence, torsion and flexible-body dynamics require separate verification unless explicitly modeled.",
        ],
        "physical_verification": False,
    }


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _PREVIOUS_EXECUTE is not None
    payload = deepcopy(args or {})
    if op not in {"add_route", "update_route", "delete_route"}:
        return _PREVIOUS_EXECUTE(op, payload, actor=actor, reason=reason)

    with core.LOCK:
        core.ensure_mutable(actor, reason or op)
        routes = _routes(core.PROJECT)
        if op == "add_route":
            route = normalize_route(payload, core.PROJECT)
            routes.append(route)
            result_route = route
        elif op == "update_route":
            route_id = str(payload.get("id") or "")
            index = next((i for i, row in enumerate(routes) if isinstance(row, dict) and str(row.get("id") or "") == route_id), None)
            if index is None:
                raise KeyError(f"Route not found: {route_id}")
            merged = deepcopy(routes[index])
            merged.update({key: value for key, value in payload.items() if key != "id"})
            route = normalize_route(merged, core.PROJECT, route_id=route_id)
            routes[index] = route
            result_route = route
        else:
            route_id = str(payload.get("id") or "")
            index = next((i for i, row in enumerate(routes) if isinstance(row, dict) and str(row.get("id") or "") == route_id), None)
            if index is None:
                raise KeyError(f"Route not found: {route_id}")
            result_route = routes.pop(index)
        core.mark_simulations_stale(None)
        core.push_history(op, actor, reason or op)
        core.persist()
    return {"ok": True, "op": op, "route": deepcopy(result_route), "project": core.PROJECT, "active_design": core.ACTIVE_DESIGN}


def _validation(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_VALIDATION is not None
    base = deepcopy(_ORIGINAL_VALIDATION(self))
    routing = analyze_routes(core.PROJECT)
    combined = list(base.get("risks") or []) + list(routing.get("risks") or [])
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for risk in combined:
        if not isinstance(risk, dict):
            continue
        key = (str(risk.get("code") or ""), str(risk.get("route_id") or risk.get("object_id") or risk.get("link_id") or risk.get("connection_id") or ""), str(risk.get("message") or ""))
        deduped[key] = risk
    risks = sorted(deduped.values(), key=lambda risk: ({"error": 0, "warning": 1, "info": 2}.get(str(risk.get("severity") or ""), 3), str(risk.get("code") or ""), str(risk.get("message") or "")))
    counts = {level: sum(1 for risk in risks if risk.get("severity") == level) for level in ("error", "warning", "info")}
    base["risks"] = risks
    base["counts"] = counts
    base["ok"] = counts["error"] == 0
    base["routing"] = routing
    return base


def install(legacy: Any) -> None:
    global _INSTALLED, _PREVIOUS_EXECUTE, _ORIGINAL_VALIDATION
    if _INSTALLED:
        return
    core.PROJECT.setdefault("routes", [])
    _PREVIOUS_EXECUTE = core.execute
    core.execute = _execute
    _ORIGINAL_VALIDATION = EngineeringProject.validation
    EngineeringProject.validation = _validation
    app = legacy.app

    @app.get("/v2/routes", dependencies=[Depends(legacy.require_session)])
    async def routes() -> dict[str, Any]:
        return {"routes": deepcopy(core.PROJECT.get("routes") or []), "analysis": analyze_routes(core.PROJECT)}

    @app.get("/v2/analysis/routes", dependencies=[Depends(legacy.require_session)])
    async def routes_analysis() -> dict[str, Any]:
        return analyze_routes(core.PROJECT)

    @app.post("/v2/routes", dependencies=[Depends(legacy.require_session)])
    async def add_route(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = core.execute("add_route", payload, actor="human", reason="Add routed cable/tube path")
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"operation": result, "analysis": analyze_routes(core.PROJECT)}

    _INSTALLED = True
