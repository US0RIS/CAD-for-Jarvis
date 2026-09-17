from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 deterministic tolerance stacks."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import project_structural, tolerance_analysis


def run() -> dict[str, object]:
    direct = tolerance_analysis.analyze_stack(
        [
            {
                "id": "A",
                "name": "Housing width",
                "nominal_mm": 10.0,
                "minus_mm": 0.10,
                "plus_mm": 0.10,
                "sigma_mm": 0.02,
                "coefficient": 1.0,
            },
            {
                "id": "B",
                "name": "Insert width",
                "nominal_mm": 4.0,
                "minus_mm": 0.05,
                "plus_mm": 0.20,
                "sigma_mm": 0.03,
                "coefficient": -1.0,
            },
        ],
        name="clearance",
        lower_spec_mm=5.65,
        upper_spec_mm=6.20,
    )
    assert math.isclose(direct["nominal_mm"], 6.0, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(direct["worst_case"]["min_mm"], 5.70, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(direct["worst_case"]["max_mm"], 6.15, rel_tol=0.0, abs_tol=1e-12)
    assert direct["worst_case"]["passes_spec"] is True
    assert math.isclose(direct["rss"]["minus_from_nominal_mm"], math.sqrt(0.10**2 + 0.20**2), rel_tol=1e-12)
    assert math.isclose(direct["rss"]["plus_from_nominal_mm"], math.sqrt(0.10**2 + 0.05**2), rel_tol=1e-12)
    assert direct["statistical"]["available"] is True
    assert math.isclose(direct["statistical"]["combined_sigma_mm"], math.sqrt(0.02**2 + 0.03**2), rel_tol=1e-12)
    assert 0.99 < direct["statistical"]["yield_fraction"] <= 1.0
    assert direct["statistical"]["cp"] > 2.0
    assert direct["sensitivity_ranked"][0]["id"] == "B"

    # No hidden sigma inference: a drawing tolerance by itself is not process capability.
    no_sigma = tolerance_analysis.analyze_stack(
        [{"name": "Unknown process", "nominal_mm": 5.0, "minus_mm": 0.1, "plus_mm": 0.1}],
        lower_spec_mm=4.7,
        upper_spec_mm=5.3,
    )
    assert no_sigma["statistical"]["available"] is False
    assert no_sigma["statistical"]["yield_fraction"] is None

    PROJECT.new_project()
    PROJECT.execute(
        "set_design_parameter",
        {"name": "body_width", "value": 40.0, "unit": "mm", "description": "Nominal body width"},
        actor="human",
        reason="Tolerance self-test design parameter",
    )
    PROJECT.execute(
        "add",
        {
            "name": "Parametric tolerance body",
            "kind": "box",
            "params": {"x": {"expr": "body_width"}, "y": 20.0, "z": 6.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "tolerance_fixture", "tags": ["fabricated", "parametric"]},
        },
        actor="human",
        reason="Create tolerance-linked geometry",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])

    # Structural constraints and tolerance constraints share canonical project storage,
    # but the structural parser must ignore the explicit nonstructural tolerance records.
    PROJECT.execute(
        "add_constraint",
        {"object_id": object_id, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Structural support",
    )
    PROJECT.execute(
        "add_load",
        {"object_id": object_id, "type": "force", "face": "x_max", "vector_n": [0.0, 0.0, -100.0]},
        actor="human",
        reason="Structural load",
    )
    PROJECT.execute(
        "add_constraint",
        {
            "object_id": object_id,
            "type": "dimension_tolerance",
            "stack": "assembly_clearance",
            "name": "Body width",
            "parameter": "x",
            "coefficient": 1.0,
            "minus_mm": 0.10,
            "plus_mm": 0.15,
            "sigma_mm": 0.03,
        },
        actor="human",
        reason="Canonical tolerance contributor tied to resolved CAD dimension",
    )
    PROJECT.execute(
        "add_constraint",
        {
            "type": "dimension_tolerance",
            "stack": "assembly_clearance",
            "name": "Mating part",
            "nominal_mm": 39.4,
            "coefficient": -1.0,
            "minus_mm": 0.10,
            "plus_mm": 0.10,
            "sigma_mm": 0.025,
        },
        actor="human",
        reason="Literal mating contributor",
    )
    PROJECT.execute(
        "add_constraint",
        {
            "type": "tolerance_spec",
            "stack": "assembly_clearance",
            "name": "Assembly clearance",
            "lower_spec_mm": 0.30,
            "upper_spec_mm": 0.90,
        },
        actor="human",
        reason="Functional clearance specification",
    )

    stacks = tolerance_analysis.project_stacks(core.PROJECT)
    assert stacks["count"] == 1 and stacks["ok"] is True
    stack = stacks["items"][0]
    assert stack["id"] == "assembly_clearance"
    assert math.isclose(stack["nominal_mm"], 0.6, abs_tol=1e-9)
    assert math.isclose(stack["worst_case"]["min_mm"], 0.4, abs_tol=1e-9)
    assert math.isclose(stack["worst_case"]["max_mm"], 0.85, abs_tol=1e-9)
    assert stack["worst_case"]["passes_spec"] is True
    assert stack["contributors"][0]["source"] == f"object:{object_id}:params.x"
    assert stacks["design_parameter_values"]["body_width"] == 40.0

    boundary = project_structural.project_boundary_conditions(core.PROJECT, object_id)
    assert boundary["complete"] is True
    assert boundary["targeted_record_count"] == 2
    assert boundary["unsupported"] == []

    return {
        "direct_nominal_mm": direct["nominal_mm"],
        "direct_worst_case_mm": [direct["worst_case"]["min_mm"], direct["worst_case"]["max_mm"]],
        "explicit_sigma_required": no_sigma["statistical"]["available"] is False,
        "project_stack_nominal_mm": stack["nominal_mm"],
        "project_stack_passes": stack["worst_case"]["passes_spec"],
        "structural_bc_records": boundary["targeted_record_count"],
        "tolerance_does_not_poison_fea": boundary["complete"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 tolerance-stack self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
