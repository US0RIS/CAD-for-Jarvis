from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 planner-visible analysis contracts."""

from ..engineering_state import PROJECT
from . import analysis_contracts, design_intelligence, project_structural


def run() -> dict[str, object]:
    PROJECT.new_project()
    contract = analysis_contracts.contracts()
    structural = contract["structural"]
    tolerance = contract["tolerance"]
    dynamics = contract["dynamics"]
    electrical = contract["electrical"]
    bc = structural["project_boundary_conditions"]

    assert structural["solver"] == "ForgeCAD SolidFEA"
    assert structural["grade"] == "engineering_iteration"
    assert structural["geometry"]["supported"] == ["exact unfeatured box"]
    assert structural["geometry"]["policy"] == "fail_closed"
    assert set(bc["faces"]) == {"x_min", "x_max", "y_min", "y_max", "z_min", "z_max"}
    assert bc["support"]["operation"] == "add_constraint"
    assert bc["support"]["schema"]["object_id"] == "$part"
    assert bc["force"]["operation"] == "add_load"
    assert bc["force"]["schema_vector"]["vector_n"] == [0.0, 0.0, -100.0]
    assert "pressure" in bc["unsupported_physics"]
    assert "dimension_tolerance" in bc["nonstructural_constraint_namespaces"]
    assert structural["result_precedence"]["when_project_boundary_conditions_supported"] == "structural_3d_project"

    assert tolerance["solver"] == "ForgeCAD ToleranceStack"
    assert tolerance["grade"] == "engineering_iteration"
    assert tolerance["project_storage"]["contributor_schema"]["type"] == "dimension_tolerance"
    assert tolerance["project_storage"]["spec_schema"]["type"] == "tolerance_spec"
    assert tolerance["project_storage"]["contributor_schema"]["coefficient"] == 1.0
    assert "Never infer sigma" in tolerance["statistical_policy"]
    assert "contributor sensitivity ranking" in tolerance["outputs"]

    assert dynamics["solver"] == "ForgeCAD RigidBody"
    assert dynamics["grade"] == "engineering_iteration"
    assert dynamics["mass_properties_endpoint"] == "/v2/analysis/mass-properties"
    assert dynamics["response_endpoint"] == "/v2/analysis/rigid-body"
    assert dynamics["request_schema"]["force_n"] == [0.0, 0.0, 0.0]
    assert "assembly mass and center of mass" in dynamics["outputs"]
    assert "unfeatured box" in dynamics["inertia_fidelity"]["analytic"]
    assert any("no joints" in limitation.lower() for limitation in dynamics["limitations"])

    assert electrical["solver"] == "ForgeCAD ElectricalGraph"
    assert electrical["grade"] == "engineering_iteration"
    assert electrical["schematic_endpoint"] == "/v2/electrical/schematic"
    assert electrical["analysis_endpoint"] == "/v2/analysis/electrical"
    assert electrical["connection_operation"]["operation"] == "connect_interfaces"
    assert electrical["connection_operation"]["schema"]["net_name"] == "+5V"
    assert electrical["connection_operation"]["schema"]["nominal_voltage_v"] == 5.0
    assert electrical["net_label_operation"]["operation"] == "label_electrical_net"
    assert "power" in electrical["connection_operation"]["net_classes"]
    assert any("SPICE" in limitation for limitation in electrical["limitations"])
    assert "conflicting modeled source voltages on one net" in electrical["fail_closed"]

    # Signed orthogonal face aliases are part of the accepted deterministic input
    # vocabulary even though canonical storage should prefer x_min/x_max/etc.
    assert project_structural._face("+x") == "x_max"
    assert project_structural._face("+Y") == "y_max"
    assert project_structural._face("+z") == "z_max"
    assert project_structural._face("-x") == "x_min"
    assert project_structural._face("y-") == "y_min"

    request = "Design a powered load-bearing mechanism, verify its electrical rails, fit tolerances, and rigid-body acceleration before manufacturing."
    architecture = design_intelligence.bootstrap_architecture(request, PROJECT.snapshot())
    context = design_intelligence.build_planner_context(request, architecture, PROJECT.snapshot())
    assert context["analysis_contracts"]["structural"]["project_boundary_conditions"]["support"]["schema"]["type"] == "fixed"
    assert context["analysis_contracts"]["tolerance"]["direct_endpoint"] == "/v2/analysis/tolerance-stack"
    assert context["analysis_contracts"]["tolerance"]["project_endpoint"] == "/v2/analysis/tolerance-stacks"
    assert context["analysis_contracts"]["dynamics"]["response_endpoint"] == "/v2/analysis/rigid-body"
    assert context["analysis_contracts"]["electrical"]["analysis_endpoint"] == "/v2/analysis/electrical"
    assert context["analysis_contracts"]["electrical"]["connection_operation"]["schema"]["net_class"] == "power"
    assert context["analysis_contracts"]["manufacturing"]["resource_id"] == "bambu-lab-p2s"
    assert context["analysis_contracts"]["manufacturing"]["direct_printer_control"] is False

    return {
        "solver": structural["solver"],
        "tolerance_solver": tolerance["solver"],
        "dynamics_solver": dynamics["solver"],
        "electrical_solver": electrical["solver"],
        "faces": len(bc["faces"]),
        "supported_force_types": len(bc["force"]["supported_types"]),
        "planner_context_contract": True,
        "tolerance_contract": True,
        "dynamics_contract": True,
        "electrical_contract": True,
        "signed_face_aliases": True,
        "unsupported_physics_fail_closed": True,
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 analysis contracts self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
