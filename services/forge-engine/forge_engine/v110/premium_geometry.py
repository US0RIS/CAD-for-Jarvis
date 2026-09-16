from __future__ import annotations

"""Premium offline geometry for broad ForgeCAD catalog coverage.

Manufacturer CAD and part-specific builders still win.  This module supplies
family-correct parametric geometry for the rest of the built-in catalog, and a
safe optional Ollama detail pass.  The local model can only add validated visual
primitives; it never executes generated Python or changes authoritative dimensions.
"""

import json
import math
import os
import re
import threading
import urllib.request
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import cadquery as cq

from . import component_registry as registry

_DETAIL_DIR = registry.ASSET_DIR / "generated-details"
_DETAIL_VERSION = 1
_DETAIL_LOCK = threading.RLock()
_DETAIL_QUEUED: set[str] = set()
_DETAIL_FAILED: set[str] = set()
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _spec(c: dict[str, Any], key: str, default: Any = None) -> Any:
    for source in (c.get("specs") or {}, c.get("legacy") or {}, c):
        if key in source and source[key] is not None:
            return source[key]
    return default


def _dims(c: dict[str, Any]) -> tuple[float, float, float]:
    vals = [float(v) for v in (c.get("dimensions_mm") or [20, 20, 20])[:3]]
    while len(vals) < 3:
        vals.append(10.0)
    return max(vals[0], 0.2), max(vals[1], 0.2), max(vals[2], 0.2)


def _box(x: float, y: float, z: float, color: str, center=(0.0, 0.0, 0.0), radius: float = 0.0):
    cx, cy, cz = (float(v) for v in center)
    wp = cq.Workplane("XY").workplane(offset=cz - z / 2).box(x, y, z, centered=(True, True, False))
    if radius > 0:
        try:
            wp = wp.edges("|Z").fillet(min(radius, x / 2 - 0.01, y / 2 - 0.01))
        except Exception:
            pass
    return wp.val().translate((cx, cy, 0)), color


def _cyl(d: float, h: float, color: str, center=(0.0, 0.0, 0.0), axis: str = "z"):
    cx, cy, cz = (float(v) for v in center)
    half = max(float(h), 0.02) / 2.0
    if axis == "x":
        shape = cq.Workplane("YZ").circle(d / 2).extrude(half, both=True).val()
    elif axis == "y":
        shape = cq.Workplane("XZ").circle(d / 2).extrude(half, both=True).val()
    else:
        shape = cq.Workplane("XY").circle(d / 2).extrude(half, both=True).val()
    return shape.translate((cx, cy, cz)), color


def _ring(od: float, bore: float, h: float, color: str, center=(0.0, 0.0, 0.0), axis: str = "z"):
    cx, cy, cz = (float(v) for v in center)
    od = max(float(od), 0.4)
    bore = min(max(float(bore), 0.0), od - 0.2)
    half = max(float(h), 0.02) / 2.0
    if axis == "x":
        wp = cq.Workplane("YZ").circle(od / 2)
    elif axis == "y":
        wp = cq.Workplane("XZ").circle(od / 2)
    else:
        wp = cq.Workplane("XY").circle(od / 2)
    if bore > 0:
        wp = wp.circle(bore / 2)
    return wp.extrude(half, both=True).val().translate((cx, cy, cz)), color


def _hex(af: float, h: float, color: str, bore: float = 0.0, center=(0.0, 0.0, 0.0)):
    cx, cy, cz = (float(v) for v in center)
    radius = max(float(af), 0.5) / math.sqrt(3)
    wp = cq.Workplane("XY").polygon(6, radius)
    if bore > 0:
        wp = wp.circle(float(bore) / 2)
    shape = wp.extrude(max(float(h), 0.02) / 2, both=True).val().translate((cx, cy, cz))
    return shape, color


def _cut_cyl(shape, diameter: float, depth: float, center=(0.0, 0.0, 0.0), axis="z"):
    tool = _cyl(diameter, depth, "#000000", center, axis)[0]
    try:
        return shape.cut(tool)
    except Exception:
        return shape


