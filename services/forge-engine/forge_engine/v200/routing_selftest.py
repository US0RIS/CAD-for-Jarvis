from __future__ import annotations

"""Deterministic regression gate for ForgeCAD 2.0 cable/tube routing."""

import math

from ..engineering_state import PROJECT
from ..v110 import core
from . import analysis_contracts, design_intelligence, routing


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
        reason=f"Routing self-test: add {name}",
    )
    created = [obj for obj in core.PROJECT.get("objects", []) if str(obj.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def _add_fluid_link(a_id: str, b_id: str) -> str:
    before = {str(row.get("id")) for row in core.PROJECT.get("constraints", []) if isinstance(row, dict)}
    core.execute(
        "add_constraint",
        {"type": "fluid_link", "a_id": a_id, "b_id": b_id, "resistance_pa_s_m3": 1.0e10},
        actor="human",
        reason="Routing self-test: bound fluid link",
    )
    created = [row for row in core.PROJECT.get("constraints", []) if isinstance(row, dict) and str(row.get("id")) not in before]
    assert len(created) == 1
    return str(created[0]["id"])


def run() -> dict[str, object]:
    PROJECT.new_project()
    source = _add_box("Tube source", [0.0, 0.0, 0.0], [12.0, 12.0, 12.0])
    target = _add_box("Tube target", [40.0, 30.0, 0.0], [12.0, 12.0, 12.0])
    obstacle = _add_box("Routing obstacle", [20.0, 0.0, 0.0], [10.0, 10.0, 10.0])
    fluid_link = _add_fluid_link(source, target)

    result = core.execute(
        "add_route",
        {
            "name": "Coolant tube",
            "kind": "tube",
            "points_mm": [[0.0, 0.0, 0.0], [40.0, 0.0, 0.0], [40.0, 30.0, 0.0]],
            "outer_diameter_mm": 4.0,
            "min_bend_radius_mm": 10.0,
            "clearance_mm": 1.0,
            "max_length_mm": 80.0,
            "fluid_link_id": fluid_link,
            "a_object_id": source,
            "b_object_id": target,
        },
        actor="human",
        reason="Routing self-test: canonical coolant path",
    )
    route_id = str(result["route"]["id"])

    report = routing.analyze_routes(core.PROJECT)
    assert report["count"] == 1
    assert report["ok"] is True, report["risks"]
    item = report["items"][0]
    assert math.isclose(float(item["polyline_length_mm"]), 70.0, rel_tol=1e-12, abs_tol=1e-12)
    expected_smooth = 70.0 - 20.0 + math.pi * 10.0 / 2.0
    assert math.isclose(float(item["bend"]["smoothed_centerline_length_mm"]), expected_smooth, rel_tol=1e-12, abs_tol=1e-12)
    assert item["bend"]["feasible"] is True
    assert item["binding"]["fluid_link_valid"] is True
    assert any(hit["object_id"] == obstacle for hit in item["obstructions"])
    assert any(risk.get("code") == "route_clearance_proxy_conflict" and risk.get("severity") == "warning" for risk in report["risks"])

    snapshot = PROJECT.snapshot()
    assert len(snapshot["routes"]) == 1
    assert snapshot["routes"][0]["id"] == route_id
    assert snapshot["routing"]["count"] == 1

    # The route is canonical project state and therefore survives undoing an unrelated
    # later operation; redo then restores that unrelated edit without touching routing.
    core.execute("add_note", {"text": "Routing history sentinel"}, actor="human", reason="Routing self-test: history sentinel")
    assert core.undo()
    assert any(str(row.get("id")) == route_id for row in core.PROJECT.get("routes", []))
    assert core.redo()

    contract = analysis_contracts.contracts()["routing"]
    assert contract["solver"] == "ForgeCAD RouteGeometry"
    architecture = design_intelligence.bootstrap_architecture(
        "Route a coolant tube between two devices while respecting bend radius and obstacles.",
        PROJECT.snapshot(),
    )
    context = design_intelligence.build_planner_context(
        "Route a coolant tube between two devices while respecting bend radius and obstacles.",
        architecture,
        PROJECT.snapshot(),
    )
    assert context["analysis_contracts"]["routing"]["analysis_endpoint"] == "/v2/analysis/routes"

    # Increase required bend radius beyond what the 30 mm outgoing leg can fit. This is
    # exact centerline geometry, so it is a hard validation failure rather than a proxy warning.
    core.execute(
        "update_route",
        {"id": route_id, "min_bend_radius_mm": 35.0},
        actor="human",
        reason="Routing self-test: intentional bend-radius failure",
    )
    failed = routing.analyze_routes(core.PROJECT)
    assert failed["ok"] is False
    assert any(risk.get("code") == "route_bend_radius_violation" for risk in failed["risks"])
    validation = PROJECT.validation()
    assert validation["routing"]["ok"] is False
    assert any(risk.get("code") == "route_bend_radius_violation" for risk in validation["risks"])

    return {
        "solver": report["solver"],
        "polyline_length_mm": item["polyline_length_mm"],
        "smoothed_length_mm": item["bend"]["smoothed_centerline_length_mm"],
        "fluid_binding_valid": True,
        "obstacle_proxy_detected": True,
        "snapshot_exposed": True,
        "history_preserved": True,
        "bend_failure_gates_validation": True,
        "planner_contract": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 routing self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
