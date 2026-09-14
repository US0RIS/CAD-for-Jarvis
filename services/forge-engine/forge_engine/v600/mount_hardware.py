from __future__ import annotations

"""Standards-backed mounting hardware realization for ForgeCAD 6.0 Milestone 2.

Geometry-backed holes are necessary but not sufficient for a physical assembly.
This module turns a verified mounting pattern into an inspectable hardware stack
without inventing a supplier or manufacturer part number.

The current controlled capability covers a double-sided female-female threaded
standoff: one screw passes through the purchased component into the standoff and
a second screw passes through the fabricated host into the opposite end.  More
retention strategies remain later work.
"""

from copy import deepcopy
import math
import re
from typing import Any

from pydantic import BaseModel, Field

from ..v110 import core
from .geometry_mounts import MountGeometryRequest, audit_mount_geometry, plan_mount_geometry


# Engineering-reference clearance subset.  These are intentionally tagged with
# their source instead of being represented as manufacturer truth.  The values
# match Accu's published general metric clearance-hole table.
_CLEARANCE_REFERENCE: dict[str, dict[str, Any]] = {
    "M2": {"major_diameter_mm": 2.0, "clearance_hole_mm": 2.6},
    "M2.5": {"major_diameter_mm": 2.5, "clearance_hole_mm": 3.1},
    "M3": {"major_diameter_mm": 3.0, "clearance_hole_mm": 3.6},
    "M4": {"major_diameter_mm": 4.0, "clearance_hole_mm": 4.8},
    "M5": {"major_diameter_mm": 5.0, "clearance_hole_mm": 5.8},
    "M6": {"major_diameter_mm": 6.0, "clearance_hole_mm": 7.0},
}
_REFERENCE = {
    "kind": "engineering_reference",
    "title": "Accu tapping drill size and clearance holes",
    "url": "https://www.accu.co.uk/p/449-tapping-drill-size-chart-clearance-holes",
    "scope": "general metric clearance-hole diameter reference; not supplier selection",
}


class MountHardwareRequest(BaseModel):
    component_id: str
    host_id: str
    component_interface: str
    host_interface: str
    strategy: str = "double_sided_female_standoff"
    standoff_height_mm: float = Field(gt=0.0, le=100.0)
    standoff_thread_depth_mm: float = Field(gt=0.0, le=50.0)
    component_mount_thickness_mm: float = Field(gt=0.0, le=50.0)
    top_screw_length_mm: float = Field(gt=0.0, le=100.0)
    bottom_screw_length_mm: float = Field(gt=0.0, le=100.0)
    minimum_thread_engagement_mm: float = Field(default=2.0, gt=0.0, le=20.0)
    clearance_tolerance_mm: float = Field(default=0.05, gt=0.0, le=1.0)
    screw_standard: str = "ISO 4762"


def _object(project: dict[str, Any], object_id: str) -> dict[str, Any]:
    for row in project.get("objects") or []:
        if str(row.get("id")) == str(object_id):
            return row
    raise KeyError(object_id)


def _source_interface(component: dict[str, Any], interface_id: str) -> dict[str, Any]:
    snapshot = component.get("component_snapshot") or {}
    for interface in snapshot.get("interfaces") or []:
        if str(interface.get("id")) == str(interface_id):
            return interface
    raise KeyError(interface_id)


