from __future__ import annotations

"""Regression gate for autonomous campaigns using canonical project SolidFEA."""

from ..engineering_state import PROJECT
from ..v110 import core


def _fixture() -> str:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Campaign SolidFEA beam",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "beam", "tags": ["fabricated", "campaign-project-fea"]},
        },
        actor="human",
        reason="Create campaign SolidFEA fixture",
    )
    return str(core.PROJECT["objects"][-1]["id"])


def run() -> dict[str, object]:
    object_id = _fixture()
    source_branch = core.ACTIVE_DESIGN
    PROJECT.execute(
        "add_constraint",
        {"id": "root", "object_id": object_id, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Define campaign support",
    )
    PROJECT.execute(
        "add_load",
        {"id": "service", "object_id": object_id, "type": "force", "face": "x_max", "force_n": 200.0, "direction": "-z"},
        actor="human",
        reason="Define canonical service load",
    )

    result = PROJECT.run_campaign(
        object_id,
        {
            "objective": "deflection",
            # Deliberately disagree with the canonical project load. The reduced-order
            # preview may retain 10 N, but candidate ranking must use the project's 200 N.
            "force_n": 10.0,
            "deflection_max_mm": 20.0,
            "yield_fos_min": 0.1,
            "max_candidates": 3,
            "process": "cnc",
            "variables": [{"name": "z", "min": 8.0, "max": 14.0}],
        },
    )
    campaign = result["project_structural_campaign"]
    assert campaign["requested"] is True
    assert campaign["applied"] is True
    assert campaign["evaluated_candidates"] == 3
    assert campaign["supported_candidates"] == 3
    assert result["roles"]["analyst"]["structural_authority"] == "canonical_project_solid_fea"
    assert result["roles"]["verifier"]["equilibrium_gate"] is True

    candidates = result["candidates"]
    assert len(candidates) == 3
    assert all(row["structural_project"]["supported"] is True for row in candidates)
    assert all(row["structural_project"]["loads"][0]["vector_n"] == [0.0, 0.0, -200.0] for row in candidates)
    assert all(row["verifier"]["structural_authority"] == "canonical_project_solid_fea" for row in candidates)
    assert all(row["verifier"]["gates"]["project_boundary_conditions"] is True for row in candidates)
    assert all(row["verifier"]["gates"]["structural_equilibrium"] is True for row in candidates)
    assert all(float(row["structural_project"]["equilibrium_relative_error"]) < 1e-6 for row in candidates)

    feasible = [row for row in candidates if row["feasible"]]
    assert feasible
    winner = result["winner"]
    assert winner is not None
    assert float(winner["score"]) == min(float(row["score"]) for row in feasible)
    assert result["winner_branch"] == winner["branch"]
    assert core.ACTIVE_DESIGN == winner["branch"]
    assert any(row.get("kind") == "autonomous_campaign_project_structural" for row in core.PROJECT.get("simulations", []))

    # Candidate generation is sibling-based; applying project FEA must not mutate the
    # campaign source load case or source geometry.
    core.switch_branch(source_branch)
    assert core.object_by_id(object_id)["params"]["z"] == 10.0
    assert core.PROJECT["loads"][0]["force_n"] == 200.0
    core.switch_branch(str(result["winner_branch"]))

    # Unsupported canonical physics must fail closed instead of falling back to a hidden
    # cantilever and selecting a misleading winner.
    blocked_id = _fixture()
    blocked_source = core.ACTIVE_DESIGN
    PROJECT.execute(
        "add_constraint",
        {"id": "blocked-root", "object_id": blocked_id, "type": "fixed", "face": "x_min"},
        actor="human",
        reason="Define blocked campaign support",
    )
    PROJECT.execute(
        "add_load",
        {"id": "pressure", "object_id": blocked_id, "type": "pressure", "face": "x_max", "pressure_mpa": 1.0},
        actor="human",
        reason="Exercise unsupported canonical pressure",
    )
    blocked = PROJECT.run_campaign(
        blocked_id,
        {
            "objective": "mass",
            "force_n": 10.0,
            "deflection_max_mm": 100.0,
            "yield_fos_min": 0.01,
            "max_candidates": 3,
            "process": "cnc",
            "variables": [{"name": "z", "min": 8.0, "max": 12.0}],
        },
    )
    assert blocked["project_structural_campaign"]["requested"] is True
    assert blocked["project_structural_campaign"]["applied"] is True
    assert blocked["project_structural_campaign"]["supported_candidates"] == 0
    assert blocked["winner_branch"] is None
    assert blocked["status"] == "no_feasible_candidate"
    assert core.ACTIVE_DESIGN == blocked_source
    assert all(row["verifier"]["gates"]["project_boundary_conditions"] is False for row in blocked["candidates"] if "error" not in row)

    return {
        "canonical_load_n": 200.0,
        "candidate_count": len(candidates),
        "supported_candidates": campaign["supported_candidates"],
        "winner_branch": result["winner_branch"],
        "source_preserved": True,
        "unsupported_project_physics_fail_closed": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 campaign project SolidFEA self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
