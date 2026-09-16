from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 named design parameters."""

from ..engineering_state import PROJECT
from ..v110 import core
from . import parametric_expressions as params
from . import structural_fea


def _set(name: str, **kwargs):
    return PROJECT.execute("set_design_parameter", {"name": name, **kwargs}, actor="human", reason=f"Set {name}")


def run() -> dict[str, object]:
    PROJECT.new_project()
    _set("body_width", value=40.0, unit="mm")
    _set("wall", value=2.0, unit="mm")
    _set("outer_width", expression="body_width + 2 * wall", unit="mm")
    _set("hole_diameter", expression="max(3.2, wall + 1.0)", unit="mm")

    report = params.parameter_report()
    assert report["count"] == 4
    assert abs(report["values"]["outer_width"] - 44.0) < 1e-9
    assert abs(report["values"]["hole_diameter"] - 3.2) < 1e-9

    PROJECT.execute(
        "add",
        {
            "name": "Parametric plate",
            "kind": "box",
            "params": {
                "x": {"expr": "outer_width"},
                "y": 20.0,
                "z": {"expr": "wall"},
            },
            "material": "aluminum_6061_t6",
            "features": [
                {"type": "hole", "diameter": {"expr": "hole_diameter"}, "axis": "z", "x": 0.0, "y": 0.0, "z": 0.0},
            ],
            "semantic": {"role": "parametric_test", "tags": ["fabricated", "parametric"]},
        },
        actor="human",
        reason="Create expression-driven geometry",
    )
    obj = core.PROJECT["objects"][-1]
    object_id = str(obj["id"])
    assert obj["params"]["x"] == {"expr": "outer_width"}
    shape = core.build_shape(obj)
    bounds = shape.BoundingBox()
    assert abs(bounds.xlen - 44.0) < 1e-5
    assert abs(bounds.ylen - 20.0) < 1e-5
    assert abs(bounds.zlen - 2.0) < 1e-5
    first_volume = float(shape.Volume())

    first_scene = PROJECT.scene_manifest()
    assert first_scene["mesh_cache"]["misses"] >= 1
    second_scene = PROJECT.scene_manifest()
    assert second_scene["mesh_cache"]["hits"] >= 1

    _set("body_width", value=50.0, unit="mm")
    updated = core.object_by_id(object_id)
    # Canonical state remains symbolic while physical geometry regenerates to 54 mm.
    assert updated["params"]["x"] == {"expr": "outer_width"}
    updated_shape = core.build_shape(updated)
    updated_bounds = updated_shape.BoundingBox()
    assert abs(updated_bounds.xlen - 54.0) < 1e-5
    assert float(updated_shape.Volume()) > first_volume
    third_scene = PROJECT.scene_manifest()
    assert third_scene["mesh_cache"]["misses"] >= 1

    resolved = params.resolve_object(updated)
    assert resolved["params"]["x"] == 54.0
    assert abs(resolved["features"][0]["diameter"] - 3.2) < 1e-9

    # The 3D solid FEA path must see resolved dimensions rather than rejecting symbolic
    # geometry. Remove the feature temporarily because the production solver's scope is
    # intentionally exact unfeatured boxes.
    fea_obj = dict(updated)
    fea_obj["features"] = []
    fea = structural_fea.solve_box(fea_obj, force_n=25.0, mesh_counts=(3, 2, 2))
    assert fea["supported"] is True
    assert fea["mesh"]["elements"] == 12

    # Unknown names and cycles are rejected transactionally.
    before = params.parameter_report()["values"].copy()
    try:
        _set("bad", expression="does_not_exist + 1")
        raise AssertionError("Unknown dependency should have failed")
    except ValueError:
        pass
    assert params.parameter_report()["values"] == before

    _set("cycle_a", value=1.0)
    _set("cycle_b", expression="cycle_a + 1")
    try:
        _set("cycle_a", expression="cycle_b + 1")
        raise AssertionError("Cyclic dependency should have failed")
    except ValueError:
        pass
    assert params.parameter_report()["values"]["cycle_a"] == 1.0

    try:
        PROJECT.execute("delete_design_parameter", {"name": "body_width"}, actor="human", reason="Dependency deletion test")
        raise AssertionError("Deleting a referenced parameter should have failed")
    except ValueError:
        pass
    assert "body_width" in params.parameter_report()["values"]

    try:
        _set("unsafe", expression="__import__('os').system('echo nope')")
        raise AssertionError("Unsafe expression should have failed")
    except ValueError:
        pass

    return {
        "parameter_count": params.parameter_report()["count"],
        "outer_width_mm": params.parameter_report()["values"]["outer_width"],
        "symbolic_geometry_preserved": core.object_by_id(object_id)["params"]["x"] == {"expr": "outer_width"},
        "resolved_width_mm": round(updated_bounds.xlen, 6),
        "scene_cache_invalidated": third_scene["mesh_cache"]["misses"] >= 1,
        "solid_fea_supported": fea["supported"],
        "unsafe_expression_blocked": "unsafe" not in params.parameter_report()["values"],
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 parametric expression self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
