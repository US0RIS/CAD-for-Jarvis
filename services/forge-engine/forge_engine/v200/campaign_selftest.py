from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 autonomous multi-branch campaigns."""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core
from . import DESIGN_INTELLIGENCE_VERSION


def run() -> dict[str, object]:
    assert DESIGN_INTELLIGENCE_VERSION == "2.0.0"
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Campaign beam",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "test_beam", "tags": ["fabricated", "campaign-selftest"]},
        },
        actor="human",
        reason="Create deterministic campaign fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    source_branch = core.ACTIVE_DESIGN
    source_params = deepcopy(core.object_by_id(object_id)["params"])

    result = PROJECT.run_campaign(
        object_id,
        {
            "objective": "mass",
            "force_n": 100.0,
            "deflection_max_mm": 1.0,
            "yield_fos_min": 1.5,
            "max_candidates": 5,
            "process": "cnc",
            "variables": [{"name": "z", "min": 6.5, "max": 13.5}],
        },
    )

    assert result["source_branch"] == source_branch
    assert result["status"] == "candidate_selected"
    assert result["winner_branch"]
    assert core.ACTIVE_DESIGN == result["winner_branch"]
    assert len(result["candidates"]) == 5
    assert any(row["feasible"] for row in result["candidates"])
    assert any(not row["feasible"] for row in result["candidates"])
    assert result["roles"]["designer"]["generated_candidates"] == 5
    assert result["roles"]["verifier"]["physical_verification_required"] is True

    winner = result["winner"]
    assert winner and winner["feasible"] is True
    feasible_scores = [float(row["score"]) for row in result["candidates"] if row["feasible"]]
    assert float(winner["score"]) == min(feasible_scores)

    campaign_branches = [str(row["branch"]) for row in result["candidates"]]
    assert len(set(campaign_branches)) == 5
    for branch in campaign_branches:
        meta = core.DESIGNS[branch]
        assert meta["parent"] == source_branch
        assert meta["physical_verified"] is False
        assert meta["status"] in {"unverified", "not_working"}

    # Prove the source branch was never optimized in place.
    core.switch_branch(source_branch)
    assert core.object_by_id(object_id)["params"] == source_params
    core.switch_branch(str(result["winner_branch"]))

    campaign_records = [row for row in core.PROJECT.get("simulations", []) if row.get("kind") == "autonomous_campaign"]
    assert len(campaign_records) == 1
    assert campaign_records[0]["result"]["winner_branch"] == result["winner_branch"]

    return {
        "version": DESIGN_INTELLIGENCE_VERSION,
        "source_branch": source_branch,
        "winner_branch": result["winner_branch"],
        "candidate_branches": len(campaign_branches),
        "feasible": sum(1 for row in result["candidates"] if row["feasible"]),
        "rejected": sum(1 for row in result["candidates"] if not row["feasible"]),
        "source_preserved": True,
        "physical_auto_verified": False,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 autonomous campaign self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
