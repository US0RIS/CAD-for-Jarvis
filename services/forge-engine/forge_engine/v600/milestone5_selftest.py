from __future__ import annotations

"""Milestone-5 acceptance for revision-bound physical feedback and retest."""

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
                "name": "M5 Physical Feedback Coupon",
                "kind": "box",
                "params": {"x": 100.0, "y": 20.0, "z": 10.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "role": "physical_retest_acceptance",
                    "repair_authority": {
                        "parameters": {
                            "z": {"enabled": True, "min": 5.0, "max": 12.0},
                        }
                    },
                },
            },
            "reason": "Create milestone 5 physical feedback fixture",
        }), "create physical feedback coupon")
        coupon = _object_named("M5 Physical Feedback Coupon")
        object_id = str(coupon["id"])

        requirement_id = "m5-bench-fit"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Bench-fit verification",
            "metric": "mass_kg",
            "op": "<=",
            "target": 1.0,
            "criticality": "important",
            "scope_object_ids": [object_id],
            "source": "v600-milestone5-acceptance",
            "confidence": 1.0,
        }), "create milestone 5 requirement")

        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "bench caliper + fixture inspection",
            "note": "Prototype interfered with the mating fixture at the tested revision.",
            "measurements": [{"name": "interference", "value": 0.8, "unit": "mm", "tolerance": 0.2}],
        }), "record failed physical requirement evidence").json()["evidence"]
        assert failed["status"] == "failed", failed
        assert failed["design_fingerprint"] == source_fingerprint, failed
        failed_id = str(failed["id"])

        source_evidence = _ok(client.get("/v2/evidence"), "read source evidence").json()
        failed_source_row = next(row for row in source_evidence["items"] if row["id"] == failed_id)
        assert failed_source_row["applies_to_current_design"] is True, failed_source_row

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed_id,
            "mutations": [{"object_id": object_id, "parameter": "z", "value": 8.0}],
            "branch_prefix": "m5-retest",
            "actor": "jarvis",
            "diagnosis": "Bench interference indicates the authorized coupon thickness should be reduced before another prototype is tested.",
        }), "begin milestone 5 physical redesign cycle").json()
        assert begun["ok"] is True, begun
        cycle = begun["cycle"]
        cycle_id = str(cycle["id"])
        redesign_branch = str(cycle["redesign_branch"])
        redesign_fingerprint = str(cycle["redesign_design_fingerprint"])
        assert cycle["source_branch"] == source_branch, cycle
        assert cycle["source_design_fingerprint"] == source_fingerprint, cycle
        assert redesign_branch != source_branch, cycle
        assert redesign_fingerprint != source_fingerprint, cycle
        assert core.ACTIVE_DESIGN == redesign_branch
        assert abs(float(core.object_by_id(object_id)["params"]["z"]) - 8.0) < 1e-12
        assert begun["source_failure_stale_on_redesign"] is True, begun
        assert int(cycle["semantic_diff_count"]) >= 1, cycle
        assert core.DESIGNS[redesign_branch]["physical_verified"] is False
        assert core.DESIGNS[redesign_branch]["physical_status"] == "pending_retest"

        redesign_evidence = _ok(client.get("/v2/evidence"), "read redesign evidence before retest").json()
        stale_failed = next(row for row in redesign_evidence["items"] if row["id"] == failed_id)
        assert stale_failed["applies_to_current_design"] is False, stale_failed
        assert stale_failed["evidence_binding"] == "stale", stale_failed

        # Drift the redesign after planning. A physical result must not be accepted
        # against a fingerprint other than the one the retest cycle was prepared for.
        coupon = core.object_by_id(object_id)
        original_x = float(coupon["params"]["x"])
        coupon["params"]["x"] = original_x + 1.0
        core.persist()
        assert design_fingerprint() != redesign_fingerprint
        wrong_revision = client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "bench caliper + fixture inspection",
            "note": "This result must be rejected because CAD changed after the retest plan was bound.",
        })
        assert wrong_revision.status_code == 409, wrong_revision.text
        assert "changed after the retest cycle began" in wrong_revision.text, wrong_revision.text

        # Restore the exact redesigned engineering state. Historical ledger entries
        # are excluded from the physical design fingerprint, so the content hash
        # returns exactly to the planned redesign fingerprint.
        coupon = core.object_by_id(object_id)
        coupon["params"]["x"] = original_x
        core.persist()
        assert design_fingerprint() == redesign_fingerprint, (design_fingerprint(), redesign_fingerprint)

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "bench caliper + fixture inspection",
            "note": "Redesigned prototype clears the mating fixture.",
            "measurements": [{"name": "clearance", "value": 0.5, "unit": "mm", "tolerance": 0.2}],
        }), "complete milestone 5 retest").json()
        assert completed["ok"] is True, completed
        assert completed["cycle"]["status"] == "retest_passed", completed
        assert completed["evidence"]["design_fingerprint"] == redesign_fingerprint, completed
        assert completed["requirement_physically_verified_on_current_fingerprint"] is True, completed
        assert completed["entire_design_physically_verified"] is False, completed
        assert core.DESIGNS[redesign_branch]["physical_verified"] is False
        assert requirement_id in core.DESIGNS[redesign_branch]["physically_verified_requirement_ids"]
        passed_id = str(completed["evidence"]["id"])

        current_evidence = _ok(client.get("/v2/evidence"), "read completed redesign evidence").json()
        old_row = next(row for row in current_evidence["items"] if row["id"] == failed_id)
        new_row = next(row for row in current_evidence["items"] if row["id"] == passed_id)
        assert old_row["applies_to_current_design"] is False, old_row
        assert new_row["applies_to_current_design"] is True, new_row

        # The source branch still retains the exact failed prototype evidence and
        # does not inherit the redesign's passing retest.
        core.switch_branch(source_branch)
        assert design_fingerprint() == source_fingerprint
        source_again = _ok(client.get("/v2/evidence"), "revisit failed source revision").json()
        failed_again = next(row for row in source_again["items"] if row["id"] == failed_id)
        assert failed_again["applies_to_current_design"] is True, failed_again
        assert all(row["id"] != passed_id for row in source_again["items"]), source_again
        assert abs(float(core.object_by_id(object_id)["params"]["z"]) - 10.0) < 1e-12

        core.switch_branch(redesign_branch)
        listed = _ok(client.get("/v6/physical/retest-cycles"), "list redesign retest cycles").json()
        assert listed["count"] == 1, listed
        assert listed["items"][0]["status"] == "retest_passed", listed
        assert listed["design_fingerprint"] == redesign_fingerprint, listed

        return {
            "ok": True,
            "milestone": 5,
            "slice": "revision_bound_physical_failure_redesign_retest",
            "failed_evidence_bound_to_source_revision": True,
            "redesign_makes_source_failure_stale": True,
            "wrong_revision_retest_rejected": True,
            "passing_retest_bound_to_redesign_revision": True,
            "source_branch_failure_preserved": True,
            "entire_design_physical_verification_not_overclaimed": True,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
