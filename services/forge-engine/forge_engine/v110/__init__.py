"""Validated ForgeCAD v1.1 engineering subsystems, integrated into the v2 desktop shell."""
ENGINEERING_LAYER_VERSION = "1.1.0"

# Exact manufacturer CAD and the existing hand-built part models retain first priority.
# The premium layer fills the rest of the catalog with family-correct parametric geometry
# and a validated, cached local-model detail pass instead of silent bounding-box stand-ins.
from . import premium_geometry as _premium_geometry
_premium_geometry.install()
from . import premium_geometry_hotfix as _premium_geometry_hotfix
_premium_geometry_hotfix.install()

# Small local planners are constrained to exact component IDs. Expand capability-language
# requests (door-open sensing, network notifications, etc.) into deterministic real-world
# catalog candidates so obvious designs do not fail merely because lexical search missed
# the enabling hardware.
from . import agent_capability_hotfix as _agent_capability_hotfix
_agent_capability_hotfix.install()
