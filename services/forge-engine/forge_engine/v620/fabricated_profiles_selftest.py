from __future__ import annotations

"""Offline CAD and .focad regression for the reusable fabricated profiles."""

from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import math
from unittest.mock import patch
import zipfile

import cadquery as cq

from ..v110 import component_registry, core, project_bundle
from . import fabricated_profiles


def _obj(kind: str, params: dict, position=(0., 0., 0.)) -> dict:
    return {
        "id": f"profile-{kind}",
        "kind": kind,
        "name": f"Profile: {kind}",
        "params": deepcopy(params),
        "material": "petg",
        "features": [],
        "transform": {
            "position": list(position), "rotation_deg": [0., 0., 0.],
            "scale": [1., 1., 1.],
        },
        "semantic": {
            "role": "fabricated_reference_geometry",
            "physical_verified": False,
            "source": "ForgeCAD analytical parametric template",
        },
        "visible": True,
    }


def _bounds(shape) -> list[float]:
    b = shape.BoundingBox()
    return [b.xlen, b.ylen, b.zlen]


def _near(actual, expected, tol=0.001):
    assert math.isclose(actual, expected, rel_tol=tol, abs_tol=tol), (actual, expected)


def _invalid(kind: str, **overrides) -> None:
    p = dict(fabricated_profiles.PROFILE_LIBRARY[kind]["params"])
    p.update(overrides)
    try:
        core.build_shape(_obj(kind, p))
    except (ValueError, KeyError):
        return
    raise AssertionError(f"Invalid {kind} parameters unexpectedly produced geometry: {overrides}")


def run() -> dict:
    objects = []
    for index, (kind, spec) in enumerate(fabricated_profiles.PROFILE_LIBRARY.items()):
        obj = _obj(kind, spec["params"], position=(index * 150., 0., 0.))
        shape = core.build_shape(obj)
        assert shape.isValid(), f"{kind}: invalid OpenCascade B-rep"
        assert len(list(shape.Solids())) == 1, f"{kind}: shape must be one contiguous fabricated solid"
        assert math.isfinite(shape.Volume()) and shape.Volume() > 0, kind
        verts, triangles = shape.tessellate(0.7, 0.3)
        assert verts and len(triangles) >= 16, f"{kind}: missing usable scene geometry"
        assert all(math.isfinite(axis) and axis > 0 for axis in _bounds(shape))
        objects.append(obj)

    # Known analytical envelopes and exact volume checks catch visually plausible
    # but wrong-sized shapes (notably doubled extrusion heights).
    at = {obj["kind"]: core.build_shape({**obj, "transform": {
        "position": [0., 0., 0.], "rotation_deg": [0., 0., 0.],
        "scale": [1., 1., 1.],
    }}) for obj in objects}
    _near(at["hollow_tube"].Volume(), math.pi * (8**2 - 6**2) * 30)
    for kind, dims in {
        "hollow_tube": [16., 16., 30.],
        "flanged_spool": [36., 36., 28.],
        "tapered_nozzle": [15., 15., 25.],
        "split_cuff": [70., 70., 24.],
        "guide_eyelet": [22., 16., 4.],
        "u_bracket": [40., 28., 22.],
        "cartridge_cup": [26., 26., 38.],
    }.items():
        for a, b in zip(_bounds(at[kind]), dims):
            _near(a, b)

    spool = math.pi * (
        (10**2 - 2.5**2) * 24 + 2 * (18**2 - 2.5**2) * 2
    )
    _near(at["flanged_spool"].Volume(), spool)
    cup = math.pi * (13**2 * 38 - 10**2 * 35)
    _near(at["cartridge_cup"].Volume(), cup)
    bracket = 40 * 28 * 3 + 2 * 3 * 28 * (22 - 3)
    _near(at["u_bracket"].Volume(), bracket)
    assert at["split_cuff"].Volume() < (
        math.pi * (35**2 - 31**2) * 24 * 0.85
    ), "Cuff needs an actual gap, not a closed ring"
    _near(objects[-1]["transform"]["position"][0], 900.)

    # Standard ForgeCAD feature history must still cut these shape families.
    drilled = deepcopy(objects[0])
    drilled["features"] = [{"type": "hole", "diameter": 3.0, "axis": "x",
                             "y": 0.0, "z": 0.0}]
    assert core.build_shape(drilled).Volume() < core.build_shape(objects[0]).Volume()

    for kind, overrides in (
        ("hollow_tube", {"inner_diameter": 20.0}),
        ("flanged_spool", {"core_diameter": 40.0}),
        ("flanged_spool", {"bore_diameter": 21.0}),
        ("tapered_nozzle", {"wall_thickness": 5.0}),
        ("split_cuff", {"opening_angle_deg": 190.0}),
        ("guide_eyelet", {"hole_diameter": 20.0}),
        ("u_bracket", {"wall_thickness": 21.0}),
        ("cartridge_cup", {"base_thickness": 40.0}),
        ("hollow_tube", {"length": float("nan")}),
        ("hollow_tube", {"length": -1.0}),
        ("hollow_tube", {"length": "not-a-number"}),
    ):
        _invalid(kind, **overrides)

    # The interchange contract is essential for agent-authored design projects:
    # keep all parametric edits, one genuine purchased SKU, and the model's
    # explicitly unverified status through a portable .focad round-trip.
    purchased = component_registry.make_project_object(
        "power.pololu.d24v50f5", name="Purchased regulator",
        transform={"position": [0., 80., 8.],
                   "rotation_deg": [0., 0., 0.], "scale": [1., 1., 1.]},
    )
    purchased.update({"id": "purchased-regulator", "features": [], "visible": True})
    stamp = datetime.now(timezone.utc).isoformat()
    project = {
        "schema": 4, "version": "6.2.1-dev",
        "name": "Fabricated profiles acceptance assembly",
        "created_at": stamp, "updated_at": stamp,
        "objects": [*objects, purchased],
        "joints": [], "loads": [], "constraints": [], "connections": [],
        "requirements": [], "simulations": [], "ledger": [],
        "bom": [component_registry.bom_item("power.pololu.d24v50f5")],
        "notebook": [{"id": "truth", "text": "Reference geometry only; never physically verified."}],
        "settings": {"units": "mm", "coordinate_system": "Z-up"},
    }
    workspace = {"active": "main", "branches": {"main": deepcopy(project)},
                 "designs": {"main": {"status": "unverified",
                                     "physical_verified": False}}}
    payload = project_bundle.export_bundle_bytes(project, workspace=workspace)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert {"manifest.json", "project.json", "components.json",
                "workspace.json"} <= set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "focad" and manifest["component_count"] == 1
    imported = project_bundle.import_bundle_bytes(payload)
    result = imported["project"]
    assert len(result["objects"]) == 8
    assert [x["kind"] for x in result["objects"][:7]] == list(fabricated_profiles.PROFILE_LIBRARY)
    assert result["objects"][7]["component_ref"] == "power.pololu.d24v50f5"
    assert imported["workspace"]["designs"]["main"]["physical_verified"] is False
    for obj in result["objects"][:7]:
        assert core.build_shape(obj).Volume() > 0, obj["kind"]

    return {"ok": True, "profile_count": len(objects), "purchased_components": 1,
            "focad_bytes": len(payload), "checks": {
                "shape_validity": True, "analytical_dimensions_and_volumes": True,
                "bad_parameters_fail_closed": True, "feature_history": True,
                "focad_multibranch_roundtrip": True, "purchased_identity_preserved": True,
                "physical_verification_not_fabricated": True}}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
