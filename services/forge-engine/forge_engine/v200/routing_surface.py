from __future__ import annotations

"""Expose canonical route state through the normal ForgeCAD project snapshot."""

from copy import deepcopy
from typing import Any, Callable

from ..engineering_state import EngineeringProject
from ..v110 import core
from . import routing


_INSTALLED = False
_ORIGINAL_SNAPSHOT: Callable[..., dict[str, Any]] | None = None


def _snapshot(self: EngineeringProject) -> dict[str, Any]:
    assert _ORIGINAL_SNAPSHOT is not None
    result = _ORIGINAL_SNAPSHOT(self)
    result["routes"] = deepcopy(core.PROJECT.get("routes") or [])
    result["routing"] = routing.analyze_routes(core.PROJECT)
    return result


def install() -> None:
    global _INSTALLED, _ORIGINAL_SNAPSHOT
    if _INSTALLED:
        return
    _ORIGINAL_SNAPSHOT = EngineeringProject.snapshot
    EngineeringProject.snapshot = _snapshot
    _INSTALLED = True
