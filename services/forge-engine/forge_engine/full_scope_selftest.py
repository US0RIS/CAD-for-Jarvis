from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import zipfile

import cadquery as cq


def main() -> None:
    from .engineering_state import PROJECT
    from .v110 import acceptance_design, component_registry, physical_components, premium_geometry, project_bundle, realistic_components, software, system_validation

    stats = component_registry.registry_stats()
    assert stats["total"] >= 1400, stats
    required = {
        "compute.raspberry_pi_5_8gb",
        "driver.adafruit.mosfet_5648",
        "solenoid.adafruit.412",
        "power.meanwell.lrs_75_12",
        "power.pololu.d24v50f5",
    }
    available = {item["id"] for item in component_registry.all_components()}
    assert required <= available, sorted(required - available)

    # Broad catalog quality gate.  ForgeCAD used to claim >1,000 components while many
    # rendered as a literal bounding box.  Keep at least 100 diverse seed exemplars on
    # the premium parametric path and explicitly prove that the reported 12 mm precision
    # shaft is cylindrical rather than a cuboid with the right bounding dimensions.
    seed_ids = premium_geometry.curated_seed_ids(100)
    assert len(seed_ids) == 100, len(seed_ids)
    seed_categories = set()
    for component_id in seed_ids:
        component = component_registry.component_by_id(component_id)
        assert premium_geometry.supports(component), component_id
        parts = premium_geometry.component_parts(component)
        assert parts and all(shape is not None for shape, _ in parts), component_id
        seed_categories.add(str(component.get("category")))
    assert len(seed_categories) >= 15, seed_categories

    shaft_component = component_registry.component_by_id("shaft.12x50")
    shaft_parts = premium_geometry.component_parts(shaft_component)
    assert shaft_parts and len(shaft_parts) >= 1
    shaft_shape = shaft_parts[0][0]
    bb = shaft_shape.BoundingBox()
    bbox_volume = max(1e-9, bb.xlen * bb.ylen * bb.zlen)
    fill_ratio = float(shaft_shape.Volume()) / bbox_volume
    assert 0.68 <= fill_ratio <= 0.86, {"fill_ratio": fill_ratio, "reason": "12 mm shaft regressed to non-cylindrical/envelope geometry"}
    assert abs(max(bb.xlen, bb.ylen) - 12.0) < 0.6, (bb.xlen, bb.ylen, bb.zlen)
    assert abs(bb.zlen - 50.0) < 0.8, (bb.xlen, bb.ylen, bb.zlen)

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

    # Fidelity metadata alone cannot prove that a visible part is realistic. A generic
    # cuboid tessellates to only 12 triangles, so require materially complex rendered
    # meshes for every purchased part in the acceptance assembly as an independent gate.
    core = __import__("forge_engine.v110.core", fromlist=["PROJECT"])
    scene_by_id = {part["id"]: part for part in scene["parts"]}
    acceptance_geometry = {}
    acceptance_meshes = {}
    for obj in core.PROJECT.get("objects", []):
        component_id = obj.get("component_ref")
        if component_id in realistic_components.ACCEPTANCE_COMPONENTS:
            status = physical_components.component_geometry_status(obj)
            acceptance_geometry[component_id] = status
            assert component_registry.GEOMETRY_RANK.get(status.get("geometry_fidelity", "none"), 0) >= component_registry.GEOMETRY_RANK["detailed_parametric"], status
            assert status.get("geometry_source") not in {"legacy_fallback", "legacy_estimate"}, status
            rendered = scene_by_id[str(obj["id"])]["mesh"]
            triangle_count = len(rendered.get("triangles") or [])
            vertex_count = len(rendered.get("positions") or [])
            acceptance_meshes[component_id] = {"triangles": triangle_count, "vertices": vertex_count}
            assert triangle_count >= 60, {"component_id": component_id, "triangles": triangle_count, "reason": "acceptance component is still visually equivalent to primitive/envelope geometry"}
            assert vertex_count >= 40, {"component_id": component_id, "vertices": vertex_count, "reason": "acceptance component mesh is insufficiently detailed"}
    assert set(acceptance_geometry) == set(realistic_components.ACCEPTANCE_COMPONENTS), acceptance_geometry

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

    # .focad is the public design exchange contract. It is deliberately a transparent
    # ZIP container so external engineering agents can inspect and author a design while
    # ForgeCAD still validates its manifest and canonical project on import.
    bundle = PROJECT.export_bundle()
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "project.json", "components.json"} <= names, names
        raw_manifest = json.loads(archive.read("manifest.json"))
        assert raw_manifest["format"] == "focad", raw_manifest
        assert raw_manifest["format_version"] == 1, raw_manifest
    restored = project_bundle.import_bundle_bytes(bundle)
    assert restored["project"]["objects"]
    assert restored["manifest"]["format"] == "focad"
    assert restored["manifest"]["format_version"] == 1
    assert restored["manifest"]["bundle_version"] == 1

    search = PROJECT.search_components("raspberry", limit=5)
    assert any(item["id"] == "compute.raspberry_pi_5_8gb" for item in search)

    # UI mutations return a project snapshot; summary metrics must stay lightweight and
    # must not rebuild every purchased component's B-rep merely to total authoritative mass.
    summary_started = time.perf_counter()
    summary = PROJECT.snapshot()
    summary_seconds = time.perf_counter() - summary_started
    assert summary["metrics"]["object_count"] >= 6
    assert summary_seconds < 10.0, summary_seconds

    protected_branch = PROJECT.active_branch
    protected_object_count = int(PROJECT.snapshot()["metrics"]["object_count"])
    with tempfile.TemporaryDirectory() as temp_dir:
        step_path = Path(temp_dir) / "selftest.step"
        cq.exporters.export(cq.Workplane("XY").box(10, 20, 5), str(step_path))
        imported = PROJECT.import_step_part(step_path.name, step_path.read_bytes())
        imported_branch = PROJECT.active_branch
        imported_id = str(imported["object"]["id"])
        assert imported_branch != protected_branch
        assert any(part["id"] == imported_id for part in PROJECT.scene_manifest()["parts"])
        PROJECT.activate_branch(protected_branch)
        assert int(PROJECT.snapshot()["metrics"]["object_count"]) == protected_object_count
        assert not any(part["id"] == imported_id for part in PROJECT.snapshot()["parts"])
        PROJECT.activate_branch(imported_branch)

    print(json.dumps({
        "full_scope_selftest": "PASS",
        "registry_total": stats["total"],
        "premium_seed_models": len(seed_ids),
        "premium_seed_categories": len(seed_categories),
        "shaft_12x50_fill_ratio": round(fill_ratio, 4),
        "focad_format": restored["manifest"]["format"],
        "focad_version": restored["manifest"]["format_version"],
        "acceptance_objects": len(acceptance["objects"]),
        "acceptance_connections": len(acceptance["connections"]),
        "scene_parts": len(scene["parts"]),
        "active_branch": PROJECT.active_branch,
        "programmable_workspace": workspace_id,
        "bundle_bytes": len(bundle),
        "validation_counts": validation.get("counts"),
        "step_import_forked_from": protected_branch,
        "step_import_branch": imported_branch,
        "protected_baseline_unchanged": True,
        "responsive_snapshot_verified": True,
        "snapshot_seconds": round(summary_seconds, 3),
        "acceptance_geometry": acceptance_geometry,
        "acceptance_meshes": acceptance_meshes,
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
