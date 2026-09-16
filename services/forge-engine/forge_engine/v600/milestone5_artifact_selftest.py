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


def _object_named(name: str) -> dict:
    return next(row for row in core.PROJECT["objects"] if row.get("name") == name)


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        _ok(client.post("/v2/operations", json={
            "op": "add",
            "args": {
                "name": "M5 Artifact Coupon",
                "kind": "box",
                "params": {"x": 80.0, "y": 20.0, "z": 10.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "role": "physical_artifact_acceptance",
                    "repair_authority": {"parameters": {"z": {"enabled": True, "min": 6.0, "max": 12.0}}},
                },
            },
            "reason": "Create milestone 5 physical artifact fixture",
        }), "create artifact coupon")
        object_id = str(_object_named("M5 Artifact Coupon")["id"])

        requirement_id = "m5-artifact-clearance"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Artifact-backed clearance verification",
            "metric": "physical_clearance_mm",
            "op": ">=",
            "target": 0.2,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-artifact-acceptance",
            "confidence": 1.0,
        }), "create artifact requirement")

        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "bench fixture",
            "note": "Source prototype interference.",
            "measurements": [{"name": "clearance", "value": -0.4, "unit": "mm"}],
        }), "record source physical failure").json()["evidence"]

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [{"object_id": object_id, "parameter": "z", "value": 8.0}],
            "criteria": [{"measurement": "clearance", "unit": "mm", "op": ">=", "target": 0.2}],
            "branch_prefix": "m5-artifact-retest",
            "diagnosis": "Reduced thickness is a testable redesign hypothesis, not proven causality.",
        }), "begin artifact retest").json()
        cycle_id = str(begun["cycle"]["id"])
        redesign_branch = str(begun["cycle"]["redesign_branch"])
        redesign_fingerprint = str(begun["cycle"]["redesign_design_fingerprint"])
        assert redesign_fingerprint != source_fingerprint
        assert design_fingerprint() == redesign_fingerprint

        contract = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifact-contract", json={
            "requirements": [{"kind": "sensor_trace", "min_count": 1, "require_integrity_verified": True}],
        }), "lock verified trace contract").json()
        assert contract["locked"] is True, contract
        assert contract["design_fingerprint"] == redesign_fingerprint, contract
        assert design_fingerprint() == redesign_fingerprint

        relock = client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifact-contract", json={
            "requirements": [{"kind": "photo", "min_count": 1, "require_integrity_verified": False}],
        })
        assert relock.status_code == 409, relock.text
        assert "already locked" in relock.text, relock.text

        # A caller-declared external hash remains useful provenance, but it cannot
        # satisfy a contract that explicitly requires ForgeCAD-verified bytes.
        unverified = client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "external-clearance-trace.csv",
                "kind": "sensor_trace",
                "media_type": "text/csv",
                "sha256": "0" * 64,
                "size_bytes": 128,
                "source_ref": "external://lab/trace-001.csv",
            }],
        })
        assert unverified.status_code == 409, unverified.text
        assert "integrity-verified sensor_trace" in unverified.text, unverified.text
        empty_after_unverified = _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/artifacts"), "list after unverified rejection").json()
        assert empty_after_unverified["count"] == 0, empty_after_unverified

        payload = b"time_s,clearance_mm\n0.000,0.50\n0.010,0.51\n"
        encoded = base64.b64encode(payload).decode("ascii")
        digest = hashlib.sha256(payload).hexdigest()
        bad_hash = client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "clearance-trace.csv",
                "kind": "sensor_trace",
                "media_type": "text/csv",
                "sha256": "f" * 64,
                "size_bytes": len(payload),
                "content_base64": encoded,
            }],
        })
        assert bad_hash.status_code == 409, bad_hash.text
        assert "SHA-256 mismatch" in bad_hash.text, bad_hash.text

        submitted = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "clearance-trace.csv",
                "kind": "sensor_trace",
                "media_type": "text/csv",
                "sha256": digest,
                "size_bytes": len(payload),
                "content_base64": encoded,
                "captured_at": "2026-09-15T02:00:00Z",
                "note": "Synthetic acceptance trace for the controlled software fixture.",
            }],
        }), "submit verified trace").json()
        assert submitted["count"] == 1, submitted
        assert submitted["integrity_verified_count"] == 1, submitted
        artifact = submitted["items"][0]
        artifact_id = str(artifact["id"])
        artifact_evidence_id = str(submitted["graph_evidence"][0]["id"])
        assert artifact["sha256"] == digest, artifact
        assert artifact["integrity_verified"] is True, artifact
        assert artifact["integrity_status"] == "verified_inline_content", artifact
        assert artifact["content_persisted"] is False, artifact
        assert "content_base64" not in artifact, artifact
        assert artifact["design_fingerprint"] == redesign_fingerprint, artifact
        assert artifact["object_ids"] == [object_id], artifact
        assert submitted["graph_evidence"][0]["kind"] == "physical_test_artifact", submitted
        assert submitted["graph_evidence"][0]["subject_node_ids"] == [f"cad:{object_id}"], submitted
        assert submitted["graph_evidence"][0]["requirement_ids"] == [requirement_id], submitted
        assert submitted["graph_evidence"][0]["status"] == "verified_content", submitted

        duplicate_submission = client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "second.csv",
                "kind": "sensor_trace",
                "media_type": "text/csv",
                "sha256": digest,
                "size_bytes": len(payload),
                "content_base64": encoded,
            }],
        })
        assert duplicate_submission.status_code == 409, duplicate_submission.text
        assert "already complete" in duplicate_submission.text, duplicate_submission.text

        listed = _ok(client.get(f"/v6/physical/retest-cycles/{cycle_id}/artifacts"), "list verified artifact").json()
        assert listed["count"] == 1 and listed["integrity_verified_count"] == 1, listed
        assert "content_base64" not in listed["items"][0], listed
        assert design_fingerprint() == redesign_fingerprint

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "bench caliper + captured sensor trace",
            "measurements": [{"name": "clearance", "value": 0.5, "unit": "mm"}],
            "instrument": "Mitutoyo 500-196-30",
            "confidence": 0.98,
        }), "complete artifact-backed retest").json()
        assert completed["ok"] is True, completed
        assert len(completed["artifacts"]) == 1, completed
        assert completed["artifacts"][0]["id"] == artifact_id, completed
        inspection_ids = completed["cycle"]["inspection_ids"]
        assert inspection_ids, completed
        assert completed["artifacts"][0]["inspection_ids"] == inspection_ids, completed
        assert artifact_evidence_id in completed["evidence"]["evidence_ids"], completed
        assert completed["entire_design_physically_verified"] is False, completed
        assert design_fingerprint() == redesign_fingerprint

        # The artifact is part of the Engineering Graph evidence plane and stays
        # revision-aware through normal graph synchronization.
        graph = _ok(client.get("/v3.1/graph"), "read artifact graph evidence").json()
        graph_artifact = next(row for row in graph["evidence"] if row["id"] == artifact_evidence_id)
        assert graph_artifact["stale"] is False, graph_artifact
        assert graph_artifact["value"] == digest, graph_artifact
        assert graph_artifact["metadata"]["inspection_ids"] == inspection_ids, graph_artifact
        assert graph_artifact["metadata"]["content_persisted"] is False, graph_artifact

        # Evidence state does not alter the engineering fingerprint. An actual CAD
        # change does, and the graph must automatically stale the artifact evidence.
        core.object_by_id(object_id)["params"]["x"] = 81.0
        core.persist()
        assert design_fingerprint() != redesign_fingerprint
        _ok(client.post("/v3.1/graph/sync"), "sync after post-test CAD change")
        changed_graph = _ok(client.get("/v3.1/graph"), "read stale artifact graph evidence").json()
        stale_artifact = next(row for row in changed_graph["evidence"] if row["id"] == artifact_evidence_id)
        assert stale_artifact["stale"] is True, stale_artifact
        assert any("input fingerprint changed" in reason for reason in stale_artifact["invalidation_reasons"]), stale_artifact
        changed_evidence = _ok(client.get("/v2/evidence"), "read requirement evidence after CAD change").json()
        retest_evidence = next(row for row in changed_evidence["items"] if row["id"] == completed["evidence"]["id"])
        assert retest_evidence["applies_to_current_design"] is False, retest_evidence

        # Returning to the source prototype restores its failure evidence and does
        # not import the redesign's artifact record.
        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        assert not any(str(row.get("id")) == artifact_id for row in core.PROJECT.get("physical_test_artifacts") or [])

        return {
            "ok": True,
            "milestone": 5,
            "slice": "content_addressed_revision_bound_physical_artifacts",
            "verified_artifact_contract_enforced": True,
            "unverified_external_hash_not_overclaimed": True,
            "bad_inline_hash_rejected": True,
            "raw_artifact_bytes_not_persisted": True,
            "artifact_linked_to_requirement_and_inspection": True,
            "artifact_evidence_stales_after_cad_change": True,
            "source_branch_does_not_inherit_redesign_artifacts": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
