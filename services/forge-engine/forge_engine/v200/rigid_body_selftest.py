from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 assembly mass properties and rigid-body dynamics."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import rigid_body_dynamics


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Dynamics block",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "semantic": {"role": "rigid_body_fixture", "tags": ["fabricated", "dynamics"]},
        },
        actor="human",
        reason="Create rigid-body regression fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])

    props = rigid_body_dynamics.assembly_mass_properties(core.PROJECT)
    expected_mass = 100.0 * 20.0 * 10.0 * 1e-9 * 2700.0
    assert math.isclose(props["mass_kg"], expected_mass, rel_tol=1e-9, abs_tol=1e-12)
    assert props["center_of_mass_mm"] == [0.0, 0.0, 0.0]
    assert props["object_count"] == 1
    assert props["inertia_approximation_count"] == 0
    body = props["bodies"][0]
    assert body["id"] == object_id
    assert body["inertia_fidelity"] == "analytic_box"

    expected_ixx = expected_mass * ((0.02 ** 2) + (0.01 ** 2)) / 12.0
    expected_iyy = expected_mass * ((0.10 ** 2) + (0.01 ** 2)) / 12.0
    expected_izz = expected_mass * ((0.10 ** 2) + (0.02 ** 2)) / 12.0
    inertia = props["inertia_tensor_com_kg_m2"]
    assert math.isclose(inertia[0][0], expected_ixx, rel_tol=1e-9)
    assert math.isclose(inertia[1][1], expected_iyy, rel_tol=1e-9)
    assert math.isclose(inertia[2][2], expected_izz, rel_tol=1e-9)
    assert max(abs(inertia[row][col]) for row in range(3) for col in range(3) if row != col) < 1e-12

    response = rigid_body_dynamics.rigid_body_response(
        core.PROJECT,
        object_ids=[object_id],
        force_n=[5.4, 0.0, 0.0],
        torque_nm=[0.0, 0.0, 0.01],
        gravity_m_s2=[0.0, 0.0, 0.0],
        duration_s=0.1,
    )
    linear = response["response"]["linear_acceleration_m_s2"]
    assert math.isclose(linear[0], 100.0, rel_tol=1e-9)
    assert math.isclose(response["response"]["final_velocity_m_s"][0], 10.0, rel_tol=1e-9)
    assert math.isclose(response["response"]["displacement_m"][0], 0.5, rel_tol=1e-9)
    expected_alpha_z = 0.01 / expected_izz
    assert math.isclose(response["response"]["angular_acceleration_rad_s2"][2], expected_alpha_z, rel_tol=1e-9)
    assert response["physical_verification"] is False

    # Validate the parallel-axis theorem on a second identical block translated +200 mm.
    PROJECT.execute(
        "add",
        {
            "name": "Offset dynamics block",
            "kind": "box",
            "params": {"x": 100.0, "y": 20.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "transform": {"position": [200.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "semantic": {"role": "rigid_body_fixture", "tags": ["fabricated", "dynamics"]},
        },
        actor="human",
        reason="Exercise assembly center of mass and parallel-axis inertia",
    )
    pair = rigid_body_dynamics.assembly_mass_properties(core.PROJECT)
    assert math.isclose(pair["mass_kg"], 2.0 * expected_mass, rel_tol=1e-9)
    assert math.isclose(pair["center_of_mass_mm"][0], 100.0, abs_tol=1e-9)
    expected_pair_iyy = 2.0 * (expected_iyy + expected_mass * 0.1 ** 2)
    expected_pair_izz = 2.0 * (expected_izz + expected_mass * 0.1 ** 2)
    assert math.isclose(pair["inertia_tensor_com_kg_m2"][1][1], expected_pair_iyy, rel_tol=1e-9)
    assert math.isclose(pair["inertia_tensor_com_kg_m2"][2][2], expected_pair_izz, rel_tol=1e-9)

    return {
        "mass_kg": props["mass_kg"],
        "center_of_mass_mm": props["center_of_mass_mm"],
        "inertia_fidelity": body["inertia_fidelity"],
        "linear_acceleration_m_s2": linear,
        "angular_acceleration_z_rad_s2": response["response"]["angular_acceleration_rad_s2"][2],
        "parallel_axis_verified": True,
        "physical_verification": response["physical_verification"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 rigid-body dynamics self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
