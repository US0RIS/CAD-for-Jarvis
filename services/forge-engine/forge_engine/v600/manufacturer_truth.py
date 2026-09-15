from __future__ import annotations

"""Manufacturer-derived mounting truth for ForgeCAD 6.0.

A spacing tuple is not a complete mounting definition when its datum is unknown.
This module installs explicit, provenance-bearing mounting coordinates for real
purchased components whose manufacturers publish the required geometry.

The overlay is intentionally applied to the source registries *and then* the
component registry is rebuilt, so later reloads preserve the corrected truth.
It also keeps deterministic offline parametric geometry consistent with the
same coordinates used by canonical component snapshots.
"""

from copy import deepcopy
from typing import Any

import cadquery as cq

from ..v110 import component_registry as registry
from ..v110 import curated_catalog, physical_components, realistic_components


PI5_ID = "compute.raspberry_pi_5_8gb"
POLOLU_D24V50F5_ID = "power.pololu.d24v50f5"

MANUFACTURER_MOUNT_TRUTH: dict[str, dict[str, Any]] = {
    PI5_ID: {
        "interface_id": "mount",
        "hole_centers_mm": [
            [-39.0, -24.5, 0.0],
            [19.0, -24.5, 0.0],
            [19.0, 24.5, 0.0],
            [-39.0, 24.5, 0.0],
        ],
        "pattern_mm": [58.0, 49.0],
        "hole_diameter_mm": 2.7,
        "fastener": "M2.5",
        "coordinate_datum": "85x56_mm_board_outline_center",
        "source_dimensions": {
            "board_x_mm": 85.0,
            "board_y_mm": 56.0,
            "left_edge_to_left_hole_center_mm": 3.5,
            "hole_spacing_x_mm": 58.0,
            "hole_spacing_y_mm": 49.0,
        },
        "source": {
            "kind": "manufacturer",
            "trust": 100,
            "title": "Raspberry Pi 5 mechanical drawing",
            "url": "https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf",
            "note": "Manufacturer drawing states dimensions are approximate/reference-only and subject to tolerance/change.",
        },
    },
    POLOLU_D24V50F5_ID: {
        "interface_id": "mount",
        "hole_centers_mm": [
            [-6.75, -8.0, 0.0],
            [6.75, 8.0, 0.0],
        ],
        "pattern_mm": [13.5, 16.0],
        "hole_diameter_mm": 2.18,
        "fastener": "M2",
        "coordinate_datum": "17.8x20.3_mm_board_outline_center",
        "drill_location_tolerance_mm": 0.1,
        "source_dimensions": {
            "board_x_mm": 17.8,
            "board_y_mm": 20.3,
            "hole_spacing_x_mm": 13.5,
            "hole_spacing_y_mm": 16.0,
        },
        "source": {
            "kind": "manufacturer",
            "trust": 100,
            "title": "Dimension diagram of the D24V50F5 Step-Down Voltage Regulator",
            "url": "https://www.pololu.com/file/0J1436/d24v50f5-step-down-voltage-regulator-dimensions.pdf",
            "drawing_date": "2018-01-02",
        },
    },
}


_ORIGINAL_PI5_REALISTIC_BUILDER = realistic_components.PARAMETRIC_BUILDERS.get(PI5_ID)
_ORIGINAL_PI5_LEGACY_BUILDER = getattr(physical_components, "_pi5_parts", None)
_INSTALLED = False


def _metadata_from_truth(truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "hole_centers_mm": deepcopy(truth["hole_centers_mm"]),
        "pattern_mm": deepcopy(truth["pattern_mm"]),
        "hole_diameter_mm": float(truth["hole_diameter_mm"]),
        "fastener": truth.get("fastener"),
        "count": len(truth["hole_centers_mm"]),
        "coordinate_datum": truth["coordinate_datum"],
        "source_dimensions": deepcopy(truth.get("source_dimensions") or {}),
        "manufacturer_mount_source": deepcopy(truth["source"]),
        **(
            {"drill_location_tolerance_mm": float(truth["drill_location_tolerance_mm"])}
            if truth.get("drill_location_tolerance_mm") is not None
            else {}
        ),
    }


def _patch_interface(interfaces: list[dict[str, Any]], component_id: str) -> None:
    truth = MANUFACTURER_MOUNT_TRUTH[component_id]
    interface_id = str(truth["interface_id"])
    interface = next((row for row in interfaces if str(row.get("id")) == interface_id), None)
    if interface is None:
        raise RuntimeError(f"Manufacturer mount truth target missing: {component_id}:{interface_id}")
    metadata = dict(interface.get("metadata") or {})
    metadata.update(_metadata_from_truth(truth))
    interface["metadata"] = metadata


def _install_source_registry_truth() -> None:
    pi_enrichment = registry.ENRICHMENTS.get(PI5_ID)
    if not isinstance(pi_enrichment, dict):
        raise RuntimeError("Raspberry Pi 5 enrichment missing from component registry")
    _patch_interface(pi_enrichment.get("interfaces") or [], PI5_ID)

    pololu = next((row for row in curated_catalog.CATALOG if row.get("id") == POLOLU_D24V50F5_ID), None)
    if pololu is None:
        raise RuntimeError("Pololu D24V50F5 missing from curated component catalog")
    _patch_interface(pololu.get("interfaces") or [], POLOLU_D24V50F5_ID)

    # Rebuild from the corrected source structures so snapshots, compatibility
    # registry rows and any later reload agree on the same truth.
    registry.reload_registry()
    registry._refresh_compat_registry()


