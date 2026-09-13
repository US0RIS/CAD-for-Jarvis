"""ForgeCAD 2.0 functional design-intelligence layer.

v1.1 remains the deterministic CAD/engineering execution substrate.  v2.0 adds the
system-architecture layer above it: goal decomposition, requirements, capability
resolution, candidate discovery, and plan quality gates.
"""

DESIGN_INTELLIGENCE_VERSION = "2.0.0"

from . import design_intelligence

__all__ = ["DESIGN_INTELLIGENCE_VERSION", "design_intelligence"]
