from __future__ import annotations

"""Feature-history enhancements for ForgeCAD 3.1.

The v1 execution core remains the canonical geometry engine. This module adds
stable feature identity, suppress/update/reorder operations and additional
parametric feature families without creating a parallel CAD state model.
"""

from copy import deepcopy
import math
from typing import Any
import uuid

import cadquery as cq

from ..v110 import core


_INSTALLED = False
_ORIGINAL_EXECUTE = core.execute
_ORIGINAL_APPLY_FEATURE = core._apply_feature
_ORIGINAL_BASE_SHAPE = core._base_shape


def _feature_id() -> str:
    return f"feat-{uuid.uuid4()}"


def normalize_feature(feature: dict[str, Any], *, actor: str = "human") -> dict[str, Any]:
    row = deepcopy(feature)
    row.setdefault("id", _feature_id())
    row.setdefault("name", str(row.get("type") or "Feature").replace("_", " ").title())
    row.setdefault("enabled", True)
    row.setdefault("created_at", core.now())
    row.setdefault("provenance", {"actor": actor, "method": "forgecad_feature_history"})
    return row


def _primitive_tool(spec: dict[str, Any], bb: Any) -> Any:
    kind = str(spec.get("primitive") or spec.get("shape") or "box")
    x = float(spec.get("x", 0.0)); y = float(spec.get("y", 0.0)); z = float(spec.get("z", 0.0))
    if kind in {"cylinder", "circle"}:
        diameter = float(spec.get("diameter", spec.get("diameter_mm", 10.0)))
        height = float(spec.get("height", spec.get("height_mm", max(bb.zlen, 10.0) + 20.0)))
        return cq.Workplane("XY").workplane(offset=z - height / 2).center(x, y).circle(diameter / 2).extrude(height).val()
    width = float(spec.get("width", spec.get("x_size", 10.0)))
    depth = float(spec.get("depth", spec.get("y_size", 10.0)))
    height = float(spec.get("height", spec.get("z_size", 10.0)))
    return cq.Workplane("XY").workplane(offset=z - height / 2).center(x, y).box(width, depth, height, centered=(True, True, False)).val()


def _slot_tool(feature: dict[str, Any], bb: Any) -> Any:
    length = float(feature.get("length", 20.0))
    width = float(feature.get("width", 5.0))
    depth = float(feature.get("depth", max(bb.zlen, 10.0) + 20.0))
    x = float(feature.get("x", 0.0)); y = float(feature.get("y", 0.0))
    top = float(feature.get("z", bb.zmax + 0.01))
    straight = max(0.0, length - width)
    wp = cq.Workplane("XY").workplane(offset=top).center(x, y)
    if straight <= 1e-9:
        return wp.circle(width / 2).extrude(-depth).val()
    # hull of two circles plus the connecting rectangle
    c1 = wp.center(-straight / 2, 0).circle(width / 2).extrude(-depth).val()
    c2 = cq.Workplane("XY").workplane(offset=top).center(x + straight / 2, y).circle(width / 2).extrude(-depth).val()
    rect = cq.Workplane("XY").workplane(offset=top).center(x, y).rect(straight, width).extrude(-depth).val()
    return c1.fuse(c2).fuse(rect)


def _offset_nested(feature: dict[str, Any], dx: float, dy: float, dz: float) -> dict[str, Any]:
    nested = deepcopy(feature)
    for key, delta in (("x", dx), ("y", dy), ("z", dz)):
        if key in nested or abs(delta) > 0:
            nested[key] = float(nested.get(key, 0.0)) + delta
    return nested


def _rotate_nested_xy(feature: dict[str, Any], angle_deg: float) -> dict[str, Any]:
    nested = deepcopy(feature)
    x, y = float(nested.get("x", 0.0)), float(nested.get("y", 0.0))
    theta = math.radians(angle_deg)
    nested["x"] = x * math.cos(theta) - y * math.sin(theta)
    nested["y"] = x * math.sin(theta) + y * math.cos(theta)
    return nested