def _corrected_pi5_realistic_parts():
    if _ORIGINAL_PI5_REALISTIC_BUILDER is None:
        raise RuntimeError("Raspberry Pi 5 deterministic geometry builder is unavailable")
    parts = list(_ORIGINAL_PI5_REALISTIC_BUILDER())
    if not parts:
        raise RuntimeError("Raspberry Pi 5 deterministic geometry builder returned no solids")
    truth = MANUFACTURER_MOUNT_TRUTH[PI5_ID]
    board, _ = realistic_components._box(85.0, 56.0, 1.6, "#16813e", radius=3.0)
    board = realistic_components._cut_round_holes(
        board,
        [(float(x), float(y)) for x, y, _ in truth["hole_centers_mm"]],
        float(truth["hole_diameter_mm"]),
        5.0,
    )
    parts[0] = (board, "#16813e")
    return parts


def _corrected_pi5_legacy_parts():
    if _ORIGINAL_PI5_LEGACY_BUILDER is None:
        return _corrected_pi5_realistic_parts()
    parts = list(_ORIGINAL_PI5_LEGACY_BUILDER())
    if not parts:
        raise RuntimeError("Raspberry Pi 5 legacy geometry builder returned no solids")
    truth = MANUFACTURER_MOUNT_TRUTH[PI5_ID]
    board, _ = physical_components._box(85.0, 56.0, 1.6, "#16813e", radius=3.0)
    board = physical_components._cut_holes(
        board,
        [(float(x), float(y)) for x, y, _ in truth["hole_centers_mm"]],
        float(truth["hole_diameter_mm"]),
        3.0,
        -1.5,
    )
    parts[0] = (board, "#16813e")
    return parts


def install_manufacturer_truth() -> dict[str, Any]:
    global _INSTALLED
    if not _INSTALLED:
        _install_source_registry_truth()
        realistic_components.PARAMETRIC_BUILDERS[PI5_ID] = _corrected_pi5_realistic_parts
        physical_components._pi5_parts = _corrected_pi5_legacy_parts
        _INSTALLED = True
    return summary()


def _interface(component_id: str) -> dict[str, Any]:
    component = registry.component_by_id(component_id)
    interface_id = str(MANUFACTURER_MOUNT_TRUTH[component_id]["interface_id"])
    return next(row for row in component.get("interfaces") or [] if str(row.get("id")) == interface_id)


def _board_shape(component_id: str):
    builder = realistic_components.PARAMETRIC_BUILDERS.get(component_id)
    if builder is None:
        return None
    parts = builder()
    return parts[0][0] if parts else None


def _witness_overlap_mm3(shape, center_xy: tuple[float, float], radius_mm: float = 0.35) -> float:
    x, y = center_xy
    witness = cq.Workplane("XY").workplane(offset=-5.0).center(x, y).circle(radius_mm).extrude(10.0).val()
    return abs(float(shape.intersect(witness).Volume()))


def audit_manufacturer_mount_truth(component_id: str) -> dict[str, Any]:
    if component_id not in MANUFACTURER_MOUNT_TRUTH:
        raise KeyError(component_id)
    install_manufacturer_truth()
    truth = MANUFACTURER_MOUNT_TRUTH[component_id]
    interface = _interface(component_id)
    metadata = interface.get("metadata") or {}
    declared = [[float(value) for value in row] for row in metadata.get("hole_centers_mm") or []]
    expected = [[float(value) for value in row] for row in truth["hole_centers_mm"]]
    findings: list[dict[str, Any]] = []
    if declared != expected:
        findings.append({"severity": "error", "code": "manufacturer_hole_centers_drift", "expected": expected, "actual": declared})
    if abs(float(metadata.get("hole_diameter_mm", 0.0)) - float(truth["hole_diameter_mm"])) > 1e-9:
        findings.append({"severity": "error", "code": "manufacturer_hole_diameter_drift"})
    if str(metadata.get("coordinate_datum") or "") != str(truth["coordinate_datum"]):
        findings.append({"severity": "error", "code": "manufacturer_coordinate_datum_missing"})
    source = metadata.get("manufacturer_mount_source") or {}
    if source.get("kind") != "manufacturer" or int(source.get("trust", 0) or 0) < 100 or not source.get("url"):
        findings.append({"severity": "error", "code": "manufacturer_mount_provenance_missing"})

    shape = _board_shape(component_id)
    geometry_checked = shape is not None
    if shape is not None:
        for index, center in enumerate(expected):
            overlap = _witness_overlap_mm3(shape, (center[0], center[1]))
            if overlap > 1e-6:
                findings.append(
                    {
                        "severity": "error",
                        "code": "manufacturer_mount_hole_missing_from_parametric_brep",
                        "pattern_index": index,
                        "interference_volume_mm3": overlap,
                    }
                )

    return {
        "ok": not findings,
        "component_id": component_id,
        "interface_id": truth["interface_id"],
        "hole_count": len(expected),
        "hole_centers_mm": expected,
        "hole_diameter_mm": float(truth["hole_diameter_mm"]),
        "coordinate_datum": truth["coordinate_datum"],
        "source": deepcopy(truth["source"]),
        "parametric_brep_checked": geometry_checked,
        "findings": findings,
    }


def audit_all_manufacturer_mount_truth() -> dict[str, Any]:
    items = [audit_manufacturer_mount_truth(component_id) for component_id in MANUFACTURER_MOUNT_TRUTH]
    return {
        "ok": all(item["ok"] for item in items),
        "count": len(items),
        "items": items,
    }


def summary() -> dict[str, Any]:
    return {
        "installed": _INSTALLED,
        "component_count": len(MANUFACTURER_MOUNT_TRUTH),
        "components": sorted(MANUFACTURER_MOUNT_TRUTH),
        "truth_model": "explicit manufacturer coordinates + datum + provenance",
    }
