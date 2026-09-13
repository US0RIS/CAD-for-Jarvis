from __future__ import annotations

"""Higher-fidelity additive-manufacturing screening for ForgeCAD 2.0.

Bambu Studio remains authoritative for slicing. ForgeCAD performs cheap deterministic
geometry screening first so the design agent can react before handoff:

- evaluates all 24 right-handed orthogonal orientations;
- estimates unsupported downward-facing projected area from the actual tessellated mesh;
- recommends the lowest-support orientation that fits the P2S envelope;
- performs conservative rectangular shelf packing to estimate a minimum practical plate
  layout before Bambu Studio's real arrangement pass;
- reports a solid-material mass estimate only when the print material is known.

These are screening calculations, not substitutes for slicer support generation or
real print validation.
"""

import itertools
import math
from copy import deepcopy
from typing import Any, Callable

from ..v110 import core
from . import manufacturing


_INSTALLED = False
_ORIGINAL_ANALYZE: Callable[..., dict[str, Any]] | None = None
_ORIGINAL_STATUS: Callable[..., dict[str, Any]] | None = None

_DENSITY_G_CM3 = {
    "pla": 1.24,
    "petg": 1.27,
    "abs": 1.04,
    "asa": 1.07,
    "pa12": 1.01,
    "nylon": 1.14,
    "tpu": 1.21,
    "pc": 1.20,
}


def _det3(matrix: list[list[int]]) -> int:
    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _orientations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    axis_names = ("X", "Y", "Z")
    for perm in itertools.permutations((0, 1, 2)):
        for signs in itertools.product((-1, 1), repeat=3):
            matrix = [[0, 0, 0] for _ in range(3)]
            for out_axis in range(3):
                matrix[out_axis][perm[out_axis]] = signs[out_axis]
            if _det3(matrix) != 1:
                continue
            label = ", ".join(
                f"{axis_names[out_axis]}={'+' if signs[out_axis] > 0 else '-'}{axis_names[perm[out_axis]]}"
                for out_axis in range(3)
            )
            rows.append({"matrix": matrix, "label": label})
    return rows


_ORIENTATIONS = _orientations()


