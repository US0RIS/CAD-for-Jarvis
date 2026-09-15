from __future__ import annotations

"""Regression checks for ForgeCAD 6.0.1 viewport startup.

The important property is not a benchmark number. A real assembly must not require one
OpenCascade tessellation per object on every launch. These checks prove that duplicate
geometry shares one local mesh, that placement-only edits do not invalidate it, and
that the cache survives a simulated Forge Engine restart.
"""

from copy import deepcopy
import math
import shutil
from typing import Any

from .engineering_state import PROJECT
from .v110 import core
from .v601_scene_runtime import clear_memory_cache, geometry_cache_key, install


def _transform(index: int) -> dict[str, list[float]]:
    return {
        "position": [float((index % 13) * 34), float((index // 13) * 41), float((index % 3) * 7)],
        "rotation_deg": [0.0, 0.0, float((index % 4) * 15)],
        "scale": [1.0, 1.0, 1.0],
    }


def _object(index: int) -> dict[str, Any]:
    family = index % 4
    return {
        "id": f"scene-cache-part-{index:02d}",
        "name": f"Scene cache part {index:02d}",
        "kind": "box",
        "params": {
            "x": 18.0 + family * 3.0,
            "y": 14.0 + family * 2.0,
            "z": 8.0 + family,
        },
        "material": "aluminum_6061_t6",
        "transform": _transform(index),
        "features": [],
        "semantic": {"role": "structure", "tags": ["v601-scene-selftest"]},
        "visible": True,
    }


def _install_fixture() -> None:
    project = core.upgrade_project(core.default_project())
    project.update({
        "name": "ForgeCAD 6.0.1 Scene Cache Selftest",
        "objects": [_object(index) for index in range(52)],
        "joints": [],
        "loads": [],
        "constraints": [],
        "requirements": [],
        "bom": [],
        "connections": [],
        "simulations": [],
        "notebook": [],
        "ledger": [],
    })
    PROJECT._install_project(
        project,
        branch="main",
        status="unverified",
        note="6.0.1 scene cache regression fixture",
        physical_verified=False,
    )
    install(PROJECT)


def _bounds(mesh: dict[str, Any]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    vertices = mesh.get("positions") or []
    assert vertices, "scene mesh unexpectedly has no vertices"
    return (
        tuple(min(float(vertex[axis]) for vertex in vertices) for axis in range(3)),
        tuple(max(float(vertex[axis]) for vertex in vertices) for axis in range(3)),
    )


def _assert_bounds_close(actual: tuple[tuple[float, float, float], tuple[float, float, float]], expected: tuple[tuple[float, float, float], tuple[float, float, float]], tolerance: float = 1e-6) -> None:
    for actual_corner, expected_corner in zip(actual, expected):
        for actual_value, expected_value in zip(actual_corner, expected_corner):
            assert math.isclose(actual_value, expected_value, rel_tol=0.0, abs_tol=tolerance), (actual, expected)


def main() -> None:
    cache_dir = core.DATA_DIR / "viewport-mesh-cache-v601"
    shutil.rmtree(cache_dir, ignore_errors=True)
    clear_memory_cache()
    _install_fixture()

    # The fixture has 52 instances but only four local geometries. The first cold scene
    # may therefore run OpenCascade at most four times.
    original_tessellate = core.tessellate
    tessellations = 0

    def counting_tessellate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal tessellations
        tessellations += 1
        return original_tessellate(*args, **kwargs)

    core.tessellate = counting_tessellate
    try:
        cold = PROJECT.scene_manifest()
    finally:
        core.tessellate = original_tessellate

    assert len(cold["parts"]) == 52
    assert tessellations == 4, f"expected four unique tessellations for 52 instances, got {tessellations}"
    assert len({geometry_cache_key(obj) for obj in core.PROJECT["objects"]}) == 4

    # Validate that the optimized local-cache path preserves the old world-space scene
    # envelope for a placed/rotated object. This guards the existing renderer contract.
    probe = deepcopy(core.PROJECT["objects"][7])
    expected = original_tessellate(probe, tolerance=0.8)
    actual = next(part["mesh"] for part in cold["parts"] if part["id"] == probe["id"])
    _assert_bounds_close(_bounds(actual), _bounds(expected), tolerance=1e-5)

    # Simulate an engine restart: clear only RAM. The second scene must be served from
    # persistent cache even if tessellation is made unavailable.
    clear_memory_cache()

    def forbidden_tessellate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("warm scene unexpectedly attempted OpenCascade tessellation")

    core.tessellate = forbidden_tessellate
    try:
        warm = PROJECT.scene_manifest()
        assert len(warm["parts"]) == 52

        # A placement-only edit must also remain cache-only. The geometry envelope should
        # translate by the exact requested amount without generating a new local mesh.
        object_zero = core.PROJECT["objects"][0]
        before = next(part["mesh"] for part in warm["parts"] if part["id"] == object_zero["id"])
        before_bounds = _bounds(before)
        object_zero["transform"]["position"][0] += 123.0
        moved = PROJECT.scene_manifest()
        after = next(part["mesh"] for part in moved["parts"] if part["id"] == object_zero["id"])
        after_bounds = _bounds(after)
        assert math.isclose(after_bounds[0][0] - before_bounds[0][0], 123.0, abs_tol=1e-6)
        assert math.isclose(after_bounds[1][0] - before_bounds[1][0], 123.0, abs_tol=1e-6)
    finally:
        core.tessellate = original_tessellate

    print({
        "forgecad_v601_scene_selftest": {
            "ok": True,
            "instances": len(cold["parts"]),
            "unique_geometry": 4,
            "cold_tessellations": tessellations,
            "persistent_cache_restart": True,
            "placement_reuses_cache": True,
        }
    })


if __name__ == "__main__":
    main()
