from __future__ import annotations

"""Deterministic acceptance for ForgeCAD 6.2 purchased-component fidelity."""

from copy import deepcopy
from pathlib import Path
import json
import tempfile
from unittest.mock import patch

import cadquery as cq

from ..v110 import core
from .. import v601_scene_runtime
from . import component_fidelity, scene_runtime


def _fixture_component() -> dict:
    return {
        "schema_version": 1,
        "id": "fixture.vendor.exact-stepper",
        "category": "stepper_motor",
        "manufacturer": "Fixture Motion",
        "model": "EXACT-42",
        "name": "Fixture Motion EXACT-42",
        "manufacturer_part_number": "EXACT-42",
        "dimensions_mm": [42.0, 42.0, 48.0],
        "mass_g": 390.0,
        "material": None,
        "tags": ["nema17", "fixture"],
        "specs": {"shaft_diameter_mm": 5.0},
        "geometry": {
            "preferred": "parametric",
            "fidelity": "detailed_parametric",
            "trust": "manufacturer",
            "profile": "stepper_motor",
            "dimensions_mm": [42.0, 42.0, 48.0],
            "assets": [],
        },
        "interfaces": [],
        "keepouts": [],
        "procurement": {},
        "software": {"programmable": False, "platform": None},
        "provenance": [{"kind": "manufacturer", "trust": 100, "title": "Fixture manufacturer drawing"}],
        "trust_score": 100,
    }


