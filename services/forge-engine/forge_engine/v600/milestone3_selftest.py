from __future__ import annotations

"""Controlled acceptance for ForgeCAD 6.0 milestone 3 repair trials."""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


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

        name = "Milestone 3 Repairable Structural Block"
        _ok(
            client.post(
                "/v2/operations",
                json={
                    "op": "add",
                    "args": {
                        "name": name,
                        "kind": "box",
                        "params": {"x": 100.0, "y": 80.0, "z": 10.0},
                        "material": "aluminum_6061_t6",
                        "semantic": {
                            "role": "repair_trial_fixture",
                            "repair_authority": {
                                "parameters": {
                                    "z": {
                                        "enabled": True,
                                        "min": 2.0,
                                        "max": 10.0,
                                        "reason": "Thickness is an explicitly bounded design variable for analysis-only mass optimization",
                                    }
                                }
                            },
                        },
                    },
                    "reason": "Create generic bounded-repair acceptance geometry",
                },
            ),
            "create repairable object",
        )
        obj = _object_named(name)
        object_id = str(obj["id"])
        box_mass = float(core.object_metrics(obj)["mass_kg"])
        baseline_mass = float(core.project_metrics()["mass_kg"])
        target_mass = baseline_mass - 0.40 * box_mass
        baseline_branch = core.ACTIVE_DESIGN
        baseline_z = float(obj["params"]["z"])
        assert baseline_z == 10.0

        requirement_id = "m3-mass-budget"
        requirement = _ok(
            client.post(
                "/v3.1/requirements",
                json={
                    "id": requirement_id,
                    "name": "Bounded repair mass budget",
                    "metric": "mass_kg",
                    "op": "<=",
                    "target": target_mass,
                    "unit": "kg",
                    "criticality": "important",
                    "scope_object_ids": [object_id],
                    "source": "milestone3_acceptance",
                    "confidence": 1.0,
                    "rationale": "Exercise evidence-preserving bounded parametric repair",
                },
            ),
            "create failing mass requirement",
        ).json()
        assert requirement["id"] == requirement_id

        baseline_verify = _ok(client.post("/v3.1/requirements/verify"), "verify failing baseline").json()
        baseline_row = next(row for row in baseline_verify["items"] if row["requirement"]["id"] == requirement_id)
        assert baseline_row["status"] == "fail", baseline_row
        baseline_evidence_id = baseline_row["evidence_id"]

        trial_request = {
            "requirement_id": requirement_id,
            "variables": [
                {
                    "object_id": object_id,
                    "parameter": "z",
                    "lower": 2.0,
                    "upper": 10.0,
                    "samples": 9,
                }
            ],
            "max_evaluations": 16,
            "branch_prefix": "m3-mass-repair",
            "actor": "jarvis",
        }
        trial = _ok(
            client.post("/v6/engineering/repair-trials/parametric", json=trial_request),
            "run bounded repair trial",
        ).json()
        assert trial["ok"] is True, trial
        assert trial["status"] == "requirement_satisfied", trial
        assert trial["baseline_branch"] == baseline_branch, trial
        repair_branch = trial["repair_branch"]
        assert repair_branch and repair_branch != baseline_branch, trial
        assert trial["baseline_evidence_preserved"] is True, trial
        assert trial["baseline_project_preserved"] is True, trial
        assert trial["final_verification"]["status"] == "pass", trial
        assert trial["final_verification"]["evidence_id"] != baseline_evidence_id, trial
        assert trial["selected"] is not None, trial
        assert float(trial["selected"]["values"][0]) < baseline_z, trial
        assert trial["policy"]["physical_validation"] == "not claimed", trial
        assert trial["semantic_diff"]["count"] >= 1, trial
        assert any(row["node_id"] == f"cad:{object_id}" and row["change"] == "modified" for row in trial["semantic_diff"]["changes"]), trial["semantic_diff"]

        repaired = core.object_by_id(object_id)
        repaired_z = float(repaired["params"]["z"])
        assert repaired_z < baseline_z, repaired
        assert core.ACTIVE_DESIGN == repair_branch
        assert core.DESIGNS[repair_branch]["analysis_status"] == "requirements_passed", core.DESIGNS[repair_branch]
        assert core.DESIGNS[repair_branch]["physical_verified"] is False, core.DESIGNS[repair_branch]

        evidence = _ok(client.get(f"/v3.1/evidence?requirement_id={requirement_id}&include_stale=true"), "read preserved evidence").json()
        evidence_by_id = {row["id"]: row for row in evidence["items"]}
        assert baseline_evidence_id in evidence_by_id, evidence
        assert trial["final_verification"]["evidence_id"] in evidence_by_id, evidence
        assert evidence_by_id[baseline_evidence_id]["status"] == "fail", evidence_by_id[baseline_evidence_id]
        assert evidence_by_id[baseline_evidence_id]["stale"] is True, evidence_by_id[baseline_evidence_id]
        assert evidence_by_id[trial["final_verification"]["evidence_id"]]["status"] == "pass", evidence_by_id[trial["final_verification"]["evidence_id"]]

        trials = _ok(client.get("/v6/engineering/repair-trials"), "read repair-trial ledger").json()
        assert trials["count"] == 1, trials
        assert trials["items"][0]["baseline_evidence_id"] == baseline_evidence_id, trials

        # The parent design remains materially unchanged and recoverable.
        core.switch_branch(baseline_branch)
        baseline_obj = core.object_by_id(object_id)
        assert abs(float(baseline_obj["params"]["z"]) - baseline_z) < 1e-12, baseline_obj
        baseline_again = _ok(client.post("/v3.1/graph/sync"), "resync preserved baseline").json()
        assert baseline_again["ok"] is True, baseline_again
        baseline_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify preserved failing baseline").json()
        baseline_reverify_row = next(row for row in baseline_reverify["items"] if row["requirement"]["id"] == requirement_id)
        assert baseline_reverify_row["status"] == "fail", baseline_reverify_row

        core.switch_branch(repair_branch)
        assert abs(float(core.object_by_id(object_id)["params"]["z"]) - repaired_z) < 1e-12
        _ok(client.post("/v3.1/graph/sync"), "resync repair branch")
        repair_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify repaired branch").json()
        repair_reverify_row = next(row for row in repair_reverify["items"] if row["requirement"]["id"] == requirement_id)
        assert repair_reverify_row["status"] == "pass", repair_reverify_row

        # Authority boundary: an unapproved parameter is rejected before branch
        # creation or mutation.
        branch_before_rejection = core.ACTIVE_DESIGN
        rejected = client.post(
            "/v6/engineering/repair-trials/parametric",
            json={
                **trial_request,
                "requirement_id": requirement_id,
                "variables": [{"object_id": object_id, "parameter": "x", "lower": 50.0, "upper": 100.0, "samples": 4}],
                "branch_prefix": "must-not-exist",
            },
        )
        assert rejected.status_code == 409, rejected.text
        assert "not explicitly authorized" in rejected.text, rejected.text
        assert core.ACTIVE_DESIGN == branch_before_rejection
        assert abs(float(core.object_by_id(object_id)["params"]["x"]) - 100.0) < 1e-12

        return {
            "ok": True,
            "milestone": 3,
            "slice": "evidence_preserving_bounded_parametric_repair",
            "baseline_branch": baseline_branch,
            "repair_branch": repair_branch,
            "baseline_requirement_status": "fail",
            "repair_requirement_status": "pass",
            "baseline_evidence_preserved": True,
            "parent_branch_preserved": True,
            "semantic_diff_verified": True,
            "unauthorized_mutation_rejected": True,
            "physical_validation_claimed": False,
            "selected_z_mm": repaired_z,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
