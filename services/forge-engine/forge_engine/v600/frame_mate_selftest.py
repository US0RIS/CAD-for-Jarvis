from __future__ import annotations

"""Adversarial acceptance test for Milestone-2 full interface frames."""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _add_box(client: TestClient, name: str, interface: dict, position: list[float]) -> str:
    _ok(
        client.post(
            "/v2/operations",
            json={
                "op": "add",
                "args": {
                    "name": name,
                    "kind": "box",
                    "params": {"x": 20.0, "y": 20.0, "z": 4.0},
                    "transform": {"position": position, "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
                    "interfaces": [interface],
                },
                "reason": "Milestone 2 full-frame fixture",
            },
        ),
        f"add {name}",
    )
    return str(next(row for row in core.PROJECT["objects"] if row.get("name") == name)["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        common = {
            "kind": "mount_face",
            "axis": [0.0, 0.0, 1.0],
            "x_axis": [1.0, 0.0, 0.0],
            "gender": "neutral",
            "mate": ["mount_face"],
            "required": True,
            "metadata": {"max_connections": 1},
        }
        target_id = _add_box(client, "Frame Target", {"id": "mount", "position_mm": [0.0, 0.0, 2.0], **common}, [25.0, -10.0, 0.0])
        source_id = _add_box(client, "Frame Source", {"id": "mount", "position_mm": [0.0, 0.0, -2.0], **common}, [-40.0, 30.0, 15.0])

        applied = _ok(
            client.post(
                "/v6/assembly/mates/apply",
                json={
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_interface": "mount",
                    "target_interface": "mount",
                    "mate_type": "fixed",
                    "axis_relation": "aligned",
                    "clocking_deg": 37.0,
                    "clocking_tolerance_deg": 0.1,
                    "require_declared_secondary_datum": True,
                },
            ),
            "apply 37 degree full-frame mate",
        ).json()
        assert applied["frame_lock"] is True, applied
        assert applied["secondary_datums_declared"] is True, applied
        assert applied["residual"]["position_error_mm"] < 1e-8, applied
        assert applied["residual"]["axis_error_deg"] < 1e-8, applied
        assert applied["residual"]["clocking_error_deg"] < 1e-8, applied
        assert abs(float(applied["transform"]["rotation_deg"][2]) - 37.0) < 1e-7, applied

        valid = _ok(client.get("/v6/assembly/constraints"), "validate full-frame mate").json()
        assert valid["ok"] is True, valid

        source = next(row for row in core.PROJECT["objects"] if str(row.get("id")) == source_id)
        correct_rotation = json.loads(json.dumps(source["transform"]["rotation_deg"]))
        drifted = list(correct_rotation)
        drifted[2] = float(drifted[2]) + 5.0
        _ok(
            client.post(
                "/v2/operations",
                json={"op": "transform", "args": {"id": source_id, "rotation_deg": drifted}, "reason": "inject clocking drift"},
            ),
            "inject 5 degree clocking error",
        )
        invalid = _ok(client.get("/v6/assembly/constraints"), "detect clocking error").json()
        assert invalid["ok"] is False, invalid
        clocking = [row for row in invalid["findings"] if row.get("code") == "mate_clocking_residual"]
        assert clocking and abs(float(clocking[0]["residual_deg"]) - 5.0) < 1e-6, clocking

        _ok(
            client.post(
                "/v2/operations",
                json={"op": "transform", "args": {"id": source_id, "rotation_deg": correct_rotation}, "reason": "restore full-frame mate"},
            ),
            "restore clocking",
        )
        restored = _ok(client.get("/v6/assembly/constraints"), "validate restored mate").json()
        assert restored["ok"] is True, restored

        # A revolute constraint must keep rotation about its axis free.  Solve it
        # on separate, unoccupied interfaces and ensure full-frame lock is absent.
        shaft_id = _add_box(
            client,
            "Revolute Shaft",
            {"id": "shaft", "kind": "shaft", "position_mm": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "gender": "male", "mate": ["cylindrical_mate"]},
            [-50.0, -50.0, 0.0],
        )
        bearing_id = _add_box(
            client,
            "Revolute Bearing",
            {"id": "bore", "kind": "cylindrical_mate", "position_mm": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "gender": "female", "mate": ["shaft"]},
            [50.0, 50.0, 0.0],
        )
        revolute = _ok(
            client.post(
                "/v6/assembly/mates/solve",
                json={
                    "source_id": shaft_id,
                    "target_id": bearing_id,
                    "source_interface": "shaft",
                    "target_interface": "bore",
                    "mate_type": "revolute",
                },
            ),
            "solve revolute mate",
        ).json()
        assert revolute["frame_lock"] is False, revolute
        assert revolute["degrees_of_freedom"]["allowed"] == ["rotation_about_axis"], revolute

        # Strict mode proves legacy inferred X datums are distinguishable from
        # authoritative rotational datums and can be rejected when required.
        no_datum_id = _add_box(
            client,
            "No Datum Source",
            {"id": "mount", "kind": "mount_face", "position_mm": [0.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0], "gender": "neutral", "mate": ["mount_face"]},
            [0.0, 60.0, 0.0],
        )
        strict = client.post(
            "/v6/assembly/mates/solve",
            json={
                "source_id": no_datum_id,
                "target_id": target_id,
                "source_interface": "mount",
                "target_interface": "mount",
                "mate_type": "fixed",
                "axis_relation": "aligned",
                "require_declared_secondary_datum": True,
                "allow_occupied": True,
            },
        )
        assert strict.status_code == 409, strict.text
        assert "secondary rotational datum" in strict.text, strict.text

        return {
            "ok": True,
            "fixed_full_frame": True,
            "clocking_deg": 37.0,
            "clocking_drift_detected_deg": 5.0,
            "revolute_rotation_remains_free": True,
            "strict_secondary_datum_fail_closed": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
