from __future__ import annotations

import base64
import hashlib
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


def _run_payload(run_id: str, specimen_id: str, clearance: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "specimen_id": specimen_id,
        "operator_ref": "operator-fixture",
        "fixture_id": "fit-fixture-01",
        "measurements": [{"name": "clearance", "value": clearance, "unit": "mm"}],
        "environment": [
            {"name": "ambient_temperature", "value": 23.0, "unit": "degC"},
            {"name": "relative_humidity", "value": 45.0, "unit": "%"},
        ],
    }


def _begin_cycle(client: TestClient, requirement_id: str, failed_evidence_id: str, object_id: str, value: float, prefix: str) -> dict[str, object]:
    return _ok(client.post("/v6/physical/retest-cycles", json={
        "requirement_id": requirement_id,
        "failed_evidence_id": failed_evidence_id,
        "mutations": [{"object_id": object_id, "parameter": "z", "value": value}],
        "criteria": [{"measurement": "clearance", "unit": "mm", "op": ">=", "target": 0.2}],
        "branch_prefix": prefix,
        "diagnosis": "Thickness change is a testable fit hypothesis, not proven causality.",
    }), f"begin {prefix}").json()


def _lock_execution(client: TestClient, cycle_id: str, *, procedure_artifact_id: str | None = None, procedure_sha256: str | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "procedure_id": "FIT-PROC-001",
        "procedure_revision": "A",
        "min_runs": 3,
        "require_unique_specimens": True,
        "environment_requirements": [
            {"name": "ambient_temperature", "unit": "degC"},
            {"name": "relative_humidity", "unit": "%"},
        ],
    }
    if procedure_artifact_id is not None:
        body["procedure_artifact_id"] = procedure_artifact_id
        body["require_verified_procedure_artifact"] = True
    if procedure_sha256 is not None:
        body["procedure_sha256"] = procedure_sha256
    return _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/execution-contract", json=body), "lock execution contract").json()


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        _ok(client.post("/v2/operations", json={
            "op": "add",
            "args": {
                "name": "M5 Repeatability Coupon",
                "kind": "box",
                "params": {"x": 80.0, "y": 20.0, "z": 10.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "repair_authority": {
                        "parameters": {"z": {"enabled": True, "min": 6.0, "max": 12.0}}
                    }
                },
            },
            "reason": "Create milestone 5 repeatability fixture",
        }), "create repeatability coupon")
        object_id = str(next(row for row in core.PROJECT["objects"] if row.get("name") == "M5 Repeatability Coupon")["id"])

        requirement_id = "m5-repeatable-clearance"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Repeatable physical clearance",
            "metric": "physical_clearance_mm",
            "op": ">=",
            "target": 0.2,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-repeatability-acceptance",
            "confidence": 1.0,
        }), "create repeatability requirement")

        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "initial fit check",
            "measurements": [{"name": "clearance", "value": -0.2, "unit": "mm"}],
        }), "record source fit failure").json()["evidence"]
        assert failed["design_fingerprint"] == source_fingerprint

        # First redesign: two favorable runs cannot hide one failing specimen.
        first = _begin_cycle(client, requirement_id, str(failed["id"]), object_id, 8.0, "m5-repeat-fail")
        first_cycle_id = str(first["cycle"]["id"])
        _lock_execution(client, first_cycle_id)

        missing_environment = client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/test-runs", json={
            "runs": [{
                "run_id": "bad-env",
                "specimen_id": "bad-env-specimen",
                "measurements": [{"name": "clearance", "value": 0.3, "unit": "mm"}],
                "environment": [{"name": "ambient_temperature", "value": 23.0, "unit": "degC"}],
            }],
        })
        assert missing_environment.status_code == 409, missing_environment.text
        assert "relative_humidity" in missing_environment.text, missing_environment.text
        assert _ok(client.get(f"/v6/physical/retest-cycles/{first_cycle_id}/test-runs"), "read empty runs").json()["count"] == 0

        duplicate_specimen = client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/test-runs", json={
            "runs": [
                _run_payload("dup-1", "same-specimen", 0.3),
                _run_payload("dup-2", "same-specimen", 0.3),
            ],
        })
        assert duplicate_specimen.status_code == 409, duplicate_specimen.text
        assert "unique specimens" in duplicate_specimen.text, duplicate_specimen.text
        assert _ok(client.get(f"/v6/physical/retest-cycles/{first_cycle_id}/test-runs"), "read empty runs after duplicate").json()["count"] == 0

        first_runs = _ok(client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/test-runs", json={
            "runs": [
                _run_payload("run-1", "specimen-1", 0.30),
                _run_payload("run-2", "specimen-2", 0.18),
                _run_payload("run-3", "specimen-3", 0.31),
            ],
        }), "record mixed repeatability runs").json()
        assert first_runs["total_run_count"] == 3, first_runs

        injected_summary = client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/complete", json={
            "status": "passed",
            "method": "repeatability fixture",
            "measurements": [{"name": "clearance", "value": 999.0, "unit": "mm"}],
        })
        assert injected_summary.status_code == 409, injected_summary.text
        assert "derives completion measurements" in injected_summary.text, injected_summary.text

        hidden_failure = client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/complete", json={
            "status": "passed",
            "method": "repeatability fixture",
        })
        assert hidden_failure.status_code == 409, hidden_failure.text
        assert "criterion-derived status 'failed'" in hidden_failure.text, hidden_failure.text
        assert not core.PROJECT.get("inspections"), core.PROJECT.get("inspections")

        first_completed = _ok(client.post(f"/v6/physical/retest-cycles/{first_cycle_id}/complete", json={
            "status": "failed",
            "method": "repeatability fixture",
            "note": "One of three specimens failed the locked clearance criterion.",
        }), "record repeatability failure").json()
        first_eval = first_completed["test_execution_evaluation"]
        assert first_eval["derived_measurements"][0]["value"] == 0.18, first_eval
        assert first_eval["all_required_runs_passed"] is False, first_eval
        assert first_completed["derived_retest_status"] == "failed", first_completed

        # Second redesign begins again from the untouched source failure. It must not
        # inherit the first redesign's run observations.
        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        assert not core.PROJECT.get("physical_test_runs"), core.PROJECT.get("physical_test_runs")
        second = _begin_cycle(client, requirement_id, str(failed["id"]), object_id, 7.5, "m5-repeat-pass")
        second_cycle_id = str(second["cycle"]["id"])
        second_fingerprint = str(second["cycle"]["redesign_design_fingerprint"])

        # Bind the execution contract to byte-verified procedure content. File
        # integrity is proven, but authorship/adequacy/compliance remain unverified.
        procedure = b"FIT-PROC-001 revision A\nMeasure clearance at three points.\n"
        procedure_sha = hashlib.sha256(procedure).hexdigest()
        _ok(client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/artifact-contract", json={
            "requirements": [{"kind": "report", "min_count": 1, "require_integrity_verified": True}],
        }), "lock procedure artifact contract")
        artifact = _ok(client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "FIT-PROC-001-A.txt",
                "kind": "report",
                "media_type": "text/plain",
                "sha256": procedure_sha,
                "size_bytes": len(procedure),
                "content_base64": base64.b64encode(procedure).decode("ascii"),
                "note": "Synthetic acceptance procedure; byte integrity only.",
            }],
        }), "submit verified procedure bytes").json()["items"][0]
        contract = _lock_execution(
            client,
            second_cycle_id,
            procedure_artifact_id=str(artifact["id"]),
            procedure_sha256=procedure_sha,
        )
        assert contract["contract"]["procedure_integrity_verified"] is True, contract
        assert contract["contract"]["procedure_authenticity_verified"] is False, contract

        first_two = _ok(client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/test-runs", json={
            "runs": [
                _run_payload("pass-1", "pass-specimen-1", 0.28),
                _run_payload("pass-2", "pass-specimen-2", 0.32),
            ],
        }), "record first two passing runs").json()
        assert first_two["total_run_count"] == 2, first_two

        too_few = client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/complete", json={
            "status": "passed",
            "method": "repeatability fixture",
        })
        assert too_few.status_code == 409, too_few.text
        assert "requires at least 3 runs" in too_few.text, too_few.text

        duplicate_run = client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/test-runs", json={
            "runs": [_run_payload("pass-2", "pass-specimen-x", 0.4)],
        })
        assert duplicate_run.status_code == 409, duplicate_run.text
        assert "run_id" in duplicate_run.text and "duplicated" in duplicate_run.text, duplicate_run.text

        third = _ok(client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/test-runs", json={
            "runs": [_run_payload("pass-3", "pass-specimen-3", 0.26)],
        }), "record third passing run").json()
        assert third["total_run_count"] == 3, third

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{second_cycle_id}/complete", json={
            "status": "passed",
            "method": "repeatability fixture",
            "note": "All three independently identified specimens cleared the criterion.",
        }), "complete repeatable physical retest").json()
        evaluation = completed["test_execution_evaluation"]
        assert evaluation["required"] is True, evaluation
        assert evaluation["run_count"] == 3, evaluation
        assert evaluation["all_required_runs_passed"] is True, evaluation
        assert evaluation["derived_measurements"][0]["value"] == 0.26, evaluation
        assert completed["criterion_results"][0]["value"] == 0.26, completed
        assert len(completed["test_runs"]) == 3, completed
        inspection_ids = completed["cycle"]["inspection_ids"]
        assert inspection_ids, completed
        assert all(row["inspection_ids"] == inspection_ids for row in completed["test_runs"]), completed["test_runs"]
        assert completed["entire_design_physically_verified"] is False, completed
        assert design_fingerprint() == second_fingerprint

        graph = _ok(client.get("/v3.1/graph"), "read repeatability graph").json()
        run_evidence = [
            row for row in graph["evidence"]
            if row["kind"] == "physical_test_run" and row["id"] in set(evaluation["evidence_ids"])
        ]
        assert len(run_evidence) == 3, run_evidence
        assert all(row["stale"] is False for row in run_evidence), run_evidence
        assert all(row["metadata"]["procedure_authenticity_verified"] is False for row in run_evidence), run_evidence

        core.object_by_id(object_id)["params"]["x"] = 81.0
        core.persist()
        _ok(client.post("/v3.1/graph/sync"), "sync graph after repeatability CAD change")
        stale_graph = _ok(client.get("/v3.1/graph"), "read stale repeatability evidence").json()
        stale_run_evidence = [
            row for row in stale_graph["evidence"]
            if row["id"] in {item["id"] for item in run_evidence}
        ]
        assert len(stale_run_evidence) == 3, stale_run_evidence
        assert all(row["stale"] is True for row in stale_run_evidence), stale_run_evidence

        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        assert not core.PROJECT.get("physical_test_runs"), core.PROJECT.get("physical_test_runs")

        return {
            "ok": True,
            "milestone": 5,
            "slice": "repeatable_revision_bound_physical_test_execution",
            "missing_environment_rejected_without_run_write": True,
            "duplicate_specimen_rejected_when_unique_required": True,
            "manual_summary_injection_blocked": True,
            "single_failing_run_cannot_hide_behind_favorable_mean": True,
            "minimum_run_count_enforced": True,
            "duplicate_run_identity_rejected": True,
            "verified_procedure_bytes_bound_to_execution_contract": True,
            "procedure_adequacy_and_compliance_not_overclaimed": True,
            "completion_uses_worst_observed_required_run": True,
            "test_run_evidence_links_to_inspection_and_stales_after_cad_change": True,
            "source_branch_does_not_inherit_retest_runs": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