def _transform(point: list[float] | tuple[float, float, float], matrix: list[list[int]]) -> tuple[float, float, float]:
    return tuple(sum(float(point[col]) * matrix[row][col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _mesh_orientation_screen(mesh: dict[str, Any], build_volume: list[float]) -> dict[str, Any] | None:
    positions = mesh.get("positions") or []
    triangles = mesh.get("triangles") or []
    if not positions or not triangles:
        return None
    threshold = -math.cos(math.radians(45.0))
    evaluations: list[dict[str, Any]] = []

    for orientation in _ORIENTATIONS:
        matrix = orientation["matrix"]
        transformed = [_transform(point, matrix) for point in positions]
        mins = [min(point[axis] for point in transformed) for axis in range(3)]
        maxs = [max(point[axis] for point in transformed) for axis in range(3)]
        bounds = [maxs[axis] - mins[axis] for axis in range(3)]
        fits = all(bounds[axis] <= float(build_volume[axis]) + 1e-6 for axis in range(3))
        support_area = 0.0
        overhang_count = 0
        surface_area = 0.0

        for tri in triangles:
            if len(tri) < 3:
                continue
            try:
                p0, p1, p2 = (transformed[int(tri[0])], transformed[int(tri[1])], transformed[int(tri[2])])
            except (IndexError, TypeError, ValueError):
                continue
            edge1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
            edge2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
            normal = _cross(edge1, edge2)
            norm = math.sqrt(sum(value * value for value in normal))
            if norm <= 1e-12:
                continue
            area = norm * 0.5
            nz = normal[2] / norm
            surface_area += area
            if nz < threshold:
                overhang_count += 1
                support_area += area * abs(nz)

        evaluations.append({
            "label": orientation["label"],
            "matrix": matrix,
            "bounds_mm": [round(value, 4) for value in bounds],
            "fits": fits,
            "estimated_support_area_mm2": round(support_area, 3),
            "overhang_triangles": overhang_count,
            "surface_area_mm2": round(surface_area, 3),
            "footprint_mm2": round(bounds[0] * bounds[1], 3),
        })

    fitting = [row for row in evaluations if row["fits"]]
    if not fitting:
        return {"recommended": None, "evaluated_orientations": len(evaluations)}
    fitting.sort(key=lambda row: (row["estimated_support_area_mm2"], row["footprint_mm2"], row["bounds_mm"][2], row["label"]))
    best = deepcopy(fitting[0])
    return {
        "recommended": best,
        "evaluated_orientations": len(evaluations),
        "method": "24-orientation mesh overhang screening",
        "overhang_threshold_deg": 45.0,
        "limitations": [
            "Projected downward-facing area is a support-risk proxy, not a slicer support tree calculation.",
            "Only right-handed orthogonal orientations are screened; Bambu Studio may find a better arbitrary-angle orientation.",
            "Bridge span, self-occlusion, support interface quality, and anisotropic strength require slicer/physical verification.",
        ],
    }


def _material_density(obj: dict[str, Any], base: dict[str, Any]) -> tuple[str | None, float | None]:
    material = base.get("material") if isinstance(base.get("material"), dict) else {}
    requested = str(material.get("requested_filament") or "").strip().lower()
    design = str(material.get("design_material") or obj.get("material") or "").strip().lower()
    for value in (requested, design):
        for token, density in _DENSITY_G_CM3.items():
            if token in value:
                return token, density
    return None, None


def _analyze_object(obj: dict[str, Any], build_shape: Callable[[dict[str, Any]], Any], *, printer: dict[str, Any] = manufacturing.P2S_PROFILE) -> dict[str, Any]:
    assert _ORIGINAL_ANALYZE is not None
    base = _ORIGINAL_ANALYZE(obj, build_shape, printer=printer)
    if not base.get("eligible"):
        return base

    try:
        mesh = core.tessellate(obj, tolerance=1.0)
        orientation = _mesh_orientation_screen(mesh, [float(value) for value in printer["build_volume_mm"]])
    except Exception as exc:
        orientation = {"recommended": None, "evaluated_orientations": 0, "error": str(exc)}

    base["orientation_analysis"] = orientation
    recommended = orientation.get("recommended") if isinstance(orientation, dict) else None
    if isinstance(recommended, dict):
        base["recommended_orientation"] = recommended["label"]
        base["recommended_orientation_matrix"] = recommended["matrix"]
        base["recommended_bounds_mm"] = recommended["bounds_mm"]
        base["estimated_support_area_mm2"] = recommended["estimated_support_area_mm2"]
        base["overhang_triangles"] = recommended["overhang_triangles"]
    else:
        base["recommended_orientation"] = None
        base["recommended_bounds_mm"] = base.get("bounds_mm")

    filament, density = _material_density(obj, base)
    volume = base.get("volume_mm3")
    base["solid_material_estimate"] = {
        "filament": filament,
        "density_g_cm3": density,
        "mass_g": round(float(volume) / 1000.0 * density, 2) if density is not None and isinstance(volume, (int, float)) else None,
        "note": "Solid-volume estimate excludes infill, shells, supports, purge, and slicer process effects.",
    }
    return base


def _pack_rectangles(parts: list[dict[str, Any]], build_volume: list[float], spacing_mm: float = 6.0) -> dict[str, Any]:
    bed_x, bed_y = float(build_volume[0]), float(build_volume[1])
    packable: list[tuple[dict[str, Any], float, float]] = []
    unplaced: list[str] = []
    for part in parts:
        bounds = part.get("recommended_bounds_mm") or part.get("bounds_mm")
        if not part.get("eligible") or not part.get("fits_build_volume") or not isinstance(bounds, list) or len(bounds) != 3:
            unplaced.append(str(part.get("id") or ""))
            continue
        width, depth = float(bounds[0]), float(bounds[1])
        if width > bed_x or depth > bed_y:
            unplaced.append(str(part.get("id") or ""))
            continue
        packable.append((part, width, depth))
    packable.sort(key=lambda row: (max(row[1], row[2]), row[1] * row[2]), reverse=True)

    plates: list[dict[str, Any]] = []
    for part, width, depth in packable:
        placed = False
        for plate in plates:
            shelves = plate["_shelves"]
            for shelf in shelves:
                if depth <= shelf["height"] + 1e-6 and shelf["x"] + width <= bed_x + 1e-6:
                    x, y = shelf["x"], shelf["y"]
                    shelf["x"] += width + spacing_mm
                    plate["parts"].append({"id": part["id"], "name": part["name"], "x_mm": round(x, 3), "y_mm": round(y, 3), "width_mm": round(width, 3), "depth_mm": round(depth, 3), "orientation": part.get("recommended_orientation")})
                    placed = True
                    break
            if placed:
                break
            next_y = max((shelf["y"] + shelf["height"] + spacing_mm for shelf in shelves), default=0.0)
            if next_y + depth <= bed_y + 1e-6:
                shelves.append({"y": next_y, "height": depth, "x": width + spacing_mm})
                plate["parts"].append({"id": part["id"], "name": part["name"], "x_mm": 0.0, "y_mm": round(next_y, 3), "width_mm": round(width, 3), "depth_mm": round(depth, 3), "orientation": part.get("recommended_orientation")})
                placed = True
                break
        if not placed:
            plates.append({"index": len(plates) + 1, "parts": [{"id": part["id"], "name": part["name"], "x_mm": 0.0, "y_mm": 0.0, "width_mm": round(width, 3), "depth_mm": round(depth, 3), "orientation": part.get("recommended_orientation")}], "_shelves": [{"y": 0.0, "height": depth, "x": width + spacing_mm}]})

    for plate in plates:
        used = sum(float(row["width_mm"]) * float(row["depth_mm"]) for row in plate["parts"])
        plate["used_footprint_mm2"] = round(used, 2)
        plate["bed_utilization"] = round(used / max(bed_x * bed_y, 1e-9), 4)
        plate.pop("_shelves", None)

    return {
        "method": "conservative rectangular shelf packing",
        "spacing_mm": spacing_mm,
        "plate_count": len(plates),
        "plates": plates,
        "unplaced_object_ids": unplaced,
        "all_packable": not unplaced,
        "authoritative_arrangement": False,
        "note": "Bambu Studio arrangement and collision/support checks remain authoritative.",
    }


def _p2s_status(project: dict[str, Any], build_shape: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
    assert _ORIGINAL_STATUS is not None
    status = _ORIGINAL_STATUS(project, build_shape)
    packing = _pack_rectangles(status.get("parts") or [], status["resource"]["build_volume_mm"])
    status["plate_packing"] = packing
    status["estimated_plate_count"] = packing["plate_count"] if packing["all_packable"] else None
    status["packing_status"] = "forgecad-screened" if packing["all_packable"] else "requires-redesign-or-split"
    status["bambu_studio_arrangement_required"] = True
    return status


def install() -> None:
    global _INSTALLED, _ORIGINAL_ANALYZE, _ORIGINAL_STATUS
    if _INSTALLED:
        return
    _ORIGINAL_ANALYZE = manufacturing.analyze_object
    _ORIGINAL_STATUS = manufacturing.p2s_status
    manufacturing.analyze_object = _analyze_object
    manufacturing.p2s_status = _p2s_status
    _INSTALLED = True