def _pcb(c: dict[str, Any]):
    x, y, z = _dims(c)
    board_h = min(1.6, max(0.8, z * 0.16))
    board, _ = _box(x, y, board_h, "#167a3b", radius=min(2.5, min(x, y) * 0.05))
    hole_d = max(1.6, min(3.2, min(x, y) * 0.055))
    inset = min(x, y) * 0.09
    for px in (-x / 2 + inset, x / 2 - inset):
        for py in (-y / 2 + inset, y / 2 - inset):
            board = _cut_cyl(board, hole_d, board_h + 3, (px, py, 0))
    parts = [(board, "#167a3b")]
    chip_z = board_h / 2 + 0.8
    parts += [
        _box(min(18, x * 0.28), min(18, y * 0.32), 1.5, "#202327", (0, 0, chip_z), 0.35),
        _box(min(8, x * 0.15), min(8, y * 0.18), 1.2, "#2d3135", (-x * 0.22, y * 0.12, chip_z), 0.25),
        _box(min(10, x * 0.18), min(9, y * 0.22), min(7, max(3, z * 0.5)), "#b8bec3", (x * 0.40, -y * 0.12, board_h / 2 + min(7, z * 0.5) / 2), 0.5),
    ]
    pins = []
    count = max(4, min(20, int(x / 3)))
    for i in range(count):
        pin, _ = _box(0.65, 0.65, min(7, max(3, z * 0.55)), "#d4a72a", (-x * 0.35 + i * (x * 0.7 / max(1, count - 1)), y * 0.40, board_h / 2 + 2.5))
        pins.append(pin)
    if pins:
        parts.append((cq.Compound.makeCompound(pins), "#d4a72a"))
    return parts


def _shaft(c: dict[str, Any]):
    d = float(_spec(c, "diameter_mm", _dims(c)[0]))
    length = float(_spec(c, "length_mm", _dims(c)[2]))
    shape = _cyl(d, length, "#c6c9cb")[0]
    try:
        shape = cq.Workplane(obj=shape).edges("%Circle").chamfer(min(0.35, d * 0.06)).val()
    except Exception:
        pass
    return [(shape, "#c6c9cb")]


def _bearing(c: dict[str, Any]):
    x, y, z = _dims(c)
    tags = {str(t) for t in c.get("tags", [])}
    bore = float(_spec(c, "bore_mm", max(2, min(x, y) * 0.38)))
    od = float(_spec(c, "outer_diameter_mm", min(x, y)))
    width = float(_spec(c, "width_mm", z))
    if "pillow-block" in tags:
        body, _ = _box(x, y, z * 0.62, "#8e969d", (0, 0, -z * 0.10), min(3, y * 0.18))
        body = _cut_cyl(body, bore * 1.12, y + 4, (0, 0, z * 0.04), "y")
        feet, _ = _box(x * 1.05, y * 1.18, z * 0.20, "#828a91", (0, 0, -z * 0.36), 1.5)
        for px in (-x * 0.36, x * 0.36):
            feet = _cut_cyl(feet, max(3, bore * 0.28), z + 4, (px, 0, -z * 0.36))
        insert = _ring(od, bore, min(width, z * 0.55), "#b8bec3", (0, 0, z * 0.04), "y")
        return [(body, "#8e969d"), (feet, "#828a91"), insert]
    outer = _ring(od, bore, width, "#b5bbc0")
    race = _ring(od * 0.78, bore * 1.16, width * 1.02, "#747b82")
    seal1 = _ring(od * 0.90, bore * 1.25, max(0.45, width * 0.08), "#3f4449", (0, 0, width * 0.45))
    seal2 = _ring(od * 0.90, bore * 1.25, max(0.45, width * 0.08), "#3f4449", (0, 0, -width * 0.45))
    if "flanged" in tags:
        flange = _ring(od * 1.18, bore, max(0.8, width * 0.16), "#aeb4b9", (0, 0, -width * 0.42))
        return [outer, race, seal1, seal2, flange]
    return [outer, race, seal1, seal2]


def _linear_bearing(c: dict[str, Any]):
    od, _, length = _dims(c)
    bore = float(_spec(c, "bore_mm", od * 0.55))
    tags = {str(t) for t in c.get("tags", [])}
    if "pillow" in tags:
        body, _ = _box(od * 2.2, od * 1.45, length * 0.72, "#8c9399", radius=min(2.5, od * 0.12))
        body = _cut_cyl(body, bore, od * 2, (0, 0, 0), "x")
        return [(body, "#8c9399"), _ring(od * 0.95, bore, length * 0.64, "#b8bdc2", axis="x")]
    sleeve = _ring(od, bore, length, "#b7bdc2")
    seals = [_ring(od * 1.02, bore * 1.02, max(0.8, length * 0.08), "#3c4146", (0, 0, length * 0.44)), _ring(od * 1.02, bore * 1.02, max(0.8, length * 0.08), "#3c4146", (0, 0, -length * 0.44))]
    if "flanged" in tags:
        flange = _ring(od * 1.6, bore, max(1.2, length * 0.10), "#aeb4b9", (0, 0, -length * 0.42))
        return [sleeve, *seals, flange]
    return [sleeve, *seals]