def _parse_thread(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(" ", "")
    match = re.fullmatch(r"M(\d+(?:\.\d+)?)", raw)
    if not match:
        raise ValueError(f"Mount interface fastener designation {value!r} is not a supported ISO metric thread")
    normalized = f"M{match.group(1)}"
    if normalized not in _CLEARANCE_REFERENCE:
        raise ValueError(f"No validated clearance reference is installed for {normalized}")
    return normalized


def _host_thickness_mm(host: dict[str, Any], axis: str) -> float:
    if str(host.get("kind") or "") != "box":
        raise ValueError("Controlled mount-hardware realization currently derives host thickness only for box geometry")
    params = host.get("params") or {}
    key = {"x": "x", "y": "y", "z": "z"}.get(str(axis))
    if key is None or params.get(key) is None:
        raise ValueError("Host thickness cannot be derived from the mounting-hole axis")
    value = float(params[key])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Derived host thickness must be finite and positive")
    return value


def _binding_features(host: dict[str, Any], binding_id: str) -> list[dict[str, Any]]:
    return [
        row
        for row in host.get("features") or []
        if isinstance(row, dict)
        and isinstance(row.get("mount_binding"), dict)
        and str(row["mount_binding"].get("binding_id") or "") == binding_id
    ]


def _realization_id(binding_id: str) -> str:
    return f"hardware::{binding_id}"


def _bom_ids(realization_id: str) -> dict[str, str]:
    return {
        "top_screw": f"{realization_id}::top_screw",
        "bottom_screw": f"{realization_id}::bottom_screw",
        "standoff": f"{realization_id}::standoff",
    }


def plan_mount_hardware(project: dict[str, Any], request: MountHardwareRequest) -> dict[str, Any]:
    if request.strategy != "double_sided_female_standoff":
        raise ValueError("Only double_sided_female_standoff is validated in this Milestone-2 controlled capability")

    component = _object(project, request.component_id)
    host = _object(project, request.host_id)
    if component.get("kind") != "component" or not component.get("component_ref"):
        raise ValueError("component_id must identify a purchased-component instance")

    interface = _source_interface(component, request.component_interface)
    metadata = interface.get("metadata") or {}
    thread = _parse_thread(metadata.get("fastener"))
    reference = _CLEARANCE_REFERENCE[thread]

    # Discover the already-materialized mount binding and its actual hole diameter.
    base_plan = plan_mount_geometry(
        project,
        MountGeometryRequest(
            component_id=request.component_id,
            host_id=request.host_id,
            component_interface=request.component_interface,
            host_interface=request.host_interface,
        ),
    )
    binding_id = str(base_plan["binding_id"])
    features = _binding_features(host, binding_id)
    if not features:
        raise ValueError("Mount hardware cannot be realized before geometry-backed mounting holes exist")
    diameters = sorted({round(float(row.get("diameter", 0.0)), 9) for row in features})
    if len(diameters) != 1 or diameters[0] <= 0:
        raise ValueError("Mount hardware requires one consistent positive host-hole diameter across the pattern")
    actual_clearance = float(diameters[0])

    # Re-audit against the actual materialized diameter rather than the source
    # component's smaller through-hole diameter.
    geometry_request = MountGeometryRequest(
        component_id=request.component_id,
        host_id=request.host_id,
        component_interface=request.component_interface,
        host_interface=request.host_interface,
        host_hole_diameter_mm=actual_clearance,
        position_tolerance_mm=0.05,
        diameter_tolerance_mm=request.clearance_tolerance_mm,
    )
    geometry_audit = audit_mount_geometry(project, geometry_request)
    if not geometry_audit["ok"]:
        raise ValueError(f"Mount geometry is not currently valid: {geometry_audit['findings']}")

    expected_clearance = float(reference["clearance_hole_mm"])
    clearance_error = abs(actual_clearance - expected_clearance)
    if clearance_error > float(request.clearance_tolerance_mm):
        raise ValueError(
            f"{thread} host clearance is {actual_clearance:.3f} mm but the installed engineering reference is "
            f"{expected_clearance:.3f} mm ± {request.clearance_tolerance_mm:.3f} mm"
        )

    source_hole = float(base_plan["pattern"]["hole_diameter_mm"])
    major = float(reference["major_diameter_mm"])
    if source_hole <= major:
        raise ValueError(
            f"Purchased component through-hole {source_hole:.3f} mm does not clear {thread} major diameter {major:.3f} mm"
        )

    axis = str(features[0].get("axis") or "")
    host_thickness = _host_thickness_mm(host, axis)
    top_engagement = float(request.top_screw_length_mm) - float(request.component_mount_thickness_mm)
    bottom_engagement = float(request.bottom_screw_length_mm) - host_thickness
    for side, engagement in (("top", top_engagement), ("bottom", bottom_engagement)):
        if engagement < float(request.minimum_thread_engagement_mm) - 1e-9:
            raise ValueError(
                f"{side} screw provides only {engagement:.3f} mm thread engagement; "
                f"minimum is {request.minimum_thread_engagement_mm:.3f} mm"
            )
        if engagement > float(request.standoff_thread_depth_mm) + 1e-9:
            raise ValueError(
                f"{side} screw engagement {engagement:.3f} mm exceeds declared standoff thread depth "
                f"{request.standoff_thread_depth_mm:.3f} mm"
            )

    quantity = int(base_plan["pattern"]["hole_count"])
    realization_id = _realization_id(binding_id)
    ids = _bom_ids(realization_id)
    bom = [
        {
            "id": ids["top_screw"],
            "description": f"{request.screw_standard} socket-head cap screw {thread} × {request.top_screw_length_mm:g} mm",
            "manufacturer": "UNRESOLVED",
            "model": f"{request.screw_standard} {thread}x{request.top_screw_length_mm:g}",
            "quantity": quantity,
            "category": "fastener",
            "standard": request.screw_standard,
            "thread": thread,
            "length_mm": float(request.top_screw_length_mm),
            "procurement_state": "standard_specification_supplier_unresolved",
            "provenance": [deepcopy(_REFERENCE), {"kind": "design_input", "field": "top_screw_length_mm"}],
            "mount_realization_id": realization_id,
        },
        {
            "id": ids["bottom_screw"],
            "description": f"{request.screw_standard} socket-head cap screw {thread} × {request.bottom_screw_length_mm:g} mm",
            "manufacturer": "UNRESOLVED",
            "model": f"{request.screw_standard} {thread}x{request.bottom_screw_length_mm:g}",
            "quantity": quantity,
            "category": "fastener",
            "standard": request.screw_standard,
            "thread": thread,
            "length_mm": float(request.bottom_screw_length_mm),
            "procurement_state": "standard_specification_supplier_unresolved",
            "provenance": [deepcopy(_REFERENCE), {"kind": "design_input", "field": "bottom_screw_length_mm"}],
            "mount_realization_id": realization_id,
        },
        {
            "id": ids["standoff"],
            "description": f"Female-female threaded standoff {thread} × {request.standoff_height_mm:g} mm",
            "manufacturer": "UNRESOLVED",
            "model": f"female-female standoff {thread}x{request.standoff_height_mm:g}",
            "quantity": quantity,
            "category": "standoff",
            "thread": thread,
            "length_mm": float(request.standoff_height_mm),
            "thread_depth_each_end_mm": float(request.standoff_thread_depth_mm),
            "procurement_state": "standard_specification_supplier_unresolved",
            "provenance": [{"kind": "design_input", "field": "standoff geometry"}],
            "mount_realization_id": realization_id,
        },
    ]

    return {
        "realization_id": realization_id,
        "binding_id": binding_id,
        "strategy": request.strategy,
        "component_id": request.component_id,
        "component_ref": component.get("component_ref"),
        "host_id": request.host_id,
        "thread": thread,
        "quantity": quantity,
        "component_hole_diameter_mm": source_hole,
        "host_clearance_hole_mm": actual_clearance,
        "reference_clearance_hole_mm": expected_clearance,
        "clearance_reference": deepcopy(_REFERENCE),
        "host_thickness_mm": host_thickness,
        "component_mount_thickness_mm": float(request.component_mount_thickness_mm),
        "standoff_height_mm": float(request.standoff_height_mm),
        "standoff_thread_depth_mm": float(request.standoff_thread_depth_mm),
        "top_screw_engagement_mm": top_engagement,
        "bottom_screw_engagement_mm": bottom_engagement,
        "minimum_thread_engagement_mm": float(request.minimum_thread_engagement_mm),
        "bom": bom,
        "geometry_audit": geometry_audit,
        "limitations": [
            "supplier/manufacturer part numbers remain unresolved until catalog selection",
            "fastener preload/torque, thread stripping, bearing stress and vibration retention are not yet analyzed",
            "standoff outer diameter/envelope and tool-access geometry remain explicit future validation",
        ],
    }


def audit_mount_hardware(project: dict[str, Any], request: MountHardwareRequest) -> dict[str, Any]:
    try:
        plan = plan_mount_hardware(project, request)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "findings": [{"severity": "error", "code": "mount_hardware_invalid", "message": str(exc)}]}
    realization_id = str(plan["realization_id"])
    realization = next(
        (row for row in project.get("mount_hardware_realizations") or [] if str(row.get("id") or "") == realization_id),
        None,
    )
    if realization is None:
        return {
            "ok": False,
            "plan": plan,
            "findings": [{"severity": "error", "code": "mount_hardware_not_realized", "message": realization_id}],
        }
    expected_ids = {row["id"] for row in plan["bom"]}
    actual = {str(row.get("id") or ""): row for row in project.get("bom") or [] if str(row.get("id") or "") in expected_ids}
    missing = sorted(expected_ids - set(actual))
    findings = []
    if missing:
        findings.append({"severity": "error", "code": "mount_hardware_bom_missing", "bom_ids": missing})
    for expected in plan["bom"]:
        current = actual.get(expected["id"])
        if current is not None and current != expected:
            findings.append({"severity": "error", "code": "mount_hardware_bom_drift", "bom_id": expected["id"]})
    return {
        "ok": not findings,
        "realization": deepcopy(realization),
        "plan": plan,
        "findings": findings,
    }


