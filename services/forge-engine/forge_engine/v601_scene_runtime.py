from __future__ import annotations

"""ForgeCAD 6.0.1 desktop scene-startup hardening.

The legacy scene path tessellates every object on every process start and keys its
in-memory cache by object id + transform. Real assemblies therefore pay the full
OpenCascade cost on every launch, duplicate hardware is re-tessellated for each
instance, and placement-only edits invalidate otherwise identical geometry.

This layer keeps the existing /v2/scene payload contract intact while caching a
local-space interactive mesh by geometry identity. The cached mesh is persisted to
disk, shared by duplicate instances, and transformed back to the legacy world-space
payload cheaply before the renderer receives it. The desktop can therefore preserve
all existing transform/selection behavior without re-running CAD tessellation.
"""

from copy import deepcopy
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from types import MethodType
from typing import Any

from . import __version__
from .v110 import core
from .v110 import physical_components

_CACHE_SCHEMA = 2
_CACHE_DIR_NAME = "viewport-mesh-cache-v601"
_MEMORY_CACHE: dict[str, dict[str, Any]] = {}
_CACHE_LOCK = threading.RLock()


def _cache_dir() -> Path:
    root = core.DATA_DIR / _CACHE_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _geometry_identity(obj: dict[str, Any]) -> dict[str, Any]:
    """Return only fields that can change local tessellated geometry.

    Placement is deliberately excluded. The browser already applies base_transform,
    so translating/rotating an object must not force an OpenCascade re-tessellation.
    """
    snapshot = obj.get("component_snapshot") or {}
    return {
        "cache_schema": _CACHE_SCHEMA,
        "engine_version": __version__,
        "kind": obj.get("kind"),
        "params": obj.get("params") or {},
        "material": obj.get("material"),
        "features": obj.get("features") or [],
        "component_ref": obj.get("component_ref"),
        "component_snapshot": {
            "id": snapshot.get("id"),
            "revision": snapshot.get("revision"),
            "dimensions_mm": snapshot.get("dimensions_mm"),
            "geometry": snapshot.get("geometry"),
            "specs": snapshot.get("specs"),
        } if snapshot else None,
    }