def _lead_screw(c: dict[str, Any]):
    d = float(_spec(c, "diameter_mm", _dims(c)[0]))
    length = float(_spec(c, "length_mm", _dims(c)[2]))
    pitch = float(_spec(c, "pitch_mm", max(2, d * 0.4)))
    shaft = _cyl(max(0.4, d - min(1.0, pitch * 0.12)), length, "#aeb4b9")
    parts = [shaft]
    ring_count = min(28, max(8, int(length / max(pitch * 4, 1))))
    for i in range(ring_count):
        z = -length * 0.46 + i * (length * 0.92 / max(1, ring_count - 1))
        parts.append(_ring(d, max(0.2, d - min(1.2, pitch * 0.18)), min(0.45, pitch * 0.16), "#c4c8cb", (0, 0, z)))
    return parts


def _coupler(c: dict[str, Any]):
    od, _, length = _dims(c)
    a = float(_spec(c, "bore_a_mm", od * 0.28))
    b = float(_spec(c, "bore_b_mm", a))
    tags = {str(t) for t in c.get("tags", [])}
    bore = max(a, b)
    body = _ring(od, bore, length, "#a8afb5")
    parts = [body, _ring(od * 1.02, bore, max(0.7, length * 0.08), "#7e858c", (0, 0, length * 0.42)), _ring(od * 1.02, bore, max(0.7, length * 0.08), "#7e858c", (0, 0, -length * 0.42))]
    if "jaw" in tags:
        spider = _ring(od * 0.72, bore * 1.1, length * 0.14, "#d24c42")
        parts.append(spider)
    elif "beam" in tags:
        for z in (-length * 0.24, -length * 0.08, length * 0.08, length * 0.24):
            parts.append(_ring(od * 1.01, od * 0.83, max(0.55, length * 0.035), "#656c73", (0, 0, z)))
    # Two radial set screws make rigid couplers read correctly even at small scale.
    parts.append(_cyl(max(1.2, od * 0.12), od * 0.32, "#555b61", (od * 0.42, 0, -length * 0.24), "x"))
    parts.append(_cyl(max(1.2, od * 0.12), od * 0.32, "#555b61", (0, od * 0.42, length * 0.24), "y"))
    return parts


def _pulley(c: dict[str, Any]):
    od, _, width = _dims(c)
    teeth = int(_spec(c, "teeth", 20))
    bore = float(_spec(c, "bore_mm", max(3, od * 0.22)))
    pitch = float(_spec(c, "pitch_mm", 2))
    root = max(bore + 2, od - max(1.0, pitch * 0.8))
    parts = [_ring(root, bore, width * 0.72, "#aeb4b9"), _ring(od * 1.03, bore, max(0.8, width * 0.09), "#c0c5c9", (0, 0, width * 0.45)), _ring(od * 1.03, bore, max(0.8, width * 0.09), "#c0c5c9", (0, 0, -width * 0.45))]
    tooth_w = max(0.55, math.pi * od / max(teeth, 1) * 0.45)
    for i in range(teeth):
        angle = 360.0 * i / teeth
        tooth, _ = _box(max(0.8, pitch * 0.65), tooth_w, width * 0.58, "#8f969c", ((root / 2 + od / 2) / 2, 0, 0), 0.12)
        parts.append((tooth.rotate((0, 0, 0), (0, 0, 1), angle), "#8f969c"))
    return parts


def _gear(c: dict[str, Any]):
    od, _, width = _dims(c)
    teeth = int(_spec(c, "teeth", 20))
    module = float(_spec(c, "module", 1.0))
    bore = float(_spec(c, "bore_mm", max(3, od * 0.18)))
    root_d = max(bore + 2, od - max(1.2, 2.2 * module))
    parts = [_ring(root_d, bore, width, "#9da4aa")]
    tooth_depth = max(0.8, (od - root_d) / 2 + module * 0.25)
    tooth_tan = max(0.6, math.pi * root_d / max(teeth, 1) * 0.44)
    for i in range(teeth):
        angle = 360.0 * i / teeth
        tooth, _ = _box(tooth_depth, tooth_tan, width * 0.92, "#aeb4b9", (root_d / 2 + tooth_depth / 2 - 0.15, 0, 0), 0.10)
        parts.append((tooth.rotate((0, 0, 0), (0, 0, 1), angle), "#aeb4b9"))
    return parts


def _extrusion(c: dict[str, Any]):
    w, h, length = _dims(c)
    body, _ = _box(w, h, length, "#aeb4b9", radius=min(1.0, min(w, h) * 0.04))
    center_d = max(3.5, min(w, h) * 0.22)
    body = _cut_cyl(body, center_d, length + 4)
    slot = max(3.5, min(w, h) * 0.18)
    depth = max(2.5, min(w, h) * 0.19)
    tools = [
        _box(slot, h + 4, length + 4, "#000", (0, h / 2 - depth / 2, 0))[0],
        _box(slot, h + 4, length + 4, "#000", (0, -h / 2 + depth / 2, 0))[0],
        _box(w + 4, slot, length + 4, "#000", (w / 2 - depth / 2, 0, 0))[0],
        _box(w + 4, slot, length + 4, "#000", (-w / 2 + depth / 2, 0, 0))[0],
    ]
    for tool in tools:
        try:
            body = body.cut(tool)
        except Exception:
            pass
    return [(body, "#aeb4b9")]


