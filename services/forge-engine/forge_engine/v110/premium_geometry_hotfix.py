from __future__ import annotations

"""Small stability overrides for premium family geometry.

A generic precision shaft is intentionally modeled as the precise cylindrical
stock described by the catalog.  Product-specific end hardware belongs on a
specific SKU/vendor model, not on the generic shaft definition.
"""

from typing import Any

from . import premium_geometry


def _precision_shaft(component: dict[str, Any]):
    diameter = float(premium_geometry._spec(component, "diameter_mm", premium_geometry._dims(component)[0]))
    length = float(premium_geometry._spec(component, "length_mm", premium_geometry._dims(component)[2]))
    # A single analytic OCC cylinder is both geometrically correct and dramatically
    # cheaper/more robust to tessellate than cosmetic edge operations on long shafts.
    return [premium_geometry._cyl(diameter, length, "#c6c9cb")]


def install() -> None:
    premium_geometry._BUILDERS["shaft"] = _precision_shaft
