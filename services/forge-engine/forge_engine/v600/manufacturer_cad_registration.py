from __future__ import annotations

"""Validated manufacturer STEP -> ForgeCAD canonical frame registration.

ForgeCAD must not center a purchased-component STEP by the whole assembly's
bounding box: asymmetric connectors and pins make that frame physically
meaningless. This module registers selected manufacturer assets against explicit
mechanical datums and fails closed when the expected evidence cannot be found.

Controlled external-validation scope:
- Raspberry Pi 5: published 85 x 56 mm PCB outline + PCB underside mount plane.
- Pololu D24V50F5: the two published mounting-hole axes + their underside plane.

Registration is rigid translation only. No scaling or geometry repair is allowed.
"""

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import cadquery as cq
import numpy as np

from ..v110 import realistic_components


PI5_ID = "compute.raspberry_pi_5_8gb"
POLOLU_D24V50F5_ID = "power.pololu.d24v50f5"

_ORIGINAL_STEP_PARTS = realistic_components._step_parts
_ORIGINAL_GEOMETRY_STATUS = realistic_components.geometry_status
_INSTALLED = False
_TRUTH: dict[str, dict[str, Any]] = {}
_REGISTRATION_EVIDENCE: dict[str, dict[str, Any]] = {}
_REGISTRATION_FAILURES: dict[str, str] = {}


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


def _vec(point: Any) -> np.ndarray:
    return np.asarray(point.toTuple() if hasattr(point, "toTuple") else point, dtype=float)


def _unit(vector: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(vector))
    if n < 1e-12:
        raise ValueError("Cannot normalize a zero vector")
    return vector / n


def _translate(shape, translation: np.ndarray):
    return shape.translate(tuple(float(value) for value in translation))


def _palette(component_id: str) -> list[str]:
    if component_id == POLOLU_D24V50F5_ID:
        return ["#1766a6", "#202428", "#c8cdd1", "#d5a52a", "#5e646a"]
    if component_id == PI5_ID:
        return ["#16813e", "#202428", "#b7bec5", "#d5a52a", "#e4ded1", "#555b61"]
    return ["#aeb7c2", "#24292d", "#16813e", "#d5a52a", "#d9dde1", "#697077"]


def _parts_from_shape(component_id: str, shape):
    try:
        solids = list(shape.Solids())
    except Exception:
        solids = []
    if not solids:
        solids = [shape]
    palette = _palette(component_id)
    return [(solid, palette[index % len(palette)]) for index, solid in enumerate(solids)]


def _circle_records(shape, diameter_mm: float, tolerance_mm: float = 0.12) -> list[dict[str, Any]]:
    target_radius = float(diameter_mm) / 2.0
    rows: list[dict[str, Any]] = []
    for edge in shape.Edges():
        try:
            if edge.geomType() != "CIRCLE" or abs(float(edge.radius()) - target_radius) > tolerance_mm:
                continue
            center = _vec(edge.Center())
            p0 = _vec(edge.positionAt(0.0))
            p1 = _vec(edge.positionAt(0.25))
            p2 = _vec(edge.positionAt(0.5))
            normal = _unit(np.cross(p1 - p0, p2 - p0))
            rows.append(
                {
                    "center_mm": center,
                    "radius_mm": float(edge.radius()),
                    "normal": normal,
                }
            )
        except Exception:
            continue
    return rows


