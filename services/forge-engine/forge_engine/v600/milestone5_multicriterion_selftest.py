from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core
from ..v200.physical_evidence import design_fingerprint


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _add_box(client: TestClient, name: str, params: dict[str, float], repair_parameter: str) -> str:
    _ok(client.post("/v2/operations", json={
        "op": "add",
        "args": {
            "name": name,
            "kind": "box",
            "params": params,
            "material": "aluminum_6061_t6",
            "semantic": {
                "role": "m5_multi_object_fixture",
                "repair_authority": {
                    "parameters": {
                        repair_parameter: {
                            "enabled": True,
                            "min": float(params[repair_parameter]) * 0.5,
                            "max": float(params[repair_parameter]) * 1.2,
                        }
                    }
                },
            },
        },
        "reason": f"Create milestone 5 multi-object fixture {name}",
    }), f"create {name}")
    return str(next(row for row in core.PROJECT["objects"] if row.get("name") == name)["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        bracket_id = _add_box(client, "M5 Multi Bracket", {"x": 80.0, "y": 24.0, "z": 10.0}, "z")
        shield_id = _add_box(client, "M5 Multi Thermal Shield", {"x": 60.0, "y": 30.0, "z": 2.0}, "y")
        requirement_id = "m5-multi-physical-acceptance"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Multi-object bench acceptance",
            "metric": "physical_test_plan",
            "criticality": "important",
            "scope_object_ids": [bracket_id, shield_id],
            "source": "v600-milestone5-multicriterion-acceptance",
            "confidence": 1.0,
            "rationale": "Bracket fit and shield temperature must both satisfy the physical test plan.",
        }), "create multi-object physical requirement")

        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "bench integration test",
            "note": "Initial assembly interfered and exceeded the thermal target.",
            "measurements": [
                {"name": "clearance", "value": -0.3, "unit": "mm"},
                {"name": "surface_temperature", "value": 58.0, "unit": "degC"},
            ],
        }), "record multi-object source failure").json()["evidence"]
        assert failed["design_fingerprint"] == source_fingerprint

        # A multi-object requirement cannot silently guess which CAD identity a
        # physical measurement belongs to.
        ambiguous = client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [
                {"object_id": bracket_id, "parameter": "z", "value": 8.0},
                {"object_id": shield_id, "parameter": "y", "value": 28.0},
            ],
            "criteria": [
                {"measurement": "clearance", "unit": "mm", "op": ">=", "target": 0.2},
                {"measurement": "surface_temperature", "unit": "degC", "op": "between", "minimum": 20.0, "maximum": 50.0},
            ],
        })
        assert ambiguous.status_code == 409, ambiguous.text
        assert "must declare object_id" in ambiguous.text, ambiguous.text
        assert core.ACTIVE_DESIGN == source_branch
        assert design_fingerprint() == source_fingerprint

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [
                {"object_id": bracket_id, "parameter": "z", "value": 8.0},
                {"object_id": shield_id, "parameter": "y", "value": 28.0},
            ],
            "criteria": [
                {"measurement": "clearance", "object_id": bracket_id, "unit": "mm", "op": ">=", "target": 0.2},
                {"measurement": "surface_temperature", "object_id": shield_id, "unit": "degC", "op": "between", "minimum": 20.0, "maximum": 50.0},
                {"measurement": "vibration_rms", "object_id": bracket_id, "unit": "mm/s", "op": "<=", "target": 1.0, "required": False},
            ],
            "branch_prefix": "m5-multi-retest",
            "diagnosis": "Geometry and heat-flow changes are test hypotheses only; the source observations do not establish causality.",
        }), "begin explicit multi-object retest").json()
        cycle_id = str(begun["cycle"]["id"])
        redesign_branch = str(begun["cycle"]["redesign_branch"])
        redesign_fingerprint = str(begun["cycle"]["redesign_design_fingerprint"])
        assert redesign_branch != source_branch
        assert design_fingerprint() == redesign_fingerprint
        assert {row["object_id"] for row in begun["cycle"]["test_criteria"]} == {bracket_id, shield_id}

        # Both physical constraints must pass. A typed overall pass cannot override
        # one objectively failing criterion, and rejection writes no inspections.
        partial_failure = client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "bench integration test",
            "measurements": [
                {"name": "clearance", "value": 0.4, "unit": "mm"},
                {"name": "surface_temperature", "value": 55.0, "unit": "degC"},
            ],
            "instrument": "fixture-caliper-plus-thermocouple",
            "confidence": 0.95,
        })
        assert partial_failure.status_code == 409, partial_failure.text
        assert "contradicts criterion-derived status 'failed'" in partial_failure.text, partial_failure.text
        assert not core.PROJECT.get("inspections"), core.PROJECT.get("inspections")

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "bench integration test",
            "measurements": [
                {"name": "clearance", "value": 0.4, "unit": "mm"},
                {"name": "surface_temperature", "value": 36.0, "unit": "degC"},
            ],
            "instrument": "fixture-caliper-plus-thermocouple",
            "confidence": 0.95,
        }), "complete multi-object retest").json()
        assert completed["derived_retest_status"] == "passed", completed
        results = {row["measurement"]: row for row in completed["criterion_results"]}
        assert results["clearance"]["passed"] is True, results
        assert results["surface_temperature"]["passed"] is True, results
        assert results["vibration_rms"]["status"] == "missing" and results["vibration_rms"]["passed"] is None, results
        inspections = completed["inspections"]
        assert len(inspections) == 2, inspections
        observation_by_metric = {row["record"]["metric"]: row["record"] for row in inspections}
        assert observation_by_metric["clearance"]["object_id"] == bracket_id, observation_by_metric
        assert observation_by_metric["surface_temperature"]["object_id"] == shield_id, observation_by_metric
        assert completed["entire_design_physically_verified"] is False, completed
        assert design_fingerprint() == redesign_fingerprint

        graph = _ok(client.get("/v3.1/graph"), "read multi-object physical graph").json()
        inspection_ids = {str(row["record"]["id"]): str(row["record"]["object_id"]) for row in inspections}
        graph_inspections = {
            str(node["source_id"]): node
            for node in graph["nodes"]
            if node["kind"] == "inspection" and str(node.get("source_id")) in inspection_ids
        }
        assert set(graph_inspections) == set(inspection_ids), graph_inspections
        for inspection_id, object_id in inspection_ids.items():
            node_id = graph_inspections[inspection_id]["id"]
            assert any(
                edge["kind"] == "observes" and edge["from_id"] == node_id and edge["to_id"] == f"cad:{object_id}"
                for edge in graph["edges"]
            ), {"inspection_id": inspection_id, "object_id": object_id}

        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        assert not core.PROJECT.get("inspections"), core.PROJECT.get("inspections")

        return {
            "ok": True,
            "milestone": 5,
            "slice": "multi_object_multi_criterion_physical_retest",
            "ambiguous_measurement_identity_rejected": True,
            "mixed_threshold_and_range_criteria_supported": True,
            "optional_measurement_may_remain_missing": True,
            "partial_failure_cannot_be_overridden_by_declared_pass": True,
            "physical_observations_bound_to_correct_cad_objects": True,
            "source_branch_does_not_inherit_retest_observations": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
