from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 constrained 2D sketches."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import sketch_solver


def rectangle_sketch() -> dict[str, object]:
    return {
        "points": [[0.0, 0.0], [39.0, 1.0], [40.0, 21.0], [-1.0, 19.0]],
        "constraints": [
            {"type": "fixed", "point": 0, "x": 0.0, "y": 0.0},
            {"type": "horizontal", "a": 0, "b": 1},
            {"type": "vertical", "a": 1, "b": 2},
            {"type": "horizontal", "a": 2, "b": 3},
            {"type": "vertical", "a": 3, "b": 0},
            {"type": "distance", "a": 0, "b": 1, "value": 40.0},
            {"type": "distance", "a": 1, "b": 2, "value": 20.0},
        ],
        "require_fully_constrained": True,
    }


def run() -> dict[str, object]:
    sketch = rectangle_sketch()
    report = sketch_solver.solve_sketch(sketch["points"], sketch["constraints"])
    assert report["status"] == "fully_constrained", report
    assert report["fully_constrained"] is True
    assert report["degrees_of_freedom"] == 0
    assert report["equation_count"] == 8
    assert report["max_residual"] < 1e-5
    solved = report["points"]
    assert abs(solved[0][0]) < 1e-6 and abs(solved[0][1]) < 1e-6
    assert abs(solved[1][0] - 40.0) < 1e-5 and abs(solved[1][1]) < 1e-5
    assert abs(solved[2][0] - 40.0) < 1e-5 and abs(solved[2][1] - 20.0) < 1e-5
    assert abs(solved[3][0]) < 1e-5 and abs(solved[3][1] - 20.0) < 1e-5

    under = sketch_solver.solve_sketch([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], [])
    assert under["status"] == "under_constrained"
    assert under["degrees_of_freedom"] == 6

    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Constrained mounting profile",
            "kind": "constrained_sketch_extrude",
            "params": {"height": 3.0, "sketch": sketch},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "structural_profile", "tags": ["fabricated", "parametric", "constrained-sketch"]},
        },
        actor="human",
        reason="Exercise constrained sketch B-rep generation",
    )
    obj = core.PROJECT["objects"][-1]
    object_report = sketch_solver.sketch_report_for_object(obj)
    assert object_report["fully_constrained"] is True
    shape = core.build_shape(obj)
    bounds = shape.BoundingBox()
    assert abs(bounds.xlen - 40.0) < 1e-4
    assert abs(bounds.ylen - 20.0) < 1e-4
    # Current ForgeCAD centered extrusion convention uses the supplied distance in each
    # direction, matching the existing sketch_extrude primitive.
    assert abs(bounds.zlen - 6.0) < 1e-4

    metrics = core.object_metrics(obj)
    assert metrics["volume_mm3"] > 0.0
    assert metrics["geometry_fidelity"] == "exact_brep"

    return {
        "status": report["status"],
        "degrees_of_freedom": report["degrees_of_freedom"],
        "equations": report["equation_count"],
        "max_residual": report["max_residual"],
        "brep_bounds_mm": [round(bounds.xlen, 4), round(bounds.ylen, 4), round(bounds.zlen, 4)],
        "underconstrained_dof": under["degrees_of_freedom"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 constrained sketch self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
