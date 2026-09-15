from __future__ import annotations

"""External manufacturer-CAD frame probe used to derive validated registration.

This is intentionally diagnostic rather than a production registration routine.
It downloads the same manufacturer STEP assets ForgeCAD can resolve, inspects the
raw (un-centered) B-rep and reports circular edges matching the published mount
hole diameters. The resulting evidence is used to replace unsafe whole-assembly
bounding-box centering with a datum-backed registration contract.
"""

import json
import math
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

    # Deduplicate repeated edge-pair representations of the same cylindrical hole.
    unique: list[dict[str, Any]] = []
    for row in candidates:
        center = np.asarray(row["center_mm"], dtype=float)
        if any(float(np.linalg.norm(center - np.asarray(other["center_mm"], dtype=float))) < 0.05 for other in unique):
            continue
        unique.append(row)
    unique.sort(key=lambda row: tuple(round(float(v), 6) for v in row["center_mm"]))
    return unique


def probe_component(component_id: str) -> dict[str, Any]:
    truth = MANUFACTURER_MOUNT_TRUTH[component_id]
    path = realistic_components.download_step(component_id, force=True)
    imported = cq.importers.importStep(str(path)).val()
    bb = imported.BoundingBox()
    circles = _matching_circles(imported, float(truth["hole_diameter_mm"]))
    lines = _paired_centerlines(circles)
    return {
        "component_id": component_id,
        "asset": str(path),
        "asset_bytes": path.stat().st_size,
        "raw_bounds_mm": {
            "xmin": float(bb.xmin), "xmax": float(bb.xmax),
            "ymin": float(bb.ymin), "ymax": float(bb.ymax),
            "zmin": float(bb.zmin), "zmax": float(bb.zmax),
            "xlen": float(bb.xlen), "ylen": float(bb.ylen), "zlen": float(bb.zlen),
        },
        "published_hole_diameter_mm": float(truth["hole_diameter_mm"]),
        "published_pattern_mm": truth["pattern_mm"],
        "matching_circle_edges": circles,
        "candidate_hole_centerlines": lines,
        "matching_circle_count": len(circles),
        "candidate_centerline_count": len(lines),
    }


def run() -> dict[str, Any]:
    results = [probe_component(PI5_ID), probe_component(POLOLU_D24V50F5_ID)]
    if any(row["candidate_centerline_count"] < len(MANUFACTURER_MOUNT_TRUTH[row["component_id"]]["hole_centers_mm"]) for row in results):
        raise AssertionError(f"Manufacturer STEP did not expose enough published mount-hole centerlines: {results}")
    return {"ok": True, "results": results}


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
