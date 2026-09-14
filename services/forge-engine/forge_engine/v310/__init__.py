"""ForgeCAD 3.1 integration layer.

3.1 unifies canonical CAD, components, BOM, electrical/software state,
requirements, analyses, manufacturing, physical evidence and the 3.0 Physical
World Model into a typed engineering graph. The graph is derived/reconstructable;
canonical mutations continue to flow through the existing deterministic project
and world stores.
"""

INTEGRATION_VERSION = "3.1.0"
ENGINEERING_GRAPH_SCHEMA_VERSION = 1
PRODUCT_PROFILE_SCHEMA_VERSION = 1

from ..v110 import core as _core

# Externally visible project/bundle metadata follows the active 3.1 release line.
_core.APP_VERSION = INTEGRATION_VERSION

__all__ = [
    "INTEGRATION_VERSION",
    "ENGINEERING_GRAPH_SCHEMA_VERSION",
    "PRODUCT_PROFILE_SCHEMA_VERSION",
]
