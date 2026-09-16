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


def _create_repairable_block(client: TestClient, name: str) -> tuple[str, float, float]:
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
        f"create {name}",
    )
    obj = _object_named(name)
    return str(obj["id"]), float(core.object_metrics(obj)["mass_kg"]), float(core.project_metrics()["mass_kg"])


def _put_requirement(client: TestClient, *, requirement_id: str, name: str, metric: str, op: str, target: float, unit: str | None, object_id: str) -> dict:
    return _ok(
        client.post(
            "/v3.1/requirements",
            json={
                "id": requirement_id,
                "name": name,
                "metric": metric,
                "op": op,
                "target": target,
                "unit": unit,
                "criticality": "important",
                "scope_object_ids": [object_id],
                "source": "milestone3_acceptance",
                "confidence": 1.0,
                "rationale": "Exercise evidence-preserving bounded parametric repair",
            },
        ),
        f"create {requirement_id}",
    ).json()


def _successful_guarded_repair(client: TestClient) -> dict[str, object]:
    PROJECT.new_project()
    _ok(client.post("/v3.1/graph/sync"), "sync clean successful-repair fixture")
    name = "Milestone 3 Repairable Structural Block"
    object_id, box_mass, baseline_mass = _create_repairable_block(client, name)
    target_mass = baseline_mass - 0.40 * box_mass
    baseline_branch = core.ACTIVE_DESIGN
    baseline_z = float(core.object_by_id(object_id)["params"]["z"])
    assert baseline_z == 10.0

    requirement_id = "m3-mass-budget"
    guardrail_id = "m3-object-count-guardrail"
    assert _put_requirement(
        client,
        requirement_id=requirement_id,
        name="Bounded repair mass budget",
        metric="mass_kg",
        op="<=",
        target=target_mass,
        unit="kg",
        object_id=object_id,
    )["id"] == requirement_id
    assert _put_requirement(
        client,
        requirement_id=guardrail_id,
        name="Repair must not add or remove product objects",
        metric="object_count",
        op="==",
        target=float(core.project_metrics()["object_count"]),
        unit="count",
        object_id=object_id,
    )["id"] == guardrail_id

    baseline_verify = _ok(client.post("/v3.1/requirements/verify"), "verify failing baseline").json()
    baseline_row = next(row for row in baseline_verify["items"] if row["requirement"]["id"] == requirement_id)
    guardrail_row = next(row for row in baseline_verify["items"] if row["requirement"]["id"] == guardrail_id)
    assert baseline_row["status"] == "fail", baseline_row
    assert guardrail_row["status"] == "pass", guardrail_row
    baseline_evidence_id = baseline_row["evidence_id"]

    trial_request = {
        "requirement_id": requirement_id,
        "guardrail_requirement_ids": [guardrail_id],
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
    assert trial["baseline_guardrails"]["ok"] is True, trial
    assert trial["final_guardrails"]["ok"] is True, trial
    assert trial["final_verification"]["status"] == "pass", trial
    assert trial["final_verification"]["evidence_id"] != baseline_evidence_id, trial
    assert trial["selected"] is not None, trial
    assert float(trial["selected"]["values"][0]) < baseline_z, trial
    assert trial["policy"]["physical_validation"] == "not claimed", trial
    assert trial["policy"]["simulation_invalidation"].startswith("changed geometry"), trial
    assert trial["semantic_diff"]["count"] >= 1, trial
    assert any(row["node_id"] == f"cad:{object_id}" and row["change"] == "modified" for row in trial["semantic_diff"]["changes"]), trial["semantic_diff"]

    repaired_z = float(core.object_by_id(object_id)["params"]["z"])
    assert repaired_z < baseline_z
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
    assert trials["items"][0]["guardrail_requirement_ids"] == [guardrail_id], trials

    core.switch_branch(baseline_branch)
    baseline_obj = core.object_by_id(object_id)
    assert abs(float(baseline_obj["params"]["z"]) - baseline_z) < 1e-12, baseline_obj
    assert _ok(client.post("/v3.1/graph/sync"), "resync preserved baseline").json()["ok"] is True
    baseline_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify preserved failing baseline").json()
    baseline_reverify_row = next(row for row in baseline_reverify["items"] if row["requirement"]["id"] == requirement_id)
    assert baseline_reverify_row["status"] == "fail", baseline_reverify_row

    core.switch_branch(repair_branch)
    assert abs(float(core.object_by_id(object_id)["params"]["z"]) - repaired_z) < 1e-12
    _ok(client.post("/v3.1/graph/sync"), "resync repair branch")
    repair_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify repaired branch").json()
    repair_reverify_row = next(row for row in repair_reverify["items"] if row["requirement"]["id"] == requirement_id)
    repair_guardrail_row = next(row for row in repair_reverify["items"] if row["requirement"]["id"] == guardrail_id)
    assert repair_reverify_row["status"] == "pass", repair_reverify_row
    assert repair_guardrail_row["status"] == "pass", repair_guardrail_row

    branch_before_rejection = core.ACTIVE_DESIGN
    rejected = client.post(
        "/v6/engineering/repair-trials/parametric",
        json={
            **trial_request,
            "variables": [{"object_id": object_id, "parameter": "x", "lower": 50.0, "upper": 100.0, "samples": 4}],
            "branch_prefix": "must-not-exist",
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert "not explicitly authorized" in rejected.text, rejected.text
    assert core.ACTIVE_DESIGN == branch_before_rejection
    assert abs(float(core.object_by_id(object_id)["params"]["x"]) - 100.0) < 1e-12

    return {
        "baseline_branch": baseline_branch,
        "repair_branch": repair_branch,
        "selected_z_mm": repaired_z,
        "baseline_evidence_preserved": True,
        "project_metric_guardrail_preserved": True,
        "unauthorized_mutation_rejected": True,
    }


def _stale_solver_guardrail_blocks_repair(client: TestClient) -> dict[str, object]:
    PROJECT.new_project()
    _ok(client.post("/v3.1/graph/sync"), "sync stale-evidence fixture")
    name = "Milestone 3 Solver Guardrail Block"
    object_id, box_mass, baseline_mass = _create_repairable_block(client, name)
    baseline_branch = core.ACTIVE_DESIGN

    target_id = "m3-small-mass-reduction"
    solver_guardrail_id = "m3-solver-safety-factor"
    _put_requirement(
        client,
        requirement_id=target_id,
        name="Small mass reduction",
        metric="mass_kg",
        op="<=",
        target=baseline_mass - 0.05 * box_mass,
        unit="kg",
        object_id=object_id,
    )
    _put_requirement(
        client,
        requirement_id=solver_guardrail_id,
        name="Existing structural screening margin must remain verified",
        metric="safety_factor",
        op=">=",
        target=1.5,
        unit=None,
        object_id=object_id,
    )
    simulation = core.record_simulation(
        "milestone3_structural_screen",
        object_id,
        {"fixture": "stale_guardrail_acceptance"},
        {"safety_factor": 2.0},
    )
    _ok(client.post("/v3.1/graph/sync"), "sync solver evidence fixture")
    baseline_verify = _ok(client.post("/v3.1/requirements/verify"), "verify solver guardrail baseline").json()
    assert next(row for row in baseline_verify["items"] if row["requirement"]["id"] == target_id)["status"] == "fail", baseline_verify
    assert next(row for row in baseline_verify["items"] if row["requirement"]["id"] == solver_guardrail_id)["status"] == "pass", baseline_verify

    trial = _ok(
        client.post(
            "/v6/engineering/repair-trials/parametric",
            json={
                "requirement_id": target_id,
                "guardrail_requirement_ids": [solver_guardrail_id],
                "variables": [{"object_id": object_id, "parameter": "z", "lower": 2.0, "upper": 10.0, "samples": 9}],
                "max_evaluations": 16,
                "branch_prefix": "m3-stale-solver-guardrail",
                "actor": "jarvis",
            },
        ),
        "run solver-guarded repair",
    ).json()
    assert trial["ok"] is False, trial
    assert trial["status"] == "blocked_by_unknown_guardrail", trial
    assert trial["selected"] is None, trial
    assert trial["final_guardrails"]["ok"] is False, trial
    assert solver_guardrail_id in trial["final_guardrails"]["unknown_requirement_ids"], trial
    assert any(row["stale_simulation_count"] >= 1 for row in trial["evaluations"]), trial
    assert core.DESIGNS[trial["repair_branch"]]["analysis_status"] == "blocked_by_unknown_guardrail", core.DESIGNS[trial["repair_branch"]]
    assert any(row["id"] == simulation["id"] and row["stale"] is True for row in core.PROJECT["simulations"]), core.PROJECT["simulations"]

    # The protected parent still retains the simulation exactly as it existed
    # before the experiment. Staleness belongs to the modified repair branch.
    core.switch_branch(baseline_branch)
    parent_sim = next(row for row in core.PROJECT["simulations"] if row["id"] == simulation["id"])
    assert parent_sim["stale"] is False, parent_sim
    assert abs(float(core.object_by_id(object_id)["params"]["z"]) - 10.0) < 1e-12
    _ok(client.post("/v3.1/graph/sync"), "resync solver-guardrail parent")
    parent_verify = _ok(client.post("/v3.1/requirements/verify"), "reverify solver-guardrail parent").json()
    assert next(row for row in parent_verify["items"] if row["requirement"]["id"] == solver_guardrail_id)["status"] == "pass", parent_verify

    return {
        "repair_blocked_when_solver_evidence_became_stale": True,
        "solver_guardrail_status_after_change": "unknown",
        "parent_simulation_preserved_current": True,
    }


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        successful = _successful_guarded_repair(client)
        stale_guardrail = _stale_solver_guardrail_blocks_repair(client)
        return {
            "ok": True,
            "milestone": 3,
            "slice": "evidence_preserving_bounded_parametric_repair_with_guardrails",
            **successful,
            **stale_guardrail,
            "semantic_diff_verified": True,
            "physical_validation_claimed": False,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
