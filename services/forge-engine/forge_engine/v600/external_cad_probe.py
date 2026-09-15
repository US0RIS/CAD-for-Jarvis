from __future__ import annotations

"""External manufacturer-CAD frame probe used to derive validated registration.

This is intentionally diagnostic rather than a production registration routine.
It downloads the same manufacturer STEP assets ForgeCAD can resolve, inspects the
raw (un-centered) B-rep and reports both published-diameter circular edges and
thin solids matching the manufacturer's PCB outline. The evidence is used to
replace unsafe whole-assembly bounding-box centering with a datum-backed frame.
"""

import json
from typing import Any

import numpy as np
import cadquery as cq

from ..v110 import realistic_components
from .manufacturer_truth import MANUFACTURER_MOUNT_TRUTH, PI5_ID, POLOLU_D24V50F5_ID


def _vec(point: Any) -> np.ndarray:
    return np.asarray(point.toTuple() if hasattr(point, "toTuple") else point, dtype=float)


def _unit(vector: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(vector))
    return vector / n if n > 1e-12 else vector


def _bounds(shape) -> dict[str, float]:
    bb = shape.BoundingBox()
    return {
        "xmin": float(bb.xmin), "xmax": float(bb.xmax),
        "ymin": float(bb.ymin), "ymax": float(bb.ymax),
        "zmin": float(bb.zmin), "zmax": float(bb.zmax),
        "xlen": float(bb.xlen), "ylen": float(bb.ylen), "zlen": float(bb.zlen),
        "cx": float((bb.xmin + bb.xmax) / 2.0),
        "cy": float((bb.ymin + bb.ymax) / 2.0),
        "cz": float((bb.zmin + bb.zmax) / 2.0),
    }


def _circle_record(edge) -> dict[str, Any]:
    center = _vec(edge.Center())
    p0 = _vec(edge.positionAt(0.0))
    p1 = _vec(edge.positionAt(0.25))
    p2 = _vec(edge.positionAt(0.5))
    normal = _unit(np.cross(p1 - p0, p2 - p0))
    return {
        "center_mm": [float(x) for x in center],
        "radius_mm": float(edge.radius()),
        "normal": [float(x) for x in normal],
    }


def _matching_circles(shape, diameter_mm: float, tolerance_mm: float = 0.12) -> list[dict[str, Any]]:
    radius = float(diameter_mm) / 2.0
    rows = []
    for edge in shape.Edges():
        try:
            if edge.geomType() != "CIRCLE":
                continue
            if abs(float(edge.radius()) - radius) > tolerance_mm:
                continue
            rows.append(_circle_record(edge))
        except Exception:
            continue
    rows.sort(key=lambda row: tuple(round(float(v), 6) for v in row["center_mm"]))
    return rows


def _paired_centerlines(circles: list[dict[str, Any]], max_span_mm: float = 6.0) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for i, a in enumerate(circles):
        ca = np.asarray(a["center_mm"], dtype=float)
        na = _unit(np.asarray(a["normal"], dtype=float))
        for b in circles[i + 1 :]:
            cb = np.asarray(b["center_mm"], dtype=float)
            nb = _unit(np.asarray(b["normal"], dtype=float))
            if abs(float(np.dot(na, nb))) < 0.995:
                continue
            delta = cb - ca
            axial = abs(float(np.dot(delta, na)))
            lateral = float(np.linalg.norm(delta - na * float(np.dot(delta, na))))
            if axial < 0.2 or axial > max_span_mm or lateral > 0.05:
                continue
            midpoint = (ca + cb) / 2.0
            candidates.append(
                {
                    "center_mm": [float(x) for x in midpoint],
                    "axis": [float(x) for x in na],
                    "span_mm": axial,
                    "radius_mm": (float(a["radius_mm"]) + float(b["radius_mm"])) / 2.0,
                }
            )

    unique: list[dict[str, Any]] = []
    for row in candidates:
        center = np.asarray(row["center_mm"], dtype=float)
        if any(float(np.linalg.norm(center - np.asarray(other["center_mm"], dtype=float))) < 0.05 for other in unique):
            continue
        unique.append(row)
    unique.sort(key=lambda row: tuple(round(float(v), 6) for v in row["center_mm"]))
    return unique


def _board_solid_candidates(shape, truth: dict[str, Any]) -> list[dict[str, Any]]:
    source = truth.get("source_dimensions") or {}
    expected_x = float(source.get("board_x_mm") or 0.0)
    expected_y = float(source.get("board_y_mm") or 0.0)
    rows: list[dict[str, Any]] = []
    for index, solid in enumerate(shape.Solids()):
        try:
            b = _bounds(solid)
            direct_error = abs(b["xlen"] - expected_x) + abs(b["ylen"] - expected_y)
            swapped_error = abs(b["xlen"] - expected_y) + abs(b["ylen"] - expected_x)
            xy_error = min(direct_error, swapped_error)
            if xy_error > 3.0 or min(b["xlen"], b["ylen"]) < 10.0 or b["zlen"] > 4.0:
                continue
            rows.append(
                {
                    "solid_index": index,
                    "bounds_mm": b,
                    "volume_mm3": abs(float(solid.Volume())),
                    "xy_dimension_error_mm": float(xy_error),
                    "axis_assignment": "xy" if direct_error <= swapped_error else "yx",
                    "matching_circle_edges": _matching_circles(solid, float(truth["hole_diameter_mm"])),
                }
            )
        except Exception:
            continue
    rows.sort(key=lambda row: (row["xy_dimension_error_mm"], -row["volume_mm3"]))
    return rows[:8]


def probe_component(component_id: str) -> dict[str, Any]:
    truth = MANUFACTURER_MOUNT_TRUTH[component_id]
    path = realistic_components.download_step(component_id, force=True)
    imported = cq.importers.importStep(str(path)).val()
    circles = _matching_circles(imported, float(truth["hole_diameter_mm"]))
    lines = _paired_centerlines(circles)
    boards = _board_solid_candidates(imported, truth)
    return {
        "component_id": component_id,
        "asset": str(path),
        "asset_bytes": path.stat().st_size,
        "raw_bounds_mm": _bounds(imported),
        "published_hole_diameter_mm": float(truth["hole_diameter_mm"]),
        "published_pattern_mm": truth["pattern_mm"],
        "matching_circle_edges": circles,
        "candidate_hole_centerlines": lines,
        "matching_circle_count": len(circles),
        "candidate_centerline_count": len(lines),
        "board_solid_candidates": boards,
        "board_solid_candidate_count": len(boards),
    }


def run() -> dict[str, Any]:
    results = [probe_component(PI5_ID), probe_component(POLOLU_D24V50F5_ID)]
    if any(row["board_solid_candidate_count"] < 1 for row in results):
        raise AssertionError(f"Manufacturer STEP did not expose a PCB solid matching published board dimensions: {results}")
    return {"ok": True, "results": results}


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