def realize_mount_hardware(project: dict[str, Any], request: MountHardwareRequest) -> dict[str, Any]:
    plan = plan_mount_hardware(project, request)
    realization_id = str(plan["realization_id"])
    rows = project.setdefault("mount_hardware_realizations", [])
    existing = next((row for row in rows if str(row.get("id") or "") == realization_id), None)
    record = {
        "id": realization_id,
        "binding_id": plan["binding_id"],
        "strategy": plan["strategy"],
        "component_id": plan["component_id"],
        "component_ref": plan["component_ref"],
        "host_id": plan["host_id"],
        "thread": plan["thread"],
        "quantity": plan["quantity"],
        "host_clearance_hole_mm": plan["host_clearance_hole_mm"],
        "standoff_height_mm": plan["standoff_height_mm"],
        "top_screw_engagement_mm": plan["top_screw_engagement_mm"],
        "bottom_screw_engagement_mm": plan["bottom_screw_engagement_mm"],
        "procurement_state": "standard_specification_supplier_unresolved",
        "bom_ids": [row["id"] for row in plan["bom"]],
        "clearance_reference": deepcopy(plan["clearance_reference"]),
    }
    if existing is not None:
        if existing != record:
            raise ValueError("Existing mount-hardware realization differs from the requested design; create an explicit redesign instead of silently rewriting it")
        audit = audit_mount_hardware(project, request)
        return {"ok": audit["ok"], "idempotent": True, "realization": deepcopy(existing), "audit": audit}

    project.setdefault("bom", []).extend(deepcopy(plan["bom"]))
    rows.append(record)
    audit = audit_mount_hardware(project, request)
    if not audit["ok"]:
        rows[:] = [row for row in rows if str(row.get("id") or "") != realization_id]
        ids = {row["id"] for row in plan["bom"]}
        project["bom"] = [row for row in project.get("bom") or [] if str(row.get("id") or "") not in ids]
        raise ValueError(f"Realized mounting hardware failed audit: {audit['findings']}")
    return {"ok": True, "idempotent": False, "realization": record, "audit": audit}