def _apply_feature(shape: Any, feature: dict[str, Any]) -> Any:
    if feature.get("enabled", True) is False:
        return shape
    typ = str(feature.get("type") or "")
    bb = shape.BoundingBox()
    if typ == "slot":
        return shape.cut(_slot_tool(feature, bb))
    if typ == "counterbore":
        hole = {"type": "hole", **feature}
        result = _ORIGINAL_APPLY_FEATURE(shape, hole)
        recess = {
            "type": "circular_pocket",
            "diameter": float(feature.get("counterbore_diameter", feature.get("diameter", 5.0) * 1.8)),
            "depth": float(feature.get("counterbore_depth", 2.0)),
            "x": float(feature.get("x", 0.0)),
            "y": float(feature.get("y", 0.0)),
        }
        return _ORIGINAL_APPLY_FEATURE(result, recess)
    if typ == "countersink":
        # Deterministic conical cut from the top surface.
        diameter = float(feature.get("diameter", 4.0))
        sink_diameter = float(feature.get("countersink_diameter", diameter * 2.0))
        angle = float(feature.get("angle_deg", 90.0))
        x = float(feature.get("x", 0.0)); y = float(feature.get("y", 0.0))
        margin = max(bb.xlen, bb.ylen, bb.zlen) + 20.0
        through = cq.Workplane("XY").center(x, y).circle(diameter / 2).extrude(margin, both=True).val()
        depth = max(0.01, (sink_diameter - diameter) / (2 * math.tan(math.radians(angle / 2))))
        cone = cq.Workplane("XY").workplane(offset=bb.zmax + 0.01).center(x, y).circle(sink_diameter / 2).workplane(offset=-depth).circle(diameter / 2).loft(combine=True).val()
        return shape.cut(through.fuse(cone))
    if typ in {"boss", "boss_box", "boss_cylinder"}:
        spec = deepcopy(feature)
        if typ == "boss_cylinder":
            spec["primitive"] = "cylinder"
        elif typ == "boss_box":
            spec["primitive"] = "box"
        return shape.fuse(_primitive_tool(spec, bb))
    if typ in {"boolean_cut", "boolean_union", "boolean_intersect"}:
        tool = _primitive_tool(feature.get("tool") or feature, bb)
        if typ == "boolean_cut":
            return shape.cut(tool)
        if typ == "boolean_union":
            return shape.fuse(tool)
        return shape.intersect(tool)
    if typ == "shell":
        thickness = float(feature.get("thickness", 1.0))
        try:
            selector = str(feature.get("remove_face") or ">Z")
            return cq.Workplane(obj=shape).faces(selector).shell(-abs(thickness)).val()
        except Exception as exc:
            raise ValueError(f"Shell feature could not be evaluated: {exc}") from exc
    if typ == "linear_pattern":
        nested = feature.get("feature") or {}
        count = max(1, min(1000, int(feature.get("count", 2))))
        spacing = float(feature.get("spacing", 10.0))
        direction = feature.get("direction") or [1.0, 0.0, 0.0]
        dx, dy, dz = [float(v) * spacing for v in list(direction)[:3]]
        result = shape
        for index in range(count):
            result = _apply_feature(result, _offset_nested(nested, dx * index, dy * index, dz * index))
        return result
    if typ == "circular_pattern":
        nested = feature.get("feature") or {}
        count = max(1, min(1000, int(feature.get("count", 4))))
        sweep = float(feature.get("angle_deg", 360.0))
        step = sweep / count
        result = shape
        for index in range(count):
            result = _apply_feature(result, _rotate_nested_xy(nested, step * index))
        return result
    if typ == "mirror_feature":
        nested = deepcopy(feature.get("feature") or {})
        axis = str(feature.get("axis") or "x").lower()
        result = _apply_feature(shape, nested)
        mirrored = deepcopy(nested)
        if axis == "x":
            mirrored["x"] = -float(mirrored.get("x", 0.0))
        elif axis == "y":
            mirrored["y"] = -float(mirrored.get("y", 0.0))
        else:
            mirrored["z"] = -float(mirrored.get("z", 0.0))
        return _apply_feature(result, mirrored)
    return _ORIGINAL_APPLY_FEATURE(shape, feature)


def _base_shape(obj: dict[str, Any]) -> Any:
    kind = str(obj.get("kind") or "")
    params = obj.get("params") or {}
    if kind == "loft":
        sections = list(params.get("sections") or [])
        if len(sections) < 2:
            raise ValueError("Loft requires at least two sections")
        first = sections[0]
        z0 = float(first.get("z", 0.0))
        wp = cq.Workplane("XY").workplane(offset=z0)
        section_type = str(first.get("type") or "rectangle")
        if section_type == "circle":
            wp = wp.circle(float(first.get("radius", 10.0)))
        else:
            wp = wp.rect(float(first.get("width", 20.0)), float(first.get("height", 20.0)))
        previous_z = z0
        for section in sections[1:]:
            z = float(section.get("z", previous_z + 10.0))
            wp = wp.workplane(offset=z - previous_z)
            current_type = str(section.get("type") or section_type)
            if current_type == "circle":
                wp = wp.circle(float(section.get("radius", 10.0)))
            else:
                wp = wp.rect(float(section.get("width", 20.0)), float(section.get("height", 20.0)))
            previous_z = z
        return wp.loft(combine=True).val()
    if kind == "sweep":
        path_points = [(float(p[0]), float(p[1])) for p in params.get("path_xz", [[0, 0], [20, 0], [20, 20]])]
        if len(path_points) < 2:
            raise ValueError("Sweep requires at least two path points")
        path = cq.Workplane("XZ").polyline(path_points)
        profile = params.get("profile") or {"type": "circle", "radius": 2.0}
        start = path_points[0]
        wp = cq.Workplane("YZ", origin=(start[0], 0, start[1]))
        if str(profile.get("type") or "circle") == "rectangle":
            wp = wp.rect(float(profile.get("width", 4.0)), float(profile.get("height", 4.0)))
        else:
            wp = wp.circle(float(profile.get("radius", 2.0)))
        return wp.sweep(path, isFrenet=True).val()
    return _ORIGINAL_BASE_SHAPE(obj)


