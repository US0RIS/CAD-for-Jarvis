from __future__ import annotations

"""Milestone-3 acceptance for fresh-analysis repair and fail-closed geometry."""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core
from ..v200 import structural_fea


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _object_named(name: str) -> dict:
    return next(row for row in core.PROJECT["objects"] if row.get("name") == name)


def _box(client: TestClient, name: str, *, featured: bool = False) -> str:
    _ok(client.post("/v2/operations", json={
        "op": "add",
        "args": {
            "name": name,
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "semantic": {
                "role": "analysis_refresh_acceptance",
                "repair_authority": {"parameters": {"z": {"enabled": True, "min": 4.0, "max": 10.0}}},
            },
        },
        "reason": "Create analysis-refresh repair fixture",
    }), f"create {name}")
    obj = _object_named(name)
    if featured:
        obj.setdefault("features", []).append({"id": "acceptance-feature", "type": "hole", "diameter": 3.0, "position": [0.0, 0.0, 0.0]})
        core.persist()
    return str(obj["id"])


def _req(client: TestClient, rid: str, name: str, metric: str, op: str, target: float, object_id: str, criticality: str = "important") -> None:
    _ok(client.post("/v3.1/requirements", json={
        "id": rid,
        "name": name,
        "metric": metric,
        "op": op,
        "target": target,
        "criticality": criticality,
        "scope_object_ids": [object_id],
        "source": "v600-analysis-refresh-acceptance",
        "confidence": 1.0,
    }), f"create requirement {rid}")


def _fresh_analysis_repair(client: TestClient) -> dict[str, object]:
    PROJECT.new_project()
    object_id = _box(client, "M3 Fresh Analysis Beam")
    obj = core.object_by_id(object_id)
    initial = structural_fea.solve_box(obj, force_n=100.0, support_axis="x", load_direction="z", mesh_counts=(6, 3, 3))
    assert initial["supported"] is True and initial["solver_grade"] == "engineering_iteration", initial
    initial_sim = core.record_simulation("m3-initial-structural", object_id, {"force_n": 100.0}, initial)
    baseline_mass = float(core.project_metrics()["mass_kg"])
    object_mass = float(core.object_metrics(obj)["mass_kg"])
    _req(client, "m3-refresh-mass", "Reduce mass with fresh structural proof", "mass_kg", "<=", baseline_mass - 0.30 * object_mass, object_id)
    _req(client, "m3-refresh-fos", "Yield factor of safety remains at least 3", "yield_fos", ">=", 3.0, object_id, "safety")
    _ok(client.post("/v3.1/graph/sync"), "sync initial structural evidence")
    before = _ok(client.post("/v3.1/requirements/verify"), "verify refresh baseline").json()
    assert next(row for row in before["items"] if row["requirement"]["id"] == "m3-refresh-mass")["status"] == "fail", before
    assert next(row for row in before["items"] if row["requirement"]["id"] == "m3-refresh-fos")["status"] == "pass", before

    baseline_branch = core.ACTIVE_DESIGN
    trial = _ok(client.post("/v6/engineering/repair-trials/analysis-refresh", json={
        "requirement_id": "m3-refresh-mass",
        "guardrail_requirement_ids": ["m3-refresh-fos"],
        "variables": [{"object_id": object_id, "parameter": "z", "lower": 4.0, "upper": 10.0, "samples": 7}],
        "structural_refresh": [{"object_id": object_id, "force_n": 100.0, "support_axis": "x", "load_direction": "z", "mesh_counts": [6, 3, 3]}],
        "max_evaluations": 10,
        "branch_prefix": "m3-fresh-analysis",
        "actor": "jarvis",
    }), "run fresh-analysis repair").json()
    assert trial["ok"] is True, trial
    assert trial["status"] == "requirement_satisfied_with_fresh_analysis", trial
    assert trial["final_verification"]["status"] == "pass", trial
    assert trial["final_guardrails"]["ok"] is True, trial
    assert trial["winner"] is not None, trial
    winning_refresh = trial["winner"]["analysis_refresh"]
    assert winning_refresh["ok"] is True, winning_refresh
    winning_item = winning_refresh["items"][0]
    assert winning_item["solver_grade"] == "engineering_iteration", winning_item
    assert winning_item["simulation_id"], winning_item
    assert float(winning_item["yield_fos"]) >= 3.0, winning_item
    assert float(core.object_by_id(object_id)["params"]["z"]) < 10.0
    assert core.ACTIVE_DESIGN != baseline_branch
    assert core.DESIGNS[core.ACTIVE_DESIGN]["physical_verified"] is False
    assert any(row["id"] == initial_sim["id"] and row["stale"] is True for row in core.PROJECT["simulations"]), core.PROJECT["simulations"]
    fresh = [row for row in core.PROJECT["simulations"] if row["kind"] == "v600_structural_repair_refresh" and not row["stale"]]
    assert len(fresh) == 1, fresh
    assert fresh[0]["id"] == winning_item["simulation_id"], (fresh, winning_item)

    core.switch_branch(baseline_branch)
    parent_sim = next(row for row in core.PROJECT["simulations"] if row["id"] == initial_sim["id"])
    assert parent_sim["stale"] is False, parent_sim
    assert abs(float(core.object_by_id(object_id)["params"]["z"]) - 10.0) < 1e-12

    return {
        "fresh_solver_evidence_selected": True,
        "stale_parent_analysis_not_reused": True,
        "structural_guardrail_preserved": True,
        "parent_branch_preserved": True,
    }


