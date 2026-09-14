from __future__ import annotations

"""Acceptance test for ForgeCAD 6.0 milestone 2.

The controlled fixture proves that an authoritative purchased-component mounting
pattern can drive editable fabricated CAD and that ForgeCAD independently checks
the final B-rep rather than trusting metadata alone.
"""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core, component_registry
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
        assert pi["component_ref"] == "compute.raspberry_pi_5_8gb", pi
        assert int(pi["component_snapshot"]["trust_score"]) >= 85, pi

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
        assert plan["pattern"]["source"] == "derived_rectangular_pattern_from_declared_spacing", plan
        expected_xy = sorted(
            (round(row["host_local_center_mm"][0], 3), round(row["host_local_center_mm"][1], 3))
            for row in plan["holes"]
        )
        assert expected_xy == [(-29.0, -24.5), (-29.0, 24.5), (29.0, -24.5), (29.0, 24.5)], expected_xy

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
        # correspondence.  Move the purchased component by 1 mm without changing
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

        # Fail closed on a real catalog entry whose legacy metadata declares two
        # holes and a 2-D spacing envelope but not the exact two hole centers.
        regulator = component_registry.component_by_id("power.pololu.d24v50f5")
        regulator_mount = next(row for row in regulator["interfaces"] if row["id"] == "mount")
        try:
            mount_pattern_definition(regulator_mount)
        except ValueError as exc:
            assert "will not guess" in str(exc), str(exc)
        else:
            raise AssertionError("Ambiguous two-hole mounting topology must fail closed")

        graph = _ok(client.post("/v3.1/graph/sync"), "sync graph after mount materialization").json()
        assert graph["ready"] is True, graph
        health = _ok(client.get("/v6/health"), "v6 health").json()
        assert health["current_milestone"] == "geometry_backed_assembly_truth", health
        assert health["geometry_backed_mount_count"] >= 1, health

        constraints = _ok(client.get("/v6/assembly/constraints"), "assembly constraint validation").json()
        assert constraints["ok"] is True, constraints

        canonical = _canonical()
        final_plate = next(row for row in canonical["objects"] if str(row.get("id")) == plate_id)
        claims = (final_plate.get("semantic") or {}).get("geometry_backed_mounts") or []
        assert len(claims) == 1, claims
        assert claims[0]["component_ref"] == "compute.raspberry_pi_5_8gb", claims
        assert len(claims[0]["feature_ids"]) == 4, claims

        return {
            "ok": True,
            "milestone": 2,
            "component_ref": pi["component_ref"],
            "mount_holes": 4,
            "pattern_source": plan["pattern"]["source"],
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
