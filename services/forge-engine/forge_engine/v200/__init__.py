"""ForgeCAD 2.0 functional design-intelligence layer.

v1.1 remains the deterministic CAD/engineering execution substrate. v2.0 adds the
system-architecture layer above it: goal decomposition, requirements, capability
resolution, candidate discovery, plan quality gates, and canonical requirement capture.
"""

DESIGN_INTELLIGENCE_VERSION = "2.0.0"

from . import design_intelligence
from . import intent_hotfix as _intent_hotfix
_intent_hotfix.install()
from . import execution_enrichment as _execution_enrichment
_execution_enrichment.install()

__all__ = ["DESIGN_INTELLIGENCE_VERSION", "design_intelligence"]