def _fixture_object(component: dict) -> dict:
    return {
        "id": "fixture-instance",
        "name": component["name"],
        "kind": "component",
        "component_ref": component["id"],
        "component_snapshot": deepcopy(component),
        "params": {"x": 42.0, "y": 42.0, "z": 48.0},
        "material": "aluminum_6061_t6",
        "features": [],
        "interfaces": [],
        "visible": True,
        "transform": {"position": [10.0, 20.0, 30.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
    }


def _write_multisolid_step(path: Path) -> bytes:
    body = cq.Workplane("XY").box(42.0, 42.0, 40.0).val().translate((0.0, 0.0, -4.0))
    front = cq.Workplane("XY").box(42.0, 42.0, 4.0).val().translate((0.0, 0.0, 18.0))
    shaft = cq.Workplane("XY").circle(2.5).extrude(20.0).val().translate((0.0, 0.0, 20.0))
    connector = cq.Workplane("XY").box(10.0, 6.0, 5.0).val().translate((0.0, -22.0, -8.0))
    compound = cq.Compound.makeCompound([body, front, shaft, connector])
    cq.exporters.export(compound, str(path))
    data = path.read_bytes()
    assert len(data) > 800
    return data


def run() -> dict:
    component = _fixture_component()
    obj = _fixture_object(component)

    with tempfile.TemporaryDirectory(prefix="forgecad-v620-selftest-") as temp_dir:
        root = Path(temp_dir)
        original_package = component_fidelity.PACKAGE_ASSET_DIR
        original_cache = component_fidelity.CACHE_ASSET_DIR
        component_fidelity.PACKAGE_ASSET_DIR = root / "package-assets"
        component_fidelity.CACHE_ASSET_DIR = root / "cache-assets"
        component_fidelity._DOWNLOAD_FAILURES.clear()
        component_fidelity._DOWNLOAD_QUEUED.clear()
        try:
            scene_runtime.install()
            v601_scene_runtime.clear_memory_cache()

            fallback_status = component_fidelity.geometry_status(obj)
            assert fallback_status.get("authoritative_cad") is False
            assert fallback_status.get("fallback") is True
            fallback_parts, fallback_render_status = component_fidelity.rich_render_parts(obj, allow_download=False)
            assert fallback_parts
            assert fallback_render_status.get("authoritative_cad") is False
            fallback_key = v601_scene_runtime.geometry_cache_key(obj)

            step_score = component_fidelity._link_score(component, "/files/EXACT-42.step", "3D STEP model")
            zip_score = component_fidelity._link_score(component, "/downloads/EXACT-42-3d.zip", "CAD files")
            pdf_score = component_fidelity._link_score(component, "/drawing/EXACT-42.pdf", "Dimension drawing")
            assert step_score > zip_score > pdf_score

            source_step = root / "fixture.step"
            data = _write_multisolid_step(source_step)
            verification = component_fidelity._validate_step_bytes(data, component_id=component["id"])
            assert verification["solid_count"] >= 4
            exact_path, metadata = component_fidelity._write_cached_asset(
                component["id"],
                data,
                {
                    "source_url": "https://manufacturer.example/EXACT-42",
                    "resolved_url": "https://manufacturer.example/files/EXACT-42.step",
                    "source_kind": "manufacturer",
                    "geometry_fidelity": "official_step",
                    "verification": verification,
                },
                root=component_fidelity.CACHE_ASSET_DIR,
            )
            assert exact_path.is_file()
            assert metadata["sha256"] == verification["sha256"]

            exact_status = component_fidelity.geometry_status(obj)
            assert exact_status["authoritative_cad"] is True
            assert exact_status["fallback"] is False
            assert exact_status["geometry_fidelity"] == "official_step"
            assert exact_status["solid_count"] >= 4
            assert exact_status["asset_sha256"] == verification["sha256"]

            # Geometry status is queried for each repeated purchased component. Its
            # solid count comes from validated metadata, never a fresh heavy STEP
            # parse for every project instance or status poll.
            with patch.object(component_fidelity.cq.importers, "importStep",
                              side_effect=AssertionError("redundant STEP import")):
                for _ in range(24):
                    repeated_status = component_fidelity.geometry_status(obj)
                    assert repeated_status["solid_count"] == verification["solid_count"]
                    assert repeated_status["asset_sha256"] == verification["sha256"]

            exact_key = v601_scene_runtime.geometry_cache_key(obj)
            assert exact_key != fallback_key, "Exact vendor CAD must invalidate a cached fallback render mesh"

            rich_parts, rich_status = component_fidelity.rich_render_parts(obj, allow_download=False)
            assert rich_status["authoritative_cad"] is True
            assert len(rich_parts) >= 4
            assert all(part.get("material_class") for part in rich_parts)
            assert all(isinstance(part.get("material"), dict) for part in rich_parts)

            mesh = core.tessellate(obj, tolerance=0.8)
            groups = mesh.get("groups") or []
            assert mesh["authoritative_cad"] is True
            assert mesh["asset_sha256"] == verification["sha256"]
            assert len(groups) == len(rich_parts)
            assert len(groups) >= 4
            assert sum(int(group["triangle_count"]) for group in groups) == len(mesh["triangles"])
            assert all("metalness" in group["material"] and "roughness" in group["material"] for group in groups)
            assert len(mesh["triangles"]) > 100, "Exact fixture should not collapse to toy-level triangle count"

            assert obj["component_ref"] == component["id"]
            assert obj["component_snapshot"]["manufacturer_part_number"] == "EXACT-42"
            assert obj["transform"]["position"] == [10.0, 20.0, 30.0]

            local_obj = deepcopy(obj)
            local_obj["transform"] = {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]}
            first = v601_scene_runtime._local_mesh(local_obj)
            assert len(first.get("groups") or []) >= 4
            v601_scene_runtime.clear_memory_cache()
            second = v601_scene_runtime._local_mesh(local_obj)
            assert first["groups"] == second["groups"]
            assert first["triangles"] == second["triangles"]

            return {
                "ok": True,
                "version": "6.2.1",
                "checks": {
                    "fallback_is_explicit": True,
                    "step_link_precedence": True,
                    "authoritative_step_precedence": True,
                    "multi_solid_preservation": True,
                    "pbr_material_groups": True,
                    "asset_sensitive_scene_cache": True,
                    "persistent_group_cache": True,
                    "canonical_component_identity_preserved": True,
                    "status_uses_verified_solid_count_without_step_reimport": True,
                },
                "fixture": {
                    "solid_count": exact_status["solid_count"],
                    "subpart_count": len(groups),
                    "triangle_count": len(mesh["triangles"]),
                },
            }
        finally:
            component_fidelity.PACKAGE_ASSET_DIR = original_package
            component_fidelity.CACHE_ASSET_DIR = original_cache
            component_fidelity._DOWNLOAD_FAILURES.clear()
            component_fidelity._DOWNLOAD_QUEUED.clear()
            v601_scene_runtime.clear_memory_cache()


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
