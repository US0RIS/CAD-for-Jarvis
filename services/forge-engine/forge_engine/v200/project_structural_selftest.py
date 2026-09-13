from __future__ import annotations

"""Regression gate for canonical project loads/constraints driving SolidFEA."""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core
from . import project_structural, structural_fea


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Boundary-condition beam",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "beam", "tags": ["fabricated", "solid-fea", "project-bc-selftest"]},
        },
        actor="human",
        reason="Create project-boundary-condition FEA fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    PROJECT.execute(
        "add_constraint",
        {
            "id": "support-xmin",
            "object_id": object_id,
            "type": "fixed",
            "face": "x_min",
            "dofs": ["x", "y", "z"],
        },
        actor="human",
        reason="Fix the local x-min face",
    )
    PROJECT.execute(
        "add_load",
        {
            "id": "tip-force",
            "object_id": object_id,
            "type": "force",
            "face": "x_max",
            "direction": "z",
            "force_n": 100.0,
        },
        actor="human",
        reason="Apply canonical tip-face load",
    )

    obj = core.object_by_id(object_id)
    boundary = project_structural.project_boundary_conditions(core.PROJECT, object_id)
    assert boundary["complete"] is True
    assert boundary["targeted_record_count"] == 2
    assert boundary["supports"][0]["face"] == "x_min"
    assert boundary["loads"][0]["vector_n"] == [0.0, 0.0, 100.0]

    explicit = project_structural.solve_project_box(obj)
    implicit = structural_fea.solve_box(obj, force_n=100.0, load_direction="z")
    assert explicit["supported"] is True
    assert implicit["supported"] is True
    assert explicit["boundary_condition_source"] == "project.loads + project.constraints"
    assert explicit["supports"][0]["id"] == "support-xmin"
    assert explicit["loads"][0]["id"] == "tip-force"
    assert abs(explicit["max_displacement_mm"] - implicit["max_displacement_mm"]) <= 1e-10
    assert abs(explicit["max_von_mises_stress_mpa"] - implicit["max_von_mises_stress_mpa"]) <= 1e-10
    assert abs(explicit["yield_fos"] - implicit["yield_fos"]) <= 1e-10
    assert explicit["equilibrium_relative_error"] < 1e-9
    assert explicit["mesh"]["fixed_dof"] > 0

    # The production simulation must promote the canonical-BC result while retaining the
    # original implicit preview for comparison and provenance.
    screen = PROJECT.run_simulation(object_id, {"force_n": 23.0, "load_direction": "y", "convergence": False})
    assert screen["structural_3d_project"]["supported"] is True
    assert screen["structural_3d_project"]["loads"][0]["vector_n"] == [0.0, 0.0, 100.0]
    assert screen["analysis_provenance"]["primary_structural_result"] == "structural_3d_project"
    assert screen["analysis_provenance"]["boundary_condition_source"] == "canonical_project"
    assert screen["structural_3d"]["load"]["force_n"] == 23.0
    latest = next(row for row in reversed(core.PROJECT["simulations"]) if row.get("kind") == "engineering_screen_v2")
    assert latest["result"]["analysis_provenance"]["primary_structural_result"] == "structural_3d_project"

    # Targeted unsupported physics must fail closed rather than disappearing from the
    # analysis. Untargeted system records may coexist without contaminating this body.
    unsupported_project = deepcopy(core.PROJECT)
    unsupported_project["loads"].append({"id": "other-body-pressure", "object_id": "other-body", "type": "pressure", "face": "x_max", "pressure_mpa": 1.0})
    assert project_structural.project_boundary_conditions(unsupported_project, object_id)["unsupported"] == []
    unsupported_project["loads"].append({"id": "pressure", "object_id": object_id, "type": "pressure", "face": "x_max", "pressure_mpa": 1.0})
    blocked = project_structural.solve_project_box(obj, unsupported_project)
    assert blocked["supported"] is False
    assert blocked["solver_grade"] == "unsupported_boundary_conditions"
    assert any(row["id"] == "pressure" for row in blocked["boundary_conditions"]["unsupported"])

    # Orthogonal supports are no longer hard-wired to x-min. A y-min fixed face and
    # vector load on y-max must solve and equilibrate.
    rotated_project = deepcopy(core.PROJECT)
    rotated_project["constraints"] = [{"id": "support-ymin", "object_id": object_id, "type": "encastre", "face": "y_min"}]
    rotated_project["loads"] = [{"id": "load-ymax", "object_id": object_id, "type": "force_vector", "face": "y_max", "vector_n": [30.0, 0.0, -40.0]}]
    rotated = project_structural.solve_project_box(obj, rotated_project, mesh_counts=(4, 3, 3))
    assert rotated["supported"] is True
    assert rotated["supports"][0]["face"] == "y_min"
    assert rotated["external_force_n"] == [30.0, 0.0, -40.0]
    assert rotated["equilibrium_relative_error"] < 1e-9
    assert rotated["max_displacement_mm"] > 0.0

    return {
        "object_id": object_id,
        "boundary_records": boundary["targeted_record_count"],
        "implicit_match": True,
        "project_primary_result": screen["analysis_provenance"]["primary_structural_result"],
        "orthogonal_support": rotated["supports"][0]["face"],
        "vector_load_n": rotated["external_force_n"],
        "equilibrium_relative_error": rotated["equilibrium_relative_error"],
        "unsupported_physics_blocked": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 project boundary-condition FEA self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
