from __future__ import annotations

"""Acceptance coverage for manufacturer CAD -> canonical ForgeCAD registration.

Default mode is deterministic/offline and constructs STEP-like raw vendor frames.
Set FORGECAD_EXTERNAL_CAD_ACCEPTANCE=1 to additionally download and validate the
actual manufacturer STEP assets referenced by ForgeCAD.
"""

import json
import os

import cadquery as cq

from ..v110 import component_registry, physical_components, realistic_components
from . import manufacturer_cad_registration as registration
from . import manufacturer_truth


def _raw_board(x: float, y: float, z: float, holes: list[tuple[float, float]], diameter: float):
    board = cq.Workplane("XY").box(x, y, z, centered=(False, False, False)).val()
    for hx, hy in holes:
        tool = cq.Workplane("XY").center(hx, hy).circle(diameter / 2.0).extrude(z + 2.0).val().translate((0.0, 0.0, -1.0))
        board = board.cut(tool)
    return board


def _offline_pi() -> dict[str, object]:
    truth = manufacturer_truth.MANUFACTURER_MOUNT_TRUTH[manufacturer_truth.PI5_ID]
    shape = _raw_board(
        85.0,
        56.0,
        1.6,
        [(3.5, 3.5), (61.5, 3.5), (61.5, 52.5), (3.5, 52.5)],
        2.7,
    )
    # Asymmetric connector proxies prove registration cannot be based on the
    # whole assembly bounding box.
    connector = cq.Workplane("XY").box(8.0, 16.0, 10.0, centered=(False, False, False)).val().translate((85.0, 4.0, 1.0))
    assembly = cq.Compound.makeCompound([shape, connector])
    registered, evidence = registration.register_shape(manufacturer_truth.PI5_ID, assembly)
    assert evidence["validated"] is True, evidence
    assert evidence["strategy"] == "published_pcb_outline_and_underside", evidence
    assert abs(float(evidence["rigid_transform"]["translation_mm"][0]) + 42.5) < 1e-9, evidence
    assert abs(float(evidence["rigid_transform"]["translation_mm"][1]) + 28.0) < 1e-9, evidence
    assert abs(float(evidence["registered_board_bounds_mm"]["xmin"]) + 42.5) < 1e-6, evidence
    assert abs(float(evidence["registered_board_bounds_mm"]["xmax"]) - 42.5) < 1e-6, evidence
    assert abs(float(evidence["registered_board_bounds_mm"]["ymin"]) + 28.0) < 1e-6, evidence
    assert abs(float(evidence["registered_board_bounds_mm"]["ymax"]) - 28.0) < 1e-6, evidence
    assert abs(float(evidence["registered_board_bounds_mm"]["zmin"]) - float(truth["canonical_mount_plane_z_mm"])) < 1e-6, evidence
    # Whole assembly remains asymmetric after correct datum registration.
    bb = registered.BoundingBox()
    assert float(bb.xmax) > 42.5, (bb.xmin, bb.xmax)
    return evidence


def _offline_pololu() -> dict[str, object]:
    truth = manufacturer_truth.MANUFACTURER_MOUNT_TRUTH[manufacturer_truth.POLOLU_D24V50F5_ID]
    shape = _raw_board(
        17.78,
        20.32,
        1.5748,
        [(2.159, 2.159), (15.621, 18.161)],
        2.1844,
    )
    package = cq.Workplane("XY").box(6.0, 5.0, 5.0, centered=(True, True, False)).val().translate((3.0, 5.0, 1.5748))
    assembly = cq.Compound.makeCompound([shape, package])
    _, evidence = registration.register_shape(manufacturer_truth.POLOLU_D24V50F5_ID, assembly)
    assert evidence["validated"] is True, evidence
    assert evidence["strategy"] == "published_mount_axes_and_underside", evidence
    assert float(evidence["max_mount_center_residual_mm"]) <= float(truth["drill_location_tolerance_mm"]), evidence
    assert abs(float(evidence["canonical_mount_plane_z_mm"]) - float(truth["canonical_mount_plane_z_mm"])) < 1e-9, evidence
    assert evidence["rigid_transform"]["rotation_deg"] == [0.0, 0.0, 0.0], evidence
    return evidence


def _external(component_id: str) -> dict[str, object]:
    path = realistic_components.download_step(component_id, force=True)
    evidence = registration.ensure_registration(component_id, path)
    assert evidence["validated"] is True, evidence
    assert int(evidence["asset_bytes"]) > 1000, evidence
    obj = {
        "id": f"external-cad-{component_id}",
        "component_ref": component_id,
        "component_snapshot": component_registry.component_by_id(component_id),
    }
    status = physical_components.component_geometry_status(obj)
    assert status["resolved"] is True, status
    assert status["fallback"] is False, status
    assert status["geometry_fidelity"] == "official_step", status
    assert status["registration_validated"] is True, status
    assert status["registration_evidence"]["validated"] is True, status
    return {
        "component_id": component_id,
        "asset_bytes": int(evidence["asset_bytes"]),
        "strategy": evidence["strategy"],
        "geometry_status": {
            "resolved": status["resolved"],
            "fallback": status["fallback"],
            "geometry_fidelity": status["geometry_fidelity"],
            "registration_validated": status["registration_validated"],
        },
        **({"max_mount_center_residual_mm": evidence["max_mount_center_residual_mm"]} if "max_mount_center_residual_mm" in evidence else {}),
    }


def run() -> dict[str, object]:
    manufacturer_truth.install_manufacturer_truth()
    registration.install(manufacturer_truth.MANUFACTURER_MOUNT_TRUTH)

    truth_audit = manufacturer_truth.audit_all_manufacturer_mount_truth()
    assert truth_audit["ok"] is True, truth_audit
    pololu = next(row for row in truth_audit["items"] if row["component_id"] == manufacturer_truth.POLOLU_D24V50F5_ID)
    assert abs(float(pololu["canonical_mount_plane_z_mm"]) + 0.7874) < 1e-9, pololu

    offline = {
        manufacturer_truth.PI5_ID: _offline_pi(),
        manufacturer_truth.POLOLU_D24V50F5_ID: _offline_pololu(),
    }
    result: dict[str, object] = {
        "ok": True,
        "offline_registration": {
            component_id: {
                "strategy": evidence["strategy"],
                "validated": evidence["validated"],
            }
            for component_id, evidence in offline.items()
        },
        "external_checked": False,
    }

    if os.environ.get("FORGECAD_EXTERNAL_CAD_ACCEPTANCE", "").strip().lower() in {"1", "true", "yes"}:
        external = [
            _external(manufacturer_truth.PI5_ID),
            _external(manufacturer_truth.POLOLU_D24V50F5_ID),
        ]
        result["external_checked"] = True
        result["external"] = external
        summary = registration.summary()
        assert not summary["registration_failures"], summary
        assert set(summary["registered_component_ids"]) >= {manufacturer_truth.PI5_ID, manufacturer_truth.POLOLU_D24V50F5_ID}, summary

    return result


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