def _spring(c: dict[str, Any]):
    od = float(_spec(c, "outer_diameter_mm", _dims(c)[0]))
    length = float(_spec(c, "free_length_mm", _dims(c)[2]))
    wire = max(0.45, min(2.2, od * 0.10))
    radius = max(wire * 1.4, od / 2 - wire / 2)
    pitch = max(wire * 1.55, length / max(5, int(length / max(wire * 2.5, 1))))
    try:
        helix = cq.Wire.makeHelix(pitch, length, radius, center=cq.Vector(0, 0, -length / 2), dir=cq.Vector(0, 0, 1))
        profile = cq.Workplane("XZ").center(radius, -length / 2).circle(wire / 2)
        shape = profile.sweep(helix, isFrenet=True).val()
        return [(shape, "#b9bec2")]
    except Exception:
        parts = []
        for i in range(10):
            z = -length * 0.45 + i * length * 0.09
            parts.append(_ring(od, od - wire * 2, wire * 0.55, "#b9bec2", (0, 0, z)))
        return parts


def _magnet(c: dict[str, Any]):
    d, _, h = _dims(c)
    return [_cyl(d, h, "#9da4aa")]


def _nut(c: dict[str, Any]):
    af, _, h = _dims(c)
    d = float(_spec(c, "diameter_mm", af * 0.5))
    return [_hex(af, h, "#aeb4b9", d)]


def _washer(c: dict[str, Any]):
    od, _, h = _dims(c)
    d = float(_spec(c, "diameter_mm", od * 0.45))
    return [_ring(od, d * 1.08, h, "#b8bdc1")]


def _insert(c: dict[str, Any]):
    od, _, length = _dims(c)
    d = float(_spec(c, "diameter_mm", od * 0.55))
    parts = [_ring(od * 0.92, d, length, "#c49a45")]
    for z in (-length * 0.32, -length * 0.12, length * 0.12, length * 0.32):
        parts.append(_ring(od, d, max(0.35, length * 0.07), "#d6ad5d", (0, 0, z)))
    return parts


def _standoff(c: dict[str, Any]):
    af, _, length = _dims(c)
    d = float(_spec(c, "diameter_mm", af * 0.5))
    return [_hex(af, length, "#b7bdc2", d)]


def _dc_motor(c: dict[str, Any]):
    d, _, length = _dims(c)
    can = _cyl(d, length * 0.78, "#9aa1a7", (0, 0, -length * 0.08))
    front = _cyl(d * 0.92, length * 0.08, "#c0c5c9", (0, 0, length * 0.35))
    rear = _cyl(d * 0.94, length * 0.08, "#555b61", (0, 0, -length * 0.47))
    shaft = _cyl(max(1.5, d * 0.12), length * 0.34, "#c9cdd0", (0, 0, length * 0.53))
    terminals = [_box(max(1.2, d * 0.08), max(0.8, d * 0.05), length * 0.12, "#d3a64f", (-d * 0.18, 0, -length * 0.54)), _box(max(1.2, d * 0.08), max(0.8, d * 0.05), length * 0.12, "#d3a64f", (d * 0.18, 0, -length * 0.54))]
    return [can, front, rear, shaft, *terminals]


def _gearmotor(c: dict[str, Any]):
    d, _, length = _dims(c)
    parts = list(_dc_motor({**deepcopy(c), "dimensions_mm": [d, d, length * 0.62]}))
    parts += [_cyl(d * 1.05, length * 0.30, "#b1b7bc", (0, 0, length * 0.34)), _cyl(max(2, d * 0.14), length * 0.26, "#c8cccf", (0, 0, length * 0.62))]
    return parts


def _bldc(c: dict[str, Any]):
    d, _, length = _dims(c)
    rotor = _ring(d, max(3, d * 0.22), length * 0.70, "#5f666c")
    bell = _cyl(d * 0.96, length * 0.08, "#8e969c", (0, 0, length * 0.35))
    stator = _ring(d * 0.74, d * 0.32, length * 0.48, "#c68e35", (0, 0, -length * 0.05))
    base = _cyl(d * 0.86, length * 0.10, "#aeb4b9", (0, 0, -length * 0.40))
    shaft = _cyl(max(2, d * 0.10), length * 0.48, "#c8cccf", (0, 0, length * 0.36))
    return [rotor, bell, stator, base, shaft]


