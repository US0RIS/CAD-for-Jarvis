"""ForgeCAD 6.2 component-fidelity release.

6.2 makes the original purchased-component contract real: authoritative manufacturer
or authorized-distributor CAD is always preferred when it exists, exact geometry is
cached and reusable, lower-fidelity fallbacks are explicit, and the desktop preserves
component submesh/material structure instead of flattening every product into one toy
mesh.
"""

from ..v110 import core as _core

MILESTONE_VERSION = "6.2.0"
RELEASE_COMPLETE = True
COMPONENT_GEOMETRY_SCHEMA_VERSION = 2
RENDER_MATERIAL_SCHEMA_VERSION = 1

_core.APP_VERSION = MILESTONE_VERSION
if isinstance(getattr(_core, "PROJECT", None), dict):
    _core.PROJECT["version"] = MILESTONE_VERSION
    if _core.ACTIVE_DESIGN in _core.BRANCHES:
        _core.BRANCHES[_core.ACTIVE_DESIGN]["version"] = MILESTONE_VERSION

__all__ = [
    "MILESTONE_VERSION",
    "RELEASE_COMPLETE",
    "COMPONENT_GEOMETRY_SCHEMA_VERSION",
    "RENDER_MATERIAL_SCHEMA_VERSION",
]
