from __future__ import annotations

"""Regression gate for named-parameter geometry and load inputs in project SolidFEA."""

from copy import deepcopy

from ..engineering_state import PROJECT
from ..v110 import core
from . import project_structural, project_structural_parametric


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute("set_design_parameter", {"name": "beam_thickness", "value": 10.0, "unit": "mm"}, actor="human", reason="Set beam thickness")
    PROJECT.execute("set_design_parameter", {"name": "service_load", "value": 100.0, "unit": "N"}, actor="human", reason="Set service load")
    PROJECT.execute(
        "add",
        {
            "name": "Parametric FEA beam",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": {"expr": "beam_thickness"}},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "beam", "tags": ["fabricated", "parametric", "project-fea"]},
        },
        actor="human",
        reason="Create expression-driven beam",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    PROJECT.execute(
        "add_constraint",
        {"id": "fixed", "object_id": object_id, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Fix beam root",
    )
    PROJECT.execute(
        "add_load",
        {"id": "service", "object_id": object_id, "type": "force", "face": "x_max", "force_n": {"expr": "service_load"}, "direction": "-z"},
        actor="human",
        reason="Apply named service load",
    )

    canonical_before = deepcopy(core.PROJECT)
    result = project_structural.solve_project_box(core.object_by_id(object_id), core.PROJECT, mesh_counts=(4, 2, 2))
    assert result["supported"] is True
    assert result["design_parameter_values"]["beam_thickness"] == 10.0
    assert result["design_parameter_values"]["service_load"] == 100.0
    assert result["loads"][0]["vector_n"] == [0.0, 0.0, -100.0]
    assert result["provenance"]["parametric_inputs"].startswith("resolved from canonical")
    assert core.PROJECT["objects"][-1]["params"]["z"] == {"expr": "beam_thickness"}
    assert core.PROJECT["loads"][-1]["force_n"] == {"expr": "service_load"}
    assert core.PROJECT["objects"] == canonical_before["objects"]
    assert core.PROJECT["loads"] == canonical_before["loads"]

    first_displacement = float(result["max_displacement_mm"])
    PROJECT.execute("set_design_parameter", {"name": "beam_thickness", "value": 12.0, "unit": "mm"}, actor="human", reason="Increase beam thickness")
    PROJECT.execute("set_design_parameter", {"name": "service_load", "value": 150.0, "unit": "N"}, actor="human", reason="Increase service load")
    updated = project_structural.solve_project_box(core.object_by_id(object_id), core.PROJECT, mesh_counts=(4, 2, 2))
    assert updated["supported"] is True
    assert updated["design_parameter_values"]["beam_thickness"] == 12.0
    assert updated["design_parameter_values"]["service_load"] == 150.0
    assert updated["loads"][0]["vector_n"] == [0.0, 0.0, -150.0]
    assert float(updated["max_displacement_mm"]) != first_displacement

    resolved_project = project_structural_parametric.resolved_analysis_project(core.PROJECT)
    assert resolved_project["loads"][-1]["force_n"] == 150.0
    assert core.PROJECT["loads"][-1]["force_n"] == {"expr": "service_load"}

    screen = PROJECT.run_simulation(object_id, {"convergence": False})
    assert screen["structural_3d_project"]["supported"] is True
    assert screen["structural_3d_project"]["loads"][0]["vector_n"] == [0.0, 0.0, -150.0]
    assert screen["analysis_provenance"]["primary_structural_result"] == "structural_3d_project"

    return {
        "object_id": object_id,
        "symbolic_geometry_preserved": True,
        "symbolic_load_preserved": True,
        "resolved_thickness_mm": updated["design_parameter_values"]["beam_thickness"],
        "resolved_load_n": abs(updated["loads"][0]["vector_n"][2]),
        "project_fea_primary": screen["analysis_provenance"]["primary_structural_result"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 parametric project SolidFEA self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