def _hole_axes(shape, diameter_mm: float, *, max_span_mm: float = 6.0) -> list[dict[str, Any]]:
    circles = _circle_records(shape, diameter_mm)
    axes: list[dict[str, Any]] = []
    for index, a in enumerate(circles):
        ca = a["center_mm"]
        na = a["normal"]
        for b in circles[index + 1 :]:
            cb = b["center_mm"]
            nb = b["normal"]
            if abs(float(np.dot(na, nb))) < 0.995:
                continue
            delta = cb - ca
            axial_signed = float(np.dot(delta, na))
            axial = abs(axial_signed)
            lateral = float(np.linalg.norm(delta - na * axial_signed))
            if axial < 0.2 or axial > max_span_mm or lateral > 0.05:
                continue
            midpoint = (ca + cb) / 2.0
            axis = na if axial_signed >= 0 else -na
            z_values = [float(ca[2]), float(cb[2])]
            row = {
                "center_mm": midpoint,
                "axis": _unit(axis),
                "span_mm": axial,
                "plane_low_z_mm": min(z_values),
                "plane_high_z_mm": max(z_values),
                "radius_mm": (float(a["radius_mm"]) + float(b["radius_mm"])) / 2.0,
            }
            if any(float(np.linalg.norm(midpoint - existing["center_mm"])) < 0.05 for existing in axes):
                continue
            axes.append(row)
    axes.sort(key=lambda row: tuple(round(float(value), 6) for value in row["center_mm"]))
    return axes


def _find_pi_board(shape, truth: dict[str, Any]):
    source = truth["source_dimensions"]
    target_x = float(source["board_x_mm"])
    target_y = float(source["board_y_mm"])
    candidates: list[tuple[float, float, Any, dict[str, float]]] = []
    for solid in shape.Solids():
        b = _bounds(solid)
        direct_error = abs(b["xlen"] - target_x) + abs(b["ylen"] - target_y)
        if direct_error > 0.25 or b["zlen"] <= 0.2 or b["zlen"] > 4.0:
            continue
        candidates.append((direct_error, -abs(float(solid.Volume())), solid, b))
    if not candidates:
        raise ValueError("Raspberry Pi STEP does not expose a PCB solid matching the published 85 x 56 mm outline")
    candidates.sort(key=lambda row: (row[0], row[1]))
    if len(candidates) > 1 and abs(candidates[1][0] - candidates[0][0]) < 1e-6 and abs(candidates[1][1] - candidates[0][1]) < 1e-3:
        raise ValueError("Raspberry Pi STEP exposes an ambiguous PCB datum solid")
    return candidates[0][2], candidates[0][3]


def _witness_overlap(shape, x: float, y: float, z_center: float, height_mm: float, radius_mm: float = 0.30) -> float:
    witness = cq.Workplane("XY").workplane(offset=float(z_center) - float(height_mm) / 2.0).center(float(x), float(y)).circle(float(radius_mm)).extrude(float(height_mm)).val()
    return abs(float(shape.intersect(witness).Volume()))


