from __future__ import annotations

"""ForgeCAD 6.0 release-candidate acceptance.

This is deliberately one canonical product lineage, not a bag of domain unit tests.
It starts from the validated M1 networked actuator rig and extends that exact design
with thermal management, an attached low-pressure liquid loop, tolerance and safety
state, a chemistry characterization cell solved by external Cantera, a revision-bound
physical redesign/retest, fabrication output, and Jarvis/Physical World identity.

The physical result recorded here is synthetic CI acceptance evidence exercising the
contract. It is never presented as real-hardware validation of the product.
"""

import io
import json
import os
import zipfile

from fastapi.testclient import TestClient

from ..desktop_entry import app
from ..v110 import core
from ..v200.fluid_network import solve_fluid_network
from ..v200.physical_evidence import design_fingerprint
from ..v200.safety_analysis import analyze_safety
from ..v200.thermal_network import solve_thermal_network
from ..v200.tolerance_analysis import project_stacks
from . import selftest as milestone1


def _ok(response, label: str):
    assert response.status_code < 400, f"{label}: {response.status_code} {response.text}"
    return response


def _named(name: str) -> dict:
    return next(row for row in core.PROJECT.get("objects") or [] if row.get("name") == name)


def _component(component_ref: str) -> dict:
    return next(row for row in core.PROJECT.get("objects") or [] if row.get("component_ref") == component_ref)


def _operation(client: TestClient, op: str, args: dict, reason: str) -> dict:
    return _ok(client.post("/v2/operations", json={"op": op, "args": args, "reason": reason}), op).json()


