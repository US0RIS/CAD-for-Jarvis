from __future__ import annotations

"""Acceptance coverage for Milestone-2 spatial constraint-rank diagnostics."""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _add(client: TestClient, name: str, interfaces: list[dict], position: list[float] | None = None) -> str:
    _ok(
        client.post(
            "/v2/operations",
            json={
                "op": "add",
                "args": {
                    "name": name,
                    "kind": "box",
                    "params": {"x": 20.0, "y": 20.0, "z": 4.0},
                    "transform": {
                        "position": position or [0.0, 0.0, 0.0],
                        "rotation_deg": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                    "interfaces": interfaces,
                },
                "reason": "constraint-rank acceptance fixture",
            },
        ),
        f"add {name}",
    )
    return str(next(row for row in core.PROJECT["objects"] if row.get("name") == name)["id"])


def _face(iid: str, x: float = 0.0) -> dict:
    return {
        "id": iid,
        "kind": "mount_face",
        "position_mm": [x, 0.0, 0.0],
        "axis": [0.0, 0.0, 1.0],
        "x_axis": [1.0, 0.0, 0.0],
        "gender": "neutral",
        "mate": ["mount_face"],
        "metadata": {"max_connections": 1},
    }


def _mate(client: TestClient, source: str, target: str, source_if: str, target_if: str, mate_type: str) -> dict:
    return _ok(
        client.post(
            "/v6/assembly/mates/apply",
            json={
                "source_id": source,
                "target_id": target,
                "source_interface": source_if,
                "target_interface": target_if,
                "mate_type": mate_type,
                "axis_relation": "aligned",
            },
        ),
        f"apply {mate_type} mate",
    ).json()


def _rank(client: TestClient) -> dict:
    return _ok(client.get("/v6/assembly/constraint-rank"), "constraint rank").json()


def run() -> dict[str, object]:
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        # One fixed joint between two rigid bodies removes all six relative DOFs.
        PROJECT.new_project()
        fixed_a = _add(client, "Rank Fixed A", [_face("mount")])
        fixed_b = _add(client, "Rank Fixed B", [_face("mount")], [40.0, 20.0, 10.0])
        _mate(client, fixed_b, fixed_a, "mount", "mount", "fixed")
        fixed = _rank(client)
        fixed_component = fixed["components"][0]
        assert fixed_component["scalar_constraint_rows"] == 6, fixed_component
        assert fixed_component["jacobian_rank"] == 6, fixed_component
        assert fixed_component["mobility_dof"] == 0, fixed_component
        assert fixed_component["status"] == "fully_constrained", fixed_component

        # A revolute joint must expose exactly one physical mobility DOF rather
        # than being reported as an underconstraint.
        PROJECT.new_project()
        shaft_if = {"id": "shaft", "kind": "shaft", "position_mm": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "gender": "male", "mate": ["cylindrical_mate"]}
        bore_if = {"id": "bore", "kind": "cylindrical_mate", "position_mm": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "gender": "female", "mate": ["shaft"]}
        shaft = _add(client, "Rank Shaft", [shaft_if], [20.0, 10.0, 5.0])
        bearing = _add(client, "Rank Bearing", [bore_if])
        _mate(client, shaft, bearing, "shaft", "bore", "revolute")
        revolute = _rank(client)["components"][0]
        assert revolute["scalar_constraint_rows"] == 5, revolute
        assert revolute["jacobian_rank"] == 5, revolute
        assert revolute["mobility_dof"] == 1, revolute
        assert revolute["ideal_independent_constraint_mobility_dof"] == 1, revolute
        assert revolute["unexpected_mobility_dof"] == 0, revolute
        assert revolute["status"] == "mechanism", revolute

        # Two geometrically consistent fixed mates between the same two bodies
        # are redundant but not contradictory.  ForgeCAD should report the
        # redundancy instead of pretending there are 12 independent constraints.
        PROJECT.new_project()
        redundant_target = _add(client, "Rank Redundant Target", [_face("left", -5.0), _face("right", 5.0)])
        redundant_source = _add(client, "Rank Redundant Source", [_face("left", -5.0), _face("right", 5.0)], [60.0, 0.0, 0.0])
        _mate(client, redundant_source, redundant_target, "left", "left", "fixed")
        _mate(client, redundant_source, redundant_target, "right", "right", "fixed")
        redundant_result = _rank(client)
        redundant = redundant_result["components"][0]
        assert redundant_result["ok"] is True, redundant_result
        assert redundant["scalar_constraint_rows"] == 12, redundant
        assert redundant["jacobian_rank"] == 6, redundant
        assert redundant["mobility_dof"] == 0, redundant
        assert redundant["redundant_constraint_rows"] == 6, redundant
        assert redundant["status"] == "constrained_with_redundancy", redundant

        # Perturb the same fully constrained body.  Constraint rank itself stays
        # six, but the canonical residual validator must classify the assembly as
        # inconsistent rather than merely redundant.
        source_obj = next(row for row in core.PROJECT["objects"] if str(row.get("id")) == redundant_source)
        displaced = list(source_obj["transform"]["position"])
        displaced[0] = float(displaced[0]) + 1.0
        _ok(
            client.post(
                "/v2/operations",
                json={"op": "transform", "args": {"id": redundant_source, "position": displaced}, "reason": "inject multi-mate inconsistency"},
            ),
            "inject redundant-mate inconsistency",
        )
        inconsistent_result = _rank(client)
        inconsistent = inconsistent_result["components"][0]
        assert inconsistent_result["ok"] is False, inconsistent_result
        assert inconsistent["jacobian_rank"] == 6, inconsistent
        assert inconsistent["inconsistent"] is True, inconsistent
        assert inconsistent["status"] == "inconsistent", inconsistent

        return {
            "ok": True,
            "fixed_rank": fixed_component["jacobian_rank"],
            "revolute_mobility_dof": revolute["mobility_dof"],
            "redundant_constraint_rows": redundant["redundant_constraint_rows"],
            "inconsistent_multi_mate_detected": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
