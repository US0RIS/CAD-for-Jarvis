from __future__ import annotations

"""Acceptance test for Milestone-2 mount hardware realization."""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _object_named(name: str) -> dict:
    return next(row for row in core.PROJECT["objects"] if row.get("name") == name)


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        plate_name = "Milestone 2 Hardware Pi Carrier"
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
                    "reason": "Create hardware-realization carrier",
                },
            ),
            "create hardware carrier",
        )
        plate_id = str(_object_named(plate_name)["id"])
        pi_payload = _ok(client.post("/v2/components/compute.raspberry_pi_5_8gb/add"), "add Pi").json()
        pi_id = str(pi_payload["component"]["instance_id"])

        _ok(
            client.post(
                "/v6/assembly/mates/apply",
                json={
                    "source_id": pi_id,
                    "target_id": plate_id,
                    "source_interface": "mount",
                    "target_interface": "pi_mount",
                    "mate_type": "fixed",
                    "gap_mm": 6.0,
                },
            ),
            "mate Pi on six millimeter standoffs",
        )

        geometry_request = {
            "component_id": pi_id,
            "host_id": plate_id,
            "component_interface": "mount",
            "host_interface": "pi_mount",
            "host_hole_diameter_mm": 3.1,
        }
        materialized = _ok(
            client.post("/v6/assembly/mounts/materialize", json=geometry_request),
            "materialize M2.5 reference clearance",
        ).json()
        assert materialized["audit"]["ok"] is True, materialized
        assert abs(float(materialized["audit"]["plan"]["mate_gap_mm"]) - 6.0) < 1e-9, materialized
        assert all(abs(float(row["diameter"]) - 3.1) < 1e-9 for row in materialized["created"]), materialized

        hardware_request = {
            "component_id": pi_id,
            "host_id": plate_id,
            "component_interface": "mount",
            "host_interface": "pi_mount",
            "strategy": "double_sided_female_standoff",
            "standoff_height_mm": 6.0,
            "standoff_thread_depth_mm": 3.0,
            "component_mount_thickness_mm": 1.6,
            "top_screw_length_mm": 4.0,
            "bottom_screw_length_mm": 6.0,
            "minimum_thread_engagement_mm": 2.0,
            "clearance_tolerance_mm": 0.05,
            "stack_tolerance_mm": 0.05,
            "screw_standard": "ISO 4762",
        }
        plan = _ok(
            client.post("/v6/assembly/mounts/hardware/plan", json=hardware_request),
            "plan Pi standoff hardware",
        ).json()
        assert plan["thread"] == "M2.5", plan
        assert plan["quantity"] == 4, plan
        assert abs(float(plan["reference_clearance_hole_mm"]) - 3.1) < 1e-9, plan
        assert abs(float(plan["mate_gap_mm"]) - 6.0) < 1e-9, plan
        assert abs(float(plan["measured_axial_separation_mm"]) - 6.0) < 1e-9, plan
        assert abs(float(plan["top_screw_engagement_mm"]) - 2.4) < 1e-9, plan
        assert abs(float(plan["bottom_screw_engagement_mm"]) - 2.0) < 1e-9, plan
        assert len(plan["bom"]) == 3, plan
        assert all(row["manufacturer"] == "UNRESOLVED" for row in plan["bom"]), plan
        assert all(row["procurement_state"] == "standard_specification_supplier_unresolved" for row in plan["bom"]), plan

        realized = _ok(
            client.post("/v6/assembly/mounts/hardware/realize", json=hardware_request),
            "realize Pi mount hardware",
        ).json()
        assert realized["ok"] is True and realized["idempotent"] is False, realized
        assert realized["audit"]["ok"] is True, realized
        assert len(core.PROJECT.get("mount_hardware_realizations") or []) == 1, core.PROJECT.get("mount_hardware_realizations")

        bom_rows = [row for row in core.PROJECT.get("bom") or [] if row.get("mount_realization_id") == plan["realization_id"]]
        assert len(bom_rows) == 3, bom_rows
        assert sorted(int(row["quantity"]) for row in bom_rows) == [4, 4, 4], bom_rows
        assert any("M2.5 × 4" in row["description"] for row in bom_rows), bom_rows
        assert any("M2.5 × 6" in row["description"] for row in bom_rows), bom_rows
        assert any("standoff M2.5 × 6" in row["description"] for row in bom_rows), bom_rows

        repeated = _ok(
            client.post("/v6/assembly/mounts/hardware/realize", json=hardware_request),
            "repeat hardware realization",
        ).json()
        assert repeated["idempotent"] is True, repeated
        assert len([row for row in core.PROJECT.get("bom") or [] if row.get("mount_realization_id") == plan["realization_id"]]) == 3

        _ok(client.post("/v3.1/graph/sync"), "sync hardware BOM graph")
        graph = _ok(client.get("/v3.1/graph"), "read hardware BOM graph").json()
        bom_nodes = [
            row for row in graph["nodes"]
            if row["kind"] == "bom_item" and row["properties"].get("mount_realization_id") == plan["realization_id"]
        ]
        assert len(bom_nodes) == 3, bom_nodes
        assert all(row["properties"].get("manufacturer") == "UNRESOLVED" for row in bom_nodes), bom_nodes

        # Fail closed if the actual host holes do not match the installed
        # engineering-reference clearance for M2.5.
        PROJECT.new_project()
        bad_plate_name = "Milestone 2 Undersized Pi Carrier"
        _ok(
            client.post(
                "/v2/operations",
                json={
                    "op": "add",
                    "args": {
                        "name": bad_plate_name,
                        "kind": "box",
                        "params": {"x": 110.0, "y": 80.0, "z": 4.0},
                        "interfaces": [
                            {
                                "id": "pi_mount",
                                "kind": "mount_pattern",
                                "position_mm": [0.0, 0.0, 2.0],
                                "axis": [0.0, 0.0, 1.0],
                                "x_axis": [1.0, 0.0, 0.0],
                                "gender": "neutral",
                                "mate": ["mount_pattern"],
                            }
                        ],
                    },
                    "reason": "negative clearance fixture",
                },
            ),
            "create undersized carrier",
        )
        bad_plate_id = str(_object_named(bad_plate_name)["id"])
        bad_pi_payload = _ok(client.post("/v2/components/compute.raspberry_pi_5_8gb/add"), "add negative Pi").json()
        bad_pi_id = str(bad_pi_payload["component"]["instance_id"])
        _ok(
            client.post(
                "/v6/assembly/mates/apply",
                json={
                    "source_id": bad_pi_id,
                    "target_id": bad_plate_id,
                    "source_interface": "mount",
                    "target_interface": "pi_mount",
                    "mate_type": "fixed",
                    "gap_mm": 6.0,
                },
            ),
            "mate negative Pi on six millimeter standoffs",
        )
        _ok(
            client.post(
                "/v6/assembly/mounts/materialize",
                json={
                    "component_id": bad_pi_id,
                    "host_id": bad_plate_id,
                    "component_interface": "mount",
                    "host_interface": "pi_mount",
                    "host_hole_diameter_mm": 2.7,
                },
            ),
            "materialize undersized reference fixture",
        )
        bad_request = dict(hardware_request)
        bad_request["component_id"] = bad_pi_id
        bad_request["host_id"] = bad_plate_id
        rejected = client.post("/v6/assembly/mounts/hardware/plan", json=bad_request)
        assert rejected.status_code == 409, rejected.text
        assert "clearance" in rejected.text.lower(), rejected.text
        assert not core.PROJECT.get("mount_hardware_realizations"), core.PROJECT.get("mount_hardware_realizations")

        return {
            "ok": True,
            "thread": "M2.5",
            "mount_positions": 4,
            "canonical_bom_lines": 3,
            "supplier_identity_preserved_as_unknown": True,
            "standoff_gap_geometry_consistent": True,
            "engagement_checked": True,
            "undersized_clearance_rejected": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
