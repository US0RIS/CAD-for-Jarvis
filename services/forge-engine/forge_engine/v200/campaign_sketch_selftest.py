from __future__ import annotations

"""Regression gate for optimizing named constrained-sketch dimensions."""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core


def _sketch() -> dict[str, object]:
    return {
        "points": [[0.0, 0.0], [40.0, 0.0], [40.0, 20.0], [0.0, 20.0]],
        "constraints": [
            {"type": "fixed", "point": 0, "x": 0.0, "y": 0.0},
            {"type": "horizontal", "a": 0, "b": 1},
            {"type": "vertical", "a": 1, "b": 2},
            {"type": "horizontal", "a": 2, "b": 3},
            {"type": "vertical", "a": 3, "b": 0},
            {"type": "distance", "name": "width", "a": 0, "b": 1, "value": 40.0},
            {"type": "distance", "name": "depth", "a": 1, "b": 2, "value": 20.0},
        ],
        "require_fully_constrained": True,
    }


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Dimension-driven plate",
            "kind": "constrained_sketch_extrude",
            "params": {"height": 3.0, "sketch": _sketch()},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "plate", "tags": ["fabricated", "parametric", "campaign-sketch-selftest"]},
        },
        actor="human",
        reason="Create constrained-sketch campaign fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    source_branch = core.ACTIVE_DESIGN
    source_params = deepcopy(core.object_by_id(object_id)["params"])
    source_mass = float(core.object_metrics(core.object_by_id(object_id))["mass_kg"])

    result = PROJECT.run_campaign(
        object_id,
        {
            "objective": "mass",
            "force_n": 0.1,
            "deflection_max_mm": 1000000.0,
            "yield_fos_min": 0.000001,
            "max_candidates": 3,
            "process": "cnc",
            # Semantic dimension name resolves to sketch.width rather than a raw vertex.
            "variables": [{"name": "width", "min": 30.0, "max": 50.0}],
        },
    )

    assert result["source_branch"] == source_branch
    assert len(result["variables"]) == 1
    variable = result["variables"][0]
    assert variable["name"] == "sketch.width"
    assert variable["kind"] == "sketch_dimension"
    assert variable["constraint_type"] == "distance"
    assert variable["path"] == ["params", "sketch", "constraints", 5, "value"]
    assert len(result["candidates"]) == 3

    widths = {float(row["parameters"]["sketch.width"]) for row in result["candidates"]}
    assert widths == {30.0, 40.0, 50.0}, widths
    for row in result["candidates"]:
        assert row["parameter_paths"]["sketch.width"] == ["params", "sketch", "constraints", 5, "value"]
        branch = str(row["branch"])
        core.switch_branch(branch)
        candidate = core.object_by_id(object_id)
        solved_width = float(candidate["params"]["sketch"]["constraints"][5]["value"])
        assert abs(solved_width - float(row["parameters"]["sketch.width"])) < 1e-9
        bounds = core.build_shape(candidate).BoundingBox()
        assert abs(bounds.xlen - solved_width) < 1e-4

    winner = result["winner"]
    assert winner is not None and winner["feasible"] is True
    assert float(winner["parameters"]["sketch.width"]) == 30.0
    core.switch_branch(str(result["winner_branch"]))
    winner_mass = float(core.object_metrics(core.object_by_id(object_id))["mass_kg"])
    assert winner_mass < source_mass

    # The source sketch and its named dimension are preserved exactly.
    core.switch_branch(source_branch)
    assert core.object_by_id(object_id)["params"] == source_params
    assert float(core.object_by_id(object_id)["params"]["sketch"]["constraints"][5]["value"]) == 40.0

    return {
        "source_branch": source_branch,
        "candidate_widths_mm": sorted(widths),
        "winner_width_mm": float(winner["parameters"]["sketch.width"]),
        "source_mass_kg": source_mass,
        "winner_mass_kg": winner_mass,
        "source_preserved": True,
        "raw_vertices_optimized": False,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 constrained-sketch campaign self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
