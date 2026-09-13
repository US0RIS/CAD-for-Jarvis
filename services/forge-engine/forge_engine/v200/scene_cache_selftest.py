from __future__ import annotations

"""Regression gate for ForgeCAD 2.0 transform-independent scene caching."""

from ..engineering_state import PROJECT
from ..v110 import core


def _close(a: float, b: float, tolerance: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def run() -> dict[str, object]:
    PROJECT.new_project()
    PROJECT.execute(
        "add",
        {
            "name": "Scene cache fixture",
            "kind": "box",
            "params": {"x": 20.0, "y": 10.0, "z": 4.0},
            "material": "aluminum_6061_t6",
            "transform": {"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
            "semantic": {"role": "cache_fixture", "tags": ["fabricated"]},
        },
        actor="human",
        reason="Create transform-independent cache fixture",
    )
    object_id = str(core.PROJECT["objects"][-1]["id"])

    original_tessellate = core.tessellate
    calls = 0

    def counted_tessellate(obj, tolerance=0.35):
        nonlocal calls
        calls += 1
        return original_tessellate(obj, tolerance=tolerance)

    core.tessellate = counted_tessellate
    try:
        first = PROJECT.scene_manifest()
        assert calls == 1, calls
        assert first["mesh_cache"]["misses"] == 1
        assert first["mesh_cache"]["hits"] == 0
        first_part = first["parts"][0]
        assert first_part["mesh"]["cache_space"] == "canonical-local"
        assert first_part["mesh"]["mesh_space"] == "world"
        first_vertex = [float(value) for value in first_part["mesh"]["positions"][0]]

        PROJECT.execute(
            "transform",
            {
                "id": object_id,
                "position": [25.0, -8.0, 3.0],
                "rotation_deg": [0.0, 0.0, 90.0],
                "scale": [1.0, 1.0, 1.0],
            },
            actor="human",
            reason="Move cache fixture without changing topology",
        )
        second = PROJECT.scene_manifest()
        assert calls == 1, {"tessellations": calls, "reason": "transform incorrectly invalidated canonical mesh cache"}
        assert second["mesh_cache"]["hits"] == 1
        assert second["mesh_cache"]["misses"] == 0
        second_vertex = [float(value) for value in second["parts"][0]["mesh"]["positions"][0]]
        expected = [-first_vertex[1] + 25.0, first_vertex[0] - 8.0, first_vertex[2] + 3.0]
        assert all(_close(actual, target) for actual, target in zip(second_vertex, expected)), {
            "actual": second_vertex,
            "expected": expected,
        }

        # Geometry edits must still invalidate and regenerate the expensive canonical mesh.
        PROJECT.execute(
            "update",
            {"id": object_id, "params": {"x": 20.0, "y": 10.0, "z": 6.0}},
            actor="human",
            reason="Change topology-driving dimensions",
        )
        third = PROJECT.scene_manifest()
        assert calls == 2, calls
        assert third["mesh_cache"]["misses"] == 1
        assert third["mesh_cache"]["hits"] == 0

        # Another placement-only edit on the revised geometry must reuse the new cache.
        PROJECT.execute(
            "transform",
            {
                "id": object_id,
                "position": [-4.0, 7.0, 2.0],
                "rotation_deg": [15.0, 25.0, 35.0],
                "scale": [1.0, 1.0, 1.0],
            },
            actor="human",
            reason="Rotate revised fixture",
        )
        fourth = PROJECT.scene_manifest()
        assert calls == 2, calls
        assert fourth["mesh_cache"]["hits"] == 1
        assert fourth["mesh_cache"]["entries"] == 1
    finally:
        core.tessellate = original_tessellate

    return {
        "canonical_tessellations": calls,
        "scene_requests": 4,
        "transform_only_requests_reused_cache": 2,
        "geometry_edit_invalidated_cache": True,
        "mesh_space": "world",
        "cache_space": "canonical-local",
    }


def main() -> None:
    result = run()
    print("ForgeCAD 2.0 scene cache self-test: PASS")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
