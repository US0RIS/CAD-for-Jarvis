from __future__ import annotations

"""Branch-safe oversized-part splitting for the ForgeCAD 2.0 P2S workflow.

ForgeCAD already detects bodies that cannot fit the Bambu Lab P2S. This module turns
that diagnostic into editable manufacturing geometry:

- divide an oversized custom solid into world-axis clipping cells that fit inside a
  conservative P2S envelope;
- preserve the exact source B-rep as an embedded snapshot in each derived piece;
- optionally add paired blind alignment sockets across internal seams;
- hide, never destroy, the unsplit source on the manufacturing branch;
- keep the known-good/source branch untouched;
- make the split pieces ordinary ForgeCAD fabricated bodies for scene rendering, 3MF
  export, mass/geometry analysis, and physical-evidence tracking.

The split is a fabrication strategy, not a claim that the resulting joint is structurally
adequate. Joint strength, adhesive/fastener selection and print anisotropy still require
engineering verification.
"""

from copy import deepcopy
import itertools
import math
from types import MethodType
from typing import Any, Callable

import cadquery as cq
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from ..v110 import core
from . import manufacturing


_INSTALLED = False
_ORIGINAL_BASE_SHAPE: Callable[[dict[str, Any]], Any] | None = None
_ORIGINAL_APPLY_FEATURE: Callable[[Any, dict[str, Any]], Any] | None = None
_ORIGINAL_IS_FABRICATED: Callable[[dict[str, Any]], bool] | None = None
_ORIGINAL_EXECUTE: Callable[..., dict[str, Any]] | None = None


class SplitPlanRequest(BaseModel):
    object_id: str
    margin_mm: float = Field(default=8.0, ge=0.0, le=40.0)
    max_pieces: int = Field(default=24, ge=2, le=64)
    alignment_diameter_mm: float = Field(default=3.2, ge=0.0, le=20.0)
    alignment_depth_mm: float = Field(default=8.0, ge=0.0, le=40.0)


class SplitApplyRequest(SplitPlanRequest):
    branch_name: str | None = None
    create_branch: bool = True


def _identity_transform() -> dict[str, list[float]]:
    return {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}


def _clip_shape(bounds: list[list[float]]) -> Any:
    mins, maxs = bounds
    size = [float(maxs[i]) - float(mins[i]) for i in range(3)]
    if any(value <= 1e-9 for value in size):
        raise ValueError("Manufacturing split clip has zero extent")
    center = [(float(mins[i]) + float(maxs[i])) * 0.5 for i in range(3)]
    return cq.Workplane("XY").box(size[0], size[1], size[2]).val().translate(tuple(center))


def _manufacturing_piece_base_shape(obj: dict[str, Any]):
    assert _ORIGINAL_BASE_SHAPE is not None
    if str(obj.get("kind") or "") != "manufacturing_piece":
        return _ORIGINAL_BASE_SHAPE(obj)
    params = obj.get("params") if isinstance(obj.get("params"), dict) else {}
    source = params.get("source_snapshot")
    bounds = params.get("clip_bounds_mm")
    if not isinstance(source, dict):
        raise ValueError("manufacturing_piece is missing source_snapshot")
    if str(source.get("kind") or "") == "manufacturing_piece":
        raise ValueError("Nested manufacturing_piece sources are not supported; split the original fabricated body instead")
    if not isinstance(bounds, list) or len(bounds) != 2 or any(not isinstance(row, list) or len(row) != 3 for row in bounds):
        raise ValueError("manufacturing_piece has invalid clip_bounds_mm")
    source_shape = core.build_shape(deepcopy(source))
    result = source_shape.intersect(_clip_shape(bounds))
    if float(result.Volume()) <= 1e-9:
        raise ValueError("Manufacturing split cell does not intersect the source solid")
    return result


