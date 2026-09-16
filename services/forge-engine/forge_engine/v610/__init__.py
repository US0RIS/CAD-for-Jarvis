"""ForgeCAD 6.1 simulation integration layer.

6.1 is intentionally simulation-focused. It keeps the canonical engineering model and
validated 6.0/6.0.1 desktop substrate, then makes mechanical connectivity executable
through multibody kinematics and binds every simulation result to explicit solver,
revision, fidelity and stale-state provenance.
"""

from typing import Any

import numpy as _np

from ..v110 import core as _core

MILESTONE_VERSION = "6.1.0"
RELEASE_COMPLETE = True
SIMULATION_SCHEMA_VERSION = 2
MULTIBODY_SCHEMA_VERSION = 1
THERMAL_TRANSIENT_SCHEMA_VERSION = 1
AERODYNAMICS_SCHEMA_VERSION = 1

_core.APP_VERSION = MILESTONE_VERSION
if isinstance(getattr(_core, "PROJECT", None), dict):
    _core.PROJECT["version"] = MILESTONE_VERSION
    if _core.ACTIVE_DESIGN in _core.BRANCHES:
        _core.BRANCHES[_core.ACTIVE_DESIGN]["version"] = MILESTONE_VERSION


def _install_numeric_normalization() -> None:
    """Accept the vector type produced by the solver itself as well as JSON arrays.

    API inputs arrive as lists, while homogeneous-transform algebra naturally produces
    NumPy vectors internally. Treating those two representations differently made the
    arbitrary-axis joint path reject its own valid intermediate values. Normalize both
    at the 6.1 package boundary so every multibody vector has exactly three finite
    components before it reaches the solver.
    """
    from . import multibody as _multibody

    def _vec3(value: Any, label: str) -> _np.ndarray:
        try:
            out = _np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} must contain three finite values") from exc
        if out.shape != (3,) or not _np.all(_np.isfinite(out)):
            raise ValueError(f"{label} must contain three finite values")
        return out.astype(float, copy=True)

    _multibody._vec3 = _vec3


_install_numeric_normalization()

__all__ = [
    "MILESTONE_VERSION",
    "RELEASE_COMPLETE",
    "SIMULATION_SCHEMA_VERSION",
    "MULTIBODY_SCHEMA_VERSION",
    "THERMAL_TRANSIENT_SCHEMA_VERSION",
    "AERODYNAMICS_SCHEMA_VERSION",
]
