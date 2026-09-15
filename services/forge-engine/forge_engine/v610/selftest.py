from __future__ import annotations

"""Deterministic source-level acceptance for ForgeCAD 6.1 simulation behavior."""

from copy import deepcopy
import math

from . import aerodynamics, joint_loads, motion_simulation, multibody, simulation_state, thermal_transient


def _box(object_id: str, name: str, position: list[float]) -> dict:
    return {
        "id": object_id,
        "name": name,
        "kind": "box",
        "params": {"x": 6.0, "y": 6.0, "z": 6.0},
        "material": "aluminum_6061_t6",
        "transform": {"position": position, "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        "features": [],
        "visible": True,
    }


def _mechanism() -> dict:
    return {
        "version": "6.1.0",
        "objects": [
            _box("base", "Base", [0.0, 0.0, 0.0]),
            _box("arm", "Arm", [10.0, 0.0, 0.0]),
            _box("payload", "Payload", [20.0, 0.0, 0.0]),
        ],
        "joints": [
            {
                "id": "hinge",
                "name": "Base hinge",
                "type": "revolute",
                "parent_id": "base",
                "child_id": "arm",
                "origin_mm": [0.0, 0.0, 0.0],
                "axis": [0.0, 0.0, 1.0],
                "lower_deg": -180.0,
                "upper_deg": 180.0,
                "home_deg": 0.0,
            },
            {
                "id": "payload-fixed",
                "name": "Payload mount",
                "type": "fixed",
                "parent_id": "arm",
                "child_id": "payload",
                "origin_mm": [10.0, 0.0, 0.0],
                "axis": [0.0, 0.0, 1.0],
            },
        ],
        "connections": [],
        "loads": [],
        "constraints": [],
        "requirements": [],
        "bom": [],
        "settings": {},
        "simulations": [],
    }


def _near(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def run() -> dict:
    mechanism = _mechanism()
    graph = multibody.assembly_graph(mechanism)
    assert graph["ok"] and graph["joint_count"] == 2
    assert [edge["child_id"] for edge in graph["edges"]] == ["arm", "payload"]

    # Core 6.1 acceptance: rotating the supporting body carries everything it holds.
    moved = multibody.solve_driver_transform(
        mechanism,
        "base",
        {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 90.0], "scale": [1.0, 1.0, 1.0]},
    )
    assert moved["affected_ids"] == ["base", "arm", "payload"]
    arm_position = moved["transforms"]["arm"]["position"]
    payload_position = moved["transforms"]["payload"]["position"]
    assert _near(arm_position[0], 0.0) and _near(arm_position[1], 10.0)
    assert _near(payload_position[0], 0.0) and _near(payload_position[1], 20.0)
    assert _near(moved["transforms"]["payload"]["rotation_deg"][2], 90.0)

    # Directly breaking an incoming joint with a free transform is prohibited; the
    # explicit joint drive path is the physically meaningful way to actuate it.
    try:
        multibody.solve_driver_transform(
            mechanism,
            "arm",
            {"position": [10.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 10.0], "scale": [1.0, 1.0, 1.0]},
        )
    except ValueError as exc:
        assert "drive joint" in str(exc)
    else:
        raise AssertionError("Free child transform should not break a canonical joint")

    joint_pose = multibody.solve_joint_pose(mechanism, "hinge", rotation_deg=90.0)
    assert joint_pose["affected_ids"] == ["arm", "payload"]
    arm_position = joint_pose["transforms"]["arm"]["position"]
    payload_position = joint_pose["transforms"]["payload"]["position"]
    assert _near(arm_position[0], 0.0) and _near(arm_position[1], 10.0)
    assert _near(payload_position[0], 0.0) and _near(payload_position[1], 20.0)

    # Time-domain motion must use the same descendant propagation, not the legacy
    # one-child sweep. The final frame therefore moves both arm and payload.
    motion = motion_simulation.simulate_joint_sweep(
        mechanism,
        "hinge",
        start_state={"rotation_deg": 0.0},
        end_state={"rotation_deg": 90.0},
        duration_s=2.0,
        samples=9,
        gravity_m_s2=[0.0, 0.0, -9.80665],
    )
    assert motion["moving_object_ids"] == ["arm", "payload"]
    assert motion["sample_count"] == 9
    assert motion["collision_free"] is True
    final_frame = motion["frames"][-1]
    assert _near(final_frame["transforms"]["arm"]["position"][0], 0.0)
    assert _near(final_frame["transforms"]["arm"]["position"][1], 10.0)
    assert _near(final_frame["transforms"]["payload"]["position"][0], 0.0)
    assert _near(final_frame["transforms"]["payload"]["position"][1], 20.0)
    assert motion["dynamics"]["peak_support_reaction_n"] > 0.0
    assert all("velocity_m_s" in row and "acceleration_m_s2" in row for row in motion["dynamics"]["bodies"])

    # Non-mated geometry in the sweep path must be reported as interference rather
    # than ignored or treated as a solved contact event.
    collision_project = deepcopy(mechanism)
    obstacle = _box("obstacle", "Obstacle", [0.0, 20.0, 0.0])
    obstacle["params"] = {"x": 10.0, "y": 10.0, "z": 20.0}
    collision_project["objects"].append(obstacle)
    collision_motion = motion_simulation.simulate_joint_sweep(
        collision_project,
        "hinge",
        start_state={"rotation_deg": 0.0},
        end_state={"rotation_deg": 90.0},
        duration_s=1.0,
        samples=13,
    )
    assert collision_motion["collision_free"] is False
    assert collision_motion["collision_count"] > 0
    assert any("obstacle" in {row["a_id"], row["b_id"]} for row in collision_motion["collisions"])

    closed = deepcopy(mechanism)
    closed["joints"].append({
        "id": "loop", "type": "fixed", "parent_id": "payload", "child_id": "base",
        "origin_mm": [20.0, 0.0, 0.0], "axis": [0.0, 0.0, 1.0],
    })
    assert not multibody.assembly_graph(closed)["ok"]
    try:
        multibody.descendants(closed, "base")
    except ValueError as exc:
        assert "Closed kinematic loop" in str(exc)
    else:
        raise AssertionError("Closed loop must fail closed")

    loads = joint_loads.solve_joint_loads(mechanism, gravity_m_s2=[0.0, 0.0, -9.80665])
    assert loads["joint_count"] == 2
    root_load = next(row for row in loads["joints"] if row["joint_id"] == "hinge")
    payload_load = next(row for row in loads["joints"] if row["joint_id"] == "payload-fixed")
    assert root_load["subtree_mass_kg"] > payload_load["subtree_mass_kg"] > 0.0
    assert root_load["load_on_parent_force_n"][2] < 0.0

    thermal_project = {
        "objects": [_box("hot", "Hot body", [0.0, 0.0, 0.0]), _box("sink", "Sink", [30.0, 0.0, 0.0])],
        "joints": [], "connections": [], "requirements": [], "bom": [], "settings": {}, "simulations": [],
        "loads": [{"id": "heat", "object_id": "hot", "type": "heat", "heat_w": 20.0}],
        "constraints": [
            {"id": "link", "type": "thermal_link", "a_id": "hot", "b_id": "sink", "conductance_w_k": 3.0},
            {"id": "conv", "type": "convection", "object_id": "sink", "ambient_c": 25.0, "h_w_m2k": 25.0, "exposed_fraction": 1.0},
            {"id": "limit", "type": "temperature_limit", "object_id": "hot", "max_temperature_c": 120.0},
        ],
    }
    transient = thermal_transient.solve_transient_thermal(
        thermal_project,
        duration_s=60.0,
        timestep_s=1.0,
        initial_temperature_c=25.0,
        max_samples=80,
    )
    hot = next(row for row in transient["nodes"] if row["object_id"] == "hot")
    assert transient["integration_steps"] == 60
    assert hot["final_temperature_c"] > 25.0
    assert math.isfinite(float(transient["energy_balance"]["residual_j"]))

    aero_project = {
        "objects": [_box("body", "Aero body", [0.0, 0.0, 0.0])],
        "joints": [], "connections": [], "loads": [], "constraints": [], "requirements": [], "bom": [], "settings": {}, "simulations": [],
    }
    aero = aerodynamics.solve_integral_aerodynamics(
        aero_project,
        relative_air_velocity_m_s=[-10.0, 0.0, 0.0],
        air_density_kg_m3=1.2,
        drag_coefficient=1.0,
        reference_area_m2=0.01,
    )
    assert _near(aero["drag_force_n"], 0.6)
    assert aero["drag_force_vector_n"][0] < 0.0
    assert aero["solver_grade"] == "screening"

    stale_project = {"simulations": [{"id": "s", "object_id": None, "stale": False}], "objects": [], "joints": [], "loads": [], "constraints": [], "requirements": [], "bom": [], "connections": [], "settings": {}}
    count = simulation_state.invalidate_simulations(stale_project, ["body"], reason="test mutation")
    assert count == 1 and stale_project["simulations"][0]["stale"] is True

    return {
        "ok": True,
        "version": "6.1.0",
        "checks": {
            "joint_graph": True,
            "supporting_body_rotation_propagates": True,
            "joint_actuation_propagates_descendants": True,
            "time_domain_subtree_motion": True,
            "motion_collision_detection": True,
            "closed_loops_fail_closed": True,
            "gravity_load_path": True,
            "transient_thermal": True,
            "integral_aerodynamics": True,
            "simulation_invalidation": True,
        },
    }


if __name__ == "__main__":
    print(run())
