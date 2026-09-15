from __future__ import annotations

"""Acceptance test for physical mount envelope and tool-access validation."""

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


def _add_blocker(client: TestClient, name: str, position: list[float]) -> str:
    _ok(
        client.post(
            "/v2/operations",
            json={
                "op": "add",
                "args": {
                    "name": name,
                    "kind": "box",
                    "params": {"x": 3.0, "y": 3.0, "z": 3.0},
                    "material": "aluminum_6061_t6",
                    "semantic": {"role": "acceptance_interference_blocker"},
                },
                "reason": "mount-access negative fixture",
            },
        ),
        f"create {name}",
    )
    blocker_id = str(_object_named(name)["id"])
    _ok(
        client.post(
            "/v2/operations",
            json={"op": "transform", "args": {"id": blocker_id, "position": position}, "reason": "place access blocker"},
        ),
        f"position {name}",
    )
    return blocker_id


def _move(client: TestClient, object_id: str, position: list[float], label: str) -> None:
    _ok(
        client.post(
            "/v2/operations",
            json={"op": "transform", "args": {"id": object_id, "position": position}, "reason": label},
        ),
        label,
    )


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        plate_name = "Milestone 2 Accessible Pi Carrier"
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
                    "reason": "create mount-access acceptance carrier",
                },
            ),
            "create access carrier",
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
            "mate Pi on 6 mm standoffs",
        )

        geometry_request = {
            "component_id": pi_id,
            "host_id": plate_id,
            "component_interface": "mount",
            "host_interface": "pi_mount",
            "host_hole_diameter_mm": 3.1,
        }
        geometry = _ok(client.post("/v6/assembly/mounts/materialize", json=geometry_request), "materialize mount holes").json()
        assert geometry["audit"]["ok"] is True, geometry

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
        realized = _ok(client.post("/v6/assembly/mounts/hardware/realize", json=hardware_request), "realize mount hardware").json()
        assert realized["ok"] is True, realized

        access_request = {
            **hardware_request,
            "standoff_outer_diameter_mm": 5.0,
            "top_tool_clearance_diameter_mm": 4.5,
            "top_tool_clearance_height_mm": 10.0,
            "bottom_tool_clearance_diameter_mm": 4.5,
            "bottom_tool_clearance_height_mm": 10.0,
            "surface_epsilon_mm": 0.05,
            "interference_volume_tolerance_mm3": 0.00001,
        }
        clear = _ok(client.post("/v6/assembly/mounts/access/audit", json=access_request), "audit clear mount access").json()
        assert clear["ok"] is True, clear
        assert clear["mount_positions"] == 4, clear
        assert clear["envelope_count"] == 12, clear
        assert clear["evidence"]["world_space_brep_intersection_checked"] is True, clear

        top = next(row for row in clear["plan"]["envelopes"] if row["kind"] == "top_driver_access")
        blocker_name = "Top Driver Blocker"
        blocker_id = _add_blocker(client, blocker_name, list(top["center_world_mm"]))
        blocked_top = _ok(client.post("/v6/assembly/mounts/access/audit", json=access_request), "detect blocked top tool access").json()
        assert blocked_top["ok"] is False, blocked_top
        top_hits = [
            row for row in blocked_top["findings"]
            if row.get("code") == "mount_access_interference"
            and row.get("envelope_kind") == "top_driver_access"
            and row.get("object_id") == blocker_id
        ]
        assert top_hits, blocked_top
        assert int(top_hits[0]["pattern_index"]) == int(top["pattern_index"]), top_hits
        assert float(top_hits[0]["interference_volume_mm3"]) > 0.0, top_hits

        far_above = list(top["center_world_mm"])
        far_above[2] = float(far_above[2]) + 30.0
        _move(client, blocker_id, far_above, "clear top driver path")
        recovered_top = _ok(client.post("/v6/assembly/mounts/access/audit", json=access_request), "verify recovered top access").json()
        assert recovered_top["ok"] is True, recovered_top

        standoff = next(row for row in recovered_top["plan"]["envelopes"] if row["kind"] == "standoff_body")
        _move(client, blocker_id, list(standoff["center_world_mm"]), "block standoff body envelope")
        blocked_standoff = _ok(client.post("/v6/assembly/mounts/access/audit", json=access_request), "detect blocked standoff envelope").json()
        assert blocked_standoff["ok"] is False, blocked_standoff
        standoff_hits = [
            row for row in blocked_standoff["findings"]
            if row.get("code") == "mount_access_interference"
            and row.get("envelope_kind") == "standoff_body"
            and row.get("object_id") == blocker_id
        ]
        assert standoff_hits, blocked_standoff
        assert int(standoff_hits[0]["pattern_index"]) == int(standoff["pattern_index"]), standoff_hits

        cleared_position = list(standoff["center_world_mm"])
        cleared_position[0] = float(cleared_position[0]) + 20.0
        cleared_position[2] = float(cleared_position[2]) + 30.0
        _move(client, blocker_id, cleared_position, "clear all mount envelopes")
        recovered_all = _ok(client.post("/v6/assembly/mounts/access/audit", json=access_request), "verify all access restored").json()
        assert recovered_all["ok"] is True, recovered_all

        return {
            "ok": True,
            "mount_positions": clear["mount_positions"],
            "envelopes_checked": clear["envelope_count"],
            "top_driver_blocker_detected": True,
            "standoff_blocker_detected": True,
            "exact_blocking_object_reported": True,
            "recovery_after_geometry_change": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