def _relay(c: dict[str, Any]):
    x, y, z = _dims(c)
    body, _ = _box(x, y, z * 0.78, "#315f9a", (0, 0, z * 0.11), min(1.5, min(x, y) * 0.06))
    base, _ = _box(x * 0.94, y * 0.92, z * 0.12, "#25292d", (0, 0, -z * 0.34), 0.5)
    pins = []
    for px in (-x * 0.30, 0, x * 0.30):
        for py in (-y * 0.30, y * 0.30):
            pins.append(_box(max(0.6, x * 0.025), max(0.6, y * 0.03), z * 0.24, "#c6c9cb", (px, py, -z * 0.48))[0])
    return [(body, "#315f9a"), (base, "#25292d"), (cq.Compound.makeCompound(pins), "#c6c9cb")]


def _switch(c: dict[str, Any]):
    x, y, z = _dims(c)
    tags = {str(t) for t in c.get("tags", [])}
    body, _ = _box(x * 0.82, y * 0.88, z * 0.55, "#25282c", (0, 0, -z * 0.08), min(1.2, min(x, y) * 0.08))
    parts = [(body, "#25282c")]
    if "toggle" in tags:
        parts += [_cyl(min(x, y) * 0.34, z * 0.18, "#aeb4b9", (0, 0, z * 0.28)), _cyl(max(2, min(x, y) * 0.13), z * 0.42, "#c6c9cb", (0, 0, z * 0.50))]
    elif "pushbutton" in tags:
        parts += [_cyl(min(x, y) * 0.72, z * 0.24, "#b9bec2", (0, 0, z * 0.30)), _cyl(min(x, y) * 0.55, z * 0.18, "#c7443c", (0, 0, z * 0.48))]
    elif "rocker" in tags:
        rocker, _ = _box(x * 0.74, y * 0.74, z * 0.22, "#34383c", (0, 0, z * 0.27), 1.2)
        parts.append((rocker.rotate((0, 0, 0), (1, 0, 0), -9), "#34383c"))
    else:
        lever, _ = _box(x * 0.92, max(1.2, y * 0.12), max(0.8, z * 0.07), "#b8bdc1", (x * 0.30, 0, z * 0.30), 0.4)
        parts.append((lever.rotate((0, 0, 0), (0, 1, 0), 14), "#b8bdc1"))
        parts.append(_cyl(max(1.8, y * 0.20), max(1.0, y * 0.18), "#c3c7ca", (x * 0.72, 0, z * 0.48), "y"))
    return parts


def _connector(c: dict[str, Any]):
    x, y, z = _dims(c)
    pins = int(_spec(c, "pin_count", max(2, int(x / max(2, float(_spec(c, "pitch_mm", 2.54)))))))
    pitch = float(_spec(c, "pitch_mm", 2.54))
    housing, _ = _box(x, y, z * 0.74, "#ece8dd", (0, 0, z * 0.10), min(0.8, y * 0.08))
    cavity, _ = _box(max(1, x - 2.0), max(1, y * 0.48), z * 0.36, "#000000", (0, -y * 0.12, z * 0.20), 0.3)
    try:
        housing = housing.cut(cavity)
    except Exception:
        pass
    pin_shapes = []
    start = -(pins - 1) * pitch / 2
    for i in range(pins):
        pin_shapes.append(_box(0.65, 0.65, z * 0.65, "#c8a74a", (start + i * pitch, 0, -z * 0.30))[0])
    return [(housing, "#ece8dd"), (cq.Compound.makeCompound(pin_shapes), "#c8a74a")]


def _display(c: dict[str, Any]):
    x, y, z = _dims(c)
    board, _ = _box(x, y, min(1.6, z * 0.26), "#1766a6", (0, 0, -z * 0.34), min(1.4, min(x, y) * 0.04))
    bezel, _ = _box(x * 0.88, y * 0.82, z * 0.32, "#17191c", (0, 0, -z * 0.05), 1.0)
    screen, _ = _box(x * 0.82, y * 0.74, max(0.35, z * 0.08), "#173142", (0, 0, z * 0.13), 0.5)
    header, _ = _box(min(x * 0.55, 28), min(4, y * 0.12), z * 0.26, "#16191c", (0, -y * 0.43, -z * 0.12), 0.2)
    return [(board, "#1766a6"), (bezel, "#17191c"), (screen, "#173142"), (header, "#16191c")]


def _camera(c: dict[str, Any]):
    x, y, z = _dims(c)
    board, _ = _box(x, y, min(1.6, z * 0.18), "#1766a6", (0, 0, -z * 0.38), 1.0)
    parts = [(board, "#1766a6"), _cyl(min(x, y) * 0.48, z * 0.48, "#25292d", (0, 0, -z * 0.02)), _cyl(min(x, y) * 0.30, z * 0.34, "#111417", (0, 0, z * 0.30)), _cyl(min(x, y) * 0.19, max(0.5, z * 0.05), "#334e61", (0, 0, z * 0.49))]
    parts.append(_box(min(10, x * 0.36), min(5, y * 0.20), max(1.2, z * 0.12), "#ede8dd", (0, -y * 0.37, -z * 0.27), 0.3))
    return parts


