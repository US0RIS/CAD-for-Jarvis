from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 canonical fluid networks."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import analysis_contracts, design_intelligence, fluid_network, project_structural


def _add_box(name: str, position: list[float]) -> str:
    before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
    core.execute(
        "add",
        {
            "name": name,
            "kind": "box",
            "params": {"x": 20.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "transform": {"position": position, "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        },
        actor="human",
        reason=f"Fluid self-test: add {name}",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    source = _add_box("Hydraulic source", [0.0, 0.0, 0.0])
    actuator = _add_box("Hydraulic actuator", [60.0, 0.0, 0.0])

    core.execute(
        "add_constraint",
        {"object_id": source, "type": "fluid_pressure", "pressure_kpa": 200.0},
        actor="human",
        reason="Fluid self-test: 200 kPa source boundary",
    )
    core.execute(
        "add_constraint",
        {"type": "fluid_link", "a_id": source, "b_id": actuator, "resistance_pa_s_m3": 1.0e10},
        actor="human",
        reason="Fluid self-test: explicit hydraulic resistance",
    )
    core.execute(
        "add_load",
        {"object_id": actuator, "type": "fluid_demand", "flow_l_min": 0.6},
        actor="human",
        reason="Fluid self-test: 0.6 L/min actuator demand",
    )
    core.execute(
        "add_constraint",
        {"object_id": actuator, "type": "fluid_pressure_limit", "min_pressure_kpa": 90.0},
        actor="human",
        reason="Fluid self-test: passing pressure requirement",
    )

    # Structural and fluid records must coexist without the hydraulic metadata being
    # misinterpreted as unsupported structural FEA boundary conditions.
    core.execute(
        "add_constraint",
        {"object_id": actuator, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Fluid self-test: structural support coexistence",
    )
    core.execute(
        "add_load",
        {"object_id": actuator, "type": "force", "face": "x_max", "vector_n": [0.0, 0.0, -10.0]},
        actor="human",
        reason="Fluid self-test: structural load coexistence",
    )

    boundary = project_structural.project_boundary_conditions(core.PROJECT, actuator)
    assert boundary["targeted_record_count"] == 2, boundary
    assert len(boundary["supports"]) == 1
    assert len(boundary["loads"]) == 1
    assert boundary["unsupported"] == []

    solved = fluid_network.solve_fluid_network(core.PROJECT)
    assert solved["requested"] is True
    assert solved["supported"] is True
    assert solved["solver"] == "ForgeCAD FluidNetwork"
    pressures = {str(node["object_id"]): float(node["pressure_pa"]) for node in solved["nodes"]}
    # 0.6 L/min = 1e-5 m^3/s. Delta-p = RQ = 1e10 * 1e-5 = 100 kPa.
    assert math.isclose(pressures[source], 200_000.0, rel_tol=1e-12, abs_tol=1e-9)
    assert math.isclose(pressures[actuator], 100_000.0, rel_tol=1e-12, abs_tol=1e-9)
    assert len(solved["links"]) == 1
    assert math.isclose(float(solved["links"][0]["flow_l_min"]), 0.6, rel_tol=1e-12, abs_tol=1e-12)
    assert abs(float(solved["continuity"]["max_unknown_node_residual_m3_s"])) < 1e-14
    assert solved["limits"][0]["passed"] is True

    clean = fluid_network.analyze_fluid(core.PROJECT)
    assert clean["ok"] is True, clean.get("risks")
    assert clean["counts"]["error"] == 0

    contract = analysis_contracts.contracts()["fluid"]
    assert contract["solver"] == "ForgeCAD FluidNetwork"
    assert "No hose" in contract["fluid_link"]["policy"]
    architecture = design_intelligence.bootstrap_architecture(
        "Design a small hydraulic actuator circuit and verify pressure and flow.",
        PROJECT.snapshot(),
    )
    context = design_intelligence.build_planner_context(
        "Design a small hydraulic actuator circuit and verify pressure and flow.",
        architecture,
        PROJECT.snapshot(),
    )
    assert context["analysis_contracts"]["fluid"]["analysis_endpoint"] == "/v2/analysis/fluid-network"

    # A fluid model without a pressure reference must fail closed rather than receiving
    # an invented pump/reservoir boundary.
    floating = core.upgrade_project(core.default_project())
    floating.update({
        "objects": [dict(obj) for obj in core.PROJECT.get("objects", [])],
        "loads": [{"object_id": actuator, "type": "fluid_demand", "flow_l_min": 0.6}],
        "constraints": [{"type": "fluid_link", "a_id": source, "b_id": actuator, "resistance_pa_s_m3": 1.0e10}],
    })
    floating_result = fluid_network.analyze_fluid(floating)
    assert floating_result["ok"] is False
    assert any(risk.get("code") == "fluid_model_invalid" for risk in floating_result["risks"])

    # Tighten the canonical pressure requirement above the deterministic 100 kPa result.
    # The same model must now block project validation and therefore the bounded repair loop.
    core.execute(
        "add_constraint",
        {"object_id": actuator, "type": "fluid_pressure_limit", "min_pressure_kpa": 110.0},
        actor="human",
        reason="Fluid self-test: intentional pressure-limit failure",
    )
    failed = fluid_network.analyze_fluid(core.PROJECT)
    assert failed["ok"] is False
    assert any(risk.get("code") == "fluid_pressure_limit_exceeded" for risk in failed["risks"])

    project_validation = PROJECT.validation()
    assert project_validation["fluid"]["ok"] is False
    assert any(risk.get("code") == "fluid_pressure_limit_exceeded" for risk in project_validation["risks"])

    return {
        "solver": solved["solver"],
        "node_count": solved["node_count"],
        "source_pressure_kpa": pressures[source] / 1000.0,
        "actuator_pressure_kpa": pressures[actuator] / 1000.0,
        "flow_l_min": solved["links"][0]["flow_l_min"],
        "continuity_residual_m3_s": solved["continuity"]["max_unknown_node_residual_m3_s"],
        "structural_bc_isolation": True,
        "floating_network_rejected": True,
        "repair_loop_pressure_gate": True,
        "planner_contract": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 fluid network self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
