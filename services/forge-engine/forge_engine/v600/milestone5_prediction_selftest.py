from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core
from ..v200.physical_evidence import design_fingerprint
from ..v200.structural_fea import solve_box


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _add_box(client: TestClient, name: str, z: float, *, repair: bool = False) -> str:
    semantic = {}
    if repair:
        semantic = {
            "repair_authority": {
                "parameters": {"z": {"enabled": True, "min": 4.0, "max": 14.0}}
            }
        }
    _ok(client.post("/v2/operations", json={
        "op": "add",
        "args": {
            "name": name,
            "kind": "box",
            "params": {"x": 80.0, "y": 20.0, "z": z},
            "material": "aluminum_6061_t6",
            "semantic": semantic,
        },
        "reason": f"Create {name}",
    }), f"create {name}")
    return str(next(row for row in core.PROJECT["objects"] if row.get("name") == name)["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        object_id = _add_box(client, "M5 Prediction Beam", 8.0, repair=True)
        other_id = _add_box(client, "M5 Other Beam", 8.0)
        requirement_id = "m5-prediction-observation"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Physical deflection remains within broad acceptance envelope",
            "metric": "physical_deflection_mm",
            "op": "<=",
            "target": 10.0,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-prediction-acceptance",
            "confidence": 1.0,
        }), "create prediction requirement")

        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "initial bench deflection",
            "measurements": [
                {"name": "deflection_total", "value": 20.0, "unit": "mm"},
                {"name": "deflection_axis", "value": 20.0, "unit": "mm"},
            ],
        }), "record prediction source failure").json()["evidence"]

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [{"object_id": object_id, "parameter": "z", "value": 10.0}],
            "criteria": [
                {"measurement": "deflection_total", "object_id": object_id, "unit": "mm", "op": "<=", "target": 10.0},
                {"measurement": "deflection_axis", "object_id": object_id, "unit": "mm", "op": "<=", "target": 10.0},
            ],
            "branch_prefix": "m5-prediction",
            "diagnosis": "Increasing section thickness is a structural hypothesis only.",
        }), "begin prediction retest").json()
        cycle_id = str(begun["cycle"]["id"])
        fingerprint = str(begun["cycle"]["redesign_design_fingerprint"])
        assert design_fingerprint() == fingerprint

        obj = core.object_by_id(object_id)
        solve = solve_box(obj, force_n=100.0, load_direction="z", mesh_counts=(4, 2, 2))
        assert solve["supported"] is True, solve
        current_sim = core.record_simulation(
            "m5_structural_prediction",
            object_id,
            {"force_n": 100.0, "load_direction": "z", "mesh_counts": [4, 2, 2]},
            solve,
        )
        predicted_total = float(solve["max_displacement_mm"])
        predicted_axis = float(solve["max_loaded_component_displacement_mm"])

        stale_sim = core.record_simulation(
            "m5_stale_prediction",
            object_id,
            {"force_n": 100.0},
            solve,
        )
        stale_sim["stale"] = True
        core.persist()

        other_solve = solve_box(core.object_by_id(other_id), force_n=100.0, load_direction="z", mesh_counts=(4, 2, 2))
        other_sim = core.record_simulation(
            "m5_wrong_object_prediction",
            other_id,
            {"force_n": 100.0},
            other_solve,
        )

        stale = client.post(f"/v6/physical/retest-cycles/{cycle_id}/prediction-contract", json={
            "bindings": [{
                "measurement": "deflection_total",
                "unit": "mm",
                "simulation_id": stale_sim["id"],
                "result_path": "max_displacement_mm",
                "max_abs_residual": 0.05,
            }],
        })
        assert stale.status_code == 409, stale.text
        assert "stale simulation" in stale.text, stale.text

        wrong_object = client.post(f"/v6/physical/retest-cycles/{cycle_id}/prediction-contract", json={
            "bindings": [{
                "measurement": "deflection_total",
                "unit": "mm",
                "simulation_id": other_sim["id"],
                "result_path": "max_displacement_mm",
                "max_abs_residual": 0.05,
            }],
        })
        assert wrong_object.status_code == 409, wrong_object.text
        assert "not criterion object" in wrong_object.text, wrong_object.text

        wrong_path = client.post(f"/v6/physical/retest-cycles/{cycle_id}/prediction-contract", json={
            "bindings": [{
                "measurement": "deflection_total",
                "unit": "mm",
                "simulation_id": current_sim["id"],
                "result_path": "does.not.exist",
                "max_abs_residual": 0.05,
            }],
        })
        assert wrong_path.status_code == 409, wrong_path.text
        assert "does not exist" in wrong_path.text, wrong_path.text

        locked = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/prediction-contract", json={
            "bindings": [
                {
                    "measurement": "deflection_total",
                    "unit": "mm",
                    "simulation_id": current_sim["id"],
                    "result_path": "max_displacement_mm",
                    "max_abs_residual": 0.05,
                    "max_relative_residual_fraction": 0.50,
                },
                {
                    "measurement": "deflection_axis",
                    "unit": "mm",
                    "simulation_id": current_sim["id"],
                    "result_path": "max_loaded_component_displacement_mm",
                    "max_abs_residual": 0.05,
                },
            ],
        }), "lock prediction residual contract").json()
        bindings = locked["contract"]["bindings"]
        assert len(bindings) == 2, bindings
        assert bindings[0]["simulation_record_sha256"], bindings
        assert bindings[0]["solver_metadata"]["solver_grade"] == "engineering_iteration", bindings[0]
        assert locked["contract"]["automatic_model_tuning"] is False, locked

        observed_total = predicted_total + 0.20
        observed_axis = predicted_axis + 0.01
        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "instrumented beam deflection",
            "measurements": [
                {"name": "deflection_total", "value": observed_total, "unit": "mm"},
                {"name": "deflection_axis", "value": observed_axis, "unit": "mm"},
            ],
            "instrument": "synthetic-displacement-gauge",
            "confidence": 0.95,
            "note": "Physical acceptance can pass while a simulation residual still exceeds the declared model-error budget.",
        }), "complete prediction retest").json()
        assert completed["derived_retest_status"] == "passed", completed
        residuals = completed["prediction_residuals"]
        assert residuals["required"] is True, residuals
        assert residuals["count"] == 2, residuals
        assert residuals["discrepancy_count"] == 1, residuals
        by_measurement = {row["measurement"]: row for row in residuals["items"]}
        assert by_measurement["deflection_total"]["status"] == "model_test_discrepancy", by_measurement
        assert abs(by_measurement["deflection_total"]["residual"] - 0.20) < 1e-9, by_measurement
        assert by_measurement["deflection_axis"]["status"] == "within_declared_model_error_budget", by_measurement
        assert by_measurement["deflection_total"]["causality_status"] == "unattributed_discrepancy", by_measurement
        assert residuals["automatic_model_tuning"] is False, residuals
        assert completed["entire_design_physically_verified"] is False, completed

        listed = _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/prediction-residuals"), "list prediction residuals").json()
        assert len(listed["items"]) == 2, listed
        assert listed["contract"]["bindings"][0]["predicted_value"] == predicted_total, listed

        graph = _ok(client.get("/v3.1/graph"), "read prediction residual graph").json()
        graph_residuals = [
            row for row in graph["evidence"]
            if row["kind"] == "physical_prediction_residual" and row["metadata"].get("cycle_id") == cycle_id
        ]
        assert len(graph_residuals) == 2, graph_residuals
        assert all(row["stale"] is False for row in graph_residuals), graph_residuals
        assert all(current_sim["id"] in row["source_ids"] for row in graph_residuals), graph_residuals
        residual_evidence_ids = {row["id"] for row in graph_residuals}

        core.object_by_id(object_id)["params"]["x"] = 81.0
        core.persist()
        _ok(client.post("/v3.1/graph/sync"), "sync graph after prediction CAD change")
        stale_graph = _ok(client.get("/v3.1/graph"), "read stale prediction residual graph").json()
        stale_rows = [row for row in stale_graph["evidence"] if row["id"] in residual_evidence_ids]
        assert len(stale_rows) == 2, stale_rows
        assert all(row["stale"] is True for row in stale_rows), stale_rows

        return {
            "ok": True,
            "milestone": 5,
            "slice": "revision_bound_prediction_vs_physical_observation_residuals",
            "stale_simulation_rejected": True,
            "wrong_object_simulation_rejected": True,
            "invalid_prediction_path_rejected": True,
            "simulation_record_frozen_before_physical_completion": True,
            "physical_requirement_can_pass_while_model_discrepancy_is_flagged": True,
            "within_budget_and_discrepancy_classifications_supported": True,
            "residual_causality_not_overclaimed": True,
            "automatic_model_tuning_disabled": True,
            "residual_graph_evidence_stales_after_cad_change": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
