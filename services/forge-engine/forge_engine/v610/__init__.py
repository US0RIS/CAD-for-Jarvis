"""ForgeCAD 6.1 simulation integration layer.

6.1 is intentionally simulation-focused. It keeps the canonical engineering model and
validated 6.0/6.0.1 desktop substrate, then makes mechanical connectivity executable
through multibody kinematics and binds every simulation result to explicit solver,
revision, fidelity and stale-state provenance.
"""

from ..v110 import core as _core

MILESTONE_VERSION = "6.1.0"
RELEASE_COMPLETE = False
SIMULATION_SCHEMA_VERSION = 2
MULTIBODY_SCHEMA_VERSION = 1
THERMAL_TRANSIENT_SCHEMA_VERSION = 1
AERODYNAMICS_SCHEMA_VERSION = 1

_core.APP_VERSION = MILESTONE_VERSION
if isinstance(getattr(_core, "PROJECT", None), dict):
    _core.PROJECT["version"] = MILESTONE_VERSION
    if _core.ACTIVE_DESIGN in _core.BRANCHES:
        _core.BRANCHES[_core.ACTIVE_DESIGN]["version"] = MILESTONE_VERSION

__all__ = [
    "MILESTONE_VERSION",
    "RELEASE_COMPLETE",
    "SIMULATION_SCHEMA_VERSION",
    "MULTIBODY_SCHEMA_VERSION",
    "THERMAL_TRANSIENT_SCHEMA_VERSION",
    "AERODYNAMICS_SCHEMA_VERSION",
]
