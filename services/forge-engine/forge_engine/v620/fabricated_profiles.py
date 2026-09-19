from __future__ import annotations

"""Editable *fabricated* mechanical primitives, not purchased-component CAD.

These are parameter-driven starting geometries for packaging and prototyping. They
carry no implied material strength, pressure rating, load capacity, or physical
verification. Purchased SKU geometry must still come from the component registry.
"""

import math
from typing import Any

import cadquery as cq


PROFILE_LIBRARY: dict[str, dict[str, Any]] = {
    "hollow_tube": {
        "description": "Straight open-ended tube or bushing, centered on Z.",
        "params": {"outer_diameter": 16.0, "inner_diameter": 12.0, "length": 30.0},
    },
    "flanged_spool": {
        "description": "Two-flange reel with hollow winding core, centered on Z.",
        "params": {"core_diameter": 20.0, "flange_diameter": 36.0,
                   "bore_diameter": 5.0, "winding_width": 24.0, "flange_thickness": 2.0},
    },
    "tapered_nozzle": {
        "description": "Hollow straight-taper transition, centered on Z; not pressure rated.",
        "params": {"inlet_diameter": 15.0, "outlet_diameter": 8.0,
                   "length": 25.0, "wall_thickness": 1.5},
    },
    "split_cuff": {
        "description": "Open circular band for layout only; not sized to a real wearer.",
        "params": {"outer_diameter": 70.0, "inner_diameter": 62.0,
                   "width": 24.0, "opening_angle_deg": 48.0},
    },
    "guide_eyelet": {
        "description": "Rectangular centered cable guide with through-bore along Z.",
        "params": {"width": 22.0, "depth": 16.0, "thickness": 4.0,
                   "hole_diameter": 7.0},
    },
    "u_bracket": {
        "description": "U-shaped sheet-like bracket with open top and ends.",
        "params": {"outer_width": 40.0, "depth": 28.0,
                   "height": 22.0, "wall_thickness": 3.0},
    },
    "cartridge_cup": {
        "description": "Open cylindrical cup with solid base; not a pressure vessel.",
        "params": {"outer_diameter": 26.0, "inner_diameter": 20.0,
                   "height": 38.0, "base_thickness": 3.0},
    },
}


def _number(params: dict[str, Any], key: str) -> float:
    try:
        value = float(params[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Fabricated profile requires numeric {key}") from exc
    if not math.isfinite(value) or value <= 0.0 or value > 100000.0:
        raise ValueError(f"Fabricated profile {key} must be finite and positive")
    return value


def _tube(outer_d: float, inner_d: float, length: float):
    if inner_d >= outer_d:
        raise ValueError("Tube inner diameter must be smaller than outer diameter")
    return (
        cq.Workplane("XY")
        .workplane(offset=-length / 2)
        .circle(outer_d / 2)
        .circle(inner_d / 2)
        .extrude(length)
        .val()
    )


def shape_for(obj: dict[str, Any]):
    """Return a B-rep for a known fabricated kind, or None for other kinds.

    All dimensional parameters are millimeters. The origin is the bounding
    envelope center; standard ForgeCAD transforms/features apply afterwards.
    """
    kind = str(obj.get("kind") or "")
    if kind not in PROFILE_LIBRARY:
        return None
    params = obj.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"Fabricated profile {kind} parameters must be an object")
    p = {name: _number(params, name) for name in PROFILE_LIBRARY[kind]["params"]}

    if kind == "hollow_tube":
        return _tube(p["outer_diameter"], p["inner_diameter"], p["length"])

    if kind == "flanged_spool":
        core, flange, bore = (p["core_diameter"], p["flange_diameter"], p["bore_diameter"])
        width, thick = p["winding_width"], p["flange_thickness"]
        if not bore < core < flange:
            raise ValueError("Spool requires bore < core < flange diameters")
        shape = _tube(core, bore, width)
        for z in (-width / 2 - thick, width / 2):
            flange_shape = (
                cq.Workplane("XY").workplane(offset=z)
                .circle(flange / 2).circle(bore / 2).extrude(thick).val()
            )
            shape = shape.fuse(flange_shape)
        return shape.clean()

    if kind == "tapered_nozzle":
        inlet, outlet, length, wall = (
            p["inlet_diameter"], p["outlet_diameter"],
            p["length"], p["wall_thickness"],
        )
        if 2 * wall >= min(inlet, outlet):
            raise ValueError("Nozzle wall is too thick for its narrower end")
        outer = (
            cq.Workplane("XY").workplane(offset=-length / 2)
            .circle(inlet / 2).workplane(offset=length)
            .circle(outlet / 2).loft(combine=True).val()
        )
        inner = (
            cq.Workplane("XY").workplane(offset=-length / 2 - 0.1)
            .circle(inlet / 2 - wall).workplane(offset=length + 0.2)
            .circle(outlet / 2 - wall).loft(combine=True).val()
        )
        return outer.cut(inner).clean()

    if kind == "split_cuff":
        outer, inner, width = (
            p["outer_diameter"], p["inner_diameter"], p["width"]
        )
        angle = p["opening_angle_deg"]
        if inner >= outer or angle >= 170.0:
            raise ValueError("Cuff requires inner < outer diameter and opening < 170 degrees")
        shape = _tube(outer, inner, width)
        reach = outer * 2
        half_angle = math.radians(angle / 2)
        wedge = (
            cq.Workplane("XY")
            .workplane(offset=-width / 2 - 1)
            .polyline([
                (0, 0),
                (reach * math.cos(half_angle), reach * math.sin(half_angle)),
                (reach * math.cos(half_angle), -reach * math.sin(half_angle)),
            ]).close().extrude(width + 2).val()
        )
        return shape.cut(wedge).clean()

    if kind == "guide_eyelet":
        width, depth, thick, hole = (
            p["width"], p["depth"], p["thickness"], p["hole_diameter"]
        )
        if hole >= min(width, depth):
            raise ValueError("Eyelet hole must fit inside the outer rectangle")
        return (
            cq.Workplane("XY").box(width, depth, thick)
            .faces(">Z").workplane().hole(hole).val()
        )

    if kind == "u_bracket":
        width, depth, height, wall = (
            p["outer_width"], p["depth"], p["height"], p["wall_thickness"]
        )
        if 2 * wall >= width or wall >= height:
            raise ValueError("U bracket needs two distinct walls and an open channel")
        base = (
            cq.Workplane("XY").box(width, depth, wall)
            .translate((0, 0, -height / 2 + wall / 2)).val()
        )
        for x in (-(width - wall) / 2, (width - wall) / 2):
            side = (
                cq.Workplane("XY").box(wall, depth, height - wall)
                .translate((x, 0, wall / 2)).val()
            )
            base = base.fuse(side)
        return base.clean()

    if kind == "cartridge_cup":
        outer, inner, height, bottom = (
            p["outer_diameter"], p["inner_diameter"],
            p["height"], p["base_thickness"],
        )
        if inner >= outer or bottom >= height:
            raise ValueError("Cup requires wall thickness and base thinner than its height")
        outer_shape = (
            cq.Workplane("XY").workplane(offset=-height / 2)
            .circle(outer / 2).extrude(height).val()
        )
        void = (
            cq.Workplane("XY").workplane(offset=-height / 2 + bottom)
            .circle(inner / 2).extrude(height - bottom + 1).val()
        )
        return outer_shape.cut(void).clean()

    raise AssertionError(f"Unknown fabricated geometry kind {kind}")
