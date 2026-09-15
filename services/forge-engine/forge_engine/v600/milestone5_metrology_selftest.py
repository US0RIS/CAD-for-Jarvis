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


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        _ok(client.post("/v2/operations", json={
            "op": "add",
            "args": {
                "name": "M5 Metrology Coupon",
                "kind": "box",
                "params": {"x": 90.0, "y": 20.0, "z": 10.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "repair_authority": {
                        "parameters": {"z": {"enabled": True, "min": 6.0, "max": 12.0}}
                    }
                },
            },
            "reason": "Create milestone 5 metrology fixture",
        }), "create metrology coupon")
        object_id = str(next(row for row in core.PROJECT["objects"] if row.get("name") == "M5 Metrology Coupon")["id"])

        requirement_id = "m5-metrology-clearance"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Uncertainty-aware physical clearance",
            "metric": "physical_clearance_mm",
            "op": ">=",
            "target": 0.2,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-metrology-acceptance",
            "confidence": 1.0,
        }), "create metrology requirement")

        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "bench measurement",
            "measurements": [{"name": "clearance", "value": -0.2, "unit": "mm"}],
        }), "record source failure").json()["evidence"]

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [{"object_id": object_id, "parameter": "z", "value": 8.0}],
            "criteria": [{"measurement": "clearance", "unit": "mm", "op": ">=", "target": 0.2}],
            "branch_prefix": "m5-metrology-retest",
            "diagnosis": "Reduced thickness is a testable fit hypothesis only.",
        }), "begin metrology retest").json()
        cycle_id = str(begun["cycle"]["id"])
        redesign_fingerprint = str(begun["cycle"]["redesign_design_fingerprint"])
        assert design_fingerprint() == redesign_fingerprint

        # Store a byte-verified calibration report as provenance. The bytes/hash are
        # verified; the issuer and calibration chain remain intentionally unverified.
        report = b"Calibration report fixture\nInstrument: CAL-001\nExpanded uncertainty: 0.05 mm\n"
        report_hash = hashlib.sha256(report).hexdigest()
        _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifact-contract", json={
            "requirements": [{"kind": "report", "min_count": 1, "require_integrity_verified": True}],
        }), "lock calibration report artifact contract")
        submitted_report = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/artifacts", json={
            "artifacts": [{
                "name": "calibration-report.txt",
                "kind": "report",
                "media_type": "text/plain",
                "sha256": report_hash,
                "size_bytes": len(report),
                "content_base64": base64.b64encode(report).decode("ascii"),
                "note": "Controlled software fixture; file integrity only.",
            }],
        }), "submit verified calibration report").json()
        calibration_artifact_id = str(submitted_report["items"][0]["id"])
        assert submitted_report["items"][0]["integrity_verified"] is True

        contract = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/metrology-contract", json={
            "requirements": [{
                "measurement": "clearance",
                "max_uncertainty": 0.08,
                "require_calibration_reference": True,
                "require_verified_calibration_artifact": True,
            }],
        }), "lock metrology contract").json()
        assert contract["locked"] is True, contract
        assert design_fingerprint() == redesign_fingerprint

        missing_calibration = client.post(f"/v6/physical/retest-cycles/{cycle_id}/metrology", json={
            "contexts": [{
                "measurement": "clearance",
                "instrument_id": "CAL-001",
                "uncertainty": 0.05,
                "unit": "mm",
            }],
        })
        assert missing_calibration.status_code == 409, missing_calibration.text
        assert "calibration reference" in missing_calibration.text or "calibration report artifact" in missing_calibration.text

        excessive_uncertainty = client.post(f"/v6/physical/retest-cycles/{cycle_id}/metrology", json={
            "contexts": [{
                "measurement": "clearance",
                "instrument_id": "CAL-001",
                "uncertainty": 0.10,
                "unit": "mm",
                "calibration_ref": "lab-record-CAL-001",
                "calibration_artifact_id": calibration_artifact_id,
            }],
        })
        assert excessive_uncertainty.status_code == 409, excessive_uncertainty.text
        assert "exceeds locked maximum" in excessive_uncertainty.text, excessive_uncertainty.text

        metrology = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/metrology", json={
            "contexts": [{
                "measurement": "clearance",
                "instrument_id": "CAL-001",
                "manufacturer": "Fixture Instruments",
                "model": "Digital Caliper",
                "serial": "SER-001",
                "uncertainty": 0.05,
                "unit": "mm",
                "confidence_level": 0.95,
                "calibration_ref": "lab-record-CAL-001",
                "calibration_artifact_id": calibration_artifact_id,
                "note": "Uncertainty is supplied by the controlled test fixture.",
            }],
        }), "submit metrology context").json()
        assert metrology["count"] == 1, metrology
        assert metrology["calibration_authenticity_verified"] is False, metrology
        record = metrology["items"][0]
        metrology_evidence_id = str(metrology["graph_evidence"][0]["id"])
        assert record["calibration_artifact_integrity_verified"] is True, record
        assert record["calibration_authenticity_verified"] is False, record
        assert record["design_fingerprint"] == redesign_fingerprint, record
        assert design_fingerprint() == redesign_fingerprint

        # Nominally 0.22 mm clears a 0.20 mm threshold, but 0.22 +/- 0.05 spans
        # 0.17..0.27 mm, so ForgeCAD must refuse to certify a pass.
        indeterminate = client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "caliper fit measurement",
            "measurements": [{"name": "clearance", "value": 0.22, "unit": "mm"}],
        })
        assert indeterminate.status_code == 409, indeterminate.text
        assert "metrologically indeterminate" in indeterminate.text, indeterminate.text
        assert "uncertainty crosses an acceptance boundary" in indeterminate.text, indeterminate.text
        assert not core.PROJECT.get("inspections"), core.PROJECT.get("inspections")

        # The same 0.05 mm uncertainty is decisive when the measured clearance is
        # farther from the threshold: interval 0.25..0.35 is entirely passing.
        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "caliper fit measurement",
            "measurements": [{"name": "clearance", "value": 0.30, "unit": "mm"}],
        }), "complete uncertainty-aware retest").json()
        evaluation = completed["metrology_evaluation"]
        assert evaluation["required"] is True, evaluation
        assert evaluation["results"][0]["status"] == "pass", evaluation
        assert evaluation["results"][0]["interval"] == [0.25, 0.35], evaluation
        assert completed["ok"] is True, completed
        assert metrology_evidence_id in completed["evidence"]["evidence_ids"], completed
        assert len(completed["metrology_records"]) == 1, completed
        assert completed["metrology_records"][0]["inspection_ids"] == completed["cycle"]["inspection_ids"], completed
        assert completed["entire_design_physically_verified"] is False, completed
        assert design_fingerprint() == redesign_fingerprint

        graph = _ok(client.get("/v3.1/graph"), "read metrology graph evidence").json()
        graph_metrology = next(row for row in graph["evidence"] if row["id"] == metrology_evidence_id)
        assert graph_metrology["stale"] is False, graph_metrology
        assert graph_metrology["kind"] == "physical_metrology_context", graph_metrology
        assert graph_metrology["metadata"]["calibration_authenticity_verified"] is False, graph_metrology
        assert any("not externally verified" in assumption for assumption in graph_metrology["assumptions"]), graph_metrology

        # An engineering change makes the metrology evidence stale through the same
        # Engineering Graph fingerprint mechanism as simulations and artifacts.
        core.object_by_id(object_id)["params"]["x"] = 91.0
        core.persist()
        _ok(client.post("/v3.1/graph/sync"), "sync after post-test metrology CAD change")
        changed_graph = _ok(client.get("/v3.1/graph"), "read stale metrology evidence").json()
        stale = next(row for row in changed_graph["evidence"] if row["id"] == metrology_evidence_id)
        assert stale["stale"] is True, stale

        return {
            "ok": True,
            "milestone": 5,
            "slice": "uncertainty_aware_revision_bound_metrology",
            "nominal_pass_with_boundary_crossing_uncertainty_rejected": True,
            "decisive_uncertainty_interval_passes": True,
            "max_uncertainty_contract_enforced": True,
            "calibration_report_file_integrity_verified": True,
            "calibration_authenticity_not_overclaimed": True,
            "metrology_evidence_linked_to_physical_inspection": True,
            "metrology_evidence_stales_after_cad_change": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
