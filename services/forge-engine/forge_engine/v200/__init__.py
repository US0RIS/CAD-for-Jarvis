"""ForgeCAD 2.0 functional design-intelligence layer.

v1.1 remains the deterministic CAD/engineering execution substrate. v2.0 adds the
system-architecture layer above it: goal decomposition, requirements, capability
resolution, candidate discovery, plan quality gates, canonical requirement capture,
a bounded design/validate/repair loop, manufacturing-resource integration including
branch-safe oversized-part splitting, constraint-driven parametric sketches,
branch-linked real-world evidence and feedback, real 3D solid finite-element screening
for supported geometry, transform-independent canonical mesh caching, portable
multi-branch workspaces, and branch-safe autonomous multi-variant engineering campaigns.
"""

DESIGN_INTELLIGENCE_VERSION = "2.0.0"

# v110 remains the execution substrate, but every externally visible project/bundle
# created while v200 is installed must carry the release version being developed.
from ..v110 import core as _core
_core.APP_VERSION = DESIGN_INTELLIGENCE_VERSION

from . import design_intelligence
from . import intent_hotfix as _intent_hotfix
_intent_hotfix.install()
from . import manufacturing_intelligence as _manufacturing_intelligence
_manufacturing_intelligence.install()
from . import manufacturing_analysis as _manufacturing_analysis
_manufacturing_analysis.install()
from . import execution_enrichment as _execution_enrichment
_execution_enrichment.install()
from . import agent_loop as _agent_loop
from .. import main as _legacy_main
_agent_loop.install(_legacy_main)
from . import sketch_solver as _sketch_solver
_sketch_solver.install(_legacy_main)
from . import structural_fea as _structural_fea
_structural_fea.install(_legacy_main)
from . import manufacturing_split as _manufacturing_split
_manufacturing_split.install(_legacy_main)
from . import scene_cache as _scene_cache
_scene_cache.install()
from . import workspace_bundle as _workspace_bundle
_workspace_bundle.install()
from . import manufacturing_api as _manufacturing_api
_manufacturing_api.install(_legacy_main)
from . import physical_evidence as _physical_evidence
_physical_evidence.install(_legacy_main)
from . import campaign_intelligence as _campaign_intelligence
_campaign_intelligence.install(_legacy_main)
from . import feedback_intelligence as _feedback_intelligence
_feedback_intelligence.install(_legacy_main)

__all__ = ["DESIGN_INTELLIGENCE_VERSION", "design_intelligence"]