def _register_pi(shape, truth: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    board, raw_board = _find_pi_board(shape, truth)
    canonical_mount_z = float(truth["canonical_mount_plane_z_mm"])
    translation = np.array([-raw_board["cx"], -raw_board["cy"], canonical_mount_z - raw_board["zmin"]], dtype=float)
    registered = _translate(shape, translation)
    registered_board = _translate(board, translation)
    board_bounds = _bounds(registered_board)

    source = truth["source_dimensions"]
    expected_x = float(source["board_x_mm"])
    expected_y = float(source["board_y_mm"])
    if abs(board_bounds["xmin"] + expected_x / 2.0) > 0.02 or abs(board_bounds["xmax"] - expected_x / 2.0) > 0.02:
        raise ValueError("Registered Raspberry Pi PCB X datum does not match published outline")
    if abs(board_bounds["ymin"] + expected_y / 2.0) > 0.02 or abs(board_bounds["ymax"] - expected_y / 2.0) > 0.02:
        raise ValueError("Registered Raspberry Pi PCB Y datum does not match published outline")
    if abs(board_bounds["zmin"] - canonical_mount_z) > 0.02:
        raise ValueError("Registered Raspberry Pi PCB underside does not match canonical mount plane")

    hole_checks: list[dict[str, Any]] = []
    witness_height = max(4.0, board_bounds["zlen"] + 2.0)
    z_center = (board_bounds["zmin"] + board_bounds["zmax"]) / 2.0
    for index, center in enumerate(truth["hole_centers_mm"]):
        x, y = float(center[0]), float(center[1])
        overlap = _witness_overlap(registered_board, x, y, z_center, witness_height)
        if overlap > 1e-6:
            raise ValueError(f"Registered Raspberry Pi manufacturer PCB is not open at published mount hole {index}")
        material_witness = _witness_overlap(registered_board, x + 2.0, y, z_center, witness_height, radius_mm=0.20)
        if material_witness <= 1e-6:
            raise ValueError(f"Raspberry Pi mount-hole witness {index} is not locally discriminating")
        hole_checks.append({"pattern_index": index, "center_mm": [x, y], "open_overlap_mm3": overlap, "offset_material_overlap_mm3": material_witness})

    return registered, {
        "validated": True,
        "component_id": PI5_ID,
        "strategy": "published_pcb_outline_and_underside",
        "rigid_transform": {"rotation_deg": [0.0, 0.0, 0.0], "translation_mm": [float(v) for v in translation]},
        "raw_board_bounds_mm": raw_board,
        "registered_board_bounds_mm": board_bounds,
        "canonical_mount_plane_z_mm": canonical_mount_z,
        "board_thickness_mm": board_bounds["zlen"],
        "hole_witnesses": hole_checks,
        "external_validation_scope": "PCB outline, mount plane, and published mount-hole openings",
    }


def _select_pololu_mount_axes(shape, truth: dict[str, Any]) -> list[dict[str, Any]]:
    axes = _hole_axes(shape, float(truth["hole_diameter_mm"]))
    if len(axes) != 2:
        raise ValueError(f"Pololu STEP must expose exactly two published-diameter through-hole axes; found {len(axes)}")
    a = axes[0]["center_mm"]
    b = axes[1]["center_mm"]
    delta = np.abs(b[:2] - a[:2])
    target = np.asarray(truth["pattern_mm"], dtype=float)
    tolerance = float(truth.get("drill_location_tolerance_mm") or 0.1)
    if float(np.max(np.abs(delta - target))) > tolerance:
        raise ValueError(f"Pololu STEP mount-axis spacing {delta.tolist()} exceeds published tolerance around {target.tolist()}")
    return axes


def _register_pololu(shape, truth: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    axes = _select_pololu_mount_axes(shape, truth)
    centers = np.asarray([row["center_mm"] for row in axes], dtype=float)
    xy_midpoint = centers[:, :2].mean(axis=0)
    mount_plane_raw_z = min(float(row["plane_low_z_mm"]) for row in axes)
    canonical_mount_z = float(truth["canonical_mount_plane_z_mm"])
    translation = np.array([-xy_midpoint[0], -xy_midpoint[1], canonical_mount_z - mount_plane_raw_z], dtype=float)
    registered = _translate(shape, translation)

    nominal = np.asarray([[float(row[0]), float(row[1])] for row in truth["hole_centers_mm"]], dtype=float)
    transformed_xy = centers[:, :2] + translation[:2]
    # Two diagonal points can arrive in either order; choose the lower total residual.
    direct = np.linalg.norm(transformed_xy - nominal, axis=1)
    reverse = np.linalg.norm(transformed_xy[::-1] - nominal, axis=1)
    if float(reverse.sum()) < float(direct.sum()):
        transformed_xy = transformed_xy[::-1]
        residuals = reverse
    else:
        residuals = direct
    tolerance = float(truth.get("drill_location_tolerance_mm") or 0.1)
    max_residual = float(np.max(residuals))
    if max_residual > tolerance:
        raise ValueError(f"Registered Pololu mount centers differ from published nominal by {max_residual:.4f} mm > {tolerance:.4f} mm")

    registered_bounds = _bounds(registered)
    return registered, {
        "validated": True,
        "component_id": POLOLU_D24V50F5_ID,
        "strategy": "published_mount_axes_and_underside",
        "rigid_transform": {"rotation_deg": [0.0, 0.0, 0.0], "translation_mm": [float(v) for v in translation]},
        "raw_mount_centers_mm": [[float(v) for v in row] for row in centers],
        "registered_mount_centers_xy_mm": [[float(v) for v in row] for row in transformed_xy],
        "nominal_mount_centers_xy_mm": nominal.tolist(),
        "mount_center_residuals_mm": [float(v) for v in residuals],
        "max_mount_center_residual_mm": max_residual,
        "drill_location_tolerance_mm": tolerance,
        "canonical_mount_plane_z_mm": canonical_mount_z,
        "registered_bounds_mm": registered_bounds,
        "external_validation_scope": "mount-hole axes, mount plane, and rigid XY datum",
    }


def register_shape(component_id: str, shape) -> tuple[Any, dict[str, Any]]:
    truth = _TRUTH.get(component_id)
    if truth is None:
        raise KeyError(component_id)
    if component_id == PI5_ID:
        return _register_pi(shape, truth)
    if component_id == POLOLU_D24V50F5_ID:
        return _register_pololu(shape, truth)
    raise KeyError(component_id)


def _registered_step_parts(component_id: str, path: Path):
    if component_id not in _TRUTH:
        return _ORIGINAL_STEP_PARTS(component_id, path)
    imported = cq.importers.importStep(str(path)).val()
    try:
        registered, evidence = register_shape(component_id, imported)
        evidence = {**evidence, "asset": str(path), "asset_bytes": int(path.stat().st_size)}
        _REGISTRATION_EVIDENCE[component_id] = evidence
        _REGISTRATION_FAILURES.pop(component_id, None)
        return _parts_from_shape(component_id, registered)
    except Exception as exc:
        _REGISTRATION_EVIDENCE.pop(component_id, None)
        _REGISTRATION_FAILURES[component_id] = str(exc)
        raise


def ensure_registration(component_id: str, path: Path | None = None) -> dict[str, Any]:
    if component_id not in _TRUTH:
        raise KeyError(component_id)
    cached = _REGISTRATION_EVIDENCE.get(component_id)
    if cached and cached.get("validated"):
        return deepcopy(cached)
    path = path or realistic_components.resolve_step(component_id, allow_download=False)
    if path is None:
        raise FileNotFoundError(f"No manufacturer STEP is cached for {component_id}")
    _registered_step_parts(component_id, path)
    return deepcopy(_REGISTRATION_EVIDENCE[component_id])


def registration_evidence(component_id: str) -> dict[str, Any] | None:
    row = _REGISTRATION_EVIDENCE.get(component_id)
    return deepcopy(row) if row else None


def registration_failure(component_id: str) -> str | None:
    return _REGISTRATION_FAILURES.get(component_id)


def _registered_geometry_status(obj: dict[str, Any], component: dict[str, Any] | None = None) -> dict[str, Any]:
    base = _ORIGINAL_GEOMETRY_STATUS(obj, component)
    component = component or {}
    component_id = str(obj.get("component_ref") or component.get("id") or "")
    if component_id not in _TRUTH:
        return base
    step = realistic_components.resolve_step(component_id, allow_download=False)
    if step is None:
        return {**base, "registration_required": True, "registration_validated": False, "registration_evidence": None}
    try:
        evidence = ensure_registration(component_id, step)
    except Exception as exc:
        return {
            **base,
            "resolved": False,
            "fallback": True,
            "registration_required": True,
            "registration_validated": False,
            "registration_error": str(exc),
            "registration_evidence": None,
        }
    return {
        **base,
        "resolved": True,
        "fallback": False,
        "registration_required": True,
        "registration_validated": True,
        "registration_evidence": evidence,
    }


def install(truth: dict[str, dict[str, Any]]) -> dict[str, Any]:
    global _INSTALLED, _TRUTH
    _TRUTH = truth
    if not _INSTALLED:
        realistic_components._step_parts = _registered_step_parts
        realistic_components.geometry_status = _registered_geometry_status
        _INSTALLED = True
    return summary()


def summary() -> dict[str, Any]:
    return {
        "installed": _INSTALLED,
        "registered_component_ids": sorted(component_id for component_id, row in _REGISTRATION_EVIDENCE.items() if row.get("validated")),
        "registration_failures": deepcopy(_REGISTRATION_FAILURES),
        "strategy": "manufacturer datum rigid registration; no assembly-bounding-box centering, scaling, or repair",
    }