def _split_feature(shape: Any, feature: dict[str, Any]):
    assert _ORIGINAL_APPLY_FEATURE is not None
    if str(feature.get("type") or "") != "split_socket":
        return _ORIGINAL_APPLY_FEATURE(shape, feature)
    diameter = float(feature.get("diameter", 3.2))
    depth = float(feature.get("depth", 8.0))
    start = feature.get("start") or [0.0, 0.0, 0.0]
    direction = feature.get("direction") or [0.0, 0.0, 1.0]
    if diameter <= 0.0 or depth <= 0.0:
        return shape
    if len(start) != 3 or len(direction) != 3:
        raise ValueError("split_socket requires 3D start and direction vectors")
    vector = [float(value) for value in direction]
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 1e-12:
        raise ValueError("split_socket direction cannot be zero")
    unit = [value / norm for value in vector]
    # Start just outside the mating plane so numerical tolerance cannot leave a membrane
    # over the socket mouth. The cylinder then extends into the piece.
    origin = [float(start[i]) - unit[i] * 0.05 for i in range(3)]
    tool = cq.Solid.makeCylinder(
        diameter * 0.5,
        depth + 0.10,
        cq.Vector(*origin),
        cq.Vector(*unit),
    )
    return shape.cut(tool)


def _is_fabricated(obj: dict[str, Any]) -> bool:
    assert _ORIGINAL_IS_FABRICATED is not None
    if str(obj.get("kind") or "") == "manufacturing_piece":
        return bool(obj.get("visible", True))
    return _ORIGINAL_IS_FABRICATED(obj)


def _axis_edges(lo: float, hi: float, count: int) -> list[float]:
    return [lo + (hi - lo) * index / count for index in range(count + 1)]


def _alignment_positions(bounds: list[list[float]], axis: int, diameter: float) -> list[list[float]]:
    mins, maxs = bounds
    cross_axes = [value for value in range(3) if value != axis]
    centers = [(float(mins[i]) + float(maxs[i])) * 0.5 for i in range(3)]
    spans = [float(maxs[i]) - float(mins[i]) for i in range(3)]
    long_cross = max(cross_axes, key=lambda value: spans[value])
    usable = spans[long_cross]
    if usable >= max(18.0, diameter * 6.0):
        offset = min(usable * 0.24, max(5.0, usable * 0.5 - diameter * 2.0))
        result = []
        for sign in (-1.0, 1.0):
            point = list(centers)
            point[long_cross] += sign * offset
            result.append(point)
        return result
    return [centers]


