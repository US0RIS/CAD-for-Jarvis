from __future__ import annotations

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


def _run(run_id: str, specimen_id: str, value: float) -> dict[str, object]:
    return {
        "run_id": run_id,
        "specimen_id": specimen_id,
        "operator_ref": "specimen-lineage-fixture",
        "fixture_id": "fit-fixture-02",
        "measurements": [{"name": "clearance", "value": value, "unit": "mm"}],
    }


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        _ok(client.post("/v2/operations", json={
            "op": "add",
            "args": {
                "name": "M5 Provenance Coupon",
                "kind": "box",
                "params": {"x": 70.0, "y": 22.0, "z": 9.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "repair_authority": {
                        "parameters": {"z": {"enabled": True, "min": 5.0, "max": 12.0}}
                    }
                },
            },
            "reason": "Create milestone 5 specimen provenance fixture",
        }), "create provenance coupon")
        object_id = str(next(row for row in core.PROJECT["objects"] if row.get("name") == "M5 Provenance Coupon")["id"])

        requirement_id = "m5-package-linked-specimens"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Package-linked physical clearance",
            "metric": "physical_clearance_mm",
            "op": ">=",
            "target": 0.2,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-specimen-acceptance",
            "confidence": 1.0,
        }), "create specimen requirement")

        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "initial fit check",
            "measurements": [{"name": "clearance", "value": -0.1, "unit": "mm"}],
        }), "record source failure").json()["evidence"]

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [{"object_id": object_id, "parameter": "z", "value": 7.5}],
            "criteria": [{"measurement": "clearance", "unit": "mm", "op": ">=", "target": 0.2}],
            "branch_prefix": "m5-specimen",
            "diagnosis": "Reduced thickness is a fit hypothesis only.",
        }), "begin provenance retest").json()
        cycle_id = str(begun["cycle"]["id"])
        redesign_fingerprint = str(begun["cycle"]["redesign_design_fingerprint"])
        assert design_fingerprint() == redesign_fingerprint

        package_response = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/fabrication-package", json={
            "name": "M5 Provenance Fixture",
            "processes": {object_id: "cnc"},
            "include_step": True,
            "include_stl": False,
        }), "generate provenance fabrication package")
        package_bytes = package_response.content
        package_id = str(package_response.headers["X-ForgeCAD-Physical-Package-ID"])
        package_sha = str(package_response.headers["X-ForgeCAD-Fabrication-SHA256"])
        assert hashlib.sha256(package_bytes).hexdigest() == package_sha
        assert package_response.headers["X-ForgeCAD-Design-Fingerprint"] == redesign_fingerprint

        package_listing = _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/fabrication-packages"), "list fabrication packages").json()
        assert package_listing["count"] == 1, package_listing
        package_record = package_listing["items"][0]
        assert package_record["id"] == package_id, package_record
        assert package_record["archive_sha256"] == package_sha, package_record
        assert package_record["package_identity_verified"] is True, package_record
        assert package_record["raw_archive_persisted"] is False, package_record
        assert package_record["physical_build_verified"] is False, package_record

        manufacturing = _ok(client.post("/v2/evidence/manufacturing", json={
            "package_sha256": package_sha,
            "resource_id": "m5-cnc-fixture",
            "outcome": "success",
            "material": "aluminum_6061_t6",
            "machine_profile": "synthetic-acceptance-cnc",
            "observations": ["Synthetic acceptance records a successful package-hash build claim."],
            "note": "This evidence does not physically authenticate any later specimen label.",
        }), "record matching manufacturing evidence").json()["evidence"]
        assert manufacturing["design_fingerprint"] == redesign_fingerprint

        mismatched = _ok(client.post("/v2/evidence/manufacturing", json={
            "package_sha256": "0" * 64,
            "resource_id": "m5-cnc-fixture",
            "outcome": "success",
            "note": "Deliberately wrong package hash for rejection coverage.",
        }), "record mismatched manufacturing evidence").json()["evidence"]

        specimen_a = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/specimens", json={
            "specimen_id": "specimen-A",
            "fabrication_package_id": package_id,
            "manufacturing_evidence_id": manufacturing["id"],
            "label": "A",
        }), "register specimen A").json()["record"]
        assert specimen_a["matching_manufacturing_evidence"] is True, specimen_a
        assert specimen_a["package_identity_verified"] is True, specimen_a
        assert specimen_a["physical_specimen_identity_verified"] is False, specimen_a

        bad_hash = client.post(f"/v6/physical/retest-cycles/{cycle_id}/specimens", json={
            "specimen_id": "specimen-bad-hash",
            "fabrication_package_id": package_id,
            "manufacturing_evidence_id": mismatched["id"],
        })
        assert bad_hash.status_code == 409, bad_hash.text
        assert "package hash does not match" in bad_hash.text, bad_hash.text

        specimen_b_weak = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/specimens", json={
            "specimen_id": "specimen-B-weak",
            "fabrication_package_id": package_id,
            "label": "B-weak",
        }), "register weak specimen B").json()["record"]
        assert specimen_b_weak["matching_manufacturing_evidence"] is False

        specimen_c = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/specimens", json={
            "specimen_id": "specimen-C",
            "fabrication_package_id": package_id,
            "manufacturing_evidence_id": manufacturing["id"],
            "label": "C",
        }), "register specimen C").json()["record"]
        assert specimen_c["matching_manufacturing_evidence"] is True

        specimens = _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/specimens"), "list specimens").json()
        assert specimens["count"] == 3, specimens
        assert specimens["physical_specimen_identity_verified_count"] == 0, specimens

        _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/specimen-contract", json={
            "require_registered_specimens": True,
            "require_matching_manufacturing_evidence": True,
        }), "lock specimen contract")
        _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/execution-contract", json={
            "procedure_id": "FIT-PROC-002",
            "procedure_revision": "A",
            "min_runs": 2,
            "require_unique_specimens": True,
        }), "lock execution contract")

        unregistered = client.post(f"/v6/physical/retest-cycles/{cycle_id}/test-runs", json={
            "runs": [_run("unregistered-run", "specimen-unregistered", 0.3)],
        })
        assert unregistered.status_code == 409, unregistered.text
        assert "not registered" in unregistered.text, unregistered.text
        assert _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/test-runs"), "check no unregistered write").json()["count"] == 0

        weak = client.post(f"/v6/physical/retest-cycles/{cycle_id}/test-runs", json={
            "runs": [_run("weak-run", "specimen-B-weak", 0.3)],
        })
        assert weak.status_code == 409, weak.text
        assert "lacks matching successful manufacturing evidence" in weak.text, weak.text
        assert _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/test-runs"), "check no weak write").json()["count"] == 0

        submitted = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/test-runs", json={
            "runs": [
                _run("run-A", "specimen-A", 0.30),
                _run("run-C", "specimen-C", 0.27),
            ],
        }), "record package-linked specimen runs").json()
        assert submitted["specimen_lineage_applied"] is True, submitted
        assert submitted["total_run_count"] == 2, submitted
        for row in submitted["items"]:
            assert row["fabrication_package_id"] == package_id, row
            assert row["fabrication_package_sha256"] == package_sha, row
            assert row["manufacturing_evidence_id"] == manufacturing["id"], row
            assert row["matching_manufacturing_evidence"] is True, row
            assert row["physical_specimen_identity_verified"] is False, row

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "package-linked repeatability fixture",
            "note": "Both registered specimen claims passed; physical identity remains unverified.",
        }), "complete specimen provenance retest").json()
        assert completed["derived_retest_status"] == "passed", completed
        assert completed["criterion_results"][0]["value"] == 0.27, completed
        assert completed["entire_design_physically_verified"] is False, completed
        assert completed["specimen_lineage"]["physical_specimen_identity_verified_count"] == 0, completed
        assert completed["fabrication_packages"]["items"][0]["archive_sha256"] == package_sha, completed
        for row in completed["test_runs"]:
            assert row["fabrication_package_sha256"] == package_sha, row
            assert row["physical_specimen_identity_verified"] is False, row
            assert row["inspection_ids"], row

        graph = _ok(client.get("/v3.1/graph"), "read specimen provenance graph").json()
        package_evidence = [row for row in graph["evidence"] if row["kind"] == "physical_fabrication_package"]
        specimen_evidence = [row for row in graph["evidence"] if row["kind"] == "physical_specimen_provenance"]
        run_evidence = [
            row for row in graph["evidence"]
            if row["kind"] == "physical_test_run" and row["metadata"].get("cycle_id") == cycle_id
        ]
        assert len(package_evidence) == 1, package_evidence
        assert len(specimen_evidence) == 3, specimen_evidence
        assert len(run_evidence) == 2, run_evidence
        assert all(row["method"] == "physical_test_execution_with_specimen_lineage" for row in run_evidence), run_evidence
        assert all(row["metadata"]["physical_specimen_identity_verified"] is False for row in run_evidence), run_evidence
        assert all(package_id in row["source_ids"] for row in run_evidence), run_evidence
        assert all(manufacturing["id"] in row["source_ids"] for row in run_evidence), run_evidence

        evidence_ids = {row["id"] for row in [*package_evidence, *specimen_evidence, *run_evidence]}
        core.object_by_id(object_id)["params"]["x"] = 71.0
        core.persist()
        _ok(client.post("/v3.1/graph/sync"), "sync after provenance CAD change")
        stale_graph = _ok(client.get("/v3.1/graph"), "read stale provenance graph").json()
        stale = [row for row in stale_graph["evidence"] if row["id"] in evidence_ids]
        assert len(stale) == len(evidence_ids), stale
        assert all(row["stale"] is True for row in stale), stale

        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        assert not core.PROJECT.get("physical_fabrication_packages"), core.PROJECT.get("physical_fabrication_packages")
        assert not core.PROJECT.get("physical_specimens"), core.PROJECT.get("physical_specimens")
        assert not core.PROJECT.get("physical_test_runs"), core.PROJECT.get("physical_test_runs")

        return {
            "ok": True,
            "milestone": 5,
            "slice": "fabrication_package_linked_physical_specimen_provenance",
            "returned_fabrication_archive_bytes_match_recorded_sha256": True,
            "raw_fabrication_archive_not_persisted": True,
            "matching_successful_manufacturing_evidence_required_when_locked": True,
            "mismatched_package_hash_rejected": True,
            "unregistered_specimen_run_rejected_without_write": True,
            "weak_specimen_run_rejected_without_write": True,
            "test_runs_carry_package_and_manufacturing_lineage": True,
            "physical_specimen_identity_not_overclaimed": True,
            "package_specimen_and_run_graph_evidence_stales_after_cad_change": True,
            "source_branch_does_not_inherit_physical_provenance": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