def geometry_cache_key(obj: dict[str, Any]) -> str:
    payload = json.dumps(_geometry_identity(obj), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.json.gz"


def clear_memory_cache() -> None:
    with _CACHE_LOCK:
        _MEMORY_CACHE.clear()


def _valid_mesh(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("positions"), list) and isinstance(value.get("triangles"), list)


def _load_cached_mesh(key: str) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        cached = _MEMORY_CACHE.get(key)
        if cached is not None:
            return deepcopy(cached)
        path = _cache_path(key)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            if int(payload.get("schema", 0)) != _CACHE_SCHEMA or not _valid_mesh(payload.get("mesh")):
                return None
            mesh = dict(payload["mesh"])
            _MEMORY_CACHE[key] = deepcopy(mesh)
            return mesh
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None


def _store_cached_mesh(key: str, mesh: dict[str, Any]) -> None:
    if not _valid_mesh(mesh) or mesh.get("error"):
        return
    clean = deepcopy(mesh)
    clean.pop("id", None)
    with _CACHE_LOCK:
        _MEMORY_CACHE[key] = deepcopy(clean)
        path = _cache_path(key)
        temp = path.with_suffix(path.suffix + ".tmp")
        try:
            with gzip.open(temp, "wt", encoding="utf-8", compresslevel=5) as handle:
                json.dump({"schema": _CACHE_SCHEMA, "mesh": clean}, handle, separators=(",", ":"))
            os.replace(temp, path)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def _local_mesh(obj: dict[str, Any]) -> dict[str, Any]:
    key = geometry_cache_key(obj)
    cached = _load_cached_mesh(key)
    if cached is not None:
        cached["id"] = str(obj["id"])
        return cached

    local_obj = deepcopy(obj)
    local_obj["transform"] = {
        "position": [0.0, 0.0, 0.0],
        "rotation_deg": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    try:
        # 0.8 mm remains substantially finer than screen-space presentation requires
        # for a whole assembly while avoiding excessive cold-start triangle counts.
        mesh = core.tessellate(local_obj, tolerance=0.8)
    except Exception as exc:
        return {
            "id": str(obj["id"]),
            "positions": [],
            "triangles": [],
            "color": "#8aa0b6",
            "error": str(exc),
        }
    _store_cached_mesh(key, mesh)
    mesh = deepcopy(mesh)
    mesh["id"] = str(obj["id"])
    return mesh


def _world_transform(mesh: dict[str, Any], obj: dict[str, Any]) -> dict[str, Any]:
    """Apply the same transform sequence as v110.core.build_shape without OCC work."""
    result = deepcopy(mesh)
    transform = obj.get("transform") or {}
    position = [float(value) for value in (transform.get("position") or [0.0, 0.0, 0.0])]
    rotation = [math.radians(float(value)) for value in (transform.get("rotation_deg") or [0.0, 0.0, 0.0])]
    scale_values = [float(value) for value in (transform.get("scale") or [1.0, 1.0, 1.0])]

    # Preserve the legacy native-shape contract: core.build_shape applies only uniform
    # scaling. Non-uniform scaling remains a viewport-level hint and is not baked into
    # server geometry.
    uniform_scale = scale_values[0] if len({round(value, 9) for value in scale_values}) == 1 else 1.0
    sx, cx = math.sin(rotation[0]), math.cos(rotation[0])
    sy, cy = math.sin(rotation[1]), math.cos(rotation[1])
    sz, cz = math.sin(rotation[2]), math.cos(rotation[2])
    tx, ty, tz = position

    transformed: list[list[float]] = []
    for vertex in result.get("positions", []):
        if not isinstance(vertex, (list, tuple)) or len(vertex) < 3:
            continue
        x, y, z = float(vertex[0]) * uniform_scale, float(vertex[1]) * uniform_scale, float(vertex[2]) * uniform_scale
        # OpenCascade path applies X, then Y, then Z rotation, then translation.
        y, z = y * cx - z * sx, y * sx + z * cx
        x, z = x * cy + z * sy, -x * sy + z * cy
        x, y = x * cz - y * sz, x * sz + y * cz
        transformed.append([x + tx, y + ty, z + tz])
    result["positions"] = transformed
    result["id"] = str(obj["id"])
    return result


def _revision() -> str:
    # This is deliberately the same revision formula as EngineeringProject.snapshot(),
    # but avoids the expensive project_metrics() geometry pass at the end of /v2/scene.
    return f"{core.ACTIVE_DESIGN}:{len(core.PROJECT.get('ledger', [])) + 1}:{core.PROJECT.get('updated_at', '')}"


def scene_manifest(_project: Any) -> dict[str, Any]:
    meshes: list[dict[str, Any]] = []
    for obj in core.PROJECT.get("objects", []):
        if not obj.get("visible", True):
            continue
        local = _local_mesh(obj)
        mesh = _world_transform(local, obj)
        geometry_status = (
            physical_components.component_geometry_status(obj)
            if obj.get("kind") == "component"
            else {"geometry_source": "forgecad_brep", "geometry_fidelity": "exact_brep", "fallback": False}
        )
        position = (obj.get("transform") or {}).get("position", [0.0, 0.0, 0.0])
        length = max(sum(float(value) ** 2 for value in position) ** 0.5, 1.0)
        explode = [float(value) / length for value in position]
        meshes.append({
            "id": str(obj["id"]),
            "name": str(obj.get("name") or obj["id"]),
            "semantic_role": str((obj.get("semantic") or {}).get("role") or obj.get("kind") or "part"),
            "mesh": mesh,
            "explode_vector": explode,
            "base_transform": deepcopy(obj.get("transform") or {
                "position": [0.0, 0.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }),
            "programmable_workspace_id": str(obj["id"]) if isinstance(obj.get("code"), dict) else None,
            "geometry_source": geometry_status.get("geometry_source"),
            "geometry_fidelity": geometry_status.get("geometry_fidelity"),
            "geometry_fallback": bool(geometry_status.get("fallback")),
        })
    return {
        "revision": _revision(),
        "branch": core.ACTIVE_DESIGN,
        "parts": meshes,
        "authoritative": True,
    }


def install(project: Any) -> None:
    """Install the optimized scene manifest only for the 6.0.1 desktop runtime."""
    if getattr(project, "_forgecad_v601_scene_runtime", False):
        return
    project.scene_manifest = MethodType(scene_manifest, project)
    project._forgecad_v601_scene_runtime = True