def split_plan(
    obj: dict[str, Any],
    *,
    printer: dict[str, Any] = manufacturing.P2S_PROFILE,
    margin_mm: float = 8.0,
    max_pieces: int = 24,
    alignment_diameter_mm: float = 3.2,
    alignment_depth_mm: float = 8.0,
) -> dict[str, Any]:
    if obj.get("kind") == "component" or obj.get("component_ref"):
        raise ValueError("Purchased components cannot be split as fabricated geometry")
    if str(obj.get("kind") or "") == "manufacturing_piece":
        raise ValueError("Split the original fabricated body rather than recursively splitting a manufacturing piece")
    shape = core.build_shape(obj)
    bb = shape.BoundingBox()
    mins = [float(bb.xmin), float(bb.ymin), float(bb.zmin)]
    maxs = [float(bb.xmax), float(bb.ymax), float(bb.zmax)]
    extents = [maxs[i] - mins[i] for i in range(3)]
    build = [float(value) for value in printer["build_volume_mm"]]
    margin = max(0.0, float(margin_mm))
    usable = [value - 2.0 * margin for value in build]
    if any(value <= 1.0 for value in usable):
        raise ValueError("Requested split margin leaves no usable P2S build volume")

    counts = [max(1, int(math.ceil(extents[i] / usable[i] - 1e-12))) for i in range(3)]
    total = counts[0] * counts[1] * counts[2]
    if total > int(max_pieces):
        raise ValueError(f"P2S split requires {total} pieces, exceeding max_pieces={max_pieces}")

    edges = [_axis_edges(mins[i], maxs[i], counts[i]) for i in range(3)]
    pieces: list[dict[str, Any]] = []
    by_grid: dict[tuple[int, int, int], dict[str, Any]] = {}
    for grid in itertools.product(*(range(count) for count in counts)):
        bounds = [
            [edges[axis][grid[axis]] for axis in range(3)],
            [edges[axis][grid[axis] + 1] for axis in range(3)],
        ]
        row = {
            "index": len(pieces) + 1,
            "grid": list(grid),
            "clip_bounds_mm": bounds,
            "bounds_mm": [bounds[1][axis] - bounds[0][axis] for axis in range(3)],
            "alignment_features": [],
        }
        pieces.append(row)
        by_grid[tuple(grid)] = row

    seam_count = 0
    alignment_pair_count = 0
    diameter = max(0.0, float(alignment_diameter_mm))
    requested_depth = max(0.0, float(alignment_depth_mm))
    if diameter > 0.0 and requested_depth > 0.0 and total > 1:
        for axis in range(3):
            for grid in itertools.product(*(range(count) for count in counts)):
                if grid[axis] >= counts[axis] - 1:
                    continue
                neighbor = list(grid)
                neighbor[axis] += 1
                a = by_grid[tuple(grid)]
                b = by_grid[tuple(neighbor)]
                seam_count += 1
                a_extent = float(a["bounds_mm"][axis])
                b_extent = float(b["bounds_mm"][axis])
                depth = min(requested_depth, a_extent * 0.35, b_extent * 0.35)
                if depth < diameter * 0.75:
                    continue
                seam = float(a["clip_bounds_mm"][1][axis])
                shared_bounds = [
                    [max(float(a["clip_bounds_mm"][0][i]), float(b["clip_bounds_mm"][0][i])) if i != axis else seam for i in range(3)],
                    [min(float(a["clip_bounds_mm"][1][i]), float(b["clip_bounds_mm"][1][i])) if i != axis else seam for i in range(3)],
                ]
                # Give the position helper a tiny normal thickness so it can treat this
                # as a 3D bounds record while choosing coordinates in the seam plane.
                shared_bounds[0][axis] = seam
                shared_bounds[1][axis] = seam
                for point in _alignment_positions(shared_bounds, axis, diameter):
                    point[axis] = seam
                    neg_direction = [0.0, 0.0, 0.0]
                    pos_direction = [0.0, 0.0, 0.0]
                    neg_direction[axis] = -1.0
                    pos_direction[axis] = 1.0
                    feature_common = {
                        "type": "split_socket",
                        "diameter": diameter,
                        "depth": depth,
                        "start": point,
                        "seam_axis": "xyz"[axis],
                        "seam_coordinate_mm": seam,
                    }
                    a["alignment_features"].append({**deepcopy(feature_common), "direction": neg_direction})
                    b["alignment_features"].append({**deepcopy(feature_common), "direction": pos_direction})
                    alignment_pair_count += 1
    else:
        seam_count = sum(
            (counts[axis] - 1) * math.prod(counts[other] for other in range(3) if other != axis)
            for axis in range(3)
        )

    return {
        "resource": deepcopy(printer),
        "object_id": str(obj.get("id") or ""),
        "object_name": str(obj.get("name") or obj.get("id") or "Part"),
        "source_bounds_mm": [round(value, 4) for value in extents],
        "usable_piece_envelope_mm": [round(value, 4) for value in usable],
        "margin_mm": margin,
        "split_required": total > 1,
        "grid_counts": counts,
        "piece_count": total,
        "seam_count": seam_count,
        "alignment_pair_count": alignment_pair_count,
        "alignment_diameter_mm": diameter,
        "alignment_depth_mm": requested_depth,
        "pieces": pieces,
        "joint_validation_required": total > 1,
        "note": "Split geometry fits the conservative build envelope by construction; seam/joint strength and final slicer orientation still require verification.",
    }


