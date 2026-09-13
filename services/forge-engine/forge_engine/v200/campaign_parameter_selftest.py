from __future__ import annotations

"""Regression gate for campaign optimization through named design relationships."""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core
from . import parametric_expressions


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "set_design_parameter",
        {"name": "plate_width", "value": 40.0, "unit": "mm", "description": "Independent plate width"},
        actor="human",
        reason="Create campaign parameter fixture",
    )
    PROJECT.execute(
        "set_design_parameter",
        {"name": "edge_margin", "value": 5.0, "unit": "mm", "description": "Independent edge margin"},
        actor="human",
        reason="Create dependent geometry fixture",
    )
    PROJECT.execute(
        "set_design_parameter",
        {"name": "overall_width", "expression": "plate_width + 2 * edge_margin", "unit": "mm", "description": "Derived overall envelope"},
        actor="human",
        reason="Encode a named parametric relationship",
    )
    PROJECT.execute(
        "add",
        {
            "name": "Expression-driven campaign plate",
            "kind": "box",
            "params": {"x": {"expr": "overall_width"}, "y": 20.0, "z": 3.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "plate", "tags": ["fabricated", "parametric", "campaign-parameter-selftest"]},
        },
        actor="human",
        reason="Create expression-driven campaign body",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    source_branch = core.ACTIVE_DESIGN
    source_definitions = deepcopy(core.PROJECT["design_parameters"])
    source_width = float(core.build_shape(core.object_by_id(object_id)).BoundingBox().xlen)
    assert abs(source_width - 50.0) < 1e-6

    result = PROJECT.run_campaign(
        object_id,
        {
            "objective": "mass",
            "force_n": 0.1,
            "deflection_max_mm": 1000000.0,
            "yield_fos_min": 0.000001,
            "max_candidates": 3,
            "process": "cnc",
            # The object uses overall_width, a derived expression. The campaign must
            # trace that dependency and mutate plate_width, not replace the expression.
            "variables": [{"name": "plate_width", "min": 30.0, "max": 50.0}],
        },
    )

    assert len(result["variables"]) == 1
    variable = result["variables"][0]
    assert variable["name"] == "design.plate_width"
    assert variable["kind"] == "design_parameter"
    assert variable["parameter_name"] == "plate_width"
    assert variable["path"] == ["design_parameters", "plate_width", "value"]
    assert variable["unit"] == "mm"

    widths = {float(row["parameters"]["design.plate_width"]) for row in result["candidates"]}
    assert widths == {30.0, 40.0, 50.0}, widths
    for row in result["candidates"]:
        core.switch_branch(str(row["branch"]))
        parameter_value = float(core.PROJECT["design_parameters"]["plate_width"]["value"])
        assert abs(parameter_value - float(row["parameters"]["design.plate_width"])) < 1e-9
        assert core.PROJECT["design_parameters"]["overall_width"]["expression"] == "plate_width + 2 * edge_margin"
        candidate = core.object_by_id(object_id)
        # Canonical geometry stays symbolic rather than getting frozen into a literal.
        assert candidate["params"]["x"] == {"expr": "overall_width"}
        expected = parameter_value + 10.0
        actual = float(core.build_shape(candidate).BoundingBox().xlen)
        assert abs(actual - expected) < 1e-6

    winner = result["winner"]
    assert winner is not None and winner["feasible"] is True
    assert float(winner["parameters"]["design.plate_width"]) == 30.0
    core.switch_branch(str(result["winner_branch"]))
    report = parametric_expressions.parameter_report()
    assert report["values"]["plate_width"] == 30.0
    assert report["values"]["overall_width"] == 40.0

    core.switch_branch(source_branch)
    assert core.PROJECT["design_parameters"] == source_definitions
    assert core.object_by_id(object_id)["params"]["x"] == {"expr": "overall_width"}
    assert abs(float(core.build_shape(core.object_by_id(object_id)).BoundingBox().xlen) - 50.0) < 1e-6

    return {
        "source_branch": source_branch,
        "candidate_plate_widths_mm": sorted(widths),
        "winner_plate_width_mm": float(winner["parameters"]["design.plate_width"]),
        "winner_overall_width_mm": 40.0,
        "derived_expression_preserved": True,
        "source_preserved": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 design-parameter campaign self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
