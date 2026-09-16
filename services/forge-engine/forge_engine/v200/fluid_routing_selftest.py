from __future__ import annotations

"""Regression gate for physical route-length coupling into hydraulic analysis."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import fluid_network


def _add_box(name: str, position: list[float]) -> str:
    before = {str(obj.get("id")) for obj in core.PROJECT.get("objects", [])}
    core.execute(
        "add",
        {
            "name": name,
            "kind": "box",
            "params": {"x": 10.0, "y": 10.0, "z": 10.0},
            "material": "aluminum_6061_t6",
            "transform": {"position": position, "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
        },
        actor="human",
        reason=f"Fluid routing self-test: add {name}",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def _new_constraint(args: dict[str, object]) -> str:
    before = {str(row.get("id")) for row in core.PROJECT.get("constraints", []) if isinstance(row, dict)}
    core.execute("add_constraint", args, actor="human", reason="Fluid routing self-test: constraint")
    created = [row for row in core.PROJECT.get("constraints", []) if isinstance(row, dict) and str(row.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    source = _add_box("Reservoir", [0.0, 0.0, 0.0])
    target = _add_box("Actuator", [70.0, 0.0, 0.0])

    link_id = _new_constraint({
        "type": "tube",
        "a_id": source,
        "b_id": target,
        "inner_diameter_mm": 4.0,
        "dynamic_viscosity_pa_s": 0.001,
        "density_kg_m3": 998.0,
    })
    _new_constraint({"object_id": source, "type": "fluid_pressure", "pressure_kpa": 100.0})
    core.execute(
        "add_load",
        {"object_id": target, "type": "fluid_demand", "flow_l_min": 0.05},
        actor="human",
        reason="Fluid routing self-test: known demand",
    )

    route_result = core.execute(
        "add_route",
        {
            "name": "Actuator supply tube",
            "kind": "tube",
            "points_mm": [[0.0, 0.0, 0.0], [70.0, 0.0, 0.0]],
            "outer_diameter_mm": 6.0,
            "fluid_link_id": link_id,
            "a_object_id": source,
            "b_object_id": target,
        },
        actor="human",
        reason="Fluid routing self-test: route-defined tube length",
    )
    route_id = str(route_result["route"]["id"])

    solved = fluid_network.solve_fluid_network(core.PROJECT)
    link = next(row for row in solved["links"] if str(row.get("id")) == link_id)
    assert link["length_source"] == "canonical_route_geometry"
    assert link["route_id"] == route_id
    assert math.isclose(float(link["route_length_mm"]), 70.0, rel_tol=1e-12)
    assert math.isclose(float(link["length_mm"]), 70.0, rel_tol=1e-12)

    expected_r = 128.0 * 0.001 * 0.070 / (math.pi * 0.004 ** 4)
    assert math.isclose(float(link["resistance_pa_s_m3"]), expected_r, rel_tol=1e-12)
    q = 0.05e-3 / 60.0
    expected_target_pressure = 100_000.0 - expected_r * q
    pressures = {str(node["object_id"]): float(node["pressure_pa"]) for node in solved["nodes"]}
    assert math.isclose(pressures[target], expected_target_pressure, rel_tol=1e-12, abs_tol=1e-8)
    assert link.get("laminar_model_valid") is True

    # Change only route geometry. The hydraulic tube resistance must update automatically;
    # no duplicated length field in the fluid constraint is allowed to become stale.
    core.execute(
        "update_route",
        {"id": route_id, "points_mm": [[0.0, 0.0, 0.0], [70.0, 0.0, 0.0], [140.0, 0.0, 0.0]]},
        actor="human",
        reason="Fluid routing self-test: double routed length",
    )
    doubled = fluid_network.solve_fluid_network(core.PROJECT)
    doubled_link = next(row for row in doubled["links"] if str(row.get("id")) == link_id)
    assert math.isclose(float(doubled_link["route_length_mm"]), 140.0, rel_tol=1e-12)
    assert math.isclose(float(doubled_link["resistance_pa_s_m3"]), 2.0 * expected_r, rel_tol=1e-12)
    doubled_pressures = {str(node["object_id"]): float(node["pressure_pa"]) for node in doubled["nodes"]}
    assert doubled_pressures[target] < pressures[target]

    return {
        "solver": solved["solver"],
        "route_id": route_id,
        "initial_route_length_mm": link["route_length_mm"],
        "doubled_route_length_mm": doubled_link["route_length_mm"],
        "initial_resistance_pa_s_m3": link["resistance_pa_s_m3"],
        "doubled_resistance_pa_s_m3": doubled_link["resistance_pa_s_m3"],
        "hydraulic_result_tracks_route_geometry": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 fluid-routing self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