def apply_split(
    object_id: str,
    *,
    margin_mm: float = 8.0,
    max_pieces: int = 24,
    alignment_diameter_mm: float = 3.2,
    alignment_depth_mm: float = 8.0,
    branch_name: str | None = None,
    create_branch: bool = True,
) -> dict[str, Any]:
    assert _ORIGINAL_EXECUTE is not None
    source = core.object_by_id(str(object_id))
    plan = split_plan(
        source,
        margin_mm=margin_mm,
        max_pieces=max_pieces,
        alignment_diameter_mm=alignment_diameter_mm,
        alignment_depth_mm=alignment_depth_mm,
    )
    if not plan["split_required"]:
        raise ValueError("Selected part already fits the conservative P2S build envelope; no split is required")

    source_branch = core.ACTIVE_DESIGN
    source_snapshot = deepcopy(source)
    if create_branch:
        default_name = f"p2s-split-{str(source.get('name') or 'part').lower().replace(' ', '-')[:28]}"
        core.create_branch(branch_name or default_name, reason=f"Split {source.get('name') or object_id} for Bambu Lab P2S")
    elif core.DESIGNS.get(core.ACTIVE_DESIGN, {}).get("physical_verified") or str(core.DESIGNS.get(core.ACTIVE_DESIGN, {}).get("status") or "") in {"working", "working_in_real_life"}:
        # Never permit an in-place manufacturing split on a protected known-good branch.
        core.create_branch(branch_name or "p2s-split", reason=f"Protected baseline branched before P2S split of {source.get('name') or object_id}")

    split_branch = core.ACTIVE_DESIGN
    split_group = core.uid()
    source_in_branch = core.object_by_id(str(object_id))
    semantic = deepcopy(source_in_branch.get("semantic") or {})
    semantic.update({
        "manufacturing": "source_unsplit_reference",
        "split_group": split_group,
        "split_resource": "bambu-lab-p2s",
    })
    _ORIGINAL_EXECUTE(
        "update",
        {"id": object_id, "visible": False, "semantic": semantic},
        actor="forge-manufacturing",
        reason="Hide unsplit source after creating P2S manufacturing pieces",
    )

    created_ids: list[str] = []
    warnings: list[str] = []
    for row in plan["pieces"]:
        name = f"{source_snapshot.get('name') or 'Part'} — P2S {row['index']}/{plan['piece_count']}"
        piece_semantic = deepcopy(source_snapshot.get("semantic") or {})
        tags = {str(value) for value in piece_semantic.get("tags") or []}
        tags.update({"fabricated", "split-piece", "p2s"})
        piece_semantic.update({
            "role": str(piece_semantic.get("role") or "fabricated_part"),
            "tags": sorted(tags),
            "manufacturing": "fabricated",
            "manufacturing_resource": "bambu-lab-p2s",
            "split_group": split_group,
            "split_source_object_id": object_id,
            "split_piece_index": row["index"],
            "split_piece_count": plan["piece_count"],
            "joint_validation_required": True,
        })
        before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
        _ORIGINAL_EXECUTE(
            "add",
            {
                "name": name,
                "kind": "manufacturing_piece",
                "params": {
                    "source_snapshot": deepcopy(source_snapshot),
                    "clip_bounds_mm": deepcopy(row["clip_bounds_mm"]),
                    "split_group": split_group,
                    "split_piece_index": row["index"],
                },
                "material": source_snapshot.get("material", "abs"),
                "transform": _identity_transform(),
                "features": deepcopy(row.get("alignment_features") or []),
                "semantic": piece_semantic,
            },
            actor="forge-manufacturing",
            reason=f"Create P2S split piece {row['index']} of {plan['piece_count']}",
        )
        created = next(obj for obj in reversed(core.PROJECT.get("objects", [])) if str(obj.get("id")) not in before)
        created_ids.append(str(created["id"]))
        try:
            check = manufacturing.analyze_object(created, core.build_shape)
            if not check.get("fits_build_volume"):
                warnings.append(f"{name} did not pass the final P2S fit screen")
            if row.get("alignment_features"):
                without_features = deepcopy(created)
                without_features["features"] = []
                removed = float(core.build_shape(without_features).Volume()) - float(core.build_shape(created).Volume())
                if removed <= 0.05:
                    warnings.append(f"{name}: planned alignment sockets did not intersect the source solid; use a different joint location")
        except Exception as exc:
            warnings.append(f"{name}: post-split validation error: {exc}")

    _ORIGINAL_EXECUTE(
        "add_note",
        {
            "kind": "manufacturing_split",
            "title": f"P2S split: {source_snapshot.get('name') or object_id}",
            "split_group": split_group,
            "source_branch": source_branch,
            "split_branch": split_branch,
            "source_object_id": object_id,
            "piece_ids": created_ids,
            "resource_id": "bambu-lab-p2s",
            "plan": deepcopy(plan),
            "warnings": list(warnings),
            "text": "Oversized body split for P2S. Alignment sockets are assembly aids only; validate joint strength and slicer output before physical use.",
        },
        actor="forge-manufacturing",
        reason="Record P2S manufacturing split plan",
    )

    return {
        "source_branch": source_branch,
        "split_branch": split_branch,
        "source_object_id": object_id,
        "split_group": split_group,
        "piece_ids": created_ids,
        "plan": plan,
        "warnings": warnings,
        "physical_verification": False,
    }


