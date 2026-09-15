from __future__ import annotations

"""Controlled acceptance for milestone 4 bounded multi-strategy repair.

Unlike the original fixture, this test does not assume a new project contains a
particular purchased component. It explicitly ingests the Raspberry Pi 5 through
the canonical component API before comparing authorized repair strategies.
"""

import json
import os

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..engineering_state import PROJECT
from ..v110 import core


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _req(client: TestClient, rid: str, name: str, metric: str, op: str, target: float, object_ids: list[str]) -> None:
    _ok(client.post("/v3.1/requirements", json={
        "id": rid,
        "name": name,
        "metric": metric,
        "op": op,
        "target": target,
        "criticality": "important",
        "scope_object_ids": object_ids,
        "source": "v600-milestone4-acceptance",
        "confidence": 1.0,
    }), f"create requirement {rid}")


def run() -> dict[str, object]:
    PROJECT.new_project()
    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        add_pi = _ok(client.post("/v2/components/compute.raspberry_pi_5_8gb/add"), "ingest Pi 5 fixture").json()
        pi_id = str(add_pi["component"]["instance_id"])
        pi = core.object_by_id(pi_id)
        assert pi["component_ref"] == "compute.raspberry_pi_5_8gb", pi

        _ok(client.post("/v2/operations", json={
            "op": "add",
            "args": {
                "name": "M4 Featured Weight Block",
                "kind": "box",
                "params": {"x": 100.0, "y": 20.0, "z": 10.0},
                "material": "aluminum_6061_t6",
                "semantic": {
                    "role": "milestone4_failed_geometry_strategy",
                    "repair_authority": {"parameters": {"z": {"enabled": True, "min": 4.0, "max": 10.0}}},
                },
            },
            "reason": "Create milestone 4 strategy-choice fixture",
        }), "create milestone 4 block")
        block = next(row for row in core.PROJECT["objects"] if row.get("name") == "M4 Featured Weight Block")
        block_id = str(block["id"])
        block.setdefault("features", []).append({"id": "m4-feature", "type": "hole", "diameter": 3.0, "position": [0.0, 0.0, 0.0]})
        core.persist()

        baseline_branch = core.ACTIVE_DESIGN
        baseline_mass = float(core.project_metrics()["mass_kg"])
        baseline_count = float(core.project_metrics()["object_count"])
        target_id = "m4-mass-budget"
        guard_id = "m4-object-count"
        _req(client, target_id, "Reduce product mass by 25 grams", "mass_kg", "<=", baseline_mass - 0.025, [pi_id, block_id])
        _req(client, guard_id, "Do not add or remove canonical objects", "object_count", "==", baseline_count, [pi_id, block_id])
        _ok(client.post("/v3.1/graph/sync"), "sync milestone 4 baseline")
        before = _ok(client.post("/v3.1/requirements/verify"), "verify milestone 4 baseline").json()
        assert next(row for row in before["items"] if row["requirement"]["id"] == target_id)["status"] == "fail", before
        assert next(row for row in before["items"] if row["requirement"]["id"] == guard_id)["status"] == "pass", before

        result = _ok(client.post("/v6/engineering/autonomous-repair", json={
            "requirement_id": target_id,
            "guardrail_requirement_ids": [guard_id],
            "branch_prefix": "m4-choice",
            "strategies": [
                {
                    "id": "thin-featured-block",
                    "kind": "analysis_refresh_parametric",
                    "change_cost": 0.1,
                    "repair": {
                        "requirement_id": target_id,
                        "guardrail_requirement_ids": [guard_id],
                        "variables": [{"object_id": block_id, "parameter": "z", "lower": 4.0, "upper": 10.0, "samples": 7}],
                        "structural_refresh": [{"object_id": block_id, "force_n": 100.0, "support_axis": "x", "load_direction": "z", "mesh_counts": [4, 2, 2]}],
                        "max_evaluations": 8,
                        "branch_prefix": "m4-featured-parametric",
                        "actor": "jarvis"
                    }
                },
                {
                    "id": "lighter-compatible-compute",
                    "kind": "component_substitution",
                    "change_cost": 0.2,
                    "object_id": pi_id,
                    "allowed_component_ids": ["compute.raspberry_pi_zero_2w"],
                    "actor": "jarvis"
                }
            ]
        }), "run milestone 4 bounded autonomous repair").json()

        assert result["ok"] is True, result
        assert result["status"] == "authorized_strategy_selected", result
        assert result["baseline_branch"] == baseline_branch, result
        assert result["selected"]["strategy_id"] == "lighter-compatible-compute", result
        assert result["selected"]["strategy_kind"] == "component_substitution", result
        assert result["final_verification"]["passed"] is True, result
        assert result["physical_validation_claimed"] is False, result

        parametric = next(row for row in result["candidates"] if row["strategy_id"] == "thin-featured-block")
        substitution = next(row for row in result["candidates"] if row["strategy_id"] == "lighter-compatible-compute")
        assert parametric["accepted"] is False, parametric
        assert substitution["accepted"] is True, substitution
        assert substitution["change"]["old_component_id"] == "compute.raspberry_pi_5_8gb", substitution
        assert substitution["change"]["new_component_id"] == "compute.raspberry_pi_zero_2w", substitution
        assert core.object_by_id(pi_id)["component_ref"] == "compute.raspberry_pi_zero_2w"
        assert float(core.project_metrics()["object_count"]) == baseline_count
        assert float(core.project_metrics()["mass_kg"]) <= baseline_mass - 0.025
        assert core.DESIGNS[core.ACTIVE_DESIGN]["physical_verified"] is False

        param_outcome = parametric["outcome"]
        assert param_outcome is not None and param_outcome["ok"] is False, parametric
        reasons = [
            item.get("reason", "")
            for evaluation in param_outcome["evaluations"]
            for item in evaluation["analysis_refresh"]["items"]
            if not item["ok"]
        ]
        assert reasons and all("tetrahedral mesher" in reason for reason in reasons), reasons
        rejected_branch = str(parametric["branch"])
        selected_branch = str(substitution["branch"])
        assert rejected_branch in core.BRANCHES and selected_branch in core.BRANCHES, core.BRANCHES.keys()

        core.switch_branch(baseline_branch)
        assert core.object_by_id(pi_id)["component_ref"] == "compute.raspberry_pi_5_8gb"
        assert abs(float(core.object_by_id(block_id)["params"]["z"]) - 10.0) < 1e-12
        _ok(client.post("/v3.1/graph/sync"), "sync preserved milestone 4 baseline")
        baseline_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify preserved milestone 4 baseline").json()
        assert next(row for row in baseline_reverify["items"] if row["requirement"]["id"] == target_id)["status"] == "fail", baseline_reverify

        core.switch_branch(selected_branch)
        _ok(client.post("/v3.1/graph/sync"), "sync selected milestone 4 branch")
        selected_reverify = _ok(client.post("/v3.1/requirements/verify"), "reverify selected milestone 4 branch").json()
        assert next(row for row in selected_reverify["items"] if row["requirement"]["id"] == target_id)["status"] == "pass", selected_reverify
        assert next(row for row in selected_reverify["items"] if row["requirement"]["id"] == guard_id)["status"] == "pass", selected_reverify

        return {
            "ok": True,
            "milestone": 4,
            "slice": "bounded_multi_strategy_autonomous_repair",
            "explicit_component_ingestion": True,
            "failed_parametric_strategy_preserved": True,
            "catalog_substitution_strategy_selected": True,
            "same_requirements_reverified": True,
            "baseline_and_rejected_branches_preserved": True,
            "physical_validation_claimed": False
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