def _power(c: dict[str, Any]):
    x, y, z = _dims(c)
    board, _ = _box(x, y, min(1.6, z * 0.15), "#1766a6", (0, 0, -z * 0.39), 1.0)
    parts = [(board, "#1766a6")]
    parts += [_box(min(14, x * 0.24), min(14, y * 0.34), min(7, z * 0.46), "#303438", (-x * 0.08, 0, -z * 0.08), 1.0), _cyl(min(8, y * 0.22), min(10, z * 0.52), "#444a50", (x * 0.28, y * 0.18, -z * 0.06)), _cyl(min(7, y * 0.20), min(9, z * 0.48), "#555c62", (x * 0.28, -y * 0.18, -z * 0.08))]
    parts += [_connector({"dimensions_mm": [min(14, x * 0.24), min(9, y * 0.30), min(8, z * 0.46)], "specs": {"pin_count": 2, "pitch_mm": 5.08}})[0], _box(min(8, x * 0.14), min(8, y * 0.22), min(2, z * 0.16), "#25282b", (x * 0.02, -y * 0.24, -z * 0.24), 0.3)]
    return parts


def _pump(c: dict[str, Any]):
    x, y, z = _dims(c)
    motor_d = min(y, z) * 0.70
    parts = [_cyl(motor_d, x * 0.48, "#9da4aa", (-x * 0.18, 0, 0), "x")]
    head, _ = _box(x * 0.34, y * 0.82, z * 0.84, "#25292d", (x * 0.28, 0, 0), min(2, y * 0.08))
    parts.append((head, "#25292d"))
    parts += [_cyl(max(3, y * 0.16), x * 0.20, "#30353a", (x * 0.48, y * 0.24, 0), "x"), _cyl(max(3, y * 0.16), y * 0.26, "#30353a", (x * 0.24, y * 0.50, 0), "y")]
    return parts


def _valve(c: dict[str, Any]):
    x, y, z = _dims(c)
    port = float(_spec(c, "port_diameter_mm", max(3, min(x, y) * 0.18)))
    body, _ = _box(x * 0.72, y * 0.82, z * 0.34, "#8d949a", (0, 0, -z * 0.24), min(2, y * 0.08))
    coil, _ = _box(x * 0.58, y * 0.60, z * 0.42, "#25292d", (0, 0, z * 0.16), 2.0)
    return [(body, "#8d949a"), (coil, "#25292d"), _ring(port * 1.55, port, x * 0.28, "#aeb4b9", (x * 0.42, 0, -z * 0.24), "x"), _ring(port * 1.55, port, x * 0.28, "#aeb4b9", (-x * 0.42, 0, -z * 0.24), "x")]


def _enclosure(c: dict[str, Any]):
    x, y, z = _dims(c)
    wall = max(1.2, min(3.0, min(x, y, z) * 0.06))
    outer, _ = _box(x, y, z * 0.82, "#60676d", (0, 0, -z * 0.08), min(4, min(x, y) * 0.04))
    inner, _ = _box(max(1, x - 2 * wall), max(1, y - 2 * wall), z * 0.72, "#000", (0, 0, z * 0.02), max(0.5, min(3, min(x, y) * 0.03)))
    try:
        outer = outer.cut(inner)
    except Exception:
        pass
    lid, _ = _box(x * 0.98, y * 0.98, wall, "#737b82", (0, 0, z * 0.42), min(3, min(x, y) * 0.035))
    screws = []
    for px in (-x * 0.42, x * 0.42):
        for py in (-y * 0.42, y * 0.42):
            screws.append(_cyl(max(1.5, wall * 0.75), wall * 0.45, "#b7bdc2", (px, py, z * 0.43))[0])
    return [(outer, "#60676d"), (lid, "#737b82"), (cq.Compound.makeCompound(screws), "#b7bdc2")]


def _belt(c: dict[str, Any]):
    length, width, thickness = _dims(c)
    r = max(width * 1.2, length / (2 * math.pi + 4.0))
    straight = max(r * 1.4, length / 2 - math.pi * r)
    outer_r = r + width / 2
    inner_r = max(0.5, r - width / 2)
    left = _ring(outer_r * 2, inner_r * 2, thickness, "#25282b", (-straight / 2, 0, 0))[0]
    right = _ring(outer_r * 2, inner_r * 2, thickness, "#25282b", (straight / 2, 0, 0))[0]
    top, _ = _box(straight, width, thickness, "#25282b", (0, r, 0), width * 0.20)
    bottom, _ = _box(straight, width, thickness, "#25282b", (0, -r, 0), width * 0.20)
    return [(left, "#25282b"), (right, "#25282b"), (top, "#25282b"), (bottom, "#25282b")]