def _execute(op: str, args: dict[str, Any] | None = None, actor: str = "human", reason: str = "") -> dict[str, Any]:
    assert _ORIGINAL_EXECUTE is not None
    if op != "split_for_manufacturing":
        return _ORIGINAL_EXECUTE(op, args, actor=actor, reason=reason)
    values = deepcopy(args or {})
    resource = str(values.get("resource_id") or "bambu-lab-p2s").lower()
    if resource not in {"bambu-lab-p2s", "p2s", "bambu", "bambu_p2s"}:
        raise ValueError(f"Unsupported manufacturing split resource: {resource}")
    object_id = str(values.get("id") or values.get("object_id") or "")
    if not object_id:
        raise ValueError("split_for_manufacturing requires id/object_id")
    result = apply_split(
        object_id,
        margin_mm=float(values.get("margin_mm", 8.0)),
        max_pieces=int(values.get("max_pieces", 24)),
        alignment_diameter_mm=float(values.get("alignment_diameter_mm", 3.2)),
        alignment_depth_mm=float(values.get("alignment_depth_mm", 8.0)),
        branch_name=str(values.get("branch_name")) if values.get("branch_name") else None,
        create_branch=bool(values.get("create_branch", True)),
    )
    return {"ok": True, "op": op, "split": result, "changed": list(result["piece_ids"])}


def install(legacy: Any) -> None:
    global _INSTALLED, _ORIGINAL_BASE_SHAPE, _ORIGINAL_APPLY_FEATURE, _ORIGINAL_IS_FABRICATED, _ORIGINAL_EXECUTE
    if _INSTALLED:
        return
    _ORIGINAL_BASE_SHAPE = core._base_shape
    _ORIGINAL_APPLY_FEATURE = core._apply_feature
    _ORIGINAL_IS_FABRICATED = manufacturing.is_fabricated_object
    _ORIGINAL_EXECUTE = core.execute
    core._base_shape = _manufacturing_piece_base_shape
    core._apply_feature = _split_feature
    manufacturing.is_fabricated_object = _is_fabricated
    core.execute = _execute

    # Keep a direct project method for the manufacturing UI/API while also exposing the
    # typed core operation so the local engineering agent can invoke the same audited path.
    legacy.PROJECT.split_for_p2s = MethodType(
        lambda self, object_id, **kwargs: apply_split(object_id, **kwargs),
        legacy.PROJECT,
    )

    app = legacy.app

    @app.post("/v2/manufacturing/p2s/split-plan", dependencies=[Depends(legacy.require_session)])
    async def p2s_split_plan(request: SplitPlanRequest) -> dict[str, Any]:
        try:
            obj = core.object_by_id(request.object_id)
            return split_plan(
                obj,
                margin_mm=request.margin_mm,
                max_pieces=request.max_pieces,
                alignment_diameter_mm=request.alignment_diameter_mm,
                alignment_depth_mm=request.alignment_depth_mm,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v2/manufacturing/p2s/split", dependencies=[Depends(legacy.require_session)])
    async def p2s_split(request: SplitApplyRequest) -> dict[str, Any]:
        try:
            result = apply_split(
                request.object_id,
                margin_mm=request.margin_mm,
                max_pieces=request.max_pieces,
                alignment_diameter_mm=request.alignment_diameter_mm,
                alignment_depth_mm=request.alignment_depth_mm,
                branch_name=request.branch_name,
                create_branch=request.create_branch,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = legacy.PROJECT.snapshot()
        await legacy.broadcast({"type": "project.updated", "project": snapshot})
        return {"split": result, "project": snapshot, "manufacturing": manufacturing.p2s_status(core.PROJECT, core.build_shape)}

    _INSTALLED = True
