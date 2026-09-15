from __future__ import annotations

"""Acceptance test for ForgeCAD 6.0 milestone 2.

The controlled fixture proves that authoritative purchased-component mounting
coordinates can drive editable fabricated CAD and that ForgeCAD independently
checks source provenance, coordinate datum, parametric component B-rep and final
fabricated B-rep rather than trusting a spacing tuple or metadata alone.
"""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core, component_registry
from . import manufacturer_truth
from .geometry_mounts import mount_pattern_definition


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _canonical() -> dict:
    return json.loads(json.dumps(core.PROJECT))


def _object_named(name: str) -> dict:
    return next(row for row in core.PROJECT["objects"] if row.get("name") == name)


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        # Manufacturer-coordinate truth is independently auditable before a
        # design uses either component. This proves metadata and deterministic
        # parametric component geometry agree on the same physical hole centers.
        manufacturer_audit = manufacturer_truth.audit_all_manufacturer_mount_truth()
        assert manufacturer_audit["ok"] is True, manufacturer_audit
        assert manufacturer_audit["count"] == 2, manufacturer_audit
        assert all(row["parametric_brep_checked"] is True for row in manufacturer_audit["items"]), manufacturer_audit

        pi_truth = next(row for row in manufacturer_audit["items"] if row["component_id"] == manufacturer_truth.PI5_ID)
        assert pi_truth["hole_centers_mm"] == [
            [-39.0, -24.5, 0.0],
            [19.0, -24.5, 0.0],
            [19.0, 24.5, 0.0],
            [-39.0, 24.5, 0.0],
        ], pi_truth
        assert pi_truth["coordinate_datum"] == "85x56_mm_board_outline_center", pi_truth
        assert pi_truth["source"]["kind"] == "manufacturer", pi_truth

        pololu_truth = next(row for row in manufacturer_audit["items"] if row["component_id"] == manufacturer_truth.POLOLU_D24V50F5_ID)
        assert pololu_truth["hole_centers_mm"] == [[-6.75, -8.0, 0.0], [6.75, 8.0, 0.0]], pololu_truth
        assert pololu_truth["coordinate_datum"] == "17.8x20.3_mm_board_outline_center", pololu_truth

        plate_name = "Milestone 2 Geometry-Backed Pi Carrier"
        _ok(
            client.post(
                "/v2/operations",
                json={
                    "op": "add",
                    "args": {
                        "name": plate_name,
                        "kind": "box",
                        "params": {"x": 110.0, "y": 80.0, "z": 4.0},
                        "material": "aluminum_6061_t6",
                        "semantic": {
                            "role": "fabricated_component_carrier",
                            "manufacturing_process": "cnc",
                            "tags": ["v6-milestone-2", "geometry-backed-mount"],
                        },
                        "interfaces": [
                            {
                                "id": "pi_mount",
                                "kind": "mount_pattern",
                                "position_mm": [0.0, 0.0, 2.0],
                                "axis": [0.0, 0.0, 1.0],
                                "x_axis": [1.0, 0.0, 0.0],
                                "gender": "neutral",
                                "required": True,
                                "mate": ["mount_pattern"],
                                "metadata": {"max_connections": 1},
                            }
                        ],
                    },
                    "reason": "Create fabricated carrier for 6.0 geometry-backed assembly acceptance",
                },
            ),
            "create carrier",
        )
        plate_id = str(_object_named(plate_name)["id"])

        add_pi = _ok(client.post("/v2/components/compute.raspberry_pi_5_8gb/add"), "add Raspberry Pi 5").json()
        pi_id = str(add_pi["component"]["instance_id"])
        pi = next(row for row in core.PROJECT["objects"] if str(row.get("id")) == pi_id)
        assert pi["component_ref"] == manufacturer_truth.PI5_ID, pi
        assert int(pi["component_snapshot"]["trust_score"]) >= 85, pi
        pi_mount_snapshot = next(row for row in pi["component_snapshot"]["interfaces"] if row["id"] == "mount")
        assert pi_mount_snapshot["metadata"]["hole_centers_mm"] == pi_truth["hole_centers_mm"], pi_mount_snapshot
        assert pi_mount_snapshot["metadata"]["coordinate_datum"] == pi_truth["coordinate_datum"], pi_mount_snapshot
        assert pi_mount_snapshot["metadata"]["manufacturer_mount_source"]["kind"] == "manufacturer", pi_mount_snapshot

        mate = _ok(
            client.post(
                "/v6/assembly/mates/apply",
                json={
                    "source_id": pi_id,
                    "target_id": plate_id,
                    "source_interface": "mount",
                    "target_interface": "pi_mount",
                    "mate_type": "fixed",
                },
            ),
            "mate Pi to carrier",
        ).json()
        assert mate["residual"]["position_error_mm"] < 1e-6, mate
        assert mate["residual"]["axis_error_deg"] < 1e-6, mate

        request = {
            "component_id": pi_id,
            "host_id": plate_id,
            "component_interface": "mount",
            "host_interface": "pi_mount",
            "host_hole_diameter_mm": 2.7,
        }
        plan = _ok(client.post("/v6/assembly/mounts/plan", json=request), "plan Pi mounting geometry").json()
        assert plan["pattern"]["hole_count"] == 4, plan
        assert plan["pattern"]["source"] == "explicit_hole_centers", plan
        expected_xy = sorted(
            (round(row["host_local_center_mm"][0], 3), round(row["host_local_center_mm"][1], 3))
            for row in plan["holes"]
        )
        assert expected_xy == [(-39.0, -24.5), (-39.0, 24.5), (19.0, -24.5), (19.0, 24.5)], expected_xy

        # The key datum regression: correct 58 x 49 spacing is insufficient if
        # somebody silently recenters the pattern at x=0. The mean X coordinate
        # must remain -10 mm relative to ForgeCAD's centered 85 mm board body.
        mean_x = sum(row["host_local_center_mm"][0] for row in plan["holes"]) / len(plan["holes"])
        assert abs(float(mean_x) + 10.0) < 1e-9, {"mean_x": mean_x, "holes": plan["holes"]}

        before_volume = float(core.object_metrics(_object_named(plate_name))["volume_mm3"])
        materialized = _ok(
            client.post("/v6/assembly/mounts/materialize", json=request),
            "materialize Pi mounting geometry",
        ).json()
        assert materialized["ok"] is True, materialized
        assert materialized["idempotent"] is False, materialized
        assert len(materialized["created"]) == 4, materialized
        assert materialized["audit"]["ok"] is True, materialized
        assert materialized["audit"]["evidence"]["feature_history_checked"] is True, materialized
        assert materialized["audit"]["evidence"]["final_brep_clearance_checked"] is True, materialized

        plate = _object_named(plate_name)
        mount_features = [
            row
            for row in plate.get("features", [])
            if isinstance(row.get("mount_binding"), dict)
            and row["mount_binding"].get("component_id") == pi_id
        ]
        assert len(mount_features) == 4, mount_features
        assert all(row.get("type") == "hole" and abs(float(row.get("diameter")) - 2.7) < 1e-9 for row in mount_features)
        after_volume = float(core.object_metrics(plate)["volume_mm3"])
        expected_removed = 4.0 * 3.141592653589793 * (2.7 / 2.0) ** 2 * 4.0
        assert abs((before_volume - after_volume) - expected_removed) < 0.5, {
            "before": before_volume,
            "after": after_volume,
            "expected_removed": expected_removed,
        }

        audit = _ok(client.post("/v6/assembly/mounts/audit", json=request), "audit Pi mounting geometry").json()
        assert audit["ok"] is True, audit
        assert audit["hole_count"] == 4 and audit["features_found"] == 4, audit

        # Materialization is idempotent: a repeat call audits the existing CAD
        # rather than silently duplicating cuts.
        repeated = _ok(
            client.post("/v6/assembly/mounts/materialize", json=request),
            "repeat Pi mounting materialization",
        ).json()
        assert repeated["idempotent"] is True and repeated["created"] == [], repeated
        assert len(_object_named(plate_name).get("features", [])) == 4, _object_named(plate_name).get("features")

        # A design change after materialization must invalidate the physical
        # correspondence. Move the purchased component by 1 mm without changing
        # the fabricated part and prove the independent audit catches it.
        pi_before = json.loads(json.dumps(next(row for row in core.PROJECT["objects"] if str(row.get("id")) == pi_id)["transform"]))
        moved = json.loads(json.dumps(pi_before))
        moved["position"][0] = float(moved["position"][0]) + 1.0
        _ok(
            client.post(
                "/v2/operations",
                json={"op": "transform", "args": {"id": pi_id, "position": moved["position"]}, "reason": "negative geometry audit"},
            ),
            "move component after mount creation",
        )
        stale = _ok(client.post("/v6/assembly/mounts/audit", json=request), "audit stale mounting geometry").json()
        assert stale["ok"] is False, stale
        assert any(row["code"] == "mount_hole_position_mismatch" for row in stale["findings"]), stale

        # Restore the component exactly and verify the same physical features are
        # valid again; the test never repairs by rewriting expected truth.
        _ok(
            client.post(
                "/v2/operations",
                json={"op": "transform", "args": {"id": pi_id, "position": pi_before["position"]}, "reason": "restore negative audit fixture"},
            ),
            "restore Pi transform",
        )
        restored = _ok(client.post("/v6/assembly/mounts/audit", json=request), "audit restored mounting geometry").json()
        assert restored["ok"] is True, restored

        # Pololu publishes the exact diagonal two-hole topology, so a real
        # component with source truth must succeed rather than being mislabeled
        # ambiguous merely because count=2.
        regulator = component_registry.component_by_id(manufacturer_truth.POLOLU_D24V50F5_ID)
        regulator_mount = next(row for row in regulator["interfaces"] if row["id"] == "mount")
        regulator_pattern = mount_pattern_definition(regulator_mount)
        assert regulator_pattern["source"] == "explicit_hole_centers", regulator_pattern
        regulator_xy = sorted((round(row[0], 3), round(row[1], 3)) for row in regulator_pattern["hole_centers_mm"])
        assert regulator_xy == [(-6.75, -8.0), (6.75, 8.0)], regulator_xy
        assert abs(float(regulator_mount["metadata"]["drill_location_tolerance_mm"]) - 0.1) < 1e-9, regulator_mount
        assert regulator_mount["metadata"]["manufacturer_mount_source"]["kind"] == "manufacturer", regulator_mount

        # Preserve fail-closed behavior for genuinely underspecified topology.
        ambiguous_two_hole = {
            "id": "synthetic_underspecified_mount",
            "kind": "mount_pattern",
            "metadata": {
                "pattern_mm": [13.5, 16.0],
                "hole_diameter_mm": 2.18,
                "count": 2,
            },
        }
        try:
            mount_pattern_definition(ambiguous_two_hole)
        except ValueError as exc:
            assert "will not guess" in str(exc), str(exc)
        else:
            raise AssertionError("An underspecified two-hole spacing envelope must fail closed")

        _ok(client.post("/v3.1/graph/sync"), "sync graph after mount materialization")
        graph = _ok(client.get("/v3.1/graph"), "read graph after mount materialization").json()
        ids = {row["id"] for row in graph["nodes"]}
        assert f"cad:{plate_id}" in ids and f"cad:{pi_id}" in ids, ids
        health = _ok(client.get("/v6/health"), "v6 health").json()
        assert "geometry_backed_assembly_truth" in health["completed_milestones"], health
        assert int((health.get("maturity") or {}).get("milestone_2", 0)) >= 2, health
        assert health["geometry_backed_mount_count"] >= 1, health
        assert health["manufacturer_mount_truth"]["installed"] is True, health
        assert health["manufacturer_mount_truth"]["component_count"] >= 2, health

        constraints = _ok(client.get("/v6/assembly/constraints"), "assembly constraint validation").json()
        assert constraints["ok"] is True, constraints

        canonical = _canonical()
        final_plate = next(row for row in canonical["objects"] if str(row.get("id")) == plate_id)
        claims = (final_plate.get("semantic") or {}).get("geometry_backed_mounts") or []
        assert len(claims) == 1, claims
        assert claims[0]["component_ref"] == manufacturer_truth.PI5_ID, claims
        assert len(claims[0]["feature_ids"]) == 4, claims

        return {
            "ok": True,
            "milestone": 2,
            "component_ref": pi["component_ref"],
            "mount_holes": 4,
            "pattern_source": plan["pattern"]["source"],
            "manufacturer_mount_truth_components": manufacturer_audit["count"],
            "pi_datum_offset_verified": True,
            "pololu_two_hole_topology_verified": True,
            "brep_verified": True,
            "negative_stale_geometry_detected": True,
            "ambiguous_pattern_failed_closed": True,
            "canonical_claims": len(claims),
        }


def main() -> None:
    result = run()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