def run() -> dict[str, object]:
    # Build the real-component electromechanical vertical slice first. This leaves the
    # exact same canonical project active so every extension below shares its identities.
    m1 = milestone1.run()
    assert m1["assembly_constraints_valid"] is True, m1
    assert m1["fabrication_archive_verified"] is True, m1

    with TestClient(app) as client:
        token = os.environ.get("FORGECAD_SESSION_TOKEN", "")
        if token:
            client.headers.update({"X-ForgeCAD-Session": token})

        deck = _named("V6 Networked Actuator Deck")
        rail = _named("Actuator Reaction Rail")
        pi = _component("compute.raspberry_pi_5_8gb")
        psu = _component("power.meanwell.lrs_75_12")
        rail_id, deck_id, pi_id, psu_id = map(str, (rail["id"], deck["id"], pi["id"], psu["id"]))

        # Add two custom bodies that remain part of this same bench system: a coolant
        # reservoir feeding the reaction rail/cold plate and a sealed chemistry
        # characterization cell. Neither implies a pneumatic launcher or unsafe device.
        _operation(client, "add", {
            "name": "RC Coolant Reservoir",
            "kind": "box",
            "params": {"x": 70.0, "y": 50.0, "z": 45.0},
            "material": "abs",
            "semantic": {"role": "low_pressure_coolant_reservoir", "manufacturing_process": "fdm", "tags": ["v6-release-candidate", "fluid"]},
        }, "Add release-candidate coolant reservoir")
        reservoir_id = str(_named("RC Coolant Reservoir")["id"])

        _operation(client, "add", {
            "name": "RC Chemistry Characterization Cell",
            "kind": "box",
            "params": {"x": 60.0, "y": 50.0, "z": 40.0},
            "material": "steel_304",
            "semantic": {"role": "sealed_chemistry_characterization_cell", "manufacturing_process": "cnc", "tags": ["v6-release-candidate", "chemistry"]},
        }, "Add release-candidate chemistry cell")
        chemistry_cell_id = str(_named("RC Chemistry Characterization Cell")["id"])

        # Thermal truth: explicit generation, explicit environmental rejection and
        # explicit allowable temperature. No contact conductance is inferred from CAD.
        _operation(client, "add_load", {
            "object_id": rail_id, "type": "heat", "heat_w": 1.0,
            "source": "release_candidate_defined_heat_load",
        }, "Define rail/cold-plate heat load")
        _operation(client, "add_constraint", {
            "object_id": rail_id, "type": "convection", "ambient_c": 25.0,
            "h_w_m2k": 20.0, "exposed_fraction": 0.8,
        }, "Define rail convection boundary")
        _operation(client, "add_constraint", {
            "object_id": rail_id, "type": "temperature_limit", "max_temperature_c": 70.0,
        }, "Define rail temperature limit")

        # Fluid truth: a low-pressure incompressible screening loop physically tied to
        # the same reaction rail. The explicit linear resistance avoids pretending a
        # detailed hose/valve geometry has been modeled here.
        _operation(client, "add_constraint", {
            "object_id": reservoir_id, "type": "fluid_pressure", "pressure_kpa": 25.0,
        }, "Define coolant supply pressure")
        _operation(client, "add_constraint", {
            "id": "rc-coolant-link", "type": "fluid_link", "a_id": reservoir_id,
            "b_id": rail_id, "resistance_pa_s_m3": 50_000_000_000.0,
        }, "Define coolant hydraulic path")
        _operation(client, "add_load", {
            "object_id": rail_id, "type": "fluid_demand", "flow_l_min": 0.01,
        }, "Define cold-plate coolant demand")
        _operation(client, "add_constraint", {
            "object_id": rail_id, "type": "fluid_pressure_limit",
            "min_pressure_kpa": 10.0, "max_pressure_kpa": 25.0,
        }, "Define cold-plate pressure window")

        # Tolerance truth stays attached to the rail dimension that the later physical
        # redesign is allowed to modify; the stack therefore regenerates from final CAD.
        _operation(client, "add_constraint", {
            "type": "dimension_tolerance", "stack": "rail_clearance_stack",
            "name": "Reaction rail height", "object_id": rail_id, "parameter": "z",
            "coefficient": 1.0, "minus_mm": 0.05, "plus_mm": 0.05, "sigma_mm": 0.015,
        }, "Add reaction-rail tolerance contributor")
        _operation(client, "add_constraint", {
            "type": "dimension_tolerance", "stack": "rail_clearance_stack",
            "name": "Fixture datum offset", "nominal_mm": 2.0,
            "coefficient": -1.0, "minus_mm": 0.02, "plus_mm": 0.02, "sigma_mm": 0.006,
        }, "Add fixture datum tolerance contributor")
        _operation(client, "add_constraint", {
            "type": "tolerance_spec", "stack": "rail_clearance_stack",
            "name": "Rail clearance dimensional window", "lower_spec_mm": 8.85, "upper_spec_mm": 9.15,
        }, "Add rail tolerance specification")

        # Safety state is canonical. Severity 6 deliberately remains an open warning,
        # not a falsely self-certified pass; it has explicit controls and test method.
        safety_added = _operation(client, "add_failure_mode", {
            "name": "Unexpected solenoid energization",
            "category": "control",
            "cause": "stale software command or driver fault",
            "effect": "unexpected actuator motion on the bench",
            "object_ids": [pi_id, str(_component("driver.adafruit.mosfet_5648")["id"]), str(_component("solenoid.adafruit.412")["id"])],
            "severity": 6,
            "occurrence": 3,
            "detection": 4,
            "controls": ["hardware enable interlock", "software maximum-on timer", "bench exclusion zone"],
            "verification_method": "fault-injection and interlock bench test",
        }, "Record release-candidate actuator hazard")
        assert safety_added["failure_mode"]["severity"] == 6

        thermal_before = solve_thermal_network(core.PROJECT)
        fluid_before = solve_fluid_network(core.PROJECT)
        safety_before = analyze_safety(core.PROJECT)
        assert thermal_before["requested"] and thermal_before["supported"] and thermal_before["ok"], thermal_before
        assert thermal_before["solver_grade"] == "engineering_iteration", thermal_before
        assert fluid_before["requested"] and fluid_before["supported"] and fluid_before["ok"], fluid_before
        assert fluid_before["solver_grade"] == "engineering_iteration", fluid_before
        assert safety_before["ok"] is True and safety_before["counts"]["warning"] >= 1, safety_before

        # Authorize exactly one bounded geometry field for the physical redesign loop.
        rail_now = core.object_by_id(rail_id)
        semantic = json.loads(json.dumps(rail_now.get("semantic") or {}))
        semantic["repair_authority"] = {"parameters": {"z": {"enabled": True, "min": 9.0, "max": 13.0}}}
        _operation(client, "update", {"id": rail_id, "semantic": semantic}, "Authorize bounded rail-height redesign")

        requirement_id = "v600-rc-rail-bench-clearance"
        _ok(client.post("/v3.1/requirements", json={
            "id": requirement_id,
            "name": "Reaction rail clears release fixture",
            "metric": "physical_clearance_mm",
            "op": ">=",
            "target": 0.2,
            "unit": "mm",
            "criticality": "important",
            "scope_object_ids": [rail_id],
            "source": "v600-release-candidate",
            "confidence": 1.0,
        }), "create RC physical requirement")
        source_branch = core.ACTIVE_DESIGN
        source_fingerprint = design_fingerprint()
        failed = _ok(client.post(f"/v2/requirements/{requirement_id}/verify", json={
            "status": "failed",
            "method": "synthetic_ci_physical_contract_fixture",
            "note": "Synthetic CI observation used only to exercise revision-bound evidence semantics; not a real-hardware measurement.",
            "measurements": [{"name": "clearance", "value": -0.4, "unit": "mm", "tolerance": 0.05}],
        }), "record RC synthetic failed observation").json()["evidence"]
        assert failed["design_fingerprint"] == source_fingerprint

        begun = _ok(client.post("/v6/physical/retest-cycles", json={
            "requirement_id": requirement_id,
            "failed_evidence_id": failed["id"],
            "mutations": [{"object_id": rail_id, "parameter": "z", "value": 11.0}],
            "criteria": [{"measurement": "clearance", "object_id": rail_id, "unit": "mm", "op": ">=", "target": 0.2, "required": True}],
            "branch_prefix": "v600-rc-retest",
            "actor": "jarvis",
            "diagnosis": "Reduced rail height is a bounded hypothesis for the observed fixture interference, not a proven cause.",
        }), "begin RC redesign/retest").json()
        cycle = begun["cycle"]
        cycle_id = str(cycle["id"])
        assert core.ACTIVE_DESIGN != source_branch
        assert cycle["source_design_fingerprint"] == source_fingerprint
        assert int(cycle["semantic_diff_count"]) >= 1
        assert cycle["failure_assessment"]["causality_status"] == "unproven_hypothesis"

        completed = _ok(client.post(f"/v6/physical/retest-cycles/{cycle_id}/complete", json={
            "status": "passed",
            "method": "synthetic_ci_physical_contract_fixture",
            "note": "Synthetic CI passing observation validates evidence plumbing only; entire design remains not physically verified.",
            "measurements": [{"name": "clearance", "value": 0.35, "unit": "mm", "tolerance": 0.05}],
            "instrument": "CI synthetic metrology fixture",
            "confidence": 0.5,
        }), "complete RC redesign/retest").json()
        assert completed["requirement_physically_verified_on_current_fingerprint"] is True, completed
        assert completed["entire_design_physically_verified"] is False, completed
        assert core.DESIGNS[core.ACTIVE_DESIGN]["physical_verified"] is False
        final_fingerprint = design_fingerprint()

        # Re-run dependent deterministic domains on the final redesign. Tolerance is
        # particularly important because its nominal value resolves directly from the
        # changed rail CAD parameter.
        thermal_final = solve_thermal_network(core.PROJECT)
        fluid_final = solve_fluid_network(core.PROJECT)
        tolerance_final = project_stacks(core.PROJECT)
        safety_final = analyze_safety(core.PROJECT)
        assert thermal_final["ok"] is True, thermal_final
        assert fluid_final["ok"] is True, fluid_final
        stack = next(row for row in tolerance_final["items"] if row["stack"] == "rail_clearance_stack")
        assert stack["worst_case"]["passes_spec"] is True, stack
        assert stack["statistical"]["available"] is True, stack
        assert safety_final["ok"] is True, safety_final

        # External chemistry now runs against an actual object in this same finalized
        # product fingerprint. It remains prediction evidence, not physical chemistry proof.
        chemistry_study = _ok(client.post("/v6/chemistry/studies", json={
            "name": "RC methane-air chemistry screen",
            "object_id": chemistry_cell_id,
            "solver_id": "cantera",
            "mechanism": "gri30.yaml",
            "mode": "equilibrium",
            "temperature_k": 300.0,
            "pressure_pa": 101325.0,
            "composition": {"CH4": 1.0, "O2": 2.0, "N2": 7.52},
            "equilibrium_basis": "HP",
            "assumptions": ["sealed characterization cell is represented only as a zero-dimensional equilibrium screening model"],
        }), "create RC chemistry study").json()["study"]
        assert chemistry_study["design_fingerprint"] == final_fingerprint
        chemistry = _ok(client.post(f"/v6/chemistry/studies/{chemistry_study['id']}/run"), "run RC chemistry").json()
        assert chemistry["run"]["solver"]["solver_grade"] == "external_engineering_analysis"
        assert chemistry["run"]["physical_validation"] is False
        assert chemistry["run"]["final_state"]["temperature_k"] > chemistry["run"]["initial_state"]["temperature_k"]
        assert design_fingerprint() == final_fingerprint, "analysis evidence must not mutate designed truth"

        # One graph/world identity plane must still see the same final objects after the
        # branch mutation and external analysis.
        _ok(client.post("/v3.1/graph/sync"), "sync final RC engineering graph")
        graph = _ok(client.get("/v3.1/graph"), "read final RC graph").json()
        graph_ids = {row["id"] for row in graph["nodes"]}
        for object_id in (deck_id, rail_id, pi_id, reservoir_id, chemistry_cell_id):
            assert f"cad:{object_id}" in graph_ids, object_id
        chemistry_evidence_id = str(chemistry["graph_evidence"]["id"])
        chemistry_evidence = next(row for row in graph["evidence"] if row["id"] == chemistry_evidence_id)
        assert chemistry_evidence["stale"] is False, chemistry_evidence

        world = _ok(client.get("/v3/world"), "read final RC physical world").json()
        for object_id in (deck_id, rail_id, pi_id, reservoir_id, chemistry_cell_id):
            assert any(str(entity.get("source_links", {}).get("forgecad_object_id") or "") == object_id for entity in world["entities"]), object_id

        jarvis = _ok(client.get("/v3.1/jarvis/context"), "read final RC Jarvis context").json()
        jarvis_ids = {row["id"] for row in jarvis["nodes"]}
        assert f"cad:{rail_id}" in jarvis_ids
        assert f"software:{pi_id}" in jarvis_ids
        assert jarvis["engineering_graph_revision"]
        assert jarvis["world"]["entity_count"] >= len(core.PROJECT.get("objects") or [])

        # Fabrication output is generated from the final redesign branch and must carry
        # all custom objects plus the exact graph revision and software workspace.
        archive = _ok(client.post("/v3.1/fabrication/archive", json={
            "name": "ForgeCAD 6.0 Release Candidate Rig",
            "processes": {
                deck_id: "fdm",
                rail_id: "cnc",
                reservoir_id: "fdm",
                chemistry_cell_id: "cnc",
            },
            "include_step": True,
            "include_stl": True,
        }), "create RC fabrication archive")
        archive_sha = str(archive.headers.get("X-ForgeCAD-Fabrication-SHA256") or "")
        assert len(archive_sha) == 64
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["engineering_graph_revision"]
            assert any(row.get("component_ref") == "compute.raspberry_pi_5_8gb" for row in manifest["bom"])
            assert any(item.get("object_id") == pi_id for item in manifest["software"])
            members = set(zf.namelist())
            for object_id in (deck_id, rail_id, reservoir_id, chemistry_cell_id):
                assert any(object_id in name and name.endswith(".step") for name in members), (object_id, members)

        v6 = _ok(client.get("/v6/health"), "read RC v6 health").json()
        assert v6["release_complete"] is False, "release flag must remain false until packaging gates pass"

        return {
            "ok": True,
            "release_candidate": "cross_domain_single_lineage",
            "source_branch": source_branch,
            "final_branch": core.ACTIVE_DESIGN,
            "semantic_diff_count": int(cycle["semantic_diff_count"]),
            "final_design_fingerprint": final_fingerprint,
            "object_count": len(core.PROJECT.get("objects") or []),
            "electrical_connection_count": len([row for row in core.PROJECT.get("connections") or [] if row.get("kind") == "electrical"]),
            "thermal_solver_grade": thermal_final["solver_grade"],
            "fluid_solver_grade": fluid_final["solver_grade"],
            "tolerance_worst_case_pass": stack["worst_case"]["passes_spec"],
            "safety_open_warning_count": safety_final["counts"]["warning"],
            "chemistry_solver": chemistry["run"]["solver"],
            "chemistry_mechanism_sha256": chemistry["run"]["mechanism_provenance"]["sha256"],
            "chemistry_graph_evidence_id": chemistry_evidence_id,
            "fabrication_archive_sha256": archive_sha,
            "jarvis_graph_revision": jarvis["engineering_graph_revision"],
            "world_entity_count": jarvis["world"]["entity_count"],
            "scoped_requirement_retest_passed": True,
            "entire_design_physically_verified": False,
            "real_hardware_validation_claimed": False,
        }


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
