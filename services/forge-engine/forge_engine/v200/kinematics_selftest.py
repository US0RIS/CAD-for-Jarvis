from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 mechanism kinematics."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import analysis_contracts, design_intelligence, mechanism_kinematics


def _add_box(name: str, position: list[float], dims: list[float]) -> str:
    before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
    core.execute(
        "add",
        {
            "name": name,
            "kind": "box",
            "params": {"x": dims[0], "y": dims[1], "z": dims[2]},
            "material": "aluminum_6061_t6",
            "transform": {"position": position, "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        },
        actor="human",
        reason=f"Kinematics self-test: add {name}",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def _add_joint(args: dict[str, object]) -> str:
    before = {str(row.get("id")) for row in core.PROJECT.get("joints", []) if isinstance(row, dict)}
    core.execute("add_joint", args, actor="human", reason="Kinematics self-test: add joint")
    created = [row for row in core.PROJECT.get("joints", []) if isinstance(row, dict) and str(row.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    base = _add_box("Base", [0.0, 0.0, 0.0], [6.0, 6.0, 6.0])
    arm = _add_box("Arm", [20.0, 0.0, 0.0], [4.0, 4.0, 4.0])
    obstacle = _add_box("Obstacle", [0.0, 25.0, 0.0], [4.0, 4.0, 4.0])

    joint_id = _add_joint({
        "name": "Arm hinge",
        "type": "revolute",
        "parent_id": base,
        "child_id": arm,
        "origin_mm": [0.0, 0.0, 0.0],
        "axis": [0.0, 0.0, 1.0],
        "lower_deg": 0.0,
        "upper_deg": 90.0,
        "home_deg": 0.0,
        "validate_sweep": True,
    })

    end_pose = mechanism_kinematics.pose_for_joint(core.PROJECT, joint_id, 90.0)
    position = end_pose["transform"]["position"]
    assert math.isclose(float(position[0]), 0.0, abs_tol=1e-9)
    assert math.isclose(float(position[1]), 20.0, abs_tol=1e-9)
    assert math.isclose(float(position[2]), 0.0, abs_tol=1e-9)
    assert end_pose["transform"]["rotation_deg"] == [0.0, 0.0, 90.0]

    sweep = mechanism_kinematics.sweep_joint(core.PROJECT, joint_id, samples=10)
    assert sweep["collision_free"] is True, sweep["collisions"]
    assert sweep["sample_count"] == 10
    assert float(sweep["swept_bounds_mm"]["x"]) > 20.0
    assert float(sweep["swept_bounds_mm"]["y"]) > 20.0

    clean = mechanism_kinematics.analyze_kinematics(core.PROJECT, samples=9)
    assert clean["ok"] is True, clean["risks"]
    assert PROJECT.validation()["kinematics"]["ok"] is True

    contract = analysis_contracts.contracts()["kinematics"]
    assert contract["solver"] == "ForgeCAD MechanismKinematics"
    assert contract["joint_operation"]["revolute_schema"]["type"] == "revolute"
    architecture = design_intelligence.bootstrap_architecture(
        "Design a hinged mechanism and verify its full travel does not hit the enclosure.",
        PROJECT.snapshot(),
    )
    context = design_intelligence.build_planner_context(
        "Design a hinged mechanism and verify its full travel does not hit the enclosure.",
        architecture,
        PROJECT.snapshot(),
    )
    assert context["analysis_contracts"]["kinematics"]["analysis_endpoint"] == "/v2/analysis/kinematics"

    # Move the obstacle into the exact 90-degree arm position. The sampled validation
    # sweep includes both limits and must now expose a hard B-rep interference failure.
    core.execute(
        "transform",
        {"id": obstacle, "position": [0.0, 20.0, 0.0]},
        actor="human",
        reason="Kinematics self-test: create sweep collision",
    )
    failed = mechanism_kinematics.analyze_kinematics(core.PROJECT, samples=9)
    assert failed["ok"] is False
    collision_risk = next(risk for risk in failed["risks"] if risk.get("code") == "kinematic_sweep_collision")
    assert collision_risk["joint_id"] == joint_id
    failed_sweep = failed["items"][0]
    assert any(event["object_id"] == obstacle and float(event["intersection_volume_mm3"]) > 0.0 for event in failed_sweep["collisions"])

    validation = PROJECT.validation()
    assert validation["kinematics"]["ok"] is False
    assert any(risk.get("code") == "kinematic_sweep_collision" for risk in validation["risks"])

    return {
        "solver": sweep["solver"],
        "joint_id": joint_id,
        "end_position_mm": position,
        "initial_sweep_collision_free": True,
        "exact_brep_collision_detected": True,
        "validation_gate": True,
        "planner_contract": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 kinematics self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