def _featured_geometry_fails_closed(client: TestClient) -> dict[str, object]:
    PROJECT.new_project()
    object_id = _box(client, "M3 Unsupported Featured Beam", featured=True)
    baseline_mass = float(core.project_metrics()["mass_kg"])
    object_mass = float(core.object_metrics(core.object_by_id(object_id))["mass_kg"])
    _req(client, "m3-featured-mass", "Attempt mass repair on featured geometry", "mass_kg", "<=", baseline_mass - 0.10 * object_mass, object_id)
    _ok(client.post("/v3.1/graph/sync"), "sync featured baseline")
    before = _ok(client.post("/v3.1/requirements/verify"), "verify featured baseline").json()
    assert next(row for row in before["items"] if row["requirement"]["id"] == "m3-featured-mass")["status"] == "fail", before

    trial = _ok(client.post("/v6/engineering/repair-trials/analysis-refresh", json={
        "requirement_id": "m3-featured-mass",
        "guardrail_requirement_ids": [],
        "variables": [{"object_id": object_id, "parameter": "z", "lower": 4.0, "upper": 10.0, "samples": 4}],
        "structural_refresh": [{"object_id": object_id, "force_n": 100.0, "support_axis": "x", "load_direction": "z", "mesh_counts": [4, 2, 2]}],
        "max_evaluations": 6,
        "branch_prefix": "m3-featured-fail-closed",
        "actor": "jarvis",
    }), "run unsupported featured repair").json()
    assert trial["ok"] is False, trial
    assert trial["status"] == "no_passing_candidate", trial
    assert trial["winner"] is None, trial
    assert trial["evaluations"], trial
    assert all(row["rejection"] == "analysis_unsupported_or_insufficient_grade" for row in trial["evaluations"]), trial
    reasons = [item["reason"] for row in trial["evaluations"] for item in row["analysis_refresh"]["items"] if not item["ok"]]
    assert reasons and all("tetrahedral mesher" in reason for reason in reasons), reasons
    assert not any(row["kind"] == "v600_structural_repair_refresh" and not row["stale"] for row in core.PROJECT["simulations"]), core.PROJECT["simulations"]
    return {"featured_geometry_failed_closed": True, "unsupported_solver_not_substituted": True}


def run() -> dict[str, object]:
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})
        a = _fresh_analysis_repair(client)
        b = _featured_geometry_fails_closed(client)
        return {"ok": True, "milestone": 3, "slice": "analysis_refreshing_bounded_repair", **a, **b, "physical_validation_claimed": False}


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