_BUILDERS: dict[str, Callable[[dict[str, Any]], list[tuple[Any, str]]]] = {
    "shaft": _shaft,
    "bearing": _bearing,
    "linear_bearing": _linear_bearing,
    "lead_screw": _lead_screw,
    "coupler": _coupler,
    "pulley": _pulley,
    "gear": _gear,
    "belt": _belt,
    "extrusion": _extrusion,
    "spring": _spring,
    "magnet": _magnet,
    "nut": _nut,
    "washer": _washer,
    "insert": _insert,
    "standoff": _standoff,
    "dc_motor": _dc_motor,
    "gearmotor": _gearmotor,
    "bldc_motor": _bldc,
    "switch": _switch,
    "relay": _relay,
    "connector": _connector,
    "display": _display,
    "camera": _camera,
    "power": _power,
    "pump": _pump,
    "valve": _valve,
    "enclosure": _enclosure,
    "compute": _pcb,
    "microcontroller": _pcb,
    "sensor": _pcb,
}


def supports(component: dict[str, Any]) -> bool:
    return str(component.get("category") or "") in _BUILDERS


def curated_seed_ids(limit: int = 100) -> tuple[str, ...]:
    groups: dict[str, list[str]] = defaultdict(list)
    for component in registry.all_components():
        if supports(component):
            groups[str(component.get("category"))].append(str(component.get("id")))
    for values in groups.values():
        values.sort()
    chosen: list[str] = []
    # Round-robin keeps the seed set diverse rather than spending all 100 on bearings.
    index = 0
    while len(chosen) < limit:
        added = False
        for category in sorted(groups):
            values = groups[category]
            if index < len(values):
                chosen.append(values[index])
                added = True
                if len(chosen) >= limit:
                    break
        if not added:
            break
        index += 1
    return tuple(chosen)


def _detail_path(component_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", component_id)
    return _DETAIL_DIR / f"{safe}.json"


def _validated_detail_recipe(component: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("details"), list):
        return []
    x, y, z = _dims(component)
    bounds = (x, y, z)
    out: list[dict[str, Any]] = []
    for raw in payload["details"][:16]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "")
        if kind not in {"box", "cylinder", "ring"}:
            continue
        center = raw.get("center") or [0, 0, 0]
        if not isinstance(center, list) or len(center) != 3:
            continue
        try:
            center = [float(v) for v in center]
        except Exception:
            continue
        if any(abs(center[i]) > bounds[i] * 0.62 + 3 for i in range(3)):
            continue
        color = str(raw.get("color") or "#8f969c")
        if not _HEX.match(color):
            color = "#8f969c"
        axis = str(raw.get("axis") or "z")
        if axis not in {"x", "y", "z"}:
            axis = "z"
        item: dict[str, Any] = {"kind": kind, "center": center, "color": color, "axis": axis}
        try:
            if kind == "box":
                size = [float(v) for v in raw.get("size", [])]
                if len(size) != 3 or any(v <= 0 for v in size) or any(size[i] > bounds[i] * 1.05 + 3 for i in range(3)):
                    continue
                item["size"] = size
                item["radius"] = max(0.0, min(float(raw.get("radius") or 0), min(size) * 0.25))
            else:
                diameter = float(raw.get("diameter") or 0)
                height = float(raw.get("height") or 0)
                if diameter <= 0 or height <= 0 or diameter > max(bounds) * 1.05 + 3 or height > max(bounds) * 1.05 + 3:
                    continue
                item["diameter"] = diameter
                item["height"] = height
                if kind == "ring":
                    bore = float(raw.get("bore") or 0)
                    if bore <= 0 or bore >= diameter:
                        continue
                    item["bore"] = bore
        except Exception:
            continue
        out.append(item)
    return out


def _render_details(details: list[dict[str, Any]]):
    parts = []
    for item in details:
        try:
            if item["kind"] == "box":
                sx, sy, sz = item["size"]
                parts.append(_box(sx, sy, sz, item["color"], item["center"], item.get("radius", 0)))
            elif item["kind"] == "cylinder":
                parts.append(_cyl(item["diameter"], item["height"], item["color"], item["center"], item["axis"]))
            elif item["kind"] == "ring":
                parts.append(_ring(item["diameter"], item["bore"], item["height"], item["color"], item["center"], item["axis"]))
        except Exception:
            continue
    return parts


