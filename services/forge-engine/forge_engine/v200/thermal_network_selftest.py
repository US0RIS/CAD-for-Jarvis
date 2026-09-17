from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 canonical thermal networks."""

from copy import deepcopy
import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import analysis_contracts, design_intelligence, project_structural, thermal_network


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
        reason=f"Thermal self-test: add {name}",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    heater = _add_box("10 W electronics", [0.0, 0.0, 0.0])
    sink = _add_box("25 C cold plate", [60.0, 0.0, 0.0])

    core.execute(
        "add_load",
        {"object_id": heater, "type": "heat", "heat_w": 10.0},
        actor="human",
        reason="Thermal self-test: 10 W heat source",
    )
    core.execute(
        "add_constraint",
        {"type": "thermal_link", "a_id": heater, "b_id": sink, "conductance_w_k": 2.0},
        actor="human",
        reason="Thermal self-test: explicit 2 W/K conductance",
    )
    core.execute(
        "add_constraint",
        {"object_id": sink, "type": "fixed_temperature", "temperature_c": 25.0},
        actor="human",
        reason="Thermal self-test: cold plate boundary",
    )
    core.execute(
        "add_constraint",
        {"object_id": heater, "type": "temperature_limit", "max_temperature_c": 31.0},
        actor="human",
        reason="Thermal self-test: passing temperature requirement",
    )

    # Structural and thermal canonical records may coexist on the same object. Thermal
    # metadata must not be misclassified as an unsupported structural boundary condition.
    core.execute(
        "add_constraint",
        {"object_id": heater, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Thermal self-test: structural support coexistence",
    )
    core.execute(
        "add_load",
        {"object_id": heater, "type": "force", "face": "x_max", "vector_n": [0.0, 0.0, -10.0]},
        actor="human",
        reason="Thermal self-test: structural load coexistence",
    )

    boundary = project_structural.project_boundary_conditions(core.PROJECT, heater)
    assert boundary["targeted_record_count"] == 2, boundary
    assert len(boundary["supports"]) == 1
    assert len(boundary["loads"]) == 1
    assert boundary["unsupported"] == []

    solved = thermal_network.solve_thermal_network(core.PROJECT)
    assert solved["requested"] is True
    assert solved["supported"] is True
    assert solved["solver"] == "ForgeCAD ThermalNetwork"
    temperatures = {str(node["object_id"]): float(node["temperature_c"]) for node in solved["nodes"]}
    assert math.isclose(temperatures[heater], 30.0, rel_tol=1e-10, abs_tol=1e-10)
    assert math.isclose(temperatures[sink], 25.0, rel_tol=1e-10, abs_tol=1e-10)
    balance = solved["energy_balance"]
    assert math.isclose(float(balance["generated_heat_w"]), 10.0, rel_tol=1e-10)
    assert math.isclose(float(balance["fixed_sink_removal_w"]), 10.0, rel_tol=1e-10)
    assert abs(float(balance["residual_w"])) < 1e-9
    assert solved["limits"][0]["passed"] is True

    clean = thermal_network.analyze_thermal(core.PROJECT)
    assert clean["ok"] is True, clean.get("risks")
    assert clean["counts"]["error"] == 0

    contract = analysis_contracts.contracts()["thermal"]
    assert contract["solver"] == "ForgeCAD ThermalNetwork"
    assert contract["thermal_link"]["policy"].startswith("Never infer contact conductance")
    architecture = design_intelligence.bootstrap_architecture(
        "Design a cooled electronics enclosure and verify steady-state temperature.",
        PROJECT.snapshot(),
    )
    context = design_intelligence.build_planner_context(
        "Design a cooled electronics enclosure and verify steady-state temperature.",
        architecture,
        PROJECT.snapshot(),
    )
    assert context["analysis_contracts"]["thermal"]["analysis_endpoint"] == "/v2/analysis/thermal-network"

    # A floating subnetwork must fail closed instead of receiving an invented ambient
    # boundary or guessed contact conductance.
    floating = deepcopy(core.PROJECT)
    floating["constraints"] = [
        row for row in floating.get("constraints", [])
        if str(row.get("type") or "").lower() not in {"fixed_temperature", "temperature", "thermal_sink", "temperature_boundary"}
    ]
    floating_result = thermal_network.analyze_thermal(floating)
    assert floating_result["ok"] is False
    assert any(risk.get("code") == "thermal_model_invalid" for risk in floating_result["risks"])

    # Tighten the canonical temperature requirement. The same deterministic model now
    # becomes a project validation failure visible to the bounded repair loop.
    core.execute(
        "add_constraint",
        {"object_id": heater, "type": "temperature_limit", "max_temperature_c": 29.0},
        actor="human",
        reason="Thermal self-test: intentional temperature-limit failure",
    )
    failed = thermal_network.analyze_thermal(core.PROJECT)
    assert failed["ok"] is False
    assert any(risk.get("code") == "temperature_limit_exceeded" for risk in failed["risks"])

    project_validation = PROJECT.validation()
    assert project_validation["thermal"]["ok"] is False
    assert any(risk.get("code") == "temperature_limit_exceeded" for risk in project_validation["risks"])

    return {
        "solver": solved["solver"],
        "node_count": solved["node_count"],
        "heater_temperature_c": temperatures[heater],
        "sink_temperature_c": temperatures[sink],
        "energy_balance_residual_w": balance["residual_w"],
        "structural_bc_isolation": True,
        "floating_network_rejected": True,
        "repair_loop_temperature_gate": True,
        "planner_contract": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 thermal network self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
