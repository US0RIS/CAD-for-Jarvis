from __future__ import annotations

"""Planner-visible capability contract for ForgeCAD 2.0 routed cables and tubes."""

from copy import deepcopy
from typing import Any, Callable

from . import analysis_contracts


_INSTALLED = False
_ORIGINAL_CONTRACTS: Callable[..., dict[str, Any]] | None = None


ROUTING_ANALYSIS_CONTRACT: dict[str, Any] = {
    "id": "forgecad-route-geometry-2.0",
    "solver": "ForgeCAD RouteGeometry",
    "grade": "engineering_iteration",
    "routes_endpoint": "/v2/routes",
    "analysis_endpoint": "/v2/analysis/routes",
    "canonical_operation": {
        "operation": "add_route",
        "schema": {
            "name": "5 V harness",
            "kind": "cable",
            "points_mm": [[0.0, 0.0, 0.0], [40.0, 0.0, 0.0], [40.0, 30.0, 0.0]],
            "outer_diameter_mm": 4.0,
            "min_bend_radius_mm": 12.0,
            "clearance_mm": 2.0,
            "max_length_mm": 150.0,
            "connection_id": "existing-electrical-connection-id",
            "a_object_id": "$controller",
            "b_object_id": "$load",
        },
        "kinds": ["cable", "wire", "wire_harness", "tube", "hose", "conduit", "generic"],
    },
    "fluid_binding": {
        "field": "fluid_link_id",
        "policy": "A tube/hose route may bind to an existing canonical fluid link. Routing never creates the hydraulic path implicitly.",
    },
    "outputs": [
        "exact polyline centerline length",
        "circular-tangent bend setback and adjacent-segment feasibility",
        "smoothed centerline length estimate for feasible constant-radius corners",
        "electrical/fluid binding validity",
        "conservative expanded-AABB obstruction screening",
    ],
    "fail_closed": [
        "zero-length or malformed route segments",
        "invalid electrical/fluid binding",
        "minimum bend radius cannot fit between supplied waypoints",
        "modeled maximum route length exceeded",
        "hard_clearance route intersects an expanded obstacle proxy",
    ],
    "unknown_policy": "Do not invent cable/tube diameter, service loop, minimum bend radius, clearance, path waypoints or endpoint binding. Store unknown routing constraints as unknown rather than guessing.",
    "limitations": [
        "waypoints are explicit centerline geometry; no automatic 3D autorouter yet",
        "obstacle screening uses expanded world-axis bounding boxes rather than exact swept flexible-body collision",
        "no torsion, cable stiffness, sag, clip/strain-relief mechanics or installation-sequence solver",
        "bend screening assumes circular tangent bends at polyline corners",
        "not physical installation verification",
    ],
}


def _contracts() -> dict[str, Any]:
    assert _ORIGINAL_CONTRACTS is not None
    result = _ORIGINAL_CONTRACTS()
    result["routing"] = deepcopy(ROUTING_ANALYSIS_CONTRACT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_CONTRACTS
    if _INSTALLED:
        return
    _ORIGINAL_CONTRACTS = analysis_contracts.contracts
    analysis_contracts.contracts = _contracts
    _INSTALLED = True