def _find_feature(obj: dict[str, Any], args: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    features = obj.setdefault("features", [])
    feature_id = args.get("feature_id")
    if feature_id is not None:
        for index, row in enumerate(features):
            if str(row.get("id")) == str(feature_id):
                return index, row
        raise KeyError(str(feature_id))
    index = int(args.get("index", -1))
    if index < 0:
        index += len(features)
    if index < 0 or index >= len(features):
        raise IndexError(index)
    return index, features[index]


def _feature_history_mutation(op: str, args: dict[str, Any], actor: str, reason: str) -> dict[str, Any]:
    with core.LOCK:
        core.ensure_mutable(actor, reason or op)
        obj = core.object_by_id(str(args.get("id")))
        if obj.get("kind") == "component":
            raise ValueError("Purchased component geometry is immutable; create a fabricated derivative instead")
        features = obj.setdefault("features", [])
        if op == "update_feature":
            index, current = _find_feature(obj, args)
            patch = deepcopy(args.get("patch") or {})
            protected = {"id", "created_at", "provenance"}
            for key, value in patch.items():
                if key not in protected:
                    current[key] = value
            current.setdefault("updated_at", core.now())
            current["updated_at"] = core.now()
            changed_feature = deepcopy(current)
        elif op == "reorder_feature":
            index, current = _find_feature(obj, args)
            target = max(0, min(len(features) - 1, int(args.get("to_index", index))))
            features.pop(index)
            features.insert(target, current)
            changed_feature = deepcopy(current)
        elif op == "suppress_feature":
            _, current = _find_feature(obj, args)
            current["enabled"] = not bool(args.get("suppressed", True))
            current["updated_at"] = core.now()
            changed_feature = deepcopy(current)
        elif op == "duplicate_feature":
            index, current = _find_feature(obj, args)
            clone = normalize_feature(current, actor=actor)
            clone["id"] = _feature_id()
            clone["name"] = str(args.get("name") or f"{current.get('name') or current.get('type') or 'Feature'} Copy")
            clone["created_at"] = core.now()
            features.insert(index + 1, clone)
            changed_feature = deepcopy(clone)
        else:
            raise ValueError(f"Unsupported feature-history operation: {op}")
        core.mark_simulations_stale(obj["id"])
        core.push_history(op, actor, reason)
        core.persist()
        return {"ok": True, "op": op, "object_id": obj["id"], "feature": changed_feature, "features": deepcopy(features), "active_design": core.ACTIVE_DESIGN}


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    payload = deepcopy(args or {})
    if op in {"update_feature", "reorder_feature", "suppress_feature", "duplicate_feature"}:
        return _feature_history_mutation(op, payload, actor, reason)
    if op == "add_feature":
        payload["feature"] = normalize_feature(payload.get("feature") or {}, actor=actor)
    elif op == "add" and payload.get("features"):
        payload["features"] = [normalize_feature(row, actor=actor) for row in payload.get("features") or []]
    elif op == "delete_feature" and payload.get("feature_id") is not None:
        with core.LOCK:
            core.ensure_mutable(actor, reason or op)
            obj = core.object_by_id(str(payload.get("id")))
            if obj.get("kind") == "component":
                raise ValueError("Purchased component geometry is immutable")
            index, current = _find_feature(obj, payload)
            obj.setdefault("features", []).pop(index)
            core.mark_simulations_stale(obj["id"])
            core.push_history(op, actor, reason)
            core.persist()
            return {"ok": True, "op": op, "object_id": obj["id"], "deleted_feature": deepcopy(current), "project": core.PROJECT, "active_design": core.ACTIVE_DESIGN}
    return _ORIGINAL_EXECUTE(op, payload, actor=actor, reason=reason)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    core._apply_feature = _apply_feature
    core._base_shape = _base_shape
    core.execute = _execute
    # Upgrade loaded legacy feature rows in-place so every subsequent graph/event
    # has stable feature identity.
    with core.LOCK:
        changed = False
        for obj in core.PROJECT.get("objects", []):
            if obj.get("kind") == "component":
                continue
            normalized = []
            for feature in obj.get("features", []):
                row = normalize_feature(feature)
                normalized.append(row)
                changed = changed or row != feature
            obj["features"] = normalized
        if changed:
            core.persist()
    _INSTALLED = True
