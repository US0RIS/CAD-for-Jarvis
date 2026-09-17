from __future__ import annotations

"""6.2 viewport geometry/material bridge.

Engineering B-rep remains canonical. This layer only changes how purchased-component
geometry is tessellated for display: every exact/fallback subpart becomes a mesh group
with its own PBR material descriptor. The persistent 6.0.1 scene cache is also keyed by
the actually resolved authoritative asset, so a newly available vendor STEP can never
remain hidden behind a previously cached family fallback.
"""

from copy import deepcopy
from typing import Any

from ..v110 import core
from .. import v601_scene_runtime
from . import component_fidelity
from . import component_fidelity_runtime


_INSTALLED = False
_ORIGINAL_TESSELLATE = None
_ORIGINAL_GEOMETRY_IDENTITY = None


def _uniform_scale(scale: list[float]) -> float:
    values = [float(value) for value in scale]
    return values[0] if len({round(value, 9) for value in values}) == 1 else 1.0


def _transform_shape(shape: Any, obj: dict[str, Any]) -> Any:
    transform = obj.get("transform") or {}
    scale = _uniform_scale(list(transform.get("scale") or [1.0, 1.0, 1.0]))
    result = shape.scale(scale) if abs(scale - 1.0) > 1e-9 else shape
    rotation = [float(value) for value in (transform.get("rotation_deg") or [0.0, 0.0, 0.0])]
    if rotation[0]:
        result = result.rotate((0, 0, 0), (1, 0, 0), rotation[0])
    if rotation[1]:
        result = result.rotate((0, 0, 0), (0, 1, 0), rotation[1])
    if rotation[2]:
        result = result.rotate((0, 0, 0), (0, 0, 1), rotation[2])
    position = tuple(float(value) for value in (transform.get("position") or [0.0, 0.0, 0.0]))
    return result.translate(position)


def _component_tessellate(obj: dict[str, Any], tolerance: float) -> dict[str, Any] | None:
    if obj.get("kind") != "component" or obj.get("features"):
        return None
    parts, status = component_fidelity.rich_render_parts(obj, allow_download=False)
    if not parts:
        return None

    angular_tolerance = 0.24 if float(tolerance) >= 0.60 else 0.08
    positions: list[list[float]] = []
    triangles: list[list[int]] = []
    groups: list[dict[str, Any]] = []
    offset = 0
    triangle_offset = 0
    for index, part in enumerate(parts):
        shape = _transform_shape(part["shape"], obj)
        vertices, faces = shape.tessellate(float(tolerance), angular_tolerance)
        local_positions = [[float(vertex.x), float(vertex.y), float(vertex.z)] for vertex in vertices]
        local_triangles = [
            [int(a) + offset, int(b) + offset, int(c) + offset]
            for a, b, c in faces
        ]
        positions.extend(local_positions)
        triangles.extend(local_triangles)
        groups.append({
            "name": str(part.get("name") or f"subpart-{index + 1:03d}"),
            "triangle_start": triangle_offset,
            "triangle_count": len(local_triangles),
            "material_class": str(part.get("material_class") or "generic_component"),
            "material": deepcopy(part.get("material") or {}),
        })
        offset += len(local_positions)
        triangle_offset += len(local_triangles)

    return {
        "id": str(obj["id"]),
        "positions": positions,
        "triangles": triangles,
        "groups": groups,
        "material": obj.get("material"),
        "color": "#ffffff",
        "geometry_fidelity": status.get("geometry_fidelity"),
        "geometry_source": status.get("geometry_source"),
        "authoritative_cad": bool(status.get("authoritative_cad")),
        "asset_sha256": status.get("asset_sha256"),
        "subpart_count": len(groups),
        "triangle_count": len(triangles),
    }


def install() -> None:
    global _INSTALLED, _ORIGINAL_TESSELLATE, _ORIGINAL_GEOMETRY_IDENTITY
    if _INSTALLED:
        return

    component_fidelity_runtime.install()
    component_fidelity.install()
    _ORIGINAL_TESSELLATE = core.tessellate
    _ORIGINAL_GEOMETRY_IDENTITY = v601_scene_runtime._geometry_identity

    def tessellate(obj: dict[str, Any], tolerance: float = 0.35) -> dict[str, Any]:
        component_mesh = _component_tessellate(obj, float(tolerance))
        if component_mesh is not None:
            return component_mesh
        assert _ORIGINAL_TESSELLATE is not None
        return _ORIGINAL_TESSELLATE(obj, tolerance)

    def geometry_identity(obj: dict[str, Any]) -> dict[str, Any]:
        assert _ORIGINAL_GEOMETRY_IDENTITY is not None
        identity = _ORIGINAL_GEOMETRY_IDENTITY(obj)
        if obj.get("kind") == "component":
            identity["component_asset_revision_v620"] = component_fidelity.geometry_revision(obj)
            identity["component_render_schema"] = 2
        return identity

    core.tessellate = tessellate
    v601_scene_runtime._geometry_identity = geometry_identity
    _INSTALLED = True
