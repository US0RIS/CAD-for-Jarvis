from __future__ import annotations

"""Geometry-backed component thumbnails for the ForgeCAD catalog.

The catalog thumbnail is rendered from the same canonical component geometry used by
ForgeCAD's 3D scene.  This deliberately avoids arbitrary stock photography: if a
component model improves, the thumbnail fingerprint changes and a new preview is cached.
"""

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from . import component_registry, core

THUMBNAIL_VERSION = 2
WIDTH = 360
HEIGHT = 250
PADDING = 22.0


def _fingerprint(component: dict[str, Any]) -> str:
    payload = {
        "renderer": THUMBNAIL_VERSION,
        "id": component.get("id"),
        "revision": component.get("revision"),
        "dimensions_mm": component.get("dimensions_mm"),
        "geometry": component.get("geometry"),
        "specs": component.get("specs"),
        "tags": component.get("tags"),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:20]


def _safe_color(value: str | None, fallback: str = "#8795a1") -> str:
    text = str(value or "").strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text.lower()
        except ValueError:
            pass
    return fallback


def _rgb(value: str) -> tuple[int, int, int]:
    color = _safe_color(value)
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _shade(value: str, factor: float) -> str:
    r, g, b = _rgb(value)
    factor = max(0.32, min(1.28, factor))
    r = max(0, min(255, round(r * factor)))
    g = max(0, min(255, round(g * factor)))
    b = max(0, min(255, round(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / length for x in v)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _cross(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _camera_basis(component: dict[str, Any]) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    dims = [float(v) for v in (component.get("dimensions_mm") or [20, 20, 20])[:3]]
    while len(dims) < 3:
        dims.append(10.0)
    # A slightly elevated three-quarter view works for most assemblies. Long axial parts
    # receive a more diagonal view so shafts, lead screws, extrusion and rails read as
    # products rather than a circle/end-on silhouette.
    longest = max(range(3), key=lambda i: dims[i])
    if dims[longest] > max(1.0, sorted(dims)[1]) * 2.6:
        camera = (1.45, -1.7, 1.1) if longest == 2 else ((1.4, -1.1, 1.55) if longest == 0 else (1.1, -1.4, 1.55))
    else:
        camera = (1.45, -1.65, 1.25)
    forward = _normalize(camera)
    world_up = (0.0, 0.0, 1.0)
    right = _normalize(_cross(forward, world_up))
    up = _normalize(_cross(right, forward))
    return right, up, forward


def _mesh_for_component(component_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    component = component_registry.component_by_id(component_id)
    obj = component_registry.make_project_object(
        component_id,
        transform={"position": [0.0, 0.0, 0.0], "rotation_deg": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0]},
    )
    obj["id"] = f"thumbnail:{component_id}"
    dims = [abs(float(v)) for v in (component.get("dimensions_mm") or [20, 20, 20])[:3]]
    max_dim = max(dims or [20.0])
    tolerance = max(0.42, min(1.35, max_dim / 95.0))
    return component, core.tessellate(obj, tolerance=tolerance)


def _render_svg(component: dict[str, Any], mesh: dict[str, Any]) -> bytes:
    raw_positions = mesh.get("positions") or []
    triangles = mesh.get("triangles") or []
    if not raw_positions or not triangles:
        raise ValueError("Component tessellation returned no visible geometry")

    positions: list[tuple[float, float, float]] = [tuple(float(v) for v in point[:3]) for point in raw_positions]
    right, up, forward = _camera_basis(component)
    projected = [(_dot(point, right), _dot(point, up), _dot(point, forward)) for point in positions]
    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    scale = min((WIDTH - PADDING * 2) / span_x, (HEIGHT - PADDING * 2) / span_y)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    screen: list[tuple[float, float, float]] = [
        (WIDTH / 2 + (x - center_x) * scale, HEIGHT / 2 - (y - center_y) * scale, depth)
        for x, y, depth in projected
    ]

    colors = mesh.get("triangle_colors") or []
    default_color = _safe_color(mesh.get("color"), "#8795a1")
    light = _normalize((0.35, -0.55, 0.76))
    faces: list[tuple[float, str, str]] = []
    for index, triangle in enumerate(triangles):
        if len(triangle) != 3:
            continue
        try:
            ia, ib, ic = (int(triangle[0]), int(triangle[1]), int(triangle[2]))
            a, b, c = positions[ia], positions[ib], positions[ic]
            sa, sb, sc = screen[ia], screen[ib], screen[ic]
        except (ValueError, TypeError, IndexError):
            continue
        normal = _normalize(_cross(_sub(b, a), _sub(c, a)))
        diffuse = abs(_dot(normal, light))
        camera_face = abs(_dot(normal, forward))
        factor = 0.57 + 0.34 * diffuse + 0.10 * camera_face
        base = _safe_color(colors[index] if index < len(colors) else default_color, default_color)
        fill = _shade(base, factor)
        points = f"{sa[0]:.2f},{sa[1]:.2f} {sb[0]:.2f},{sb[1]:.2f} {sc[0]:.2f},{sc[1]:.2f}"
        depth = (sa[2] + sb[2] + sc[2]) / 3
        faces.append((depth, fill, points))

    if not faces:
        raise ValueError("Component thumbnail projection returned no faces")
    faces.sort(key=lambda row: row[0])

    # Extremely detailed supplier CAD can contain many thousands of viewport triangles.
    # A 360 px catalog thumbnail cannot resolve all of them. Keep a stable bounded SVG
    # size while preserving the full geometry in the actual CAD scene.
    max_faces = 2600
    if len(faces) > max_faces:
        step = len(faces) / max_faces
        faces = [faces[min(len(faces) - 1, int(i * step))] for i in range(max_faces)]

    polygons = "".join(
        f'<polygon points="{points}" fill="{fill}" stroke="#27313a" stroke-opacity="0.18" stroke-width="0.42"/>'
        for _, fill, points in faces
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<defs><filter id="shadow" x="-30%" y="-30%" width="160%" height="180%">'
        '<feDropShadow dx="0" dy="6" stdDeviation="5" flood-color="#15202a" flood-opacity="0.18"/>'
        '</filter></defs>'
        f'<rect width="{WIDTH}" height="{HEIGHT}" rx="18" fill="#f2f5f6"/>'
        f'<g filter="url(#shadow)">{polygons}</g>'
        '</svg>'
    ).encode("utf-8")


def render_component_thumbnail(component_id: str, cache_dir: Path) -> tuple[bytes, str]:
    component = component_registry.component_by_id(component_id)
    digest = _fingerprint(component)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{sha256(component_id.encode('utf-8')).hexdigest()[:16]}-{digest}.svg"
    if cache_path.is_file():
        return cache_path.read_bytes(), digest

    component, mesh = _mesh_for_component(component_id)
    rendered = _render_svg(component, mesh)
    temp_path = cache_path.with_suffix(".tmp")
    temp_path.write_bytes(rendered)
    temp_path.replace(cache_path)

    # Geometry revisions naturally create new fingerprints. Remove only stale versions
    # of this exact component so the cache cannot grow forever across model improvements.
    prefix = sha256(component_id.encode("utf-8")).hexdigest()[:16] + "-"
    for stale in cache_dir.glob(f"{prefix}*.svg"):
        if stale != cache_path:
            try:
                stale.unlink()
            except OSError:
                pass
    return rendered, digest
