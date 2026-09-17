from __future__ import annotations

"""Transform-independent scene mesh caching for ForgeCAD 2.0.

OpenCascade tessellation is materially more expensive than moving a part in the desktop
viewport. v1 cached the final world-space mesh, which meant every translate/rotate edit
invalidated the cache and forced a new OCC tessellation. That becomes increasingly
expensive as purchased-component geometry gets richer.

This module changes only the cache boundary, not the public scene contract:

* OCC tessellates canonical geometry once with an identity transform;
* the local mesh is cached by geometry identity, excluding placement;
* current uniform scale / XYZ rotation / translation are applied numerically to copied
  vertices when constructing `/v2/scene`;
* the frontend still receives the same world-space mesh plus `base_transform`, so no
  Three.js contract change is required.

OpenCascade remains on Forge Engine's main thread. This module never moves tessellation
to a worker, preserving the Windows stability rule established by the v1 scene path.
"""

from copy import deepcopy
import json
import math
from typing import Any

from ..engineering_state import EngineeringProject
from ..v110 import core, physical_components


_INSTALLED = False


def geometry_cache_key(obj: dict[str, Any]) -> str:
    """Stable geometry identity that intentionally excludes object placement."""
    payload = {
        "kind": obj.get("kind"),
        "params": obj.get("params"),
        "material": obj.get("material"),
        "features": obj.get("features"),
        "component_ref": obj.get("component_ref"),
        # Frozen component snapshots are part of .focad's engineering provenance and
        # may contain dimensions or geometry-source revisions used by component builders.
        "component_snapshot": obj.get("component_snapshot"),
        # A small number of custom geometry builders use semantic manufacturing tags.
        # Include semantics so those changes cannot accidentally reuse stale topology.
        "semantic": obj.get("semantic"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _identity_transform() -> dict[str, list[float]]:
    return {
        "position": [0.0, 0.0, 0.0],
        "rotation_deg": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }


def _canonical_object(obj: dict[str, Any]) -> dict[str, Any]:
    local = deepcopy(obj)
    local["transform"] = _identity_transform()
    return local


def _rotation_xyz(point: list[float], rotation_deg: list[float]) -> list[float]:
    """Match core.build_shape's sequential X, then Y, then Z rotations."""
    x, y, z = (float(point[0]), float(point[1]), float(point[2]))
    rx, ry, rz = (math.radians(float(rotation_deg[index] if index < len(rotation_deg) else 0.0)) for index in range(3))

    if abs(rx) > 1e-15:
        c, s = math.cos(rx), math.sin(rx)
        y, z = y * c - z * s, y * s + z * c
    if abs(ry) > 1e-15:
        c, s = math.cos(ry), math.sin(ry)
        x, z = x * c + z * s, -x * s + z * c
    if abs(rz) > 1e-15:
        c, s = math.cos(rz), math.sin(rz)
        x, y = x * c - y * s, x * s + y * c
    return [x, y, z]


def _world_positions(positions: list[list[float]], transform: dict[str, Any]) -> list[list[float]]:
    scale = [float(value) for value in (transform.get("scale") or [1.0, 1.0, 1.0])]
    while len(scale) < 3:
        scale.append(1.0)
    # Preserve the authoritative v1 geometry convention exactly: OCC only bakes scale
    # when it is uniform. Non-uniform scale remains a viewport hint and is therefore not
    # applied to the world-space mesh here either.
    uniform_scale = scale[0] if len({round(value, 9) for value in scale[:3]}) == 1 else 1.0
    rotation = [float(value) for value in (transform.get("rotation_deg") or [0.0, 0.0, 0.0])]
    while len(rotation) < 3:
        rotation.append(0.0)
    position = [float(value) for value in (transform.get("position") or [0.0, 0.0, 0.0])]
    while len(position) < 3:
        position.append(0.0)

    result: list[list[float]] = []
    for vertex in positions:
        scaled = [float(vertex[0]) * uniform_scale, float(vertex[1]) * uniform_scale, float(vertex[2]) * uniform_scale]
        rotated = _rotation_xyz(scaled, rotation)
        result.append([
            rotated[0] + position[0],
            rotated[1] + position[1],
            rotated[2] + position[2],
        ])
    return result


def _world_mesh(local_mesh: dict[str, Any], transform: dict[str, Any]) -> dict[str, Any]:
    mesh = deepcopy(local_mesh)
    mesh["positions"] = _world_positions(mesh.get("positions") or [], transform)
    mesh["mesh_space"] = "world"
    mesh["cache_space"] = "canonical-local"
    return mesh


def _scene_manifest(self: EngineeringProject) -> dict[str, Any]:
    meshes: list[dict[str, Any]] = []
    live_ids: set[str] = set()
    cache_hits = 0
    cache_misses = 0

    for obj in core.PROJECT.get("objects", []):
        if not obj.get("visible", True):
            continue
        object_id = str(obj["id"])
        live_ids.add(object_id)
        cache_key = geometry_cache_key(obj)
        cached = self._mesh_cache.get(object_id)
        if cached and cached[0] == cache_key:
            local_mesh = deepcopy(cached[1])
            cache_hits += 1
        else:
            try:
                # Keep OCC on this thread. The identity-transform copy guarantees that
                # placement edits never become part of expensive tessellation work.
                local_mesh = core.tessellate(_canonical_object(obj), tolerance=0.65)
            except Exception as exc:
                local_mesh = {
                    "id": obj["id"],
                    "positions": [],
                    "triangles": [],
                    "color": "#8aa0b6",
                    "error": str(exc),
                }
            self._mesh_cache[object_id] = (cache_key, deepcopy(local_mesh))
            cache_misses += 1

        transform = deepcopy(obj.get("transform") or _identity_transform())
        mesh = _world_mesh(local_mesh, transform)
        pos = transform.get("position", [0, 0, 0])
        length = max(sum(float(value) ** 2 for value in pos) ** 0.5, 1.0)
        explode = [float(value) / length for value in pos]
        geometry_status = (
            physical_components.component_geometry_status(obj)
            if obj.get("kind") == "component"
            else {"geometry_source": "forgecad_brep", "geometry_fidelity": "exact_brep", "fallback": False}
        )
        meshes.append({
            "id": object_id,
            "name": str(obj.get("name") or obj["id"]),
            "semantic_role": str((obj.get("semantic") or {}).get("role") or obj.get("kind") or "part"),
            "mesh": mesh,
            "explode_vector": explode,
            "base_transform": transform,
            "programmable_workspace_id": object_id if isinstance(obj.get("code"), dict) else None,
            "geometry_source": geometry_status.get("geometry_source"),
            "geometry_fidelity": geometry_status.get("geometry_fidelity"),
            "geometry_fallback": bool(geometry_status.get("fallback")),
        })

    for stale_id in set(self._mesh_cache) - live_ids:
        self._mesh_cache.pop(stale_id, None)

    return {
        "revision": self.snapshot()["revision"],
        "branch": core.ACTIVE_DESIGN,
        "parts": meshes,
        "authoritative": True,
        "mesh_cache": {
            "space": "canonical-local",
            "hits": cache_hits,
            "misses": cache_misses,
            "entries": len(self._mesh_cache),
        },
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    EngineeringProject._mesh_cache_key = staticmethod(geometry_cache_key)  # type: ignore[method-assign]
    EngineeringProject.scene_manifest = _scene_manifest  # type: ignore[method-assign]
    _INSTALLED = True
