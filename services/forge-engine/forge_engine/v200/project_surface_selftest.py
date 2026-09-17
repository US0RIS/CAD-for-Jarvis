from __future__ import annotations

"""Regression gate for canonical engineering records exposed through project snapshots."""

from ..engineering_state import PROJECT
from ..v110 import core


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute("set_design_parameter", {"name": "thickness", "value": 8.0, "unit": "mm"}, actor="human", reason="Create surfaced parameter")
    PROJECT.execute(
        "add",
        {
            "name": "Surface test body",
            "kind": "box",
            "params": {"x": 80.0, "y": 20.0, "z": {"expr": "thickness"}},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "beam", "tags": ["surface-selftest"]},
        },
        actor="human",
        reason="Create surface test geometry",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])
    PROJECT.execute(
        "add_constraint",
        {"id": "support", "object_id": object_id, "type": "fixed", "face": "x_min", "dofs": ["x", "y", "z"]},
        actor="human",
        reason="Create surfaced support",
    )
    PROJECT.execute(
        "add_load",
        {"id": "load", "object_id": object_id, "type": "force", "face": "x_max", "force_n": 75.0, "direction": "-z"},
        actor="human",
        reason="Create surfaced load",
    )
    simulation = PROJECT.run_simulation(object_id, {"convergence": False})
    assert simulation["structural_3d_project"]["supported"] is True

    snapshot = PROJECT.snapshot()
    state = snapshot["engineering_state"]
    assert state["version"] == "2.0.0"
    assert state["design_parameters"]["thickness"]["value"] == 8.0
    assert state["parameter_report"]["values"]["thickness"] == 8.0
    assert state["loads"][0]["id"] == "load"
    assert state["constraints"][0]["id"] == "support"
    assert state["units"] == "mm"
    assert state["coordinate_system"] == "Z-up"
    summary = state["simulation_summary"][-1]
    assert summary["kind"] == "engineering_screen_v2"
    assert summary["object_id"] == object_id
    assert summary["primary_structural_result"] == "structural_3d_project"
    assert summary["physical_verification"] is False
    assert "stress_field" not in summary
    assert state["physical_feedback"]["branch"] == snapshot["active_branch"]

    return {
        "version": state["version"],
        "design_parameters": state["parameter_report"]["count"],
        "loads": len(state["loads"]),
        "constraints": len(state["constraints"]),
        "simulation_summaries": len(state["simulation_summary"]),
        "primary_structural_result": summary["primary_structural_result"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 project surface self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
