"""ForgeCAD 6.0 release integration layer.

6.0 keeps the validated 3.1 substrate but adds geometry-backed assembly truth,
repair/reverification, revision-bound physical feedback, external solver orchestration
and canonical chemistry. RELEASE_COMPLETE is deliberately independent of the semantic
version: staged 6.0.0 binaries remain non-release until native installer validation has
passed on Windows and both supported macOS architectures.
"""

MILESTONE_VERSION = "6.0.0"
RELEASE_COMPLETE = False
ASSEMBLY_CONSTRAINT_SCHEMA_VERSION = 1
GEOMETRY_BACKED_MOUNT_SCHEMA_VERSION = 1
PHYSICAL_RETEST_SCHEMA_VERSION = 1
CHEMISTRY_STUDY_SCHEMA_VERSION = 1

from ..v110 import core as _core

# v310 remains the validated integration/API substrate, but externally persisted project
# and bundle metadata follows the active 6.0 product release once v600 is loaded.
_core.APP_VERSION = MILESTONE_VERSION
if isinstance(getattr(_core, "PROJECT", None), dict):
    _core.PROJECT["version"] = MILESTONE_VERSION
    if _core.ACTIVE_DESIGN in _core.BRANCHES:
        _core.BRANCHES[_core.ACTIVE_DESIGN]["version"] = MILESTONE_VERSION

__all__ = [
    "MILESTONE_VERSION",
    "RELEASE_COMPLETE",
    "ASSEMBLY_CONSTRAINT_SCHEMA_VERSION",
    "GEOMETRY_BACKED_MOUNT_SCHEMA_VERSION",
    "PHYSICAL_RETEST_SCHEMA_VERSION",
    "CHEMISTRY_STUDY_SCHEMA_VERSION",
]