def cached_details(component: dict[str, Any]):
    component_id = str(component.get("id") or "")
    if not component_id:
        return []
    path = _detail_path(component_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if payload.get("version") != _DETAIL_VERSION or payload.get("component_id") != component_id:
        return []
    return _render_details(_validated_detail_recipe(component, payload))


def _background_enabled() -> bool:
    if os.environ.get("CI"):
        return False
    value = os.environ.get("FORGECAD_BACKGROUND_GEOMETRY", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _refine_worker(component: dict[str, Any]) -> None:
    component_id = str(component.get("id") or "")
    try:
        x, y, z = _dims(component)
        model = os.environ.get("FORGECAD_OLLAMA_MODEL", "qwen3:8b")
        compact = {
            "id": component_id,
            "category": component.get("category"),
            "name": component.get("name"),
            "dimensions_mm": [x, y, z],
            "specs": component.get("specs") or {},
            "tags": component.get("tags") or [],
        }
        system = (
            "You add SMALL VISUAL DETAILS to an existing mechanical component model. Return JSON only as "
            "{\"details\":[...]}. Allowed detail kinds: box(size:[x,y,z],center:[x,y,z],radius,color), "
            "cylinder(diameter,height,center,axis,color), ring(diameter,bore,height,center,axis,color). "
            "Use millimeters centered on the existing component origin. Add 3-12 realistic secondary features such as "
            "pins, caps, seams, screws, terminals, hubs or housings. Do not replace the main body, do not change the "
            "authoritative overall dimensions, and do not invent a different product family."
        )
        body = json.dumps({
            "model": model,
            "stream": False,
            "think": False,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(compact)}],
            "options": {"temperature": 0.08, "num_predict": 900},
        }).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=75) as response:
            result = json.loads(response.read().decode("utf-8"))
        raw = str((result.get("message") or {}).get("content") or result.get("response") or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("No JSON detail recipe")
        details = _validated_detail_recipe(component, json.loads(raw[start:end + 1]))
        if len(details) < 2:
            raise ValueError("Detail recipe did not contain enough validated geometry")
        _DETAIL_DIR.mkdir(parents=True, exist_ok=True)
        _detail_path(component_id).write_text(json.dumps({"version": _DETAIL_VERSION, "component_id": component_id, "details": details}, indent=2), encoding="utf-8")
    except Exception:
        with _DETAIL_LOCK:
            _DETAIL_FAILED.add(component_id)
    finally:
        with _DETAIL_LOCK:
            _DETAIL_QUEUED.discard(component_id)


def queue_refinement(component: dict[str, Any]) -> None:
    if not _background_enabled() or not supports(component):
        return
    component_id = str(component.get("id") or "")
    if not component_id or component_id in curated_seed_ids() or _detail_path(component_id).is_file():
        return
    with _DETAIL_LOCK:
        if component_id in _DETAIL_QUEUED or component_id in _DETAIL_FAILED:
            return
        _DETAIL_QUEUED.add(component_id)
    threading.Thread(target=_refine_worker, args=(deepcopy(component),), name=f"ForgeCAD geometry {component_id}", daemon=True).start()


def component_parts(component: dict[str, Any]):
    builder = _BUILDERS.get(str(component.get("category") or ""))
    if not builder:
        return None
    try:
        parts = list(builder(component))
    except Exception:
        return None
    details = cached_details(component)
    queue_refinement(component)
    return parts + details


def refinement_state(component: dict[str, Any]) -> str:
    component_id = str(component.get("id") or "")
    if component_id in curated_seed_ids():
        return "seed"
    if _detail_path(component_id).is_file():
        return "cached"
    with _DETAIL_LOCK:
        if component_id in _DETAIL_QUEUED:
            return "generating"
        if component_id in _DETAIL_FAILED:
            return "family-only"
    return "eligible"


def install() -> None:
    """Patch realistic_components so exact vendor CAD keeps first priority."""
    from . import realistic_components

    if getattr(realistic_components, "_premium_geometry_installed", False):
        return
    original_parts = realistic_components.component_parts
    original_status = realistic_components.geometry_status

    def wrapped_parts(obj: dict[str, Any], component: dict[str, Any] | None = None, *, allow_download: bool = False):
        exact = original_parts(obj, component, allow_download=allow_download)
        if exact:
            return exact
        comp = component or {}
        return component_parts(comp)

    def wrapped_status(obj: dict[str, Any], component: dict[str, Any] | None = None) -> dict[str, Any]:
        status = original_status(obj, component)
        if status.get("resolved"):
            return status
        comp = component or {}
        if supports(comp):
            component_id = str(obj.get("component_ref") or comp.get("id") or "")
            seed = component_id in curated_seed_ids()
            return {
                "component_id": component_id,
                "resolved": True,
                "geometry_source": "forgecad_derived",
                "geometry_fidelity": "detailed_parametric",
                "asset": str(_detail_path(component_id)) if _detail_path(component_id).is_file() else None,
                "fallback": False,
                "geometry_model": "curated_seed" if seed else "family_parametric",
                "background_refinement": refinement_state(comp),
            }
        return status

    realistic_components.component_parts = wrapped_parts
    realistic_components.geometry_status = wrapped_status
    realistic_components._premium_geometry_installed = True
