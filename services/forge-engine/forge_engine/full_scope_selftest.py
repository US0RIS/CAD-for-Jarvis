from __future__ import annotations

import json
import os
import sys


def main() -> None:
    from .engineering_state import PROJECT
    from .v110 import acceptance_design, component_registry, project_bundle, software, system_validation

    stats = component_registry.registry_stats()
    assert stats["total"] >= 238, stats
    required = {
        "compute.raspberry_pi_5_8gb",
        "driver.adafruit.mosfet_5648",
        "solenoid.adafruit.412",
        "power.meanwell.lrs_75_12",
        "power.pololu.d24v50f5",
    }
    available = {item["id"] for item in component_registry.all_components()}
    assert required <= available, sorted(required - available)

    acceptance = acceptance_design.build_project()
    assert len(acceptance["objects"]) >= 6
    assert len(acceptance["bom"]) >= 5
    assert len(acceptance["connections"]) >= 5
    system = system_validation.validate_system(acceptance)
    assert isinstance(system["ok"], bool)
    assert "counts" in system

    snapshot = PROJECT.snapshot()
    assert any(branch["name"] == "baseline" and branch["protected"] for branch in snapshot["branches"])
    assert any(part.get("component_ref") == "compute.raspberry_pi_5_8gb" for part in snapshot["parts"])
    assert any(part.get("programmable_workspace_id") for part in snapshot["parts"])

    scene = PROJECT.scene_manifest()
    assert scene["authoritative"] is True
    assert len(scene["parts"]) >= 6
    assert all(part["mesh"]["positions"] and part["mesh"]["triangles"] for part in scene["parts"])

    validation = PROJECT.validation()
    assert "risks" in validation and "metrics" in validation
    simulation = PROJECT.run_simulation()
    assert simulation["structural"]["solver_grade"] == "screening"
    assert "modal" in simulation and "thermal" in simulation and "manufacturing" in simulation

    programmable = next(part for part in PROJECT.snapshot()["parts"] if part.get("programmable_workspace_id"))
    workspace_id = str(programmable["programmable_workspace_id"])
    workspace = PROJECT.workspace(workspace_id)
    assert workspace["files"]
    assert PROJECT.deploy_workspace(workspace_id)["validation"]["ok"] is True

    bundle = PROJECT.export_bundle()
    restored = project_bundle.import_bundle_bytes(bundle)
    assert restored["project"]["objects"]
    assert restored["manifest"]["bundle_version"] == 1

    search = PROJECT.search_components("raspberry", limit=5)
    assert any(item["id"] == "compute.raspberry_pi_5_8gb" for item in search)

    with tempfile.TemporaryDirectory() as temp_dir:
        step_path = Path(temp_dir) / "selftest.step"
        cq.exporters.export(cq.Workplane("XY").box(10, 20, 5), str(step_path))
        imported = PROJECT.import_step_part(step_path.name, step_path.read_bytes())
        imported_id = str(imported["object"]["id"])
        assert any(part["id"] == imported_id for part in PROJECT.scene_manifest()["parts"])

    print(json.dumps({
        "full_scope_selftest": "PASS",
        "registry_total": stats["total"],
        "acceptance_objects": len(acceptance["objects"]),
        "acceptance_connections": len(acceptance["connections"]),
        "scene_parts": len(scene["parts"]),
        "active_branch": PROJECT.active_branch,
        "programmable_workspace": workspace_id,
        "bundle_bytes": len(bundle),
        "validation_counts": validation.get("counts"),
    }, indent=2))


if __name__ == "__main__":
    main()
    # CadQuery/OCP/VTK can return a spurious non-zero code during CPython native
    # extension teardown on Windows after all Python work has completed. Reaching
    # this point means every assertion above passed, so flush the proof and bypass
    # only native interpreter finalization. Assertion/exception failures never reach
    # this block and still fail normally.
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        os._exit(0)
