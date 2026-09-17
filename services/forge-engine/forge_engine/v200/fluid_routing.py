from __future__ import annotations

"""Couple canonical tube/hose route geometry into ForgeCAD FluidNetwork.

A routed tube's physical centerline length is authoritative when a canonical route binds
to a fluid link. This adapter injects that length into Hagen-Poiseuille tube analysis
without requiring the planner to duplicate the same number in two project records.
"""

from copy import deepcopy
import math
from typing import Any, Callable

from ..v110 import core
from . import fluid_network


_INSTALLED = False
_ORIGINAL_SOLVE: Callable[..., dict[str, Any]] | None = None


def _route_length_mm(route: dict[str, Any]) -> float:
    points = route.get("points_mm") or []
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"Fluid-bound route {route.get('id')} has no valid centerline")
    total = 0.0
    for index in range(len(points) - 1):
        a, b = points[index], points[index + 1]
        if not isinstance(a, (list, tuple)) or not isinstance(b, (list, tuple)) or len(a) != 3 or len(b) != 3:
            raise ValueError(f"Fluid-bound route {route.get('id')} contains invalid 3D points")
        delta = [float(b[i]) - float(a[i]) for i in range(3)]
        length = math.sqrt(sum(value * value for value in delta))
        if not math.isfinite(length) or length <= 0.0:
            raise ValueError(f"Fluid-bound route {route.get('id')} contains a zero/non-finite segment")
        total += length
    return total


def _prepare(project: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    prepared = deepcopy(project)
    routes_by_link: dict[str, list[dict[str, Any]]] = {}
    for route in prepared.get("routes") or []:
        if not isinstance(route, dict):
            continue
        link_id = str(route.get("fluid_link_id") or "").strip()
        if link_id:
            routes_by_link.setdefault(link_id, []).append(route)

    provenance: dict[str, dict[str, Any]] = {}
    for row in prepared.get("constraints") or []:
        if not isinstance(row, dict):
            continue
        typ = str(row.get("type", row.get("kind", ""))).strip().lower()
        if typ not in {"fluid_link", "hydraulic_link", "tube", "pipe"}:
            continue
        link_id = str(row.get("id") or "").strip()
        bound = routes_by_link.get(link_id, [])
        if len(bound) > 1:
            raise ValueError(f"Fluid link {link_id} has multiple canonical routes; exactly one routed centerline may define tube length")
        if not bound:
            continue
        route = bound[0]
        route_kind = str(route.get("kind") or "generic").lower()
        if route_kind not in {"tube", "hose", "conduit", "generic"}:
            raise ValueError(f"Fluid link {link_id} is bound to non-fluid route kind {route_kind!r}")
        length = _route_length_mm(route)
        declared = row.get("length_mm")
        if declared is not None:
            declared_value = float(declared)
            tolerance = max(1.0, 0.01 * length)
            if abs(declared_value - length) > tolerance:
                raise ValueError(
                    f"Fluid link {link_id} declares length {declared_value:g} mm but canonical route {route.get('id')} is {length:g} mm; remove the duplicate length or reconcile the route"
                )
        if typ in {"tube", "pipe"} and row.get("resistance_pa_s_m3") is None and row.get("hydraulic_resistance_pa_s_m3") is None:
            row["length_mm"] = length
        provenance[link_id] = {
            "route_id": str(route.get("id") or ""),
            "route_name": str(route.get("name") or route.get("id") or "Route"),
            "route_length_mm": length,
            "length_source": "canonical_route_geometry",
        }
    return prepared, provenance


def _solve(project: dict[str, Any] | None = None) -> dict[str, Any]:
    assert _ORIGINAL_SOLVE is not None
    source = project if project is not None else core.PROJECT
    prepared, provenance = _prepare(source)
    result = _ORIGINAL_SOLVE(prepared)
    for link in result.get("links") or []:
        link_id = str(link.get("id") or "")
        if link_id in provenance:
            link.update(deepcopy(provenance[link_id]))
    if provenance:
        result.setdefault("provenance", {})["route_coupling"] = {
            "bound_link_count": len(provenance),
            "policy": "Canonical routed centerline length drives tube resistance when explicit route binding exists.",
        }
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_SOLVE
    if _INSTALLED:
        return
    _ORIGINAL_SOLVE = fluid_network.solve_fluid_network
    fluid_network.solve_fluid_network = _solve
    _INSTALLED = True
